// §4.8: own nearest-target-in-direction algorithm. Never rely on platform auto-focus
// for in-video targets — the boxes are absolutely positioned over a video surface and
// browser/RN focus engines do the wrong thing with them.

export interface FocusTarget {
  id: string;
  /** Center, in any consistent coordinate space (normalized or px). */
  cx: number;
  cy: number;
  /** Box size in the same space. Only needed for overlap cycling; omit to disable it. */
  w?: number;
  h?: number;
}

export type Direction = "up" | "down" | "left" | "right";

/** Off-axis drift costs more than straight-line distance, so a box dead ahead wins. */
const OFF_AXIS_PENALTY = 2;

/** Two boxes "overlap" when their intersection covers this much of the smaller one. */
const OVERLAP_MIN = 0.3;

function overlaps(a: FocusTarget, b: FocusTarget): boolean {
  if (!a.w || !a.h || !b.w || !b.h) return false;
  const ix = Math.min(a.cx + a.w / 2, b.cx + b.w / 2) - Math.max(a.cx - a.w / 2, b.cx - b.w / 2);
  const iy = Math.min(a.cy + a.h / 2, b.cy + b.h / 2) - Math.max(a.cy - a.h / 2, b.cy - b.h / 2);
  if (ix <= 0 || iy <= 0) return false;
  return (ix * iy) / Math.min(a.w * a.h, b.w * b.h) >= OVERLAP_MIN;
}

/**
 * Nearest candidate inside the 90° cone of `dir` from `fromId`.
 *
 * When the cone is empty but other boxes overlap the focused one (players screening each
 * other, whose centres the cone cannot tell apart), repeated presses cycle through that
 * overlapping group: right/down step forward, left/up step back, in a stable left-to-right
 * order. Otherwise an empty cone returns `fromId` unchanged (E-11).
 */
export function nextFocus(
  targets: FocusTarget[],
  fromId: string | null,
  dir: Direction,
): string | null {
  if (targets.length === 0) return null;
  const from = targets.find((t) => t.id === fromId);
  if (!from) return targets[0].id;

  let best: string | null = null;
  let bestScore = Infinity;
  for (const t of targets) {
    if (t.id === from.id) continue;
    const dx = t.cx - from.cx;
    const dy = t.cy - from.cy;
    let along: number;
    let off: number;
    switch (dir) {
      case "right":
        along = dx;
        off = Math.abs(dy);
        break;
      case "left":
        along = -dx;
        off = Math.abs(dy);
        break;
      case "down":
        along = dy;
        off = Math.abs(dx);
        break;
      case "up":
        along = -dy;
        off = Math.abs(dx);
        break;
    }
    // 90° cone: the along-axis component must dominate the off-axis one.
    if (along <= 0 || off > along) continue;
    const score = Math.hypot(dx, dy) + OFF_AXIS_PENALTY * off;
    if (score < bestScore) {
      bestScore = score;
      best = t.id;
    }
  }
  if (best) return best;

  const group = targets
    .filter((t) => t.id === from.id || overlaps(from, t))
    .sort((a, b) => a.cx - b.cx || a.cy - b.cy || (a.id < b.id ? -1 : 1));
  if (group.length < 2) return from.id;
  const i = group.findIndex((t) => t.id === from.id);
  const step = dir === "right" || dir === "down" ? 1 : -1;
  return group[(i + step + group.length) % group.length].id;
}
