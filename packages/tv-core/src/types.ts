// Hand-written from REPLAY_PLAN.md §4.5 (data contracts) and §4.6 (API). Shared by
// apps/web and apps/tv through packages/tv-core.
// Source of truth is the plan; if the backend diverges, fix this file, not the callers.

export type StageState = "pending" | "running" | "done" | "partial" | "error";
export type GameStatus =
  | "created"
  | "uploading"
  | "uploaded"
  | "calibrated"
  | "processing"
  | "ready"
  | "error";

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
  /** Seconds this id has a box in the tracks (courtcam). Absent on older games. */
  seen_s?: number;
  /** The id's box time is split between kits, so `team` is a guess (courtcam). */
  team_mixed?: boolean;
  /** How the side was decided: shirt colours, who-guards-whom, or the user (courtcam). */
  team_source?: TeamSource;
}

export type TeamSource = "kit" | "matchups" | "user";

export interface Team {
  id: number;
  color_hex: string;
  team_source?: TeamSource;
}

export interface Game extends TvReadiness {
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
    /** D-94: false when the court fit disagrees with the people (positions, zones and
     *  shot charts unreliable; nobody was dropped for where they stand). Older: absent. */
    trusted?: boolean;
  };
  renditions: { wide: string; players?: Record<string, string> };
  players: Player[];
  teams: Team[];
  tracks: {
    rate_hz: number;
    chunk_s: number;
    url_template: string;
    chunks: number;
    /** Every id is one person for the whole clip (D-89): a follow never moves to another id. */
    people?: boolean;
  };
  croppaths: { rate_hz: number; url_template: string };
  events_url: string;
  /** Not §4.5 game.json fields; the API adds them to GET /games/{id} (D-13, D-14). */
  sport_ui?: SportUi | null;
  thumb_url?: string | null;
  calib_url?: string | null;
  /** Seek previews: GET it with `api.getStoryboard(game)` (key auth); absent until the
   *  worker's storyboard stage ran. */
  storyboard_url?: string;
  /** What a basket is worth (PUT /games/{id}/scoring); the API adds it. Absent: standard. */
  scoring?: ScoringMode;
}

/** "standard": 2s and 3s; "pickup": 1s and 2s (inside the arc 1, beyond it 2). */
export type ScoringMode = "standard" | "pickup";

/** Per-feature readiness keys (docs/ux/redesign.md "Tiered readiness"). */
export type FeatureKey =
  | "moments"
  | "previews"
  | "follow"
  | "angles"
  | "free_view"
  /** each tracked player's virtual POV (Tier C `pov:<pid>` replay angles) */
  | "pov"
  | "highlights"
  | "condensed"
  | "stats"
  | "commentary";

export interface FeatureState {
  /** pending: this run will make it; unavailable: it will not exist for this game. */
  state: "ready" | "pending" | "unavailable";
  /** Estimated seconds until ready (pending only; absent when the API cannot tell). */
  eta_s?: number;
}

/** Readiness and hero art, on both Game and GameSummary. All optional: an older API or a
 *  game created before the redesign sends none of them. */
export interface TvReadiness {
  /** The best-moment frame, 16:9 JPEG 1280x720 (top hype moment, else best event, else
   *  mid-game). Absent until processing finished. */
  hero_url?: string;
  /** True once a playable rendition exists: ingest's media/wide.mp4, after ingest is done
   *  (mid-run, `renditions.wide` is filled in for it). */
  watchable?: boolean;
  /** Seconds until processing finishes. An ESTIMATE from per-stage hfbox costs scaled by
   *  the video's duration (services/api/replay_api/readiness.py); say "about". */
  eta_s?: number;
  /** Plain words for the running stage, sentence case ("Finding players"). */
  stage_label?: string;
  features?: Partial<Record<FeatureKey, FeatureState>>;
}

/** Library list item — §4.6 GET /games. A trimmed Game is also accepted. */
export interface GameSummary extends TvReadiness {
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

/** GET {storyboard_url}: frame i (time i * interval_s) is on sheet floor(i / (cols*rows)),
 *  cell i % (cols*rows), row-major; each cell is width x height. The last sheet may be
 *  shorter (only the rows it uses). */
export interface Storyboard {
  schema?: "replay.storyboard.v1";
  interval_s: number;
  width: number;
  height: number;
  cols: number;
  rows: number;
  /** Number of frames across all sheets. */
  count?: number;
  /** Absolute sheet JPEG URLs, in order. */
  sheets: string[];
}

export type MomentKind = "score" | "play" | "bookmark";

/** One row of GET /games/{id}/moments (sorted by t). The label is built only from what
 *  the detector reported (a shot whose make is unknown is "Shot", never a basket). */
export interface Moment {
  /** The event id. */
  id: string;
  /** Key time (the event's t_key), seconds. */
  t: number;
  t_start: number;
  t_end: number;
  kind: MomentKind;
  label: string;
  player?: {
    id: string;
    name?: string | null;
    number?: number;
    color_hex?: string;
  };
  /** 480x270 JPEG at `t`; null when no frame was grabbed (a game processed before the
   *  moments stage existed). */
  thumb_url: string | null;
  /** Where the event came from and how sure the detector was (keep the honesty cues). */
  source?: "heuristic" | "vlm" | "user";
  confidence?: number | null;
  confirmed?: boolean;
}

/** D-80 resume: GET /games/{id}/upload/parts — what S3 holds, fresh URLs for the rest. */
export interface MultipartParts {
  upload_id: string;
  part_size: number;
  done: { n: number; etag: string; size: number }[];
  parts: { n: number; url: string }[];
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
  | "bookmark"
  // M4, additive (courtcam schema.py)
  | "turnover"
  | "contact"
  | "block"
  | "hype"
  // a defender who lost their man (courtcam events.detect_lost_man)
  | "lost_man";

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
  /** M4, additive (courtcam schema.py): the event's side (a contact: the hitter's), a
   *  shot's value, why a possession changed or a point ended, who won a rally/point. */
  team?: number | null;
  points?: number | null;
  cause?: string | null;
  winner_side?: number | null;
  /** lost_man: the man the defender (`player_id`) lost, and how far apart they got. */
  opponent_id?: string;
  max_sep_m?: number;
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
  /** D-80: per-game capability for the phone page (sent as X-Replay-Upload-Token). */
  upload_token?: string;
  /** D-80: `${public web base}/u/{id}#t={token}` — what the TV's QR encodes. Absent when
   *  the API has no public web base. */
  upload_page_url?: string;
  /** D-80: `put` = the existing PUT route (local mode); `multipart` = presigned S3 parts. */
  upload?: { mode: "put" | "multipart"; url?: string };
}

/** D-80: POST /games/{id}/upload/multipart. Part `n` covers bytes [(n-1)*part_size, n*part_size). */
export interface MultipartInit {
  upload_id: string;
  part_size: number;
  parts: { n: number; url: string }[];
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
  /** false = dots to drag, not dots to accept: committing them unmoved needs a confirm. */
  ok: boolean;
  reprojection_error_px?: number | null;
  /** The template fit's line score and the bar `ok` needs (template backend only). */
  score?: number | null;
  min_score?: number;
}

export type AutoCalibrationState =
  "idle" | "queued" | "running" | "done" | "failed";

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

/** GET /config (public). `web_base`: where apps/web's phone pages live, or null. */
export interface PublicConfig {
  web_base: string | null;
}

/** What a phone page (apps/web `/p/:id`) is opened for. */
export type PhoneJob = "clip" | "tag" | "review" | "search" | "reel";

/** POST /games/{id}/phone-link: `url` = `{web_base}/p/{id}?job=..&t=..#k=<token>`, null
 *  when the server has no web base. `expires_at`: epoch seconds. */
export interface PhoneLink {
  url: string | null;
  token: string;
  expires_at: number;
}

/** GET /tv/commands: a command for the TV, e.g. `play` (the phone's "Play on the TV": seek
 *  `game_id` to `t`). Alexa's kinds (`clip`, `reel`) share the queue; the TV ignores them. */
export interface TvCommand {
  id: string;
  kind: string;
  game_id: string | null;
  t: number | null;
}

/** POST /games/{id}/players/{pid}/render — 202 with the queued job. */
export interface RenderJob {
  job_id: string;
  status: string;
  player_id: string;
}

// ---------------------------------------------------------------- 2.5D scene package
// replay.scene_package.v1 (docs/scene-format.md). Scene frame: court metres, z up, floor
// z = 0 (x already negated when the calibration was mirrored). Angles in degrees.

export type Vec2 = [number, number];
export type Vec3 = [number, number, number];
/** World corners of a texture's edges for uv (0,0), (1,0), (1,1), (0,1); uv origin is
 *  the image's top-left, v down. */
export type Quad = [Vec3, Vec3, Vec3, Vec3];

export interface ScenePlate {
  id: "backdrop" | "floor";
  /** RGBA PNG; alpha 0 where the real camera never saw the texel. */
  file: string;
  /** Absolute URL, added by GET /games/{id}/scenes/{play_id}. */
  url?: string;
  size_px: Vec2;
  corners_m: Quad;
}

export interface SceneAtlas {
  file: string;
  url?: string;
  size_px: Vec2;
  cell_px: Vec2;
  grid: Vec2;
  inset_px: number;
  /** The mask texel of a colour uv is at u + mask_offset_u. */
  mask_offset_u: number;
  /** alpha = clamp((mask - lo) / (hi - lo), 0, 1), mask in 0..1 after decoding. */
  mask_ramp: [number, number];
  codec: string;
  gop_frames: number;
}

/** One visible player in one frame. The billboard is the vertical rectangle
 *  foot + s * axis + z * up for s in [s0, s1], z in [z0, z1]; uv is its colour rect. */
export interface SceneSprite {
  pid: string;
  cell: number;
  foot: Vec2;
  rect: [number, number, number, number];
  uv: [number, number, number, number];
  /** Distance along the real camera's optical axis to the chest point (m). */
  depth: number;
}

export interface SceneCameraState {
  /** Offset from envelope.azimuth0_deg. */
  azimuth_deg: number;
  elevation_deg: number;
  distance_m: number;
  roll_deg: number;
  fov_y_deg: number;
}

export interface ScenePreset extends SceneCameraState {
  id: string;
  label: string;
}

export interface SceneViewMetrics {
  seen: number;
  az_dev: number;
  el_dev: number;
  mag: number;
  players: number;
}

export interface SceneEnvelope {
  target_m: Vec3;
  azimuth0_deg: number;
  fov_y_deg: number;
  azimuth_deg: Vec2;
  elevation_deg: Vec2;
  distance_m: Vec2;
  limits: {
    az_dev_max_deg: number;
    el_dev_max_deg: number;
    seen_min_of_real: number;
    mag_max_rel_real: number;
  };
  edge_metrics: Record<string, SceneViewMetrics>;
}

export interface SceneHoop {
  rim_m: Vec3;
  rim_radius_m: number;
  backboard_m: Quad;
}

/** GET /games/{id}/scenes/{play_id} (the package's layout.json plus game_id and urls). */
export interface SceneLayout {
  schema: "replay.scene_package.v1";
  game_id?: string;
  play_id: string;
  label: string | null;
  sport: string | null;
  synthetic: boolean;
  /** Must stay visible while the scene is shown. */
  honesty_label: string;
  t_start: number;
  t_end: number;
  fps: number;
  n_frames: number;
  frame: { units: "m"; up: "+z"; floor: "z = 0"; mirror_x: boolean };
  /** Real camera, OpenCV convention: x_cam = R X + t, pixels = K x_cam (x right, y down). */
  camera: {
    image_size: Vec2;
    K: number[][];
    R: number[][];
    t: Vec3;
    position_m: Vec3;
  };
  plates: ScenePlate[];
  atlas: SceneAtlas;
  players: Record<string, { team: number | null }>;
  billboard: { facing: "real" | "viewer"; shadow_radius_m: number };
  /** frames[f] = sprites of atlas frame f (media time f / fps). */
  frames: SceneSprite[][];
  static: {
    hoops: SceneHoop[];
    net: null | { top_l_m: Vec3; top_r_m: Vec3; depth_m: number };
  };
  ball: null | {
    source: "model";
    note: string;
    radius_m: number;
    xyz: (Vec3 | null)[];
  };
  envelope: SceneEnvelope;
  presets: ScenePreset[];
}

/** One row of GET /games/{id}/scenes. */
export interface SceneSummary {
  play_id: string;
  label: string;
  schema: string;
  t_start: number;
  t_end: number;
  n_frames: number;
  synthetic: boolean;
  layout_url: string;
}
