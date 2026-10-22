// Pure-logic checks for the modules apps/tv shares with apps/web (no page).
import { expect, test } from "@playwright/test";
import {
  createFollowCam,
  cropTransform,
} from "../../../packages/tv-core/src/follow";
import type { TrackPlayer } from "../../../packages/tv-core/src/types";
import { createClock } from "../../../packages/tv-core/src/clock";
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

// D-82 follow-cam on synthetic tracks: `who(t)` lists the boxes on court at t.
const fakeTracks = (who: (t: number) => TrackPlayer[]) => ({ playersAt: who });
const at = (id: string, x: number, y = 0.4, h = 0.16): TrackPlayer => ({
  id,
  bb: [x, y, h * 0.3, h],
});
/** Run the camera at 60 fps from t0 to t1 (media time = wall time, playing). */
function run(
  cam: ReturnType<typeof createFollowCam>,
  t0: number,
  t1: number,
  each?: (t: number, v: ReturnType<typeof cam.step>) => void,
  zoom = true,
) {
  for (let t = t0; t <= t1 + 1e-9; t += 1 / 60) {
    const v = cam.step(t, 1 / 60, zoom); // not inside `each?.()`: it would skip the step
    each?.(t, v);
  }
}
const inside = (b: number[], r: number[]) =>
  b[0] >= r[0] - 1e-9 &&
  b[0] + b[2] <= r[0] + r[2] + 1e-9 &&
  b[1] >= r[1] - 1e-9 &&
  b[1] + b[3] <= r[1] + r[3] + 1e-9;

test("follow-cam: moves on the first frame, then keeps a running player in the window", () => {
  // Across the court and back in 8 s, 0.2 of the frame per second at the fastest.
  const x = (t: number) => 0.45 + 0.4 * Math.sin(t * 0.5);
  const cam = createFollowCam(
    fakeTracks((t) => [at("p1", x(t))]),
    "p1",
  );
  const first = cam.step(0, 1 / 60, true);
  expect(first.rect[2]).toBeLessThan(1); // already zooming in
  expect(first.box).not.toBeNull();
  const xs: number[] = [];
  let outside = 0;
  run(cam, 1 / 60, 30, (t, v) => {
    xs.push(v.rect[0]);
    if (t > 1.5 && !inside(v.box!, v.rect)) outside++;
  });
  expect(outside).toBe(0);
  // It pans the whole time (not parked) and is 16:9: zoom 2.5 × box height = 0.4.
  expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan(0.4);
  const r = cam.current().rect;
  expect(r[3]).toBeCloseTo(0.4, 2);
  expect(r[2]).toBeCloseTo(0.4, 2);
  // ... and it leads: moving right, the box sits left of the window's centre.
  const v = createFollowCam(
    fakeTracks((t) => [at("p1", 0.2 + 0.15 * t)]),
    "p1",
  );
  run(v, 0, 2);
  const { rect, box } = v.current();
  expect(box![0] + box![2] / 2).toBeLessThan(rect[0] + rect[2] / 2);
});

test("follow-cam: near the frame edge it zooms in a little to keep the player centred", () => {
  // Player 26 at 0:38 of the Nottingham game: box centre x 0.86, 0.08 of the frame tall.
  const cam = createFollowCam(
    fakeTracks(() => [at("p1", 0.848, 0.43, 0.08)]),
    "p1",
  );
  run(cam, 0, 4);
  const { rect } = cam.current();
  const off = 0.86 - (rect[0] + rect[2] / 2);
  expect(Math.abs(off)).toBeLessThan(0.025); // 0.06 with the 0.4 window
  expect(rect[3]).toBeGreaterThanOrEqual(0.32 - 1e-6); // never past ~3.1x on 1080p
  expect(rect[0] + rect[2]).toBeLessThanOrEqual(1 + 1e-9);
});

test("follow-cam: hands off only when unambiguous, never across teams or into a crowd", () => {
  const team: Record<string, number> = { p1: 0, p9: 0, p8: 0, p2: 0, p3: 1 };
  /** Follow p1 (on court until 5 s at x 0.5) for 6 s; which id is the camera on? */
  const after = (others: (t: number) => TrackPlayer[]) => {
    const cam = createFollowCam(
      fakeTracks((t) => [...(t < 5 ? [at("p1", 0.5)] : []), ...others(t)]),
      "p1",
      16 / 9,
      (id) => team[id],
    );
    run(cam, 0, 6);
    return cam.current().id;
  };
  const from = (t0: number, p: TrackPlayer) => (t: number) =>
    t >= t0 ? [p] : [];
  // a new id where p1 vanished (p2 far away): the same person, carried on
  expect(after((t) => [...from(5.2, at("p9", 0.51))(t), at("p2", 0.1)])).toBe(
    "p9",
  );
  // an id born on top of p1 half a second before p1 ended (a duplicate): carried on
  expect(after(from(4.5, at("p9", 0.505)))).toBe("p9");
  // the other team at the very spot: never
  expect(after(from(5.2, at("p3", 0.5)))).toBe("p1");
  // two new ids at the spot (a huddle): ambiguous, hold
  expect(
    after((t) => [
      ...from(5.2, at("p9", 0.51))(t),
      ...from(5.2, at("p8", 0.49))(t),
    ]),
  ).toBe("p1");
  // someone on court nearby all along (a screen): another player, hold
  expect(after(() => [at("p2", 0.53)])).toBe("p1");
  // ids that are people (game.tracks.people, D-89): the new id is someone else, hold
  const cam = createFollowCam(
    fakeTracks((t) => [
      ...(t < 5 ? [at("p1", 0.5)] : []),
      ...from(5.2, at("p9", 0.51))(t),
    ]),
    "p1",
    16 / 9,
    (id) => team[id],
    true,
  );
  run(cam, 0, 6);
  expect(cam.current().id).toBe("p1");
});

test("follow-cam: a gap holds the spot and widens slowly; Back eases to exactly wide", () => {
  const who = (t: number) => (t < 3 ? [at("p1", 0.3)] : [at("p5", 0.9)]);
  const cam = createFollowCam(fakeTracks(who), "p1");
  run(cam, 0, 3);
  const before = cam.current().rect;
  const hs: number[] = [];
  let maxStep = 0;
  let prev = before;
  run(cam, 3 + 1 / 60, 7, (_t, v) => {
    hs.push(v.rect[3]);
    maxStep = Math.max(maxStep, Math.abs(v.rect[0] - prev[0]));
    prev = v.rect;
  });
  expect(cam.current().id).toBe("p1"); // p5 is far away: not us
  expect(cam.current().lost).toBeGreaterThan(3.9); // the screen offers a re-pick ...
  expect(cam.current().last?.[0]).toBeCloseTo(0.3, 3); // ... near where p1 was
  expect(hs[10]).toBeCloseTo(before[3], 2); // holds first ...
  expect(hs[hs.length - 1]).toBeGreaterThan(0.9); // ... then widens to the court
  expect(maxStep).toBeLessThan(0.02); // no jump, eased every frame
  run(cam, 7, 10, undefined, false);
  expect(cam.current().rect).toEqual([0, 0, 1, 1]);
});

test("follow-cam: not seen yet is not lost; lost counts from when it started looking", () => {
  // device: paused right after Select, the chip read "Lost sight of" (lost was Infinity
  // until the first box)
  const late = (t: number) => (t < 12 ? [] : [at("p1", 0.3)]);
  const cam = createFollowCam(fakeTracks(late), "p1");
  expect(cam.current().lost).toBe(0);
  cam.step(10, 1 / 60, true);
  expect(cam.current().lost).toBe(0);
  run(cam, 10 + 1 / 60, 11);
  expect(cam.current().lost).toBeCloseTo(1, 1);
  run(cam, 11, 12.5);
  expect(cam.current().lost).toBe(0);
});

test("clock: Play after a pause does not jump by the pause; extrapolation is capped", () => {
  // Drive the clock by hand: a fake wall clock and animation frame.
  let wall = 0;
  let frame: (() => void) | null = null;
  const g = globalThis as unknown as Record<string, unknown>;
  const saved = [g.requestAnimationFrame, g.cancelAnimationFrame];
  g.requestAnimationFrame = (fn: () => void) => ((frame = fn), 1);
  g.cancelAnimationFrame = () => {};
  const now = Object.getOwnPropertyDescriptor(performance, "now");
  Object.defineProperty(performance, "now", {
    value: () => wall,
    configurable: true,
  });
  try {
    const media = { t: 10, paused: false };
    const clock = createClock({
      currentTime: () => media.t,
      paused: () => media.paused,
    });
    const tick = (ms: number) => {
      wall += ms;
      frame?.();
    };
    tick(16);
    tick(100); // between reports: extrapolated
    expect(clock.now()).toBeCloseTo(10.1, 2);
    media.paused = true;
    tick(16);
    tick(5000); // a 5 s pause
    expect(clock.now()).toBe(10);
    media.paused = false; // Play; the player has not reported yet
    tick(16);
    expect(clock.now()).toBeLessThan(10.05); // was 15.0: the whole pause
    tick(2000); // no report for 2 s (a stall the player has not flagged)
    expect(clock.now()).toBeLessThanOrEqual(10.5);
    clock.stop();
  } finally {
    [g.requestAnimationFrame, g.cancelAnimationFrame] = saved;
    if (now) Object.defineProperty(performance, "now", now);
    else delete (performance as unknown as Record<string, unknown>).now;
  }
});

test("follow-cam: a seek jumps there; a 2560x960 panorama gets a 16:9 window", () => {
  const cam = createFollowCam(
    fakeTracks((t) => [at("p1", t < 50 ? 0.1 : 0.8)]),
    "p1",
    2560 / 960,
  );
  run(cam, 0, 5);
  const [, , w, h] = cam.current().rect;
  expect((w * 2560) / (h * 960)).toBeCloseTo(16 / 9, 3);
  cam.step(60, 1 / 60, true); // seek
  const { rect, box } = cam.current();
  expect(inside(box!, rect)).toBe(true);
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
