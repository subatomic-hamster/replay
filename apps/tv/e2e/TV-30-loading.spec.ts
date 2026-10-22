// Loading, errors and the honest edges of the data (the polish pass): anything that waits
// shows the one busy presentation (a blurred backdrop of what was on screen and a spinner),
// never a blank page with "Loading…"; Home draws its last list at once; an error keeps the
// backdrop with calm words; the Stats panel spins while its data loads, says so honestly
// when no shot went in, and draws two alike team colours apart.
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, menuTo, openWatch, smallText } from "./helpers";

type MockApi = Record<string, (...a: unknown[]) => Promise<unknown>>;

/** Hold one mock API method until `release()` (window.__release) is called. */
async function hold(page: Page, method: string) {
  await page.evaluate((name) => {
    const w = window as unknown as {
      __replayMock: { api: MockApi };
      __release?: () => void;
    };
    const api = w.__replayMock.api;
    const orig = api[name].bind(api);
    let open!: () => void;
    const gate = new Promise<void>((r) => (open = r));
    w.__release = open;
    api[name] = (...a: unknown[]) => gate.then(() => orig(...a));
  }, method);
}

type Mock = {
  api: MockApi;
  games: Map<string, { teams: { id: number; color_hex: string }[] }>;
};

/** Patch the mock API as its module installs it (before the first render) on every
 *  page load; `patch` runs in the page (it is sent as source, so it closes over nothing). */
async function patchMock(page: Page, patch: (m: Mock, id: string) => void) {
  await page.addInitScript({
    content: `(() => {
      let v;
      Object.defineProperty(window, "__replayMock", {
        configurable: true,
        get: () => v,
        set: (m) => { v = m; (${patch.toString()})(m, ${JSON.stringify(GAME_ID)}); },
      });
    })();`,
  });
}

const noLoadingText = async (page: Page) =>
  expect(page.getByText(/Loading/)).toHaveCount(0);

test("TV-30 Home: a spinner over the backdrop while games load, then the list drawn at once on return", async ({
  page,
}) => {
  await page.goto("/tv/settings");
  await expect(page.getByTestId("settings")).toBeVisible();
  await hold(page, "listGames");
  await page.keyboard.press("Escape"); // to Home, whose list is held
  const busy = page.getByTestId("busy");
  await expect(busy).toBeVisible();
  await expect(busy.getByRole("progressbar")).toBeAttached();
  await expect(page.getByTestId("backdrop")).toBeVisible();
  await noLoadingText(page);
  await page.evaluate(() =>
    (window as unknown as { __release: () => void }).__release(),
  );
  await expect(page.getByTestId("home")).toBeVisible();
  await expect(busy).toHaveCount(0);

  // Into a game and back: Home is there at once (its last list), even with the list held.
  await hold(page, "listGames");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("watch")).toBeVisible();
  for (let i = 0; i < 3 && !(await page.getByTestId("home").count()); i++) {
    await page.keyboard.press("Escape"); // peels the transport, then Home
    await page.waitForTimeout(400);
  }
  await expect(page.getByTestId("home")).toBeVisible();
  await expect(page.getByTestId("game-card").first()).toBeVisible();
  await expect(busy).toHaveCount(0);
});

test("TV-30 Home after a restart: the saved list draws before the API answers", async ({
  page,
}) => {
  await page.goto("/tv");
  await expect(page.getByTestId("game-card").first()).toBeVisible();
  const n = await page.getByTestId("game-card").count();
  // a "restart" whose list never arrives (patched as the mock module installs itself)
  await page.addInitScript(() => {
    let v: { api: MockApi } | undefined;
    Object.defineProperty(window, "__replayMock", {
      configurable: true,
      get: () => v,
      set: (m: { api: MockApi }) => {
        v = m;
        m.api.listGames = () => new Promise(() => {});
      },
    });
  });
  await page.reload();
  await expect(page.getByTestId("home")).toBeVisible();
  await expect(page.getByTestId("game-card")).toHaveCount(n);
  await expect(page.getByTestId("busy")).toHaveCount(0);
});

test("TV-30 an API error keeps the backdrop: calm words, Try again, Settings, no small text", async ({
  page,
}) => {
  await page.goto("/tv/settings");
  await expect(page.getByTestId("settings")).toBeVisible();
  await page.evaluate(() => {
    const api = (window as unknown as { __replayMock: { api: MockApi } })
      .__replayMock.api;
    api.listGames = () => Promise.reject(new Error("Network request failed"));
  });
  await page.keyboard.press("Escape");
  const err = page.getByTestId("api-error");
  await expect(err).toBeVisible();
  await expect(err.getByTestId("backdrop")).toBeVisible();
  await expect(err).toContainText("Replay can't connect");
  await expect(page.getByTestId("api-error-retry")).toContainText("Try again");
  await expect(page.getByTestId("api-error-retry")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await expect(page.getByTestId("api-error-detail")).toContainText(
    "Network request failed",
  );
  expect(await smallText(page)).toEqual([]);
});

test("TV-30 the player: the blurred backdrop and spinner until the first frame, then the video", async ({
  page,
}) => {
  await page.goto(`/tv/${GAME_ID}`);
  // either still loading (the backdrop with a spinner) or already past it; never a bare page
  await expect(page.getByTestId("video")).toBeAttached();
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            document.querySelector<HTMLVideoElement>('[data-testid="video"]')
              ?.readyState ?? 0,
        ),
      { timeout: 15_000 },
    )
    .toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("player-loading")).toHaveCount(0);
  await noLoadingText(page);
});

test("TV-30 Stats: a spinner while it loads; no made shots said plainly; alike team colours drawn apart", async ({
  page,
}) => {
  await patchMock(page, (m) => {
    const orig = m.api.getStats.bind(m.api);
    let open = () => {};
    const gate = new Promise<void>((r) => (open = r));
    (window as unknown as { __release: () => void }).__release = open;
    // every shot missed: points and makes all zero
    m.api.getStats = (...a: unknown[]) =>
      gate.then(() =>
        orig(...a).then((s) => {
          const st = s as {
            box_score: { makes: number; points?: number; attempts: number }[];
            shots: { made: boolean }[];
          };
          return {
            ...st,
            box_score: st.box_score.map((r) => ({
              ...r,
              makes: 0,
              points: 0,
              attempts: Math.max(1, r.attempts),
            })),
            shots: st.shots.map((x) => ({ ...x, made: false })),
          };
        }),
      );
  });
  await openWatch(page, GAME_ID, "?t=2");
  await menuTo(page, "nav-review");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("stats-panel")).toBeVisible();
  await expect(page.getByTestId("stats-loading")).toBeAttached();
  await page.evaluate(() =>
    (window as unknown as { __release: () => void }).__release(),
  );
  await expect(page.getByTestId("stats-loading")).toHaveCount(0);
  await expect(page.getByTestId("stats-no-makes")).toContainText(
    "No made shots detected",
  );
  await expect(page.getByTestId("stats-score")).toHaveCount(0);
  await expect(page.getByText("Pts", { exact: true })).toHaveCount(0);
  expect(await page.getByTestId("box-score-row").count()).toBeGreaterThan(0);
  expect(await smallText(page)).toEqual([]);
});

test("TV-30 Stats score: two alike jersey colours are drawn apart, in order, and legible on the panel", async ({
  page,
}) => {
  await patchMock(page, (m, id) => {
    // jersey colours as read off real footage: two dark browns
    const g = m.games.get(id);
    if (g)
      g.teams = [
        { id: 0, color_hex: "#57282A" },
        { id: 1, color_hex: "#402B28" },
      ];
  });
  await openWatch(page, GAME_ID, "?t=2");
  await menuTo(page, "nav-review");
  await page.keyboard.press("Enter");
  const sw = page.getByTestId("team-swatch");
  await expect(sw).toHaveCount(2);
  const [a, b] = await Promise.all(
    [0, 1].map(async (i) => (await sw.nth(i).getAttribute("data-color")) ?? ""),
  );
  // relative luminance (WCAG) of #RRGGBB
  const lum = (hex: string) => {
    const [r, g, bl] = [1, 3, 5].map((k) => {
      const c = parseInt(hex.slice(k, k + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const ratio = (x: number, y: number) =>
    (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  expect(ratio(lum(a), lum(b))).toBeGreaterThan(2); // apart from each other
  const bench = lum("#1D2834");
  expect(ratio(lum(a), bench)).toBeGreaterThan(2); // both show on the panel
  expect(ratio(lum(b), bench)).toBeGreaterThan(2);
  expect(lum(a)).toBeGreaterThan(lum(b)); // #57282A is the lighter jersey: kept lighter
});
