import { expect, test } from "@playwright/test";
import { FRAME, enterSelectMode, openWatch, transform, video } from "./helpers";

// S-19 Enter triggers follow, S-20 the client transform (D-6), S-21 Back returns to wide.
test("S-19/S-20/S-21 follow, transform, and back at the same timestamp", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);
  await page.keyboard.press("ArrowRight"); // p2

  const before = (await video(page))!.currentTime;
  expect(await transform(page)).toBe("none");

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toBeVisible({ timeout: 2000 });
  await expect(page.getByTestId("followcam-active")).toHaveAttribute("data-player-id", "p2");

  // S-19: the boxes are gone.
  await expect(page.locator('[data-testid^="select-box-"]')).toHaveCount(0);

  // The timestamp is untouched — following is a camera change, not a seek.
  expect(Math.abs((await video(page))!.currentTime - before)).toBeLessThanOrEqual(FRAME);

  // S-20: a real matrix with scale ≈ 1/0.5 = 2.
  await expect.poll(() => transform(page)).toMatch(/^matrix\(/);
  const m1 = parseMatrix(await transform(page));
  expect(m1.scaleX).toBeCloseTo(2, 2);
  expect(m1.scaleY).toBeCloseTo(2, 2);
  // Crop origin is pushed off-screen to the left/top so the rect fills the viewport.
  expect(m1.tx).toBeLessThan(0);
  expect(m1.ty).toBeLessThan(0);

  // S-20: recomputed as time advances — E-13, a seek re-syncs to the same player.
  await page.keyboard.press(".");
  await expect.poll(async () => (await video(page))!.currentTime).toBeGreaterThan(9);
  await expect.poll(async () => parseMatrix(await transform(page)).tx).not.toBe(m1.tx);
  await expect(page.getByTestId("followcam-active")).toHaveAttribute("data-player-id", "p2");

  // S-21: Back → wide, identity transform, same timestamp.
  const atBack = (await video(page))!.currentTime;
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("followcam-active")).toHaveCount(0);
  await expect.poll(() => transform(page)).toBe("none");
  expect(Math.abs((await video(page))!.currentTime - atBack)).toBeLessThanOrEqual(FRAME);
  // Returns to wide playback, not back into select mode.
  await expect(page.locator('[data-testid^="select-box-"]')).toHaveCount(0);
});

test("E-21 reload restores mode and player from the URL", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("followcam-active")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("followcam-active")).toHaveAttribute("data-player-id", "p2");
});

function parseMatrix(t: string) {
  const n = t
    .replace(/^matrix\(|\)$/g, "")
    .split(",")
    .map((v) => Number(v.trim()));
  return { scaleX: n[0], scaleY: n[3], tx: n[4], ty: n[5] };
}
