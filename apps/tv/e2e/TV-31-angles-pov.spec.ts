// Replay angles and the players' views are reachable from anywhere in the player, by
// remote: Do more → Replay angles opens the room on the nearest play at its first cut (a
// game with no replays keeps the tile, says why, and cannot choose it), the player's view
// is one cut in the room (Left/Right), Up on it switches player, and Moments → Down opens
// the replay of a moment's play. Mock g_mock01: play_0001 covers 0–20 s with four angles,
// POVs for p1 (Marcus) and p2 (Jordan) and a scene; g_pickle4 has no replays.
// The mock serves every angle as /mock/wide.mp4?angle=<id> (MOCK, not pipeline output).
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, media, menuTo, openWatch, smallText } from "./helpers";

const replay = (page: Page) => page.getByTestId("replay");

test("TV-31 Player's view: a cut in the room, Up switches player, honest label, Back", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=6");
  await menuTo(page, "nav-replays");
  await expect(page.getByTestId("nav-replays")).toContainText("Replay angles");
  await page.keyboard.press("Enter");
  await expect(replay(page)).toHaveAttribute("data-angle", "wide");
  await expect(page.getByTestId("context-chip")).toContainText("Replay angles");

  // Left from the first cut wraps to the players' view slot: the key player's first
  await page.keyboard.press("ArrowLeft");
  await expect(replay(page)).toHaveAttribute("data-pov", "p1");
  await expect(replay(page)).toHaveAttribute("data-tier", "C");
  await expect(replay(page)).toHaveAttribute("data-cuts", "5");
  await expect(page.getByTestId("replay-angle-label")).toHaveText(
    "Player's view · Marcus",
  );
  await expect(page.getByTestId("replay-tier-badge")).toHaveText(
    "Virtual replay",
  );
  await expect(page.getByTestId("pov-honesty")).toHaveText(
    "A recreated player's-eye view, not a camera",
  );
  await expect
    .poll(async () => (await media(page)).src)
    .toContain("angle=pov:p1");
  await expect(page.getByTestId("legend-▲")).toHaveAttribute(
    "data-label",
    "Next player",
  );
  await expect(page.getByTestId("key-legend").locator("> *")).toHaveCount(3);
  expect(await smallText(page)).toEqual([]);

  await page.keyboard.press("ArrowUp"); // the next player's eyes
  await expect(replay(page)).toHaveAttribute("data-pov", "p2");
  await expect(page.getByTestId("replay-angle-label")).toHaveText(
    "Player's view · Jordan",
  );
  await page.keyboard.press("ArrowUp"); // wraps
  await expect(replay(page)).toHaveAttribute("data-pov", "p1");
  await page.keyboard.press("ArrowLeft"); // out of the POV slot, into the other angles
  await expect(replay(page)).toHaveAttribute("data-angle", "orbit");
  await expect(replay(page)).toHaveAttribute("data-pov", "");

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
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
  await expect(page.getByTestId("moment-angles")).toHaveText("▼ Replay angles");
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

test("TV-31 no replays: the Replay angles tile stays, says why, and cannot be chosen", async ({
  page,
}) => {
  await openWatch(page, "g_pickle4");
  await menuTo(page, "nav-replays");
  await expect(page.getByTestId("nav-replays")).toContainText(
    /Not ready for this game|Getting ready/,
  );
  expect(await smallText(page)).toEqual([]);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("domore")).toBeVisible();
  await expect(page.getByTestId("replay")).toHaveCount(0);
  for (const id of ["angle-recorded", "action-free-view", "action-pov"])
    await expect(page.getByTestId(id)).toHaveCount(0);
});
