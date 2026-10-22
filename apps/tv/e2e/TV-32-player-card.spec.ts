import { expect, test, type Page } from "@playwright/test";
import { statLine } from "../../../packages/tv-core/src/display";
import { mockApi } from "../../../packages/tv-core/src/mock";
import type { GameEvent } from "../../../packages/tv-core/src/types";
import {
  GAME_ID,
  enterSelectMode,
  focusedBoxId,
  menuTo,
  mockCalls,
  openWatch,
  video,
} from "./helpers";

// D-83 player card. The UI runs on the mock API (synthetic fixture game g_mock01: a
// testsrc2 video with four mock players, not real footage); the real-game checks are in
// docs/progress.md.

/** Synthetic volleyball rallies (hand-written, courtcam's event shapes: rally + serve +
 *  point + one contact per hit, winner_side on the rally). */
function volleyEvents(): GameEvent[] {
  const ev = (
    id: string,
    type: GameEvent["type"],
    t: number,
    extra: Partial<GameEvent> = {},
  ): GameEvent => ({
    id,
    type,
    t_start: t,
    t_key: t,
    t_end: t,
    confidence: 0.6,
    source: "heuristic",
    confirmed: false,
    ...extra,
  });
  return [
    // rally 1: p1 serves, p4 digs, p2 hits it down, side 0 wins → a kill for p2
    ev("r1", "rally", 0, { t_end: 6, winner_side: 0 }),
    ev("s1", "serve", 0.5, { t_start: 0, player_id: "p1", team: 0 }),
    ev("c1", "contact", 0.5, { player_id: "p1", team: 0 }),
    ev("c2", "contact", 2, { player_id: "p4", team: 1 }),
    ev("c3", "contact", 5, { player_id: "p2", team: 0 }),
    ev("pt1", "point", 6, { player_id: "p2", team: 0, winner_side: 0 }),
    // rally 2: p1 serves and nobody touches it → an ace for p1
    ev("r2", "rally", 10, { t_end: 12, winner_side: 0 }),
    ev("s2", "serve", 10.4, { t_start: 10, player_id: "p1", team: 0 }),
    ev("c4", "contact", 10.4, { player_id: "p1", team: 0 }),
    ev("pt2", "point", 12, { player_id: "p1", team: 0, winner_side: 0 }),
    // rally 3: p2's last touch, but side 1 won it → no kill
    ev("r3", "rally", 20, { t_end: 24, winner_side: 1 }),
    ev("c5", "contact", 21, { player_id: "p3", team: 1 }),
    ev("c6", "contact", 23, { player_id: "p2", team: 0 }),
    ev("b1", "block", 23.5, { player_id: "p3", team: 1 }),
  ];
}

const cells = (l: ReturnType<typeof statLine>) =>
  Object.fromEntries(l.cells.map((c) => [c.label, c.value]));

test("TV-32 statLine counts a rally game's kills, aces, blocks, serves and touches (synthetic)", () => {
  const evs = volleyEvents();
  const p1 = statLine(evs, "p1");
  expect(cells(p1)).toEqual({
    Kills: "0",
    Aces: "1",
    Blk: "0",
    Serves: "2",
    Touches: "2",
  });
  expect(p1.missing).toEqual(["digs"]);
  expect(cells(statLine(evs, "p2"))).toMatchObject({ Kills: "1", Aces: "0" });
  expect(cells(statLine(evs, "p3"))).toMatchObject({ Blk: "1", Touches: "1" });
  // no basketball stats on a rally game
  expect(Object.keys(cells(p1))).not.toContain("Pts");

  // rallies whose winner is unknown, contacts nobody is credited with: not 0s, "missing"
  const blind = evs.map((e) =>
    e.type === "contact" || e.type === "block"
      ? { ...e, player_id: undefined }
      : { ...e, winner_side: null },
  );
  const b = statLine(blind, "p1");
  expect(cells(b)).toEqual({ Serves: "2" });
  expect(b.missing).toEqual(["kills", "aces", "blocks", "touches", "digs"]);
});

test("TV-32 statLine on shots: points and FG only once the game has a detected make (synthetic)", async () => {
  const evs = await mockApi.getEvents(await mockApi.getGame(GAME_ID));
  // g_mock01: p1 made 2 of 2, p2 missed 1, p3 made 1
  expect(cells(statLine(evs, "p1"))).toEqual({ Pts: "4", FG: "2/2" });
  expect(cells(statLine(evs, "p2"))).toEqual({ Pts: "0", FG: "0/1" });
  expect(statLine(evs, "p1").missing).toEqual([
    "rebounds",
    "assists",
    "steals",
    "blocks",
  ]);
  // the live CC BY game's shape: shots with made unknown → Shots, no points or FG
  const blind = evs.map((e) => ({ ...e, made: undefined }));
  const l = statLine(blind, "p1");
  expect(cells(l)).toEqual({ Shots: "2" });
  expect(l.missing).toContain("points");
  expect(l.note).toBe("Made or missed is not detected in this game");
  // a dismissed shot (D-11) does not count
  const dismissed = evs.map((e) =>
    e.id === "e_0001" ? { ...e, dismissed: true } : e,
  );
  expect(cells(statLine(dismissed, "p1"))).toEqual({ Pts: "2", FG: "1/1" });
});

/** Follow p2 (untagged) from the select markers; playback goes on. */
async function followP2(page: Page) {
  await openWatch(page);
  await enterSelectMode(page);
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => focusedBoxId(page)).toBe("p2");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toHaveAttribute(
    "data-player-id",
    "p2",
  );
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
}

test("TV-32 Menu while following opens the player card paused; the stat line is the game's events; Back resumes", async ({
  page,
}) => {
  await followP2(page);
  await page.keyboard.press("m");
  const card = page.getByTestId("player-card");
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute("data-player-id", "p2");
  await expect(page.getByTestId("watch")).toHaveAttribute(
    "data-layer",
    "player",
  );
  await expect.poll(async () => (await video(page))?.paused).toBe(true);
  const at = (await video(page))!.currentTime;

  await expect(page.getByTestId("player-card-name")).toHaveText("Player 2");
  await expect(card).toContainText("Anonymous until named");
  // the mock's p2 has a mixed kit (team_mixed): no team line rather than a wrong one
  await expect(page.getByTestId("player-card-team")).toHaveCount(0);
  await expect(card).not.toContainText("Team ");
  // Expected values straight from the events (not through statLine): p2's shots.
  const evs = await mockApi.getEvents(await mockApi.getGame(GAME_ID));
  const shots = evs.filter((e) => e.type === "shot" && e.player_id === "p2");
  const makes = shots.filter((e) => e.made === true).length;
  await expect(page.getByTestId("player-stat-FG")).toHaveAttribute(
    "data-value",
    `${makes}/${shots.length}`,
  );
  await expect(page.getByTestId("player-stat-Pts")).toHaveAttribute(
    "data-value",
    String(2 * makes),
  );
  await expect(page.getByTestId("player-stat-Reb")).toHaveCount(0);
  await expect(page.getByTestId("player-stat-missing")).toContainText(
    "rebounds, assists, steals, blocks",
  );

  // D-pad: Down walks the actions, Up comes back, the ends hold.
  await expect(page.getByTestId("player-card-edit")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("player-card-edit")).toHaveAttribute(
    "data-focused",
    "true",
  );
  for (const id of ["follow", "moments", "moments"]) {
    await page.keyboard.press("ArrowDown");
    await expect(page.getByTestId(`player-card-${id}`)).toHaveAttribute(
      "data-focused",
      "true",
    );
  }
  await expect(page.getByTestId("player-card-follow")).toHaveText(
    "Stop following",
  );
  await expect(page.getByTestId("player-card-profile")).toHaveCount(0); // not linked

  // Back: the card closes, the game plays on from where it paused, still following p2.
  await page.keyboard.press("Escape");
  await expect(card).toHaveCount(0);
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  expect((await video(page))!.currentTime).toBeGreaterThanOrEqual(at - 0.1);
  await expect(page.getByTestId("followcam-active")).toHaveAttribute(
    "data-player-id",
    "p2",
  );
});

test("TV-32 Edit name on the card saves through the API and the follow ring and chip show it", async ({
  page,
}) => {
  await followP2(page);
  await page.keyboard.press("m");
  await page.keyboard.press("Enter"); // Name this player
  const dialog = page.getByTestId("player-name-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("data-player-id", "p2");
  const press = async (key: string, n = 1) => {
    for (let i = 0; i < n; i++) await page.keyboard.press(key);
  };
  // no presets: row 0 is A..J. Z = row 2 col 5, O = row 1 col 4, E = row 0 col 4.
  await press("ArrowDown", 2);
  await press("ArrowRight", 5);
  await press("Enter");
  await press("ArrowUp");
  await press("ArrowLeft");
  await press("Enter");
  await press("ArrowUp");
  await press("Enter");
  await expect(page.getByTestId("player-name-value")).toHaveText("Zoe");
  await press("ArrowDown", 3); // control row, col 4 clamps to CANCEL
  await press("ArrowLeft"); // SAVE
  await press("Enter");

  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId("player-card-status")).toHaveText("Name saved");
  await expect(page.getByTestId("player-card-name")).toHaveText("Zoe");
  const patch = (await mockCalls(page)).find((c) => c.method === "PATCH");
  expect(patch).toEqual({
    method: "PATCH",
    path: `/games/${GAME_ID}/players/p2`,
    body: { name: "Zoe" },
  });
  // the card keeps the remote after the dialog: Back closes it
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("player-card")).toHaveCount(0);
  await expect(page.getByTestId("followcam-active")).toContainText(
    "Following Zoe",
  );
  await expect(page.getByTestId("follow-frame")).toContainText("Zoe");
});

/** Follow p1 (Marcus, linked to a profile) and open the card on them. */
async function cardOnP1(page: Page) {
  await openWatch(page);
  await enterSelectMode(page);
  await expect.poll(() => focusedBoxId(page)).toBe("p1");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toHaveAttribute(
    "data-player-id",
    "p1",
  );
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  await page.keyboard.press("m");
  await expect(page.getByTestId("player-card")).toHaveAttribute(
    "data-player-id",
    "p1",
  );
  await expect.poll(async () => (await video(page))?.paused).toBe(true);
}

test("TV-32 a failed name save says so on the card and keeps the old name", async ({
  page,
}) => {
  await cardOnP1(page);
  // the API refuses the PATCH the way the real client reports it (status + message)
  await page.evaluate(() => {
    const w = window as unknown as {
      __replayMock: {
        api: { patchPlayer: (...a: unknown[]) => Promise<unknown> };
        ApiError: new (status: number, msg: string) => Error;
      };
    };
    w.__replayMock.api.patchPlayer = () =>
      Promise.reject(new w.__replayMock.ApiError(503, "Service Unavailable"));
  });
  await page.keyboard.press("Enter"); // Edit name
  const value = page.getByTestId("player-name-value");
  await expect(value).toHaveText("Marcus");
  await page.keyboard.press("Enter"); // A: the name changes
  await expect(value).not.toHaveText("Marcus");
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowDown");
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowLeft");
  for (let i = 0; i < 2; i++) await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("player-name-key-SAVE")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");

  const status = page.getByTestId("player-card-status");
  await expect(status).toHaveText(
    "Couldn't save the name (503: Service Unavailable)",
  );
  await expect(status).toHaveAttribute("data-error", "true");
  await expect(page.getByTestId("player-card-name")).toHaveText("Marcus");
  await expect(page.getByTestId("player-card-team")).toHaveAttribute(
    "data-team",
    "0",
  );
  // the card keeps the remote; Back closes it and the ring still says Marcus
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("player-card")).toHaveCount(0);
  await expect(page.getByTestId("followcam-active")).toContainText(
    "Following Marcus",
  );
});

test("TV-32 View profile from the card: one Back returns to the card, paused where it was; the next Back plays on", async ({
  page,
}) => {
  await cardOnP1(page);
  const at = (await video(page))?.currentTime ?? -1;
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("player-card-profile")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile")).toBeVisible();
  await expect(page.getByTestId("profile-name")).toHaveText("Marcus");

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("profile")).toHaveCount(0);
  await expect(page.getByTestId("player-card")).toHaveAttribute(
    "data-player-id",
    "p1",
  );
  // still following p1 (the chip hides under the card)
  const watch = page.getByTestId("watch");
  await expect(watch).toHaveAttribute("data-mode", "follow");
  await expect(watch).toHaveAttribute("data-followed", "p1");
  await expect
    .poll(async () => (await video(page))?.currentTime ?? -1)
    .toBeCloseTo(at, 0);
  expect((await video(page))?.paused).toBe(true);

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("player-card")).toHaveCount(0);
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  await expect(page.getByTestId("followcam-active")).toHaveAttribute(
    "data-player-id",
    "p1",
  );
});

test("TV-32 Player details from Do more while picking; Their moments filters Moments; Menu elsewhere is Do more", async ({
  page,
}) => {
  await openWatch(page);
  // not following: Menu opens Do more as before
  await page.keyboard.press("m");
  await expect(page.getByTestId("domore")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("domore")).toHaveCount(0);

  // picking (paused on the markers), the focused player: p1, Marcus, linked to a profile
  await enterSelectMode(page);
  await expect.poll(() => focusedBoxId(page)).toBe("p1");
  await menuTo(page, "follow-card");
  await expect(page.getByTestId("follow-card")).toContainText("Marcus");
  await page.keyboard.press("Enter");
  const card = page.getByTestId("player-card");
  await expect(card).toHaveAttribute("data-player-id", "p1");
  await expect(page.getByTestId("player-card-name")).toHaveText("Marcus");
  await expect(page.getByTestId("player-card-follow")).toHaveText(
    "Follow Marcus",
  );
  await expect(page.getByTestId("player-card-profile")).toBeVisible();
  // Their moments: the Moments layer with only p1's
  const moments = await mockApi.getMoments(GAME_ID);
  const mine = moments.filter((m) => m.player?.id === "p1");
  expect(mine.length).toBeGreaterThan(0);
  await expect(page.getByTestId("player-card-moments")).toHaveText(
    `Their moments (${mine.length})`,
  );
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(card).toHaveCount(0);
  await expect(page.getByTestId("watch")).toHaveAttribute(
    "data-layer",
    "moments",
  );
  const cards = page.getByTestId("moment-card");
  await expect(cards).toHaveCount(mine.length);
  expect(
    (
      await cards.evaluateAll((els) =>
        els.map((e) => e.getAttribute("data-moment-id")),
      )
    ).sort(),
  ).toEqual(mine.map((m) => m.id).sort());
});
