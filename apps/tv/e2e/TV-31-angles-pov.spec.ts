// Angles and the players' virtual POVs are reachable from anywhere in the player, by
// remote: Do more → Angles is always there (a game with no replays offers the views it
// has now: the recorded camera and a follow cam), Do more → Player POV picks whose eyes
// (key player first), Up in a POV angle switches player, and Moments → Down opens the
// replay of a moment's play. Mock g_mock01: play_0001 covers 0–20 s with four angles,
// POVs for p1 (Marcus) and p2 (Jordan) and a scene; g_pickle4 has no replays.
// The mock serves every angle as /mock/wide.mp4?angle=<id> (MOCK, not pipeline output).
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, media, menuTo, openWatch, smallText } from "./helpers";

const replay = (page: Page) => page.getByTestId("replay");

test("TV-31 Player POV: chips of the play's players, Up switches, honest label, Back", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=6");
  await menuTo(page, "action-pov");
  await expect(page.getByTestId("action-pov")).toContainText("Player POV");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("domore")).toHaveAttribute(
    "data-row",
    "action-pov",
  );
  const chips = page.locator('[data-testid="domore"] [data-testid^="pov-"]');
  await expect(chips).toHaveCount(2);
  // the key player first, named like everywhere else in the player
  await expect(chips.first()).toHaveAttribute("data-testid", "pov-p1");
  await expect(chips.first()).toContainText("Marcus");
  await menuTo(page, "pov-p2");
  await page.keyboard.press("Enter");

  await expect(replay(page)).toHaveAttribute("data-pov", "p2");
  await expect(replay(page)).toHaveAttribute("data-tier", "C");
  await expect(page.getByTestId("replay-angle-label")).toHaveText(
    "Virtual POV · Jordan",
  );
  await expect(page.getByTestId("pov-honesty")).toContainText(
    "reconstructed court, not a camera",
  );
  await expect
    .poll(async () => (await media(page)).src)
    .toContain("angle=pov:p2");
  await expect(page.getByText("Next player")).toBeVisible();
  expect(await smallText(page)).toEqual([]);

  await page.keyboard.press("ArrowUp"); // the next player's eyes (wraps)
  await expect(replay(page)).toHaveAttribute("data-pov", "p1");
  await page.keyboard.press("ArrowLeft"); // out of the POV slot, into the other angles
  await expect(replay(page)).toHaveAttribute("data-angle", "orbit");
  await expect(replay(page)).toHaveAttribute("data-pov", "");

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
});

test("TV-31 Angles row: one POV thumbnail (the key player's) among the angles", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=6");
  await menuTo(page, "angle-pov:p1");
  await expect(page.getByTestId("angle-pov:p1")).toBeAttached();
  await expect(
    page.locator('[data-testid="domore"]').getByText("Virtual POV · Marcus"),
  ).toBeVisible();
  await expect(page.getByTestId("angle-pov:p2")).toHaveCount(0);
  await page.keyboard.press("Enter");
  await expect(replay(page)).toHaveAttribute("data-pov", "p1");
  await expect(replay(page)).toHaveAttribute("data-cuts", "5");
});

test("TV-31 Moments → Down opens the replay angles of the moment's play", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=7.5");
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  const t0 = (await media(page)).t;
  await page.keyboard.press("ArrowDown");
  const card = page.locator('[data-testid="moment-card"][data-focused="true"]');
  await expect(card).toHaveAttribute("data-angles", "true");
  await expect(page.getByTestId("moment-angles")).toHaveText("▼ Angles");
  expect(await smallText(page)).toEqual([]);

  await page.keyboard.press("ArrowDown");
  await expect(replay(page)).toHaveAttribute("data-play", "play_0001");
  await expect(replay(page)).toHaveAttribute("data-angle", "wide");

  // Back: the game where it was, still paused
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
  await expect
    .poll(async () => Math.abs((await media(page)).t - t0))
    .toBeLessThan(0.1);
});

test("TV-31 no replays: Angles still there, says so, offers the views there are now", async ({
  page,
}) => {
  await openWatch(page, "g_pickle4");
  await menuTo(page, "nav-replays");
  await expect(page.getByTestId("nav-replays")).toContainText(
    "No replay angles for this game",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("domore")).toHaveAttribute(
    "data-row",
    "nav-replays",
  );
  await expect(page.getByTestId("angle-recorded")).toHaveAttribute(
    "data-on",
    "true",
  );
  await expect(page.getByTestId("angle-recorded")).toHaveAttribute(
    "data-focused",
    "true",
  );
  expect(await smallText(page)).toEqual([]);
  // the frame fills its 16:9 tile edge to edge (one storyboard cell, no text padding
  // around it): the sprite sits on whole cells of its sheet. Retried until it holds: the
  // tile's and the sprite's boxes are two reads, and while Do more is still sliding in
  // (or the storyboard, a deferred extra, is still arriving) they come from different
  // frames, a couple of pixels apart (failed once in CI, 2.2 px).
  const sprite = page.getByTestId("angle-recorded").getByTestId("seek-sprite");
  await expect(async () => {
    if (!(await sprite.count())) return;
    const tile = (await sprite.locator("..").boundingBox())!;
    const s = (await sprite.boundingBox())!;
    const cellW = s.width / 10, // 10 columns of 320 x 180 frames
      cellH = (cellW * 180) / 320;
    expect(Math.abs(tile.width - cellW)).toBeLessThan(1.5);
    expect(Math.abs(tile.height - cellH)).toBeLessThan(1.5);
    for (const [off, cell] of [
      [tile.x - s.x, cellW],
      [tile.y - s.y, cellH],
    ]) {
      const r = ((off % cell) + cell) % cell;
      expect(Math.min(r, cell - r)).toBeLessThan(1.5);
    }
  }).toPass({ timeout: 5000 });
  await page.keyboard.press("Enter"); // the recorded camera is what is playing
  await expect(page.getByTestId("domore")).toHaveCount(0);
  await expect(page.getByTestId("replay")).toHaveCount(0);
});
