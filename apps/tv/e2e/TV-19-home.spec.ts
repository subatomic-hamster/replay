import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, smallText, video } from "./helpers";

// TV-19 Home, the immersive list (docs/ux/redesign.md "Home"): the hero follows the
// focused card, a processing game shows a ring and plain words (and opens once it is
// watchable), the gear is reached with Up, the Players row opens a profile, and an empty
// library becomes "Add your first game".

const card = (page: Page, id: string) =>
  page.locator(`[data-testid="game-card"][data-game-id="${id}"]`);
const PROC = "g_proc03";

type MockWindow = {
  __replayMock: {
    api: { listGames: () => Promise<Record<string, unknown>[]> };
    games: Map<string, unknown>;
  };
};

/** Change the mock before Home mounts: open Settings, run `fn` in the page, Back to Home. */
async function homeAfter(page: Page, fn: () => void) {
  await page.goto("/tv/settings");
  await expect(page.getByTestId("settings")).toBeVisible();
  await page.evaluate(fn);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("home")).toBeVisible();
}

test("TV-19 the hero follows focus; a processing card shows a ring and words; Up reaches the gear", async ({
  page,
}) => {
  // The processing game as an older API sends it: no readiness fields, so it is not
  // watchable and its words come from the stages (the fallback path).
  await homeAfter(page, () => {
    const m = (window as unknown as MockWindow).__replayMock.api;
    const list = m.listGames.bind(m);
    m.listGames = async () =>
      (await list()).map((g) => {
        if (g.id !== "g_proc03") return g;
        const { watchable, eta_s, stage_label, features, ...old } = g;
        void [watchable, eta_s, stage_label, features];
        return old;
      });
  });
  const hero = page.getByTestId("hero");
  await expect(card(page, GAME_ID)).toHaveAttribute("data-focused", "true");
  await expect(hero).toHaveAttribute("data-game-id", GAME_ID);
  await expect(page.getByTestId("hero-title")).toHaveText(
    "Tuesday run — CRC court 2",
  );
  await expect(page.getByTestId("hero-play")).toBeVisible();
  await expect(page.getByTestId("hero-highlights")).toBeVisible();
  // Condensed only when the API says the game has it (no `features` here).
  await expect(page.getByTestId("hero-condensed")).toHaveCount(0);
  // UI pass: the legend says what Select does and that Up has more ways to watch
  await expect(page.getByTestId("legend-Select")).toHaveAttribute(
    "data-label",
    "Play",
  );
  await expect(page.getByTestId("legend-▲")).toHaveAttribute(
    "data-label",
    "More ways to watch",
  );

  // The focused card: scale 1.06 and a Chalk ring, after the 150 ms ease-out.
  const ring = card(page, GAME_ID).locator(":scope > div").first();
  await expect
    .poll(() =>
      ring.evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).a),
    )
    .toBeCloseTo(1.06, 2);
  expect(await ring.evaluate((el) => getComputedStyle(el).borderTopColor)).toBe(
    "rgb(236, 239, 242)",
  );

  // Order: Add game, then the processing game, then the rest.
  const ids = await page
    .locator('[data-testid="game-card"]')
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-game-id")));
  expect(ids).toEqual([PROC, GAME_ID, "g_mock02", "g_pickle4"]);

  // Left: the processing game. Dimmed art, a ring at its progress, plain words; the hero swaps.
  await page.keyboard.press("ArrowLeft");
  const proc = card(page, PROC);
  await expect(proc).toHaveAttribute("data-focused", "true");
  await expect(proc).toHaveAttribute("data-processing", "true");
  await expect(hero).toHaveAttribute("data-game-id", PROC);
  await expect(page.getByTestId("hero-title")).toHaveText("Friday scrimmage");
  // mock: stages 0-1 done, "detect" half way → 2.5 of 9
  await expect(proc.getByTestId("progress-ring")).toHaveAttribute(
    "data-progress",
    "0.28",
  );
  await expect(proc.getByTestId("game-status")).toHaveText(
    "Finding players, 28%",
  );
  await expect(page.getByTestId("hero-meta")).toHaveText(
    "Finding players, 28%",
  );
  await expect(card(page, GAME_ID).getByTestId("progress-ring")).toHaveCount(0);
  // Not watchable yet: no Play, Select does nothing (and the legend does not offer it).
  await expect(page.getByTestId("hero-play")).toHaveCount(0);
  await expect(page.getByTestId("key-legend")).toHaveCount(0);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("home")).toBeVisible();

  // No hero actions for it, so Up goes straight to the gear; Down comes back.
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("library-settings")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("ArrowDown");
  await expect(proc).toHaveAttribute("data-focused", "true");

  // A ready game: Up → Play, Right → Highlights, Up → gear, Down → back on the hero.
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("hero-play")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("hero-highlights")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("library-settings")).toHaveAttribute(
    "data-focused",
    "true",
  );
  expect(await smallText(page)).toEqual([]);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("settings")).toBeVisible();
});

test("TV-19 Back on Home exits only on a second press, with a note after the first", async ({
  page,
}) => {
  await page.goto("/");
  await expect(card(page, GAME_ID)).toHaveAttribute("data-focused", "true");
  // Handled keys are preventDefault-ed on the web build; an unhandled Back is the one
  // the Fire TV turns into leaving the app.
  const back = () =>
    page.evaluate(() => {
      const e = new KeyboardEvent("keydown", {
        key: "Escape",
        cancelable: true,
      });
      window.dispatchEvent(e);
      return e.defaultPrevented;
    });
  const note = page.getByTestId("home-exit-note");
  expect(await back()).toBe(true);
  await expect(note).toHaveText("Press Back again to exit");
  await expect(page.getByTestId("home")).toBeVisible();
  // any other key cancels it: the next Back only warns again
  await page.keyboard.press("ArrowRight");
  await expect(note).toHaveCount(0);
  expect(await back()).toBe(true);
  await expect(note).toBeVisible();
  expect(await back()).toBe(false); // the second press: the app exits
  // the note goes by itself after 3 s, and so does the guard
  await page.keyboard.press("ArrowLeft");
  expect(await back()).toBe(true);
  await expect(note).toHaveCount(0, { timeout: 5000 });
  expect(await back()).toBe(true);
});

test("TV-19 Play on the hero opens the game", async ({ page }) => {
  await page.goto("/");
  await expect(card(page, GAME_ID)).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("video")).toBeAttached();
  await expect
    .poll(async () => (await video(page))?.readyState ?? 0, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
});

test("TV-19 a watchable processing game: an estimate in words, and Play works", async ({
  page,
}) => {
  await homeAfter(page, () => {
    const m = (window as unknown as MockWindow).__replayMock.api;
    const list = m.listGames.bind(m);
    m.listGames = async () =>
      (await list()).map((g) =>
        g.id === "g_proc03"
          ? {
              ...g,
              watchable: true,
              eta_s: 380,
              stage_label: "Finding players",
              features: { highlights: { state: "pending" } },
            }
          : g,
      );
  });
  const proc = card(page, PROC);
  await expect(proc.getByTestId("game-status")).toHaveText(
    "Finding players, about 6 min",
  );
  await expect(proc.getByTestId("progress-ring")).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(proc).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("hero-play")).toBeVisible();
  await expect(page.getByTestId("hero-highlights")).toHaveCount(0); // still getting ready
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("video")).toBeAttached();
});

test("TV-19 keys faster than a render all count in the Games row", async ({
  page,
}) => {
  await page.goto("/");
  await expect(card(page, GAME_ID)).toHaveAttribute("data-focused", "true");
  const ids = await page
    .getByTestId("game-card")
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-game-id")));
  const from = ids.indexOf(GAME_ID);
  // Two Rights in one task, before React re-renders (a held remote on a slow Fire TV).
  await page.evaluate(() => {
    for (let i = 0; i < 2; i++)
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight" }));
  });
  await expect(card(page, ids[from + 2] ?? "")).toHaveAttribute(
    "data-focused",
    "true",
  );
});

test("TV-19 the Players row opens a profile", async ({ page }) => {
  await page.goto("/");
  await expect(card(page, GAME_ID)).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("home")).toHaveAttribute(
    "data-zone",
    "players",
  );
  const first = page.getByTestId("home-player").first();
  await expect(first).toHaveAttribute("data-focused", "true");
  await expect(first).toBeInViewport({ ratio: 1 });
  const id = await first.getAttribute("data-profile-id");
  await page.keyboard.press("ArrowUp");
  await expect(card(page, GAME_ID)).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-profile-id",
    id ?? "",
  );
});

test("TV-19 an empty library: the hero is Add your first game, with Add game focused", async ({
  page,
}) => {
  await homeAfter(page, () =>
    (window as unknown as MockWindow).__replayMock.games.clear(),
  );
  await expect(page.getByTestId("hero")).toHaveAttribute(
    "data-game-id",
    "empty",
  );
  await expect(page.getByTestId("hero-title")).toHaveText(
    "Add your first game",
  );
  await expect(page.getByTestId("game-card")).toHaveCount(0);
  await expect(page.getByTestId("library-add")).toHaveAttribute(
    "data-focused",
    "true",
  );
  expect(await smallText(page)).toEqual([]);
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("library-settings")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("add-game")).toBeVisible();
});
