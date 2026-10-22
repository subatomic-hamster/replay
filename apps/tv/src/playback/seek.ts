// The player's seek maths (docs/ux/redesign.md "Remote mapping" and "the timeline as a
// court line"): hold acceleration, seek stops (grid + moments), Rew/FF speeds, moment
// jumps, storyboard cells. Pure, so TV-20's maths test pins the numbers.
import type {
  Moment,
  Storyboard,
} from "../../../../packages/tv-core/src/types";

/** Holding Left/Right: 10 s steps, 30 s after 1 s held, 1 min after 3 s, 2 min after 5 s. */
const HOLD_TIERS: [number, number][] = [
  [5000, 120],
  [3000, 60],
  [1000, 30],
  [0, 10],
];
export const holdStep = (heldMs: number) =>
  HOLD_TIERS.find(([ms]) => heldMs >= ms)?.[1] ?? 10;

/** Repeats closer than this are dropped, so a keyboard's fast auto-repeat seeks at the
 *  Fire TV remote's 120 ms pace. */
export const REPEAT_FLOOR_MS = 100;
/** After a release, another tap within this adds to the same seek; then playback resumes. */
export const LINGER_MS = 600;
/** Stops closer than this to the seek point count as "here" (no zero-length steps, and a
 *  moment a hair off a grid point is one stop, not two). */
const SAME_S = 0.25;
/** The first back step from the playing video skips a stop under this far behind, like
 *  Prev: tapping Left 1 s after resuming from 0:40 goes to 0:30, not back to 0:40. */
const BACK_GRACE_S = 2;
/** From this step up (only reached by holding) a grid interval keeps one moment stop. */
const SPARSE_STEP = 60;
const RANK = { score: 0, play: 1, bookmark: 2 } as const;

export interface Stop {
  t: number;
  /** The moment whose start this stop is, or null for a grid point / the game's ends. */
  moment: Moment | null;
}

/**
 * Left/Right: where one step (a tap or a key repeat) of `step` seconds lands from `from`.
 *
 * The stops are the union of
 *   - a grid every `step` s anchored at 0 (0:40, 0:50, …; the step grows as the hold
 *     tiers kick in, so a 30 s tier stops at 0:30, 1:00, …),
 *   - every moment's start (`t_start`, where a moment commits), and
 *   - the game's start and end.
 * A step goes to the next stop strictly beyond `from` in `dir`, so a moment between two
 * grid points is an extra stop, never a replacement: 0:30 → 0:40 → 0:43 Basket → 0:50.
 * A moment within SAME_S of a grid point stands in for it (one stop, with the label).
 * At steps ≥ SPARSE_STEP a dense run of moments must not stall the hold: each grid
 * interval keeps at most one moment, the most important (score > play > bookmark, then
 * the earliest). `live`: `from` is the playing video, not a stop (the gesture's first
 * step), which gives a back step BACK_GRACE_S of slack.
 */
export function nextStop(
  moments: Moment[],
  from: number,
  dir: 1 | -1,
  step: number,
  duration: number,
  live = false,
): Stop {
  const end = duration > 0 ? duration : Infinity;
  // Already at the end (or the start) in that direction: stay.
  if (dir > 0 ? from >= end - SAME_S : from <= SAME_S)
    return { t: from, moment: null };
  const edge = from + dir * (live && dir < 0 ? BACK_GRACE_S : SAME_S);
  const grid =
    dir > 0
      ? Math.min(end, (Math.floor(edge / step) + 1) * step)
      : Math.max(0, (Math.ceil(edge / step) - 1) * step);

  let picks = moments;
  if (step >= SPARSE_STEP) {
    const best = new Map<number, Moment>();
    for (const m of moments) {
      const k = Math.floor(m.t_start / step);
      const b = best.get(k);
      if (
        !b ||
        RANK[m.kind] < RANK[b.kind] ||
        (RANK[m.kind] === RANK[b.kind] && m.t_start < b.t_start)
      )
        best.set(k, m);
    }
    picks = [...best.values()];
  }
  let stop: Stop = { t: grid, moment: null };
  for (const m of picks) {
    const t = Math.max(0, Math.min(end, m.t_start));
    if (dir > 0 ? t <= edge : t >= edge) continue; // not beyond the seek point
    const d = dir * (t - stop.t); // < 0: nearer than the stop so far
    if (stop.moment ? d < 0 : d <= SAME_S) stop = { t, moment: m };
  }
  return stop;
}

/** Rew/FF scrub speeds; each press of the same key goes one faster. */
export const SCRUB_SPEEDS = [2, 4, 8, 16];
/** Transport hides after this much playback without a key (Media3's default). */
export const HIDE_MS = 5000;

/** The next scrub speed for a Rew (-1) / FF (+1) press: faster in the same direction
 *  (capped at 16), back to 2× when the direction flips. */
export function nextScrub(
  cur: { dir: 1 | -1; speed: number } | null,
  dir: 1 | -1,
): { dir: 1 | -1; speed: number } {
  if (!cur || cur.dir !== dir) return { dir, speed: SCRUB_SPEEDS[0] };
  const i = SCRUB_SPEEDS.indexOf(cur.speed);
  return { dir, speed: SCRUB_SPEEDS[Math.min(SCRUB_SPEEDS.length - 1, i + 1)] };
}

/** Index of the moment nearest `t` (-1 when there are none). */
export function nearestIndex(moments: Moment[], t: number): number {
  let best = -1;
  moments.forEach((m, i) => {
    if (best < 0 || Math.abs(m.t - t) < Math.abs(moments[best].t - t)) best = i;
  });
  return best;
}

/** Prev/Next keys: the next moment starting after `now`, or the previous one (a press
 *  within 2 s of a moment's start goes one further back, like a CD player). */
export function jumpMoment(
  moments: Moment[],
  now: number,
  dir: 1 | -1,
): Moment | null {
  if (dir > 0) return moments.find((m) => m.t_start > now + 0.25) ?? null;
  return [...moments].reverse().find((m) => m.t_start < now - 2) ?? null;
}

/** "+2:00" / "−0:30": the seek's distance from where it started. */
export function fmtDelta(s: number): string {
  const a = Math.round(Math.abs(s));
  return `${s < 0 ? "−" : "+"}${Math.floor(a / 60)}:${String(a % 60).padStart(2, "0")}`;
}

/** Where frame `t` sits in the storyboard: its sheet, the cell's offset in the sheet and
 *  the sheet's size (the last sheet holds only the rows it uses), all in sheet pixels. */
export function storyboardCell(sb: Storyboard, t: number) {
  const per = sb.cols * sb.rows;
  const count = sb.count ?? sb.sheets.length * per;
  if (!count || !sb.sheets.length) return null;
  const i = Math.max(0, Math.min(count - 1, Math.floor(t / sb.interval_s)));
  const s = Math.min(sb.sheets.length - 1, Math.floor(i / per));
  const cell = i - s * per;
  const used = Math.min(per, count - s * per);
  return {
    sheet: sb.sheets[s],
    x: (cell % sb.cols) * sb.width,
    y: Math.floor(cell / sb.cols) * sb.height,
    sheetW: sb.cols * sb.width,
    sheetH: Math.ceil(used / sb.cols) * sb.height,
  };
}
