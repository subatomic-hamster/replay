import { expect, test } from "@playwright/test";
import { enterSelectMode, openWatch, video } from "./helpers";

// S-17 select mode on pause, S-23 spotlight overlay, S-22 court inset.
test("S-17 pausing draws a box per on-court player", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);

  const boxes = page.locator('[data-testid^="select-box-"]');
  await expect(boxes).toHaveCount(4);

  // Boxes are positioned from the normalized bb within the surface rect (±2 px).
  const surface = await page.getByTestId("player-surface").boundingBox();
  const box = await page.getByTestId("select-box-p1").boundingBox();
  expect(surface && box).toBeTruthy();
  expect(Math.abs(box!.width - surface!.width * 0.06)).toBeLessThan(2);
  expect(Math.abs(box!.height - surface!.height * 0.2)).toBeLessThan(2);

  // NF-05: paused time does not drift, so the overlay stays put.
  const t0 = (await video(page))?.currentTime;
  await page.waitForTimeout(700);
  expect((await video(page))?.currentTime).toBe(t0);
});

test("S-10 boxes carry their team colour", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);
  await expect(page.getByTestId("select-box-p1")).toHaveCSS("border-color", "rgb(31, 79, 160)");
  await expect(page.getByTestId("select-box-p2")).toHaveCSS("border-color", "rgb(232, 232, 232)");
});

test("S-23 the spotlight overlay dims everything but the focused player", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);
  await expect(page.getByTestId("spotlight-overlay")).toHaveCount(0);
  await page.keyboard.press("s");
  await expect(page.getByTestId("spotlight-overlay")).toBeVisible();
  await page.keyboard.press("s");
  await expect(page.getByTestId("spotlight-overlay")).toHaveCount(0);
});

test("S-22 the court inset plots one dot per tracked player", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);
  await expect(page.getByTestId("court-inset")).toBeVisible();
  await expect(page.locator('[data-testid^="court-dot-"]')).toHaveCount(4);
});
