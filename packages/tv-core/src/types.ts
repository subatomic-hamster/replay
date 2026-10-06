// Hand-written from REPLAY_PLAN.md §4.5 (data contracts) and §4.6 (API). Shared by
// apps/web and apps/tv through packages/tv-core.
// Source of truth is the plan; if the backend diverges, fix this file, not the callers.

export type StageState = "pending" | "running" | "done" | "partial" | "error";
export type GameStatus = "created" | "uploading" | "processing" | "ready" | "error";

export interface SportUi {
  /** Preset query chips shown on the Highlights screen (H3). */
  chips?: string[];
  /** Which review surfaces apply, e.g. ["shot_chart", "box_score"] / ["rally_browser"]. */
  review?: string[];
  /** Court polygons in meters, drawn by CourtInset / ShotChart. */
  court?: CourtTemplate;
}

export interface CourtTemplate {
  /** Court extent in meters: [width_x, length_y]. */
  size_m: [number, number];
  /** Named polygons, each a list of [x_m, y_m] points. */
  polygons: Record<string, [number, number][]>;
  /** Axis extents in meters. A half court's origin is the baseline centre, so x is
   *  negative on the left — without these the SVG viewBox clips half the court. */
  x_range?: [number, number];
  y_range?: [number, number];
}

export interface SportProfile {
  id: string;
  display_name: string;
  tier: number;
  /** Landmark keys to click, in click order (§4.4 stage 2). */
  landmarks: string[];
  /** Extra named points the fit accepts when a required one is off-frame (D-18/D-19). */
  landmarks_optional?: string[];
  variants?: string[];
  sport_ui?: SportUi;
}

export interface Player {
  id: string;
  name: string | null;
  team: number;
  color_hex?: string;
  tagged?: boolean;
  /** M10: set while this roster player is linked to a profile (D-58). */
  profile_id?: string;
}

export interface Team {
  id: number;
  color_hex: string;
}

export interface Game {
  schema: "replay.game.v1";
  id: string;
  title: string;
  recorded_at?: string | null;
  status: GameStatus;
  /** Ordered: the keys are the pipeline's own stage list, in run order (S-08). */
  stages: Record<string, StageState>;
  /** D-9/S-08: per-stage fraction, merged in from the job record while a job runs. */
  progress?: Record<string, number>;
  video: { duration_s: number; fps: number; width: number; height: number };
  sport: string;
  court: {
    variant: string;
    standard?: string;
    landmarks_px?: Record<string, [number, number]>;
  };
  renditions: { wide: string; players?: Record<string, string> };
  players: Player[];
  teams: Team[];
  tracks: { rate_hz: number; chunk_s: number; url_template: string; chunks: number };
  croppaths: { rate_hz: number; url_template: string };
  events_url: string;
  /** Not §4.5 game.json fields; the API adds them to GET /games/{id} (D-13, D-14). */
  sport_ui?: SportUi | null;
  thumb_url?: string | null;
  calib_url?: string | null;
}

/** Library list item — §4.6 GET /games. A trimmed Game is also accepted. */
export interface GameSummary {
  id: string;
  title: string;
  status: GameStatus;
  /** null for a game created without a recording date */
  recorded_at?: string | null;
  duration_s?: number | null;
  thumb_url?: string | null;
  stages?: Record<string, StageState>;
  progress?: Record<string, number>;
}

export interface TrackPlayer {
  id: string;
  /** [x, y, w, h] normalized to the video frame. */
  bb: [number, number, number, number];
  /** Court coordinates in meters. */
  ct?: [number, number];
  /** Detection confidence. */
  c?: number;
}

export interface TracksChunk {
  schema: "replay.tracks.v1";
  t0: number;
  rate_hz: number;
  frames: { t: number; p: TrackPlayer[] }[];
}

export interface CropPath {
  schema: "replay.crops.v1";
  player_id: string;
  rate_hz: number;
  t0: number;
  /** Per-frame crop rects [x, y, w, h] normalized. */
  rects: [number, number, number, number][];
}

export type EventType =
  | "shot"
  | "possession_change"
  | "rally"
  | "point"
  | "serve"
  | "bookmark";

export interface GameEvent {
  id: string;
  type: EventType;
  made?: boolean;
  t_start: number;
  t_key: number;
  t_end: number;
  player_id?: string;
  court?: [number, number];
  confidence: number;
  source: "heuristic" | "vlm" | "user";
  confirmed: boolean;
  label?: string;
  /** D-11 "not a shot": kept in events.json, excluded from query and stats. */
  dismissed?: boolean;
}

export interface EventsFile {
  schema: "replay.events.v1";
  events: GameEvent[];
}

export interface Clip {
  t_start: number;
  t_end: number;
  event_id?: string;
  label?: string;
}

export interface QueryResult {
  interpretation: string;
  clips: Clip[];
}

export interface ShotPoint {
  event_id: string;
  player_id?: string;
  court: [number, number];
  made: boolean;
  confirmed?: boolean;
  /** M11: "unknown" when the detector could not tell (drawn as a ring). */
  outcome?: "make" | "miss" | "unknown";
}

export interface BoxScoreRow {
  player_id: string;
  name: string | null;
  attempts: number;
  makes: number;
  confidence?: number;
  /** M11 (D-48), additive: shown only for the stats in `Stats.available`. */
  team?: number;
  points?: number;
  rebounds?: number;
  steals?: number;
  blocks?: number;
  distance_m?: number;
}

export interface Stats {
  /** D-48: always "auto-detected", with the mean event confidence. */
  label?: string;
  confidence?: number | null;
  /** Which event-backed stats this game can support ("shots", "rebounds", …). */
  available?: string[];
  box_score: BoxScoreRow[];
  shots: ShotPoint[];
  /** Optional per-player occupancy grid (R2, P2 — rendered only if present).
   *  `values` is row-major, `cols * rows` long. */
  heatmap?: {
    player_id: string;
    cols: number;
    rows: number;
    values: number[];
    x_range?: [number, number];
    y_range?: [number, number];
  }[];
}

export interface CreateGameResult {
  id: string;
  upload_url: string;
}

/** D-23: what the vision model thinks the landmarks are. Not a calibration yet — the
 *  client still POSTs /calibration with the points the user accepted. */
export interface LandmarkProposal {
  landmarks_px: Record<string, [number, number]>;
  /** 0..1 per landmark; below 0.5 the dot is drawn hollow and is not committed. */
  confidence: Record<string, number>;
  /** Whether the point was pulled onto a detected court line. */
  snapped?: Record<string, boolean>;
  source: string;
  notes?: string;
  ok: boolean;
  reprojection_error_px?: number | null;
}

export type AutoCalibrationState = "idle" | "queued" | "running" | "done" | "failed";

/** GET /games/{id}/calibration/auto */
export interface AutoCalibration {
  status: AutoCalibrationState;
  proposal?: LandmarkProposal;
  ok: boolean;
  reprojection_error_px?: number | null;
  error?: string;
}

/** POST /games/{id}/calibration/auto — 202 with the queued job. */
export interface AutoCalibrationJob {
  job_id: string;
  status: string;
  game_id?: string;
}

export interface CalibrationResult {
  ok: boolean;
  /** Reprojection error in pixels; gate is < 5 (§4.4 stage 2). */
  reprojection_error_px?: number;
  /** Per-landmark reprojection error in pixels, so the worst click can be named. */
  residuals_px?: Record<string, number>;
  error?: string;
}

export interface Session {
  id: string;
  code: string;
}

/** POST /games/{id}/players/{pid}/render — 202 with the queued job. */
export interface RenderJob {
  job_id: string;
  status: string;
  player_id: string;
}
