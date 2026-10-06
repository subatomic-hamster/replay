import { expect, test } from "@playwright/test";
import { FRAME, GAME_ID, enterSelectMode, focusedBoxId, menuTo, transform, video } from "./helpers";

// The DoD path on the RN TV app's web build: library → watch → select → follow → back,
// driven only by remote keys (Arrows, Enter = Select, Escape = Back).
test("TV-01 library → watch → select → follow → back → library", async ({ page }) => {
  await page.goto("/");
  const cards = page.getByTestId("game-card");
  await expect(cards.first()).toBeVisible();
  await expect(cards.first()).toHaveAttribute("data-focused", "true");

  // D-pad across the cards and back to the first one.
  await page.keyboard.press("ArrowRight");
  await expect(cards.nth(1)).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowLeft");
  await expect(cards.first()).toHaveAttribute("data-focused", "true");
  await expect(cards.first()).toHaveAttribute("data-game-id", GAME_ID);

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("video")).toBeAttached();
  await expect.poll(async () => (await video(page))?.readyState ?? 0, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("event-marker")).toHaveCount(4);
  await expect(page.getByTestId("court-inset")).toBeVisible();

  // W3: Select pauses the wide shot and opens select mode on the leftmost box.
  await enterSelectMode(page);
  await expect.poll(() => focusedBoxId(page)).toBe("p1");
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => focusedBoxId(page)).toBe("p2");
  await page.keyboard.press("ArrowDown");
  await expect.poll(() => focusedBoxId(page)).toBe("p4");
  await page.keyboard.press("ArrowUp");
  await expect.poll(() => focusedBoxId(page)).toBe("p2");
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => focusedBoxId(page)).toBe("p3");

  // Boxes sit on the player: p3's box matches its normalized bb on the 16:9 surface.
  const surface = (await page.getByTestId("player-surface").boundingBox())!;
  const box = (await page.getByTestId("select-box-p3").boundingBox())!;
  expect(Math.abs((box.x - surface.x) / surface.width - 0.745)).toBeLessThan(0.02);
  expect(Math.abs(box.width / surface.width - 0.06)).toBeLessThan(0.005);

  // W4: Select follows at the same timestamp; the crop transform scales by 1/0.5.
  const before = (await video(page))!.currentTime;
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toBeVisible();
  await expect(page.getByTestId("followcam-active")).toHaveAttribute("data-player-id", "p3");
  await expect(page.locator('[data-testid^="select-box-"]')).toHaveCount(0);
  await expect.poll(async () => (await transform(page))[0], { timeout: 5_000 }).toBeCloseTo(2, 2);
  const [sx, sy, tx] = await transform(page);
  expect(sy).toBeCloseTo(2, 2);
  expect(tx).toBeLessThan(0); // panned right, toward p3
  expect(Math.abs((await video(page))!.currentTime - before)).toBeLessThanOrEqual(FRAME);
  expect(sx).toBeCloseTo(2, 2);
  await expect(page.getByTestId("follow-frame")).toHaveAttribute("data-pid", "p3");

  // Back: wide shot at the same time, identity transform, the frame stays on p3 (W4).
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("followcam-active")).toHaveCount(0);
  await expect.poll(async () => (await transform(page))[0]).toBeCloseTo(1, 3);
  expect(Math.abs((await video(page))!.currentTime - before)).toBeLessThanOrEqual(FRAME);
  await expect(page.getByTestId("follow-frame")).toHaveAttribute("data-pid", "p3");
  await expect(page.getByTestId("mode-pill")).toHaveText("WIDE");

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("game-card").first()).toBeVisible();
});

test("TV-02 Up at the top of select mode opens the action row; spotlight + event jump by D-pad", async ({
  page,
}) => {
  await page.goto(`/tv/${GAME_ID}`);
  await expect.poll(async () => (await video(page))?.readyState ?? 0, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
  await enterSelectMode(page);
  await page.keyboard.press("ArrowUp"); // nothing above p1 → action row
  await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Escape"); // Back closes the menu; select mode is still on

  // ◀ Event / Event ▶ / Spotlight live in the "Playback ▸" group.
  await menuTo(page, "action-next-event");
  const t0 = (await video(page))!.currentTime;
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await video(page))!.currentTime).toBeGreaterThan(t0 + 0.5);
  await expect.poll(async () => {
    const t = (await video(page))!.currentTime;
    return [3, 8, 14, 17].some((k) => Math.abs(t - k) < 0.05);
  }).toBe(true);

  await menuTo(page, "action-spotlight");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("spotlight-overlay")).toBeVisible();
});
