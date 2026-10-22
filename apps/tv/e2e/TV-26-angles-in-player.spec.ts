// Do more → Angles: thumbnails of the nearest play's replay angles (and Free view, when
// the play has a scene) in the layer; choosing one plays that angle in the player, Left/
// Right cut, and Back returns to the game at the same time and play state. Free view
// chosen straight from Do more goes back to the game on Back too.
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, media, menuTo, openWatch, smallText } from "./helpers";

const replay = (page: Page) => page.getByTestId("replay");

/** Pause the game at about `t` s. */
async function pauseAt(page: Page, t: number) {
  await expect
    .poll(async () => (await media(page)).t, { timeout: 10_000 })
    .toBeGreaterThan(t);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  return (await media(page)).t;
}

test("TV-26 Angles in the player: thumbnails, play an angle, cut, Back at the same time", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=6");
  const t0 = await pauseAt(page, 6);

  await menuTo(page, "nav-replays");
  await expect(page.getByTestId("nav-replays")).toContainText(
    "Marcus — make (mock)",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("domore")).toHaveAttribute(
    "data-row",
    "nav-replays",
  );
  const thumbs = page.locator('[data-testid="domore"] [data-testid^="angle-"]');
  // four angles, one virtual POV (the key player's; the players' POVs share it), Free view
  await expect(thumbs).toHaveCount(6);
  await expect(thumbs.nth(4)).toHaveAttribute("data-testid", "angle-pov:p1");
  await expect(thumbs.last()).toHaveAttribute("data-testid", "angle-free");
  await expect(page.getByText("Broadcast high")).toBeVisible();
  await page.waitForTimeout(300);
  // the whole thumbnails keep to the safe zone; the next one peeks at the clipped edge
  const all = await thumbs.all();
  for (const t of all.slice(0, 5)) {
    const b = (await t.boundingBox())!;
    expect(b.x).toBeGreaterThanOrEqual(96 - 12);
    expect(b.x + b.width).toBeLessThanOrEqual(1920 - 96 + 12);
  }
  expect((await all[5].boundingBox())!.x).toBeLessThan(1920 - 96);
  expect(await smallText(page)).toEqual([]);

  // Broadcast high plays in the player.
  await menuTo(page, "angle-broadcast_high");
  await page.keyboard.press("Enter");
  await expect(replay(page)).toHaveAttribute("data-angle", "broadcast_high");
  await expect
    .poll(async () => (await media(page)).src)
    .toContain("angle=broadcast_high");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await page.keyboard.press("ArrowRight");
  await expect(replay(page)).toHaveAttribute("data-angle", "orbit");
  expect(await smallText(page)).toEqual([]);

  // Back: the game where it was, still paused.
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
  await expect
    .poll(async () => (await media(page)).src)
    .toMatch(/\/mock\/wide\.mp4$/);
  await expect
    .poll(async () => Math.abs((await media(page)).t - t0))
    .toBeLessThan(0.1);
  await page.waitForTimeout(300);
  expect((await media(page)).paused).toBe(true);

  // Playing when an angle opens: playing again after Back, from the same point.
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await menuTo(page, "angle-wide");
  const t1 = (await media(page)).t;
  await page.keyboard.press("Enter");
  await expect(replay(page)).toHaveAttribute("data-angle", "wide");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  const back = await media(page);
  expect(back.t).toBeGreaterThanOrEqual(t1 - 0.1);
  expect(back.t).toBeLessThan(t1 + 3);
});

test("TV-26 Free view from Do more: the play's scene, Back to the game at the same time", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=8");
  const t0 = await pauseAt(page, 8);

  // its own tile, in the spec's place, and the last thumbnail of Angles
  await menuTo(page, "action-free-view");
  await page.keyboard.press("Enter");
  await expect(replay(page)).toHaveAttribute("data-mode", "free");
  await expect(page.getByTestId("free-view")).toHaveAttribute(
    "data-ready",
    "true",
    { timeout: 15_000 },
  );
  await expect(replay(page)).toHaveAttribute("data-paused", "false");
  expect(await smallText(page)).toEqual([]);

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
  await expect
    .poll(async () => Math.abs((await media(page)).t - t0))
    .toBeLessThan(0.1);

  await menuTo(page, "angle-free");
  await page.keyboard.press("Enter");
  await expect(replay(page)).toHaveAttribute("data-mode", "free");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
});
