// M8 multi-angle replays: the API contract and the pure bits of the Replay view, shared by
// apps/web (/tv/:id/replays/:playId) and apps/tv. Every angle of one replay is time-aligned
// (t=0 is the play's t_start, equal durations), so cutting between them keeps the playback
// position — the player surfaces already resume a src swap at the same time and play state.

export type ReplayTier = "A" | "B" | "C";

export interface ReplayAngle {
  /** Tier A: `wide`, `follow:<pid>`, `tight:<pid>`; Tier B: `broadcast_high`, `orbit`,
   *  `push_in`, `reverse`; Tier C (virtual views): `3d:<kind>` (wing, courtside,
   *  baseline) and `pov:<pid>` (a virtual POV). */
  id: string;
  tier: ReplayTier;
  label: string;
  url: string;
  /** The angle's middle frame (jpg), for its thumbnail; absent in older manifests. */
  poster?: string | null;
  duration_s: number;
  width: number;
  height: number;
}

/** GET /games/{id}/replays/{play_id} — `angles` is in cut order (Tier A first). */
export interface ReplayManifest {
  schema: "replay.replay_manifest.v1";
  game_id: string;
  play_id: string;
  label: string;
  sport: string;
  t_start: number;
  t_end: number;
  source: "plays" | "events" | "synthetic_gt";
  synthetic: boolean;
  angles: ReplayAngle[];
  commentary: null | { text_url: string | null; audio_url: string | null };
  /** The 2.5D scene package's layout route (GET /games/{id}/scenes/{play_id}), or null
   *  when the play has none (docs/scene-format.md). Older APIs omit it. */
  scene_url?: string | null;
}

/** One row of GET /games/{id}/replays. */
export interface ReplaySummary {
  play_id: string;
  label: string;
  t_start: number;
  t_end: number;
  angles: number;
  manifest_url: string;
}

// Plain words on screen (UI pass glossary): the camera's own pixels, or recreated from them.
// Tier C is image-based since D-86: the real players' pixels on a reconstructed court.
const TIER_BADGE: Record<ReplayTier, string> = {
  A: "Camera",
  B: "Virtual replay",
  C: "Virtual replay",
};

export const tierBadge = (tier: ReplayTier): string => TIER_BADGE[tier] ?? tier;

/** An angle's on-screen name: a virtual POV ("Virtual POV · Player 3" in the manifest)
 *  reads "Player's view · Player 3"; every other label as rendered. */
export const angleLabel = (a: ReplayAngle): string =>
  povOf(a) ? a.label.replace(/^Virtual POV\b/, "Player's view") : a.label;

/** The honesty line of a recreated view (a virtual cut, Free view). */
export const RECREATED =
  "Recreated from the real players on a model of the court";

/** The plain honesty line under a recreated angle; null for the camera's own video. */
export function angleHonesty(a: ReplayAngle): string | null {
  if (a.tier === "A") return null;
  return povOf(a) ? "A recreated player's-eye view, not a camera" : RECREATED;
}

/** The next angle index for a Left (-1) / Right (+1) press; wraps both ways. */
export function cycleAngle(index: number, count: number, dir: 1 | -1): number {
  if (count <= 0) return 0;
  return (((index + dir) % count) + count) % count;
}

/** A Tier C virtual POV (`pov:<pid>`): that player's eyes in the 3D reconstruction. */
export const povOf = (a: ReplayAngle | undefined): string | null =>
  a?.id.startsWith("pov:") ? a.id.slice(4) : null;

/** The angle indices Left/Right cut between: every angle but the virtual POVs, which
 *  share one slot — `at` when it is a POV, else the first POV (the play's key player).
 *  A play has a POV per tracked player; Up picks another (`nextPov`). */
export function cutOrder(angles: ReplayAngle[], at: number): number[] {
  const slot = povOf(angles[at]) ? at : angles.findIndex((a) => povOf(a));
  return angles.flatMap((a, i) => (!povOf(a) || i === slot ? [i] : []));
}

/** The next player's POV after the one at `at` (wraps); `at` when there is no other. */
export function nextPov(angles: ReplayAngle[], at: number): number {
  const povs = angles.flatMap((a, i) => (povOf(a) ? [i] : []));
  return povs.length ? povs[(povs.indexOf(at) + 1) % povs.length] : at;
}

/** How long the angle label and its honesty line stay big after a cut, in ms. */
export const ANGLE_BUG_MS = 5000;
