// Where each game was left (game time and whether it was playing), so the player comes
// back there from a sub-screen or from Home's "Resume". App state, mirrored to the
// platform's settings storage (localStorage on web, memory on Fire TV: platform/config).
import { loadResume, saveResume } from "./platform/config";

export interface Spot {
  t: number;
  playing: boolean;
  /** the game's length, so Home can tell a finished game from one to resume */
  duration: number;
}

/** Closer than this to either end is not worth a "Resume" on Home. */
const EDGE_S = 5;
const MAX_GAMES = 20;

let spots: Record<string, Spot> = (() => {
  try {
    return JSON.parse(loadResume() || "{}") as Record<string, Spot>;
  } catch {
    return {};
  }
})();

export const resumeSpot = (gameId: string): Spot | null =>
  spots[gameId] ?? null;

/** The time Home offers to resume at, or null (never watched, or near either end). */
export function resumeAt(gameId: string): number | null {
  const s = spots[gameId];
  if (!s || s.t < EDGE_S || (s.duration > 0 && s.t > s.duration - EDGE_S))
    return null;
  return s.t;
}

export function rememberSpot(gameId: string, spot: Spot): void {
  const { [gameId]: prev, ...rest } = spots;
  if (prev && prev.t === spot.t && prev.playing === spot.playing) return;
  // the most recent last, so the oldest falls off
  const ids = Object.keys(rest);
  for (const id of ids.slice(0, Math.max(0, ids.length - (MAX_GAMES - 1))))
    delete rest[id];
  spots = { ...rest, [gameId]: spot };
  saveResume(JSON.stringify(spots));
}
