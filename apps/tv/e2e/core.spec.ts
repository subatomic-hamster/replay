// Pure-logic checks for the modules apps/tv shares with apps/web (no page).
import { expect, test } from "@playwright/test";
import { cropTransform } from "../../../packages/tv-core/src/follow";
import {
  nextFocus,
  type FocusTarget,
} from "../../../packages/tv-core/src/spatial";
import {
  clipEdited,
  type PlayClip,
} from "../../../packages/tv-core/src/discovery";
import {
  menuStep,
  watchMenu,
  type MenuAction,
  type MenuFocus,
} from "../../../packages/tv-core/src/menu";
import {
  facePhotosError,
  initials,
  statPatch,
  statRows,
  stepStat,
  suggestionKey,
  visibleSuggestions,
} from "../../../packages/tv-core/src/profiles";
import { routeFromPath } from "../src/nav";

const box = (
  id: string,
  x: number,
  y: number,
  w = 0.06,
  h = 0.2,
): FocusTarget => ({
  id,
  cx: x + w / 2,
  cy: y + h / 2,
  w,
  h,
});

test("spatial: overlapping boxes cycle on repeated presses; a lone box is a wall (E-11)", () => {
  // a and b screen each other (centres 0.01 apart), c is far right.
  const targets = [
    box("a", 0.4, 0.4),
    box("b", 0.41, 0.42),
    box("c", 0.8, 0.4),
  ];
  // Right from a: b is mostly below (off-axis), so the cone skips it → c.
  expect(nextFocus(targets, "a", "right")).toBe("c");
  // Down from a: b's centre is 0.02 below, 0.01 across → b (normal cone).
  expect(nextFocus(targets, "a", "down")).toBe("b");
  // Down from b: empty cone, but a overlaps → cycle forward (wrapping) to a.
  expect(nextFocus(targets, "b", "down")).toBe("a");
  // Up from a: empty cone; the group [a, b] steps back and wraps → b.
  expect(nextFocus(targets, "a", "up")).toBe("b");
  // Left from a: same — repeated presses alternate between the screening pair.
  expect(nextFocus(targets, "a", "left")).toBe("b");
  // c overlaps nobody: an empty cone stays put.
  expect(nextFocus(targets, "c", "right")).toBe("c");
  // Without sizes (apps/web's call) overlap cycling is off: E-11 wall.
  const bare = targets.map(({ id, cx, cy }) => ({ id, cx, cy }));
  expect(nextFocus(bare, "b", "down")).toBe("b");
});

test("follow: cropTransform makes the crop rect fill the viewport", () => {
  const { tx, ty, sx, sy } = cropTransform([0.3, 0.22, 0.5, 0.5], 1920, 1080);
  expect(sx).toBe(2);
  expect(sy).toBe(2);
  // The rect's top-left lands on the viewport origin: sx*0.3*W + tx = 0.
  expect(sx * 0.3 * 1920 + tx).toBeCloseTo(0, 6);
  expect(sy * 0.22 * 1080 + ty).toBeCloseTo(0, 6);
});

test("nav: web deep links map to routes", () => {
  expect(routeFromPath("/")).toEqual({ name: "library" });
  expect(routeFromPath("/tv/g1?mode=follow&pid=p3&t=4.5")).toEqual({
    name: "watch",
    gameId: "g1",
    mode: "follow",
    pid: "p3",
    t: 4.5,
  });
  expect(routeFromPath("/tv/pair?game=g1")).toEqual({
    name: "pair",
    gameId: "g1",
  });
  // The folded Highlights / Rallies screens open the player in that way to watch.
  expect(routeFromPath("/tv/g1/highlights?q=Makes")).toEqual({
    name: "watch",
    gameId: "g1",
    way: "highlights",
    q: "Makes",
  });
  expect(routeFromPath("/tv/g1/rallies")).toEqual({
    name: "watch",
    gameId: "g1",
    way: "condensed",
  });
  expect(routeFromPath("/tv/g1?way=condensed&t=3")).toEqual({
    name: "watch",
    gameId: "g1",
    way: "condensed",
    t: 3,
  });
  expect(routeFromPath("/tv/players")).toEqual({ name: "players" });
  expect(routeFromPath("/tv/players?from=g1")).toEqual({
    name: "players",
    from: "g1",
  });
  expect(routeFromPath("/tv/players/pr_00000000a001")).toEqual({
    name: "profile",
    profileId: "pr_00000000a001",
  });
});

test("menu: one top row, groups open in place, Back/Down close a group then the menu", () => {
  const menu = watchMenu(new Set());
  expect(menu.map((e) => e.id)).toEqual([
    "nav-library",
    "action-broadcast",
    "action-captions",
    "menu-game",
    "menu-playback",
    "menu-players",
    "nav-pair",
  ]);
  // Every item of the old flat menu is still somewhere.
  const all = menu.flatMap((e) =>
    e.items ? e.items.map((i) => i.id) : [e.id],
  );
  expect(all).toHaveLength(19);
  expect(new Set(all).size).toBe(19);

  let f: MenuFocus = { group: null, i: 0 };
  expect(menuStep(menu, f, "left").focus).toEqual(f);
  f = menuStep(menu, { group: null, i: 4 }, "select").focus as MenuFocus;
  expect(f).toEqual({ group: "menu-playback", i: 0 });
  expect(menuStep(menu, f, "up").focus).toEqual(f);
  const r = menuStep(menu, { group: "menu-playback", i: 3 }, "select");
  expect(r.run?.action).toBe("spotlight");
  expect(
    menuStep(menu, { group: "menu-playback", i: 4 }, "right").focus,
  ).toEqual({ group: "menu-playback", i: 4 });
  expect(menuStep(menu, f, "back").focus).toEqual({ group: null, i: 4 });
  expect(menuStep(menu, f, "down").focus).toEqual({ group: null, i: 4 });
  expect(menuStep(menu, { group: null, i: 2 }, "back").focus).toBeNull();

  // Hidden actions drop out; a group with nothing left goes too.
  const slim = watchMenu(
    new Set<MenuAction>([
      "broadcast",
      "highlights",
      "review",
      "replays",
      "clips",
      "rallies",
      "search",
    ]),
  );
  expect(slim.map((e) => e.id)).not.toContain("menu-game");
  expect(slim.map((e) => e.id)).not.toContain("action-broadcast");
});

test("profiles: stat rows, D-pad steps, PATCH body, suggestion guard, face photo bounds", () => {
  const rows = statRows({
    stats: { zeta: 1, points: 12, games: 2, rebounds: 5 },
    auto: { zeta: 1, points: 12, games: 2, rebounds: 3 },
    edited: ["rebounds"],
  });
  expect(rows.map((r) => r.key)).toEqual([
    "games",
    "points",
    "rebounds",
    "zeta",
  ]);
  expect(rows.find((r) => r.key === "rebounds")).toMatchObject({
    value: 5,
    auto: 3,
    edited: true,
    editable: true,
  });
  expect(rows.find((r) => r.key === "games")?.editable).toBe(false);
  expect(rows.find((r) => r.key === "zeta")?.label).toBe("Zeta");
  expect(statRows(undefined)).toEqual([]);

  expect(stepStat(0, -1)).toBe(0);
  expect(stepStat(2.6, 1)).toBe(4);
  expect(statPatch("basketball", "rebounds", 4)).toEqual({
    stats: { basketball: { rebounds: 4 } },
  });
  expect(statPatch("basketball", "rebounds", null)).toEqual({
    stats: { basketball: { rebounds: null } },
  });

  const list = [
    {
      game_id: "g1",
      player_id: "p1",
      reasons: [{ kind: "face" as const, similarity: 0.6, votes: 3 }],
    },
    {
      game_id: "g1",
      player_id: "p2",
      reasons: [{ kind: "same_name" as const }],
    },
  ];
  // Never a face suggestion for a profile that did not enroll.
  expect(
    visibleSuggestions({ face_enrolled: false }, list).map(suggestionKey),
  ).toEqual(["g1/p2"]);
  expect(
    visibleSuggestions({ face_enrolled: true }, list).map(suggestionKey),
  ).toEqual(["g1/p1", "g1/p2"]);

  expect(facePhotosError(0)).not.toBeNull();
  expect(facePhotosError(1)).toBeNull();
  expect(facePhotosError(10)).toBeNull();
  expect(facePhotosError(11)).not.toBeNull();
  expect(initials("marcus  lee jr")).toBe("ML");
  expect(initials(" ")).toBe("?");
});

test("clips: `edited` comes from the API; absent (older clips) means not edited", () => {
  const base: PlayClip = {
    id: "c1",
    play_id: "pl1",
    trigger_id: "t1",
    t_start: 0,
    t_end: 1,
    attribution: {},
    participants: [],
    source: "user",
  };
  expect(clipEdited(base)).toBe(false); // a user-sourced clip (e.g. a phone tap) is not "edited"
  expect(clipEdited({ ...base, edited: false })).toBe(false);
  expect(clipEdited({ ...base, edited: true })).toBe(true);
  expect(clipEdited({ ...base, source: "auto", edited: true })).toBe(true);
});
