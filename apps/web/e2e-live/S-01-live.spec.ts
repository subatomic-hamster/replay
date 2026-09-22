// The whole product against the real services/api (REPLAY_PIPELINE=fake), not the mock.
// Serial on purpose: one API process, one data dir, and the tests below reuse the game
// that S-01 uploads.
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(here, "../../..");
const FIXTURE = path.join(REPO, "services/api/fixtures/tiny.mp4");
const API = "http://localhost:8000";

/** Landmarks projected from courtcam's basketball_half template onto a 1280x720 frame
 *  (the same values services/api/tests/conftest.py calibrates with: ~0.02 px error). */
const LANDMARKS: Record<string, [number, number]> = {
  corner_nl: [180, 660],
  corner_nr: [1100, 660],
  corner_fl: [430, 300],
  corner_fr: [860, 300],
  rim: [641.1, 583.2],
};

let gameId = "";

test.describe.configure({ mode: "serial" });

async function video(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v && { currentTime: v.currentTime, paused: v.paused, readyState: v.readyState };
  });
}

async function waitForVideo(page: Page) {
  await expect(page.getByTestId("video")).toBeAttached();
  await expect
    .poll(async () => (await video(page))?.readyState ?? 0, { timeout: 30_000 })
    .toBeGreaterThanOrEqual(2);
}

test("L-00 a fresh data dir shows the empty library", async ({ page }) => {
  await page.goto("/tv");
  await expect(page.getByTestId("library-empty")).toBeVisible();
  await expect(page.getByTestId("game-card")).toHaveCount(0);
});

test("S-01 upload -> calibrate -> process -> watch -> follow -> highlights -> review", async ({
  page,
}) => {
  test.setTimeout(300_000); // the fake pipeline still transcodes the upload with ffmpeg

  // --- create ------------------------------------------------------------
  await page.goto("/upload");
  await expect(page.getByTestId("sport-option-basketball")).toBeVisible();
  await page.getByTestId("game-title-input").fill("Live run");
  await page.getByTestId("create-game").click();
  await page.waitForURL(/\/upload\/g_[a-z0-9]+/);
  gameId = new URL(page.url()).pathname.split("/")[2];

  // --- upload (XHR PUT with the file's own Content-Type) ------------------
  await page.getByTestId("file-input").setInputFiles(FIXTURE);
  await expect(page.getByTestId("upload-progress")).toBeVisible();
  await expect(page.getByTestId("upload-done")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("upload-progress")).toHaveJSProperty("value", 100);
  await page.getByTestId("go-calibrate").click();

  // --- calibrate ---------------------------------------------------------
  const img = page.getByTestId("calib-image");
  await expect(img).toBeVisible();
  const frame = await img.evaluate((el: HTMLImageElement) => ({
    w: el.naturalWidth,
    h: el.naturalHeight,
  }));
  expect(frame.w).toBeGreaterThan(0); // D-14: the frame exists before processing

  const box = (await img.boundingBox())!;
  for (const [name, [x, y]] of Object.entries(LANDMARKS)) {
    await expect(page.getByTestId("calib-prompt")).toContainText(name.replace(/_/g, " "));
    await page.mouse.click(box.x + (x / frame.w) * box.width, box.y + (y / frame.h) * box.height);
    await expect(page.getByTestId(`landmark-${name}`)).toBeVisible();
  }

  const error = page.getByTestId("calib-error");
  await expect(error).toHaveAttribute("data-ok", "true");
  const px = Number((await error.textContent())!.replace(" px", ""));
  expect(px).toBeLessThan(5);

  // --- process -----------------------------------------------------------
  await expect(page.getByTestId("start-processing")).toBeEnabled();
  await page.getByTestId("start-processing").click();
  await page.waitForURL(new RegExp(`/upload/${gameId}/status`));
  // S-08 / D-9: while the job runs, GET /games/{id} merges the job record's stage state,
  // so the status page shows exactly one stage `running` with the later ones `pending`.
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const status = document.querySelector('[data-testid="game-status"]')?.textContent;
          const states = [...document.querySelectorAll('[data-testid^="stage-"]')]
            .map((el) => el.getAttribute("data-state"))
            .join(",");
          return `${status} ${states}`;
        }),
      { timeout: 120_000 },
    )
    // exactly one running stage, everything before it done, everything after pending
    .toMatch(/^processing (done,)*running(,pending)*$/);
  for (const stage of ["ingest", "detect", "track", "render", "label"]) {
    await expect(page.getByTestId(`stage-${stage}`)).toHaveAttribute("data-state", /done|partial/, {
      timeout: 240_000,
    });
  }
  await expect(page.getByTestId("game-status")).toHaveText("ready");

  // --- library -----------------------------------------------------------
  await page.goto("/tv");
  const card = page.locator(`[data-testid=game-card][data-game-id="${gameId}"]`);
  await expect(card).toBeVisible();
  await expect(card.getByTestId("game-status")).toHaveText("ready");
  await page.keyboard.press("Enter");
  await page.waitForURL(new RegExp(`/tv/${gameId}$`));

  // --- watch: play, then pause into select mode --------------------------
  await waitForVideo(page);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  await expect.poll(async () => (await video(page))?.currentTime ?? 0).toBeGreaterThan(0.3);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await video(page))?.paused).toBe(true);

  // boxes come from the real tracks chunks served out of the game dir
  const boxes = page.locator('[data-testid^="select-box-"]');
  await expect(boxes.first()).toBeVisible();
  await expect(boxes).toHaveCount(2);

  // --- follow ------------------------------------------------------------
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          getComputedStyle(document.querySelector('[data-testid="player-transform"]')!).transform,
      ),
    )
    .not.toMatch(/^(none|matrix\(1, 0, 0, 1, 0, 0\))$/);

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("followcam-active")).toHaveCount(0);

  // --- highlights (reached with the D-pad, not a URL) ---------------------
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("nav-highlights")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await page.waitForURL(new RegExp(`/tv/${gameId}/highlights`));

  // The chips come from the sport profile; take the "all shots" one.
  const chips = page.getByTestId("query-chip");
  await expect(chips.first()).toBeVisible();
  const labels = await chips.evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-chip") ?? ""),
  );
  const target = labels.findIndex((l) => /all shots/i.test(l));
  expect(target, `no "all shots" chip in ${JSON.stringify(labels)}`).toBeGreaterThanOrEqual(0);
  for (let i = 0; i < target; i++) await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("reel-clip").first()).toBeVisible();
  const clips = await page.getByTestId("reel-clip").count();
  expect(clips).toBeGreaterThan(0);
  await expect(page.getByTestId("clip-counter")).toContainText(`/${clips}`);

  await waitForVideo(page);
  const tStart = Number(
    await page.getByTestId("reel-clip").first().getAttribute("data-t-start"),
  );
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  expect(Math.abs(((await video(page))?.currentTime ?? 0) - tStart)).toBeLessThan(1.5);

  // --- review: confirm one low-confidence event --------------------------
  await page.goto(`/tv/${gameId}/review`);
  const item = page.getByTestId("review-item");
  await expect(item).toBeVisible();
  const eventId = await item.getAttribute("data-event-id");
  await page.keyboard.press("Enter"); // "Made" is the focused action
  await expect(page.getByTestId("review-empty")).toBeVisible();

  // PATCH actually persisted: re-read events.json off the API
  const events = await (await page.request.get(`${API}/media/games/${gameId}/events.json`)).json();
  const patched = events.events.find((e: { id: string }) => e.id === eventId);
  expect(patched).toMatchObject({ made: true, confirmed: true, source: "user" });

  // --- bookmark ----------------------------------------------------------
  await page.goto(`/tv/${gameId}`);
  await waitForVideo(page);
  const before = await page.getByTestId("event-marker").count();
  await page.keyboard.press("b");
  await expect(page.getByTestId("event-marker")).toHaveCount(before + 1);
  const after = await (await page.request.get(`${API}/media/games/${gameId}/events.json`)).json();
  expect(after.events.filter((e: { type: string }) => e.type === "bookmark")).toHaveLength(2);
});

test("E-22 an unreachable API shows the error banner, not a white page", async ({ page }) => {
  await page.route(`${API}/games`, (route) => route.abort("connectionrefused"));
  await page.goto("/tv");
  await expect(page.getByTestId("api-error")).toBeVisible();
  await expect(page.getByTestId("game-card")).toHaveCount(0);
});

test("D-3 the wide MP4 is range-seekable and the player settles on the target", async ({
  page,
}) => {
  expect(gameId, "S-01 must have run first").not.toBe("");

  const wide = `${API}/media/games/${gameId}/media/wide.mp4`;
  const ranged = await page.request.get(wide, { headers: { Range: "bytes=0-99" } });
  expect(ranged.status()).toBe(206);
  expect((await ranged.body()).length).toBe(100);

  await page.goto(`/tv/${gameId}`);
  await waitForVideo(page);
  await page.evaluate(() => {
    document.querySelector<HTMLVideoElement>('[data-testid="video"]')!.currentTime = 10;
  });
  await expect
    .poll(async () => {
      const v = await video(page);
      return v && v.readyState >= 2 ? Math.abs(v.currentTime - 10) : 99;
    })
    .toBeLessThan(0.5);
});

// S-31 / H4 — phone companion over the session WebSocket. Two pages in one context
// (separate tabs, so separate sessionStorage); the WS fan-out is in-process, so the mock
// cannot stand in for it. Lives here because the live project runs one file serially.
test("S-31 a phone query moves the TV to the matching highlights", async ({ page, context }) => {
  expect(gameId, "S-01 must have run first").not.toBe("");

  // --- TV: reach the pairing code with the remote only (`p` on Highlights) ---------
  await page.goto(`/tv/${gameId}/highlights`);
  await expect(page.getByTestId("query-chip").first()).toBeVisible();
  await page.keyboard.press("p");
  await page.waitForURL(/\/tv\/pair\?game=/);
  await expect(page.getByTestId("pair-code")).toHaveText(/^\d{4}$/);
  const code = (await page.getByTestId("pair-code").textContent())!.trim();

  // --- phone: enter the code, then send a query ------------------------------------
  const phone = await context.newPage();
  await phone.goto("/companion");
  await phone.getByTestId("companion-code-input").fill(code);
  await phone.getByTestId("companion-connect").click();
  await phone.waitForURL(new RegExp(`/companion/${code}`));
  await expect(phone.getByTestId("companion-status")).toHaveAttribute("data-state", "open");

  await phone.getByTestId("companion-query").fill("Marcus — all shots");
  await phone.getByTestId("companion-send").click();
  await expect(phone.getByTestId("companion-sent")).toContainText("Marcus");

  // --- TV: jumps to the results with no remote input (within 2 s per S-31) ---------
  await page.waitForURL(new RegExp(`/tv/${gameId}/highlights\\?q=`), { timeout: 5000 });
  await expect(page.getByTestId("query-interpretation")).toBeVisible();
  await expect(page.getByTestId("query-interpretation")).toContainText("Marcus");
  await expect(page.getByTestId("reel-clip").first()).toBeVisible();

  // --- a second query lands on the Highlights screen itself, still no remote --------
  await phone.getByTestId("companion-query").fill("misses");
  await phone.getByTestId("companion-send").click();
  await expect(page.getByTestId("query-interpretation")).toContainText("missed shots", {
    timeout: 5000,
  });
  await phone.close();
});

test("S-31/AC-13 an unpaired code reports a closed session instead of hanging", async ({
  page,
}) => {
  // Pairing codes are always four digits, so this one can never resolve (D-16).
  await page.goto("/companion/s_nope");
  await expect(page.getByTestId("companion-status")).toHaveAttribute("data-state", "closed");
  await expect(page.getByTestId("companion-error")).toBeVisible();
  await expect(page.getByTestId("companion-send")).toBeDisabled();
});
