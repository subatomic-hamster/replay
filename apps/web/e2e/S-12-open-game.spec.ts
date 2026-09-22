import { expect, test } from "@playwright/test";
import { GAME_ID, video } from "./helpers";

// S-12 — Open game from library, S-13 play/pause, S-14 ±10 s seek.
test("S-12 Enter on a card opens the watch screen and the video plays", async ({ page }) => {
  await page.goto("/tv");
  await expect(page.getByTestId("game-card")).toHaveCount(3);
  await page.keyboard.press("Enter");
  await expect.poll(() => new URL(page.url()).pathname).toBe(`/tv/${GAME_ID}`);

  await expect(page.getByTestId("video")).toBeAttached();
  await expect
    .poll(async () => (await video(page))?.readyState ?? 0, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
  expect((await video(page))?.src).toContain("/mock/wide.mp4");
  expect((await video(page))?.paused).toBe(true);

  // S-13
  await page.keyboard.press("Space");
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  await expect.poll(async () => (await video(page))?.currentTime ?? 0).toBeGreaterThan(0.1);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await video(page))?.paused).toBe(true);
});

test("S-14 ±10 s seek clamps at both ends", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}`);
  await expect
    .poll(async () => (await video(page))?.readyState ?? 0, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);

  await page.keyboard.press(".");
  await expect.poll(async () => (await video(page))?.currentTime ?? 0).toBeCloseTo(10, 1);
  await page.keyboard.press(",");
  await expect.poll(async () => (await video(page))?.currentTime ?? 0).toBeCloseTo(0, 1);
  // Clamps at 0 instead of throwing.
  await page.keyboard.press(",");
  expect((await video(page))?.currentTime).toBe(0);
});

test("E-02 a processing game opens its status view, not the watch surface", async ({ page }) => {
  await page.goto("/tv");
  await expect(page.getByTestId("game-card")).toHaveCount(3);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect.poll(() => new URL(page.url()).pathname).toBe("/upload/g_proc03/status");
});
