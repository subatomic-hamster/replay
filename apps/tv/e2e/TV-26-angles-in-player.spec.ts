// Do more → Replay angles opens the nearest play's angles room directly, at its first cut
// (no thumbnail row: the room is the chooser, Left/Right cut, Down is Free view). Back
// returns to the game at the same time and play state. Free view and Player POV are no
// longer tiles of their own.
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

test("TV-26 Replay angles opens the room on the nearest play; cut; Back at the same time", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=6");
  const t0 = await pauseAt(page, 6);

  await menuTo(page, "nav-replays");
  const tile = page.getByTestId("nav-replays");
  await expect(tile).toContainText("Replay angles");
  await expect(tile).toContainText("Marcus — make (mock)");
  await expect(tile).toHaveAttribute("data-children", "0"); // no thumbnail row
  for (const gone of ["action-free-view", "action-pov"])
    await expect(page.getByTestId(gone)).toHaveCount(0);
  await page.keyboard.press("Enter");

  // The room, at the play's first cut, playing.
  await expect(page.getByTestId("domore")).toHaveCount(0);
  await expect(replay(page)).toBeVisible();
  const first = await replay(page).getAttribute("data-angle");
  expect(first).toBeTruthy();
  await expect
    .poll(async () => (await media(page)).src)
    .toContain(`angle=${first}`);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await page.keyboard.press("ArrowRight");
  await expect(replay(page)).not.toHaveAttribute("data-angle", first!);
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

  // Playing when the room opens: playing again after Back, from the same point.
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await menuTo(page, "nav-replays");
  const t1 = (await media(page)).t;
  await page.keyboard.press("Enter");
  await expect(replay(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  const back = await media(page);
  expect(back.t).toBeGreaterThanOrEqual(t1 - 0.1);
  expect(back.t).toBeLessThan(t1 + 3);
});

test("TV-26 Free view is Down in the room; Back, Back returns to the game at the same time", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=8");
  const t0 = await pauseAt(page, 8);

  await menuTo(page, "nav-replays");
  await page.keyboard.press("Enter");
  await expect(replay(page)).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await expect(replay(page)).toHaveAttribute("data-mode", "free");
  await expect(page.getByTestId("free-view")).toHaveAttribute(
    "data-ready",
    "true",
    { timeout: 15_000 },
  );
  expect(await smallText(page)).toEqual([]);

  await page.keyboard.press("Escape"); // Free view → the angle
  await expect(replay(page)).not.toHaveAttribute("data-mode", "free");
  await page.keyboard.press("Escape"); // → the game
  await expect(page.getByTestId("watch")).toBeVisible();
  await expect
    .poll(async () => Math.abs((await media(page)).t - t0))
    .toBeLessThan(0.1);
});
