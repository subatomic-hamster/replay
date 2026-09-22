import { expect, test } from "@playwright/test";
import { FRAME, openWatch, video } from "./helpers";

// S-16 — seek-bar event markers and [ / ] jumps. Fixture events: t_key 3, 8, 14, 17.
test("S-16 markers render and ] / [ jump between event keyframes", async ({ page }) => {
  await openWatch(page);

  const markers = page.getByTestId("event-marker");
  await expect(markers).toHaveCount(4);

  // Marker positions track t_key / duration within 1% of the bar width.
  const track = await page.locator(".seekbar-track").boundingBox();
  const first = await page.locator('[data-event-id="e_0001"]').boundingBox();
  expect(Math.abs((first!.x - track!.x) / track!.width - 3 / 20)).toBeLessThan(0.01);

  await page.keyboard.press("]");
  await expect.poll(async () => (await video(page))!.currentTime).toBeCloseTo(3, 1);
  await page.keyboard.press("]");
  await expect.poll(async () => (await video(page))!.currentTime).toBeCloseTo(8, 1);
  await page.keyboard.press("]");
  await expect.poll(async () => (await video(page))!.currentTime).toBeCloseTo(14, 1);

  await page.keyboard.press("[");
  await expect.poll(async () => (await video(page))!.currentTime).toBeCloseTo(8, 1);
  expect(Math.abs((await video(page))!.currentTime - 8)).toBeLessThanOrEqual(FRAME);
});

// S-32 — bookmarks (H5).
test("S-32 b creates a bookmark event at the current time", async ({ page }) => {
  await openWatch(page);
  await page.keyboard.press("."); // t = 10, clear of every fixture event
  await expect.poll(async () => (await video(page))!.currentTime).toBeCloseTo(10, 1);

  await page.keyboard.press("b");
  const bookmark = page.locator('[data-testid="event-marker"][data-type="bookmark"]');
  await expect(bookmark).toHaveCount(1);
  await expect(page.getByTestId("event-marker")).toHaveCount(5);

  const tKey = Number(await bookmark.getAttribute("data-t-key"));
  expect(Math.abs(tKey - 10)).toBeLessThan(0.2);

  // And it is jumpable like any other event.
  await page.keyboard.press("["); // back to t = 8
  await expect.poll(async () => (await video(page))!.currentTime).toBeCloseTo(8, 1);
  await page.keyboard.press("]");
  await expect.poll(async () => (await video(page))!.currentTime).toBeCloseTo(tKey, 1);
});
