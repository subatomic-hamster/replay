import { expect, test, type Locator, type Page } from "@playwright/test";
import { enterSelectMode, focusedBoxId, openWatch, video } from "./helpers";

// S-22b — W4's follow frame: the amber rounded rect that stays on the followed player in
// follow mode (where it has to be mapped through the crop rect the transform uses) and
// keeps sitting on them after Escape returns to the wide shot.

async function centre(loc: Locator) {
  const b = await loc.boundingBox();
  if (!b) throw new Error("no bounding box");
  return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
}

/** Seek exactly — the ±10 s / ±5 s keys cannot land inside a 1 s gap. */
async function seekTo(page: Page, t: number) {
  await page.evaluate((to) => {
    document.querySelector<HTMLVideoElement>('[data-testid="video"]')!.currentTime = to;
  }, t);
  await expect.poll(async () => (await video(page))!.currentTime).toBeCloseTo(t, 1);
}

async function followP1(page: Page) {
  await openWatch(page);
  await enterSelectMode(page);
  expect(await focusedBoxId(page)).toBe("p1"); // leftmost box is the default focus
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toHaveAttribute("data-player-id", "p1");
}

test("S-22b the follow frame tracks the player inside the zoomed viewport", async ({ page }) => {
  await followP1(page);

  const frame = page.getByTestId("follow-frame");
  await expect(frame).toBeVisible({ timeout: 2000 });
  await expect(frame).toHaveAttribute("data-pid", "p1");

  // Mapped through the crop rect, so it lands on the player in the zoomed view rather
  // than off-screen where the raw frame coordinates would put it.
  const surface = (await page.getByTestId("player-surface").boundingBox())!;
  const c = await centre(frame);
  expect(c.x).toBeGreaterThan(surface.x);
  expect(c.x).toBeLessThan(surface.x + surface.width);
  expect(c.y).toBeGreaterThan(surface.y);
  expect(c.y).toBeLessThan(surface.y + surface.height);

  // It moves while the video plays.
  await page.keyboard.press("Space");
  await expect.poll(async () => (await video(page))!.paused).toBe(false);
  const a = await centre(frame);
  await expect
    .poll(async () => {
      const b = await centre(frame);
      return Math.abs(b.x - a.x) + Math.abs(b.y - a.y);
    }, { timeout: 2000 })
    .toBeGreaterThan(0.5);
  await page.keyboard.press("Space");
});

test("S-22b Escape keeps the frame on the same player in the wide shot", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);
  expect(await focusedBoxId(page)).toBe("p1");
  // Where p1's select box sits at this (paused) timestamp.
  const boxAt = await centre(page.getByTestId("select-box-p1"));

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("follow-frame")).toBeVisible({ timeout: 2000 });
  await page.keyboard.press("Escape");

  // Wide shot, nothing selected any more — but the frame stays on p1 (D-6 / W4).
  await expect(page.getByTestId("followcam-active")).toHaveCount(0);
  const frame = page.getByTestId("follow-frame");
  await expect(frame).toBeVisible();
  await expect(frame).toHaveAttribute("data-pid", "p1");

  const c = await centre(frame);
  expect(Math.abs(c.x - boxAt.x)).toBeLessThanOrEqual(8);
  expect(Math.abs(c.y - boxAt.y)).toBeLessThanOrEqual(8);
});

test("S-22b the frame fades out where the player has no track, and returns", async ({ page }) => {
  await followP1(page);
  const frame = page.getByTestId("follow-frame");
  await expect(frame).toBeVisible({ timeout: 2000 });

  // The mock scripts an occlusion for p1 over [12, 13) s.
  await seekTo(page, 12.5);
  await expect(frame).toBeHidden({ timeout: 2000 });

  await seekTo(page, 14);
  await expect(frame).toBeVisible({ timeout: 2000 });
});
