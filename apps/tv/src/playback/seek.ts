// The player's seek maths (docs/ux/redesign.md "Remote mapping" and "the timeline as a
// court line"): hold acceleration, Rew/FF speeds, moment snap and jumps, storyboard cells.
// Pure, so core.spec.ts pins the numbers.
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
/** The preview snaps to a moment this close to the seek point. */
export const SNAP_S = 3;
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

/** The moment nearest `t` within SNAP_S, or null. */
export function snapTo(moments: Moment[], t: number): Moment | null {
  let best: Moment | null = null;
  for (const m of moments) {
    const d = Math.abs(m.t - t);
    if (d <= SNAP_S && (!best || d < Math.abs(best.t - t))) best = m;
  }
  return best;
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
