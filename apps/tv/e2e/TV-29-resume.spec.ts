// Resume: Back from a sub-screen (Stats → Review here) comes back to the same game time
// and play state, not 0:00; Home's hero then offers "Resume 0:09" (and Start over) for the
// game, and it resumes there. Kept in app state and the settings storage (localStorage on
// the web build).
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, media, menuTo, openWatch } from "./helpers";

/** Stats → Review → Back. */
async function viaReview(page: Page) {
  await menuTo(page, "nav-review");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("stats-review")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("review-item")).toBeVisible();
  await expect(page.getByTestId("video")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
  await expect
    .poll(async () => (await media(page)).ready, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
  // Back from Review lands on the Stats panel it came from; Back again closes it.
  await expect(page.getByTestId("stats-panel")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("stats-panel")).toHaveCount(0);
}

test("TV-29 a sub-screen's Back resumes at the same time and play state; Home offers Resume", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=6");
  await expect
    .poll(async () => (await media(page)).t, { timeout: 10_000 })
    .toBeGreaterThan(6);

  // Playing: back playing, from about where it was.
  const t0 = (await media(page)).t;
  await viaReview(page);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  expect((await media(page)).t).toBeGreaterThanOrEqual(t0 - 0.1);

  // Paused: back paused, at the same frame.
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  const t1 = (await media(page)).t;
  expect(t1).toBeGreaterThan(5);
  expect(t1).toBeLessThan(15);
  await viaReview(page);
  await expect
    .poll(async () => Math.abs((await media(page)).t - t1))
    .toBeLessThan(0.1);
  await page.waitForTimeout(500);
  expect((await media(page)).paused).toBe(true);

  // Home: the game's hero says Resume and when; Start over beside it.
  await page.keyboard.press("Escape"); // → Home (one Back: no hide-the-transport step)
  await expect(page.getByTestId("home")).toBeVisible();
  const card = page.locator(
    `[data-testid="game-card"][data-game-id="${GAME_ID}"]`,
  );
  await expect(card).toHaveAttribute("data-focused", "true");
  const play = page.getByTestId("hero-play");
  const at = Math.floor(t1);
  await expect(play).toHaveText(`Resume 0:${String(at).padStart(2, "0")}`);
  expect(
    Math.abs(Number(await play.getAttribute("data-resume")) - t1),
  ).toBeLessThan(0.1);
  await expect(page.getByTestId("hero-restart")).toHaveText("Start over");
  // another game never watched: plain Play
  await page.keyboard.press("ArrowRight");
  await expect(play).toHaveText("Play");
  await page.keyboard.press("ArrowLeft");
  await expect(play).toHaveText(/^Resume/);

  // Resume plays from there.
  await page.keyboard.press("ArrowUp");
  await expect(play).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect
    .poll(async () => (await media(page)).ready, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  expect((await media(page)).t).toBeGreaterThanOrEqual(t1 - 0.1);
  expect((await media(page)).t).toBeLessThan(t1 + 3);

  // Left paused, the game's card (Select or Play/Pause) still opens it playing, there.
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  const tp = (await media(page)).t;
  await page.keyboard.press("Escape");
  await expect(card).toHaveAttribute("data-focused", "true");
  await page.keyboard.press(" ");
  await expect
    .poll(async () => (await media(page)).ready, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  expect((await media(page)).t).toBeGreaterThanOrEqual(tp - 0.1);
  expect((await media(page)).t).toBeLessThan(tp + 3);

  // The position survives a reload (settings storage): pause, leave (stored at once,
  // not on the 5 s cadence), reload.
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  const t2 = (await media(page)).t;
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("home")).toBeVisible();
  await page.goto("/");
  await expect(card).toHaveAttribute("data-focused", "true");
  await expect(play).toHaveText(
    `Resume 0:${String(Math.floor(t2)).padStart(2, "0")}`,
  );
  expect(
    Math.abs(Number(await play.getAttribute("data-resume")) - t2),
  ).toBeLessThan(0.1);
});

test("TV-29 stored positions keep the 50 most recent games", async ({
  page,
}) => {
  // 60 old games, oldest first; watching one more drops the 11 oldest.
  await page.addInitScript(() => {
    if (localStorage.getItem("replay.resume")) return; // only before the first load
    const old: Record<string, object> = {};
    for (let i = 0; i < 60; i++)
      old[`g_old${i}`] = { t: 30, playing: false, duration: 100 };
    localStorage.setItem("replay.resume", JSON.stringify(old));
  });
  await openWatch(page, GAME_ID, "?t=6");
  const ids = async () =>
    Object.keys(
      await page.evaluate(
        () =>
          JSON.parse(localStorage.getItem("replay.resume") ?? "{}") as object,
      ),
    );
  await expect.poll(async () => (await ids()).at(-1)).toBe(GAME_ID);
  const kept = await ids();
  expect(kept).toHaveLength(50);
  expect(kept.slice(0, 49)).toEqual(
    Array.from({ length: 49 }, (_, i) => `g_old${i + 11}`),
  );
});
