// M8 multi-angle replays: the API contract and the pure bits of the Replay view, shared by
// apps/web (/tv/:id/replays/:playId) and apps/tv. Every angle of one replay is time-aligned
// (t=0 is the play's t_start, equal durations), so cutting between them keeps the playback
// position — the player surfaces already resume a src swap at the same time and play state.

export type ReplayTier = "A" | "B" | "C";

export interface ReplayAngle {
  /** Tier A: `wide`, `follow:<pid>`, `tight:<pid>`; Tier B: `broadcast_high`, `orbit`,
   *  `push_in`, `reverse`. */
  id: string;
  tier: ReplayTier;
  label: string;
  url: string;
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

const TIER_BADGE: Record<ReplayTier, string> = { A: "Real video", B: "2.5D", C: "3D" };

export const tierBadge = (tier: ReplayTier): string => TIER_BADGE[tier] ?? tier;

/** The next angle index for a Left (-1) / Right (+1) press; wraps both ways. */
export function cycleAngle(index: number, count: number, dir: 1 | -1): number {
  if (count <= 0) return 0;
  return (((index + dir) % count) + count) % count;
}

/** How long the angle label stays big after a cut (broadcast lower-third), in ms. */
export const ANGLE_BUG_MS = 2000;
