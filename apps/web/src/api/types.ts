// Hand-written from REPLAY_PLAN.md §4.5 (data contracts) and §4.6 (API).
// Source of truth is the plan; if the backend diverges, fix this file, not the callers.

export type StageName = "ingest" | "detect" | "track" | "render" | "label";
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
}

export interface SportProfile {
  id: string;
  display_name: string;
  tier: number;
  /** Landmark keys to click, in click order (§4.4 stage 2). */
  landmarks: string[];
  variants?: string[];
  sport_ui?: SportUi;
}

export interface Player {
  id: string;
  name: string | null;
  team: number;
  color_hex?: string;
  tagged?: boolean;
}

export interface Team {
  id: number;
  color_hex: string;
}

export interface Game {
  schema: "replay.game.v1";
  id: string;
  title: string;
  recorded_at?: string;
  status: GameStatus;
  stages: Partial<Record<StageName, StageState>>;
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
  /** Not in §4.5; see API assumptions in the web README/report. Optional everywhere. */
  sport_ui?: SportUi;
  thumb_url?: string;
  calib_url?: string;
}

/** Library list item — §4.6 GET /games. A trimmed Game is also accepted. */
export interface GameSummary {
  id: string;
  title: string;
  status: GameStatus;
  recorded_at?: string;
  duration_s?: number;
  thumb_url?: string;
  stages?: Partial<Record<StageName, StageState>>;
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
}

export interface BoxScoreRow {
  player_id: string;
  name: string | null;
  attempts: number;
  makes: number;
  confidence?: number;
}

export interface Stats {
  box_score: BoxScoreRow[];
  shots: ShotPoint[];
  /** Optional per-player occupancy grid (R2, P2 — rendered only if present). */
  heatmap?: { player_id: string; cols: number; rows: number; values: number[] }[];
}

export interface CreateGameResult {
  id: string;
  upload_url: string;
}

export interface CalibrationResult {
  ok: boolean;
  /** Reprojection error in pixels; gate is < 5 (§4.4 stage 2). */
  reprojection_error_px?: number;
  error?: string;
}

export interface Session {
  id: string;
  code: string;
}
