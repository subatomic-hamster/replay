// §4.8: own nearest-target-in-direction algorithm. Never rely on platform auto-focus
// for in-video targets — the boxes are absolutely positioned over a video surface and
// browser/RN focus engines do the wrong thing with them.

export interface FocusTarget {
  id: string;
  /** Center, in any consistent coordinate space (normalized or px). */
  cx: number;
  cy: number;
}

export type Direction = "up" | "down" | "left" | "right";

/** Off-axis drift costs more than straight-line distance, so a box dead ahead wins. */
const OFF_AXIS_PENALTY = 2;

/**
 * Nearest candidate inside the 90° cone of `dir` from `fromId`.
 * Returns `fromId` unchanged when the cone is empty (E-11).
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
  return best ?? from.id;
}
