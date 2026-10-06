// Pure-logic checks for the modules apps/tv shares with apps/web (no page).
import { expect, test } from "@playwright/test";
import { cropTransform } from "../../../packages/tv-core/src/follow";
import { nextFocus, type FocusTarget } from "../../../packages/tv-core/src/spatial";
import { routeFromPath } from "../src/nav";

const box = (id: string, x: number, y: number, w = 0.06, h = 0.2): FocusTarget => ({
  id,
  cx: x + w / 2,
  cy: y + h / 2,
  w,
  h,
});

test("spatial: overlapping boxes cycle on repeated presses; a lone box is a wall (E-11)", () => {
  // a and b screen each other (centres 0.01 apart), c is far right.
  const targets = [box("a", 0.4, 0.4), box("b", 0.41, 0.42), box("c", 0.8, 0.4)];
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
  expect(routeFromPath("/tv/pair?game=g1")).toEqual({ name: "pair", gameId: "g1" });
  expect(routeFromPath("/tv/g1/highlights?q=Makes")).toEqual({ name: "highlights", gameId: "g1", q: "Makes" });
});
