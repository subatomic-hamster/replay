// TV-39 slow motion in the replay angles: Rewind (◀◀, `,` on the keyboard) plays the
// angle at 0.5× with a "0.5×" badge in the bug, the legend names it ("Slow-mo"), a cut to
// another angle keeps it, and Rewind again (or Fast-forward) is normal speed. Also the
// demo's path: Home → Highlights → the best play → Do more → Replay angles → slow-mo.
// SYNTHETIC mock g_mock01; every angle is /mock/wide.mp4?angle=<id> (a real src swap).
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, menuTo, smallText } from "./helpers";

async function video(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v
      ? { rate: v.playbackRate, src: v.currentSrc, ready: v.readyState }
      : { rate: -1, src: "", ready: 0 };
  });
}

const replay = (page: Page) => page.getByTestId("replay");

async function slowMoWorks(page: Page) {
  await expect(page.getByTestId("legend-◀◀")).toHaveAttribute(
    "data-label",
    "Slow-mo",
  );
  await expect(page.getByTestId("replay-rate")).toHaveCount(0);
  await expect(replay(page)).toHaveAttribute("data-rate", "1");

  await page.keyboard.press(","); // Rewind: slow-mo on
  await expect(replay(page)).toHaveAttribute("data-rate", "0.5");
  await expect(page.getByTestId("replay-rate")).toHaveText("0.5×");
  await expect.poll(async () => (await video(page)).rate).toBe(0.5);
  expect(await smallText(page)).toEqual([]);
  await page.screenshot({ path: test.info().outputPath("slow-mo.png") });

  // a cut to another angle stays slow (the new source loads at 0.5× too)
  const angle = await replay(page).getAttribute("data-angle");
  await page.keyboard.press("ArrowRight");
  await expect(replay(page)).not.toHaveAttribute("data-angle", angle ?? "");
  await expect
    .poll(async () => (await video(page)).src)
    .not.toContain(`angle=${angle}`);
  await expect.poll(async () => (await video(page)).ready).toBeGreaterThan(0);
  await expect.poll(async () => (await video(page)).rate).toBe(0.5);
  await expect(page.getByTestId("replay-rate")).toHaveText("0.5×");

  await page.keyboard.press(","); // again: normal speed
  await expect(page.getByTestId("replay-rate")).toHaveCount(0);
  await expect.poll(async () => (await video(page)).rate).toBe(1);
  await page.keyboard.press(",");
  await expect.poll(async () => (await video(page)).rate).toBe(0.5);
  await page.keyboard.press("."); // Fast-forward: normal speed
  await expect.poll(async () => (await video(page)).rate).toBe(1);
  await expect(page.getByTestId("replay-rate")).toHaveCount(0);
}

test("TV-39 Rewind toggles slow-mo in the replay angles, kept across cuts", async ({
  page,
}) => {
  await page.goto(`/tv/${GAME_ID}/replays/play_0001`);
  await expect.poll(async () => (await video(page)).ready).toBeGreaterThan(1);
  await expect(page.getByTestId("key-legend").locator("> *")).toHaveCount(4);
  await slowMoWorks(page);
});

test("TV-39 demo path: Highlights → best play → Replay angles → slow-mo", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.locator(`[data-testid="game-card"][data-game-id="${GAME_ID}"]`),
  ).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter"); // Home → Highlights
  await expect(page.getByTestId("highlights-layer")).toBeVisible();
  const best = page.locator('[data-testid="highlight-card"][data-best="true"]');
  for (let k = 0; k < 8; k++) {
    if ((await best.getAttribute("data-focused")) === "true") break;
    await page.keyboard.press("ArrowRight");
  }
  await expect(best).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("best-play-card")).toBeVisible();

  await menuTo(page, "nav-replays"); // Do more → Replay angles
  await page.keyboard.press("Enter");
  await expect(replay(page)).toBeVisible();
  await expect.poll(async () => (await video(page)).ready).toBeGreaterThan(1);
  await slowMoWorks(page);

  // Back: the play again, then the list
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("highlights-layer")).toBeVisible();
});
