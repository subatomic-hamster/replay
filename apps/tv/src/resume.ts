// Where each game was left (game time and whether it was playing), so the player comes
// back there from a sub-screen or from Home's "Resume". App state, mirrored to the
// platform's settings storage (localStorage on web, SharedPreferences on Fire TV:
// platform/config) at most every SAVE_MS, and at once on a pause, a leave or the app
// going to the background.
import { AppState } from "react-native";
import { loadResume, saveResume } from "./platform/config";

export interface Spot {
  t: number;
  playing: boolean;
  /** the game's length, so Home can tell a finished game from one to resume */
  duration: number;
}

/** Closer than this to either end is not worth a "Resume" on Home. */
const EDGE_S = 5;
const MAX_GAMES = 50;
const SAVE_MS = 5000;

let spots: Record<string, Spot> = (() => {
  try {
    return JSON.parse(loadResume() || "{}") as Record<string, Spot>;
  } catch {
    return {};
  }
})();

let savedAt = 0;
let timer: ReturnType<typeof setTimeout> | null = null;

function save() {
  if (timer) clearTimeout(timer);
  timer = null;
  savedAt = Date.now();
  saveResume(JSON.stringify(spots));
}

AppState.addEventListener("change", (s) => {
  if (s !== "active" && timer) save();
});

export const resumeSpot = (gameId: string): Spot | null =>
  spots[gameId] ?? null;

/** The time Home offers to resume at, or null (never watched, or near either end). */
export function resumeAt(gameId: string): number | null {
  const s = spots[gameId];
  if (!s || s.t < EDGE_S || (s.duration > 0 && s.t > s.duration - EDGE_S))
    return null;
  return s.t;
}

/** `now`: persist at once (leaving the player), not on the SAVE_MS cadence. */
export function rememberSpot(gameId: string, spot: Spot, now = false): void {
  const { [gameId]: prev, ...rest } = spots;
  if (prev && prev.t === spot.t && prev.playing === spot.playing) {
    if (now && timer) save();
    return;
  }
  // the most recent last, so the oldest falls off
  const ids = Object.keys(rest);
  for (const id of ids.slice(0, Math.max(0, ids.length - (MAX_GAMES - 1))))
    delete rest[id];
  spots = { ...rest, [gameId]: spot };
  const wait = savedAt + SAVE_MS - Date.now();
  if (now || prev?.playing !== spot.playing || wait <= 0) save();
  else timer ??= setTimeout(save, wait);
}
