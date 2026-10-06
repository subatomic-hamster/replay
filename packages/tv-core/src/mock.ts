// Dev/test double for §4.6. Enabled with VITE_MOCK_API=1 so the TV UIs (apps/web /tv and
// the apps/tv web build) and their Playwright suites run without services/api. Serves
// fixture games backed by apps/web/public/mock/wide.mp4 (20 s, 1280x720, 30 fps).
// ponytail: in-memory only — state resets on reload. Good enough; the real API is the
// persistence story.
import type {
  AutoCalibration,
  AutoCalibrationJob,
  CalibrationResult,
  CreateGameResult,
  CropPath,
  Game,
  GameEvent,
  GameSummary,
  Player,
  QueryResult,
  RenderJob,
  Session,
  SportProfile,
  Stats,
  TracksChunk,
  TrackPlayer,
} from "./types";
import { queryAsSearch, reviewBody, type CalibrationPayload, type ReplayApi } from "./api";
import type { ReplayAngle, ReplayManifest } from "./replays";
import { REVIEW_CONFIDENCE_THRESHOLD } from "./display";
import type {
  Advice,
  Commentary,
  Hype,
  JobStatus,
  PlayClip,
  RallyDoc,
  Rendition,
  ReviewOption,
  ReviewQuestion,
  Trigger,
  VerticalExport,
} from "./discovery";
import type { CareerReel, PlayerCard, Profile, ProfileSuggestion, SportStats } from "./profiles";

export interface MockCall {
  method: string;
  path: string;
  body?: unknown;
}

/** Playwright asserts against this (S-24, S-29, S-36, S-37). */
export const mockCalls: MockCall[] = [];
function log(method: string, path: string, body?: unknown) {
  mockCalls.push({ method, path, body });
  (globalThis as { __replayMockCalls?: MockCall[] }).__replayMockCalls = mockCalls;
}

const DURATION = 20;
const FPS = 30;

/** D-23. Deliberately a few px off the fixture court so "Adjust" has something to do,
 *  and `rim` sits under the 0.5 bar so the hollow-dot path is exercised. */
const AUTOCALIB_MS = 600;
const autoStartedAt: Record<string, number> = {};
const PROPOSAL = {
  landmarks_px: {
    corner_nl: [126, 634],
    corner_nr: [1154, 637],
    corner_fl: [433, 213],
    corner_fr: [847, 208],
    rim: [636, 254],
  } as Record<string, [number, number]>,
  confidence: { corner_nl: 0.93, corner_nr: 0.9, corner_fl: 0.84, corner_fr: 0.79, rim: 0.42 },
  snapped: { corner_nl: true, corner_nr: true, corner_fl: true, corner_fr: false, rim: false },
  source: "claude-cli",
  notes: "",
  ok: true,
  reprojection_error_px: 3.4,
};

const BASKETBALL: SportProfile = {
  id: "basketball",
  display_name: "Basketball",
  tier: 2,
  landmarks: ["corner_nl", "corner_nr", "corner_fl", "corner_fr", "rim"],
  variants: ["half", "full"],
  sport_ui: {
    chips: ["All shots", "Makes", "Misses"],
    review: ["shot_chart", "heatmap", "box_score"],
    court: {
      size_m: [15, 14],
      polygons: {
        outer: [
          [0, 0],
          [15, 0],
          [15, 14],
          [0, 14],
        ],
        paint: [
          [5.05, 0],
          [9.95, 0],
          [9.95, 5.8],
          [5.05, 5.8],
        ],
      },
    },
  },
};

/** A net sport, so the variant picker and `sport_ui.review` have a second shape to be
 *  right about: one variant (no radio to check) and no shot chart or box score. */
const PICKLEBALL: SportProfile = {
  id: "pickleball",
  display_name: "Pickleball",
  tier: 1,
  landmarks: ["corner_nl", "corner_nr", "corner_fl", "corner_fr", "net_post_l", "net_post_r"],
  variants: ["doubles"],
  sport_ui: {
    chips: ["Rallies", "Longest rallies", "Bookmarks"],
    review: ["heatmap"],
    court: {
      size_m: [6.1, 13.41],
      polygons: {
        outer: [
          [0, 0],
          [6.1, 0],
          [6.1, 13.41],
          [0, 13.41],
        ],
        net: [
          [0, 6.705],
          [6.1, 6.705],
        ],
      },
    },
  },
};

function player(id: string, name: string | null, team: number): Player {
  return {
    id,
    name,
    team,
    color_hex: team === 0 ? "#1f4fa0" : "#e8e8e8",
    tagged: name !== null,
  };
}

/** Deterministic, smooth player motion so follow-cam transforms actually change. */
const MOTION: Record<string, (t: number) => [number, number]> = {
  p1: (t) => [0.08 + 0.01 * Math.sin(t * 0.5), 0.4],
  p2: (t) => [0.44 + 0.01 * Math.sin(t * 0.7 + 1), 0.4],
  p3: (t) => [0.74 + 0.01 * Math.sin(t * 0.6 + 2), 0.38],
  p4: () => [0.52, 0.7],
};
const BOX_W = 0.06;
const BOX_H = 0.2;

/** A scripted occlusion: p1 has no track box between these seconds, so the follow frame's
 *  fade-out and return (S-22b) is testable. Tracks only — MOTION, the crop path and the
 *  heatmap stay continuous, which is exactly what a real occlusion looks like. */
const TRACK_GAP: Record<string, [number, number]> = { p1: [12, 13] };
const tracked = (id: string, t: number) => {
  const gap = TRACK_GAP[id];
  return !gap || t < gap[0] || t >= gap[1];
};

function trackAt(id: string, t: number): TrackPlayer {
  const [x, y] = MOTION[id](t);
  return {
    id,
    bb: [x, y, BOX_W, BOX_H],
    ct: [Number(((x + BOX_W / 2) * 15).toFixed(2)), Number(((y + BOX_H) * 14).toFixed(2))],
    c: 0.9,
  };
}

// courtcam's own stage list (courtcam/courtcam/pipeline.py STAGES), which the API sends
// as the ordered keys of `stages` (S-08). The screens never hardcode it; only the mock does.
const STAGE_ORDER = [
  "ingest",
  "calibrate",
  "detect",
  "track",
  "court",
  "identity",
  "tracks",
  "crops",
  "events",
] as const;

/** Stages before `running` done, that one running, the rest pending. */
const stagesAt = (running: number): Game["stages"] =>
  Object.fromEntries(
    STAGE_ORDER.map((s, i) => [s, i < running ? "done" : i === running ? "running" : "pending"]),
  );
const progressAt = (running: number, frac: number): Record<string, number> =>
  Object.fromEntries(STAGE_ORDER.map((s, i) => [s, i < running ? 1 : i === running ? frac : 0]));

function baseGame(id: string, title: string, status: Game["status"]): Game {
  const done = status === "ready";
  return {
    schema: "replay.game.v1",
    id,
    title,
    recorded_at: "2026-09-29T19:30:00-04:00",
    status,
    stages: stagesAt(done ? STAGE_ORDER.length : 2),
    ...(done ? {} : { progress: progressAt(2, 0.5) }),
    video: { duration_s: DURATION, fps: FPS, width: 1280, height: 720 },
    sport: "basketball",
    court: {
      variant: "half",
      standard: "fiba",
      landmarks_px: {
        corner_nl: [120, 640],
        corner_nr: [1160, 640],
        corner_fl: [430, 210],
        corner_fr: [850, 210],
        rim: [640, 250],
      },
    },
    renditions: { wide: "/mock/wide.mp4" },
    players: done
      ? [player("p1", "Marcus", 0), player("p2", null, 1), player("p3", null, 0), player("p4", null, 1)]
      : [],
    teams: [
      { id: 0, color_hex: "#1f4fa0" },
      { id: 1, color_hex: "#e8e8e8" },
    ],
    tracks: { rate_hz: 10, chunk_s: 10, url_template: "tracks/{chunk:05d}.json", chunks: 2 },
    croppaths: { rate_hz: FPS, url_template: "crops/{player_id}.json" },
    events_url: "events.json",
    sport_ui: BASKETBALL.sport_ui,
    thumb_url: "/mock/calib.jpg",
    calib_url: "/mock/calib.jpg",
  };
}

function ev(
  id: string,
  t_key: number,
  player_id: string,
  made: boolean,
  confidence: number,
  court: [number, number],
): GameEvent {
  return {
    id,
    type: "shot",
    made,
    t_start: Math.max(0, t_key - 1.5),
    t_key,
    t_end: Math.min(DURATION, t_key + 1.5),
    player_id,
    court,
    confidence,
    source: confidence > 0.7 ? "vlm" : "heuristic",
    confirmed: false,
  };
}

const HEAT_COLS = 15;
const HEAT_ROWS = 14;

/** R2 — the same occupancy grid services/api derives from the tracks chunks (D-12):
 *  bin every 10 Hz sample of a player's court position into one cell per court metre. */
function heatmapFor(playerId: string): number[] {
  const values = new Array(HEAT_COLS * HEAT_ROWS).fill(0);
  const motion = MOTION[playerId];
  if (!motion) return values;
  for (let i = 0; i < DURATION * 10; i++) {
    const { ct } = trackAt(playerId, i / 10);
    const ix = Math.floor((ct![0] / 15) * HEAT_COLS);
    const iy = Math.floor((ct![1] / 14) * HEAT_ROWS);
    if (ix >= 0 && ix < HEAT_COLS && iy >= 0 && iy < HEAT_ROWS) values[iy * HEAT_COLS + ix] += 1;
  }
  return values;
}

/** Distance covered along the same 10 Hz court positions (the API's D-48 rule without
 *  the jump filter — the mock motion has no jumps). */
function distanceFor(playerId: string): number {
  if (!MOTION[playerId]) return 0;
  let d = 0;
  let prev = trackAt(playerId, 0).ct;
  for (let i = 1; i < DURATION * 10; i++) {
    const ct = trackAt(playerId, i / 10).ct;
    if (ct && prev) d += Math.hypot(ct[0] - prev[0], ct[1] - prev[1]);
    prev = ct;
  }
  return Number(d.toFixed(1));
}

const games = new Map<string, Game>();
const events = new Map<string, GameEvent[]>();

function seed() {
  games.clear();
  events.clear();
  const g1 = baseGame("g_mock01", "Tuesday run — CRC court 2", "ready");
  const g2 = baseGame(
    "g_mock02",
    "Thursday pickup game with a deliberately very long title that must be truncated by the card layout instead of breaking it",
    "ready",
  );
  const g3 = baseGame("g_proc03", "Friday scrimmage", "processing");
  const g4 = baseGame("g_pickle4", "Sunday doubles — court 3", "ready");
  g4.sport = "pickleball";
  g4.sport_ui = PICKLEBALL.sport_ui;
  g4.court = { ...g4.court, variant: "doubles" };
  for (const g of [g1, g2, g3, g4]) games.set(g.id, g);
  events.set("g_mock01", [
    ev("e_0001", 3.0, "p1", true, 0.82, [4.0, 5.0]),
    ev("e_0002", 8.0, "p2", false, 0.74, [9.0, 6.5]),
    ev("e_0003", 14.0, "p1", true, 0.91, [6.5, 3.2]),
    ev("e_0004", 17.0, "p3", true, 0.55, [11.0, 4.0]),
  ]);
  events.set("g_mock02", []);
  events.set("g_proc03", []);
  events.set("g_pickle4", []);
}
seed();

/** Finish one stage per poll (the next one shows as half done) so the status screen
 *  runs through courtcam's nine stages in ~20 s. */
function advance(g: Game) {
  if (g.status !== "processing") return;
  const at = STAGE_ORDER.findIndex((s) => g.stages[s] !== "done");
  if (at + 1 < STAGE_ORDER.length) {
    g.stages = stagesAt(at + 1);
    g.progress = progressAt(at + 1, 0.5);
    return;
  }
  // `progress` rides along only while a job runs (D-17).
  g.stages = stagesAt(STAGE_ORDER.length);
  delete g.progress;
  g.status = "ready";
  g.players = baseGame(g.id, g.title, "ready").players;
}

function needGame(id: string): Game {
  const g = games.get(id);
  if (!g) throw new Error(`unknown game ${id}`);
  return g;
}

const delay = <T,>(v: T, ms = 10) => new Promise<T>((r) => setTimeout(() => r(v), ms));

function matchEvents(list: GameEvent[], text: string, players: Player[]): GameEvent[] {
  const q = text.toLowerCase();
  let out = list.filter((e) => e.type === "shot" && !e.dismissed);
  const named = players.find((p) => p.name && q.includes(p.name.toLowerCase()));
  if (named) out = out.filter((e) => e.player_id === named.id);
  if (/\bmake|\bmade\b/.test(q)) out = out.filter((e) => e.made === true);
  else if (/\bmiss/.test(q)) out = out.filter((e) => e.made === false);
  else if (!/\bshot|\ball\b|\btop\b|\bplay/.test(q) && !named) out = [];
  return out.sort((a, b) => a.t_start - b.t_start);
}

export const mockApi: ReplayApi = {
  listSports: () => {
    log("GET", "/sports");
    return delay([BASKETBALL, PICKLEBALL]);
  },

  createGame(title, sport) {
    log("POST", "/games", { title, sport });
    const id = `g_${Math.random().toString(36).slice(2, 8)}`;
    const g = baseGame(id, title, "created");
    g.sport = sport;
    g.stages = {};
    g.players = [];
    games.set(id, g);
    events.set(id, []);
    return delay<CreateGameResult>({ id, upload_url: `/__mock_upload/${id}` });
  },

  upload(uploadUrl, file, onProgress) {
    log("PUT", uploadUrl, { name: file.name, size: file.size });
    return new Promise((resolve) => {
      let pct = 0;
      const timer = setInterval(() => {
        pct = Math.min(100, pct + 25);
        onProgress(pct);
        if (pct >= 100) {
          clearInterval(timer);
          resolve();
        }
      }, 40);
    });
  },

  startAutoCalibration(gameId, sport, variant) {
    log("POST", `/games/${gameId}/calibration/auto`, { sport, variant });
    needGame(gameId);
    autoStartedAt[gameId] = Date.now();
    return delay<AutoCalibrationJob>({ job_id: "j_autocalib", status: "queued" });
  },

  getAutoCalibration(gameId) {
    needGame(gameId);
    const started = autoStartedAt[gameId];
    if (!started) return delay<AutoCalibration>({ status: "idle", ok: false });
    if (Date.now() - started < AUTOCALIB_MS) {
      return delay<AutoCalibration>({ status: "running", ok: false });
    }
    return delay<AutoCalibration>({
      status: "done",
      ok: true,
      reprojection_error_px: PROPOSAL.reprojection_error_px,
      proposal: { ...PROPOSAL, landmarks_px: { ...PROPOSAL.landmarks_px } },
    });
  },

  calibrate(gameId, payload: CalibrationPayload) {
    log("POST", `/games/${gameId}/calibration`, payload);
    const g = needGame(gameId);
    const pts = Object.values(payload.landmarks_px);
    if (pts.length < 4) {
      return delay<CalibrationResult>({ ok: false, error: `need ${4 - pts.length} more points` });
    }
    // Degenerate check (E-06): largest triangle area among the first 4 points.
    let area = 0;
    for (let i = 0; i < pts.length; i++)
      for (let j = i + 1; j < pts.length; j++)
        for (let k = j + 1; k < pts.length; k++) {
          const a = Math.abs(
            (pts[j][0] - pts[i][0]) * (pts[k][1] - pts[i][1]) -
              (pts[k][0] - pts[i][0]) * (pts[j][1] - pts[i][1]),
          );
          area = Math.max(area, a / 2);
        }
    if (area < 500) return delay<CalibrationResult>({ ok: false, error: "invalid points" });
    g.court.variant = payload.court_variant;
    g.court.landmarks_px = payload.landmarks_px;
    // Not a homography — just something that moves when a point moves, so the UI can
    // prove it re-validates after a drag (S-04b).
    const spread = pts.reduce((a, [x, y]) => a + x + y, 0);
    const err = Math.round((1 + (spread % 290) / 100) * 10) / 10;
    return delay<CalibrationResult>({
      ok: true,
      reprojection_error_px: err,
      // Not a real residual either — just per-landmark and with one clear worst, which
      // is all the `calib-worst` readout needs.
      residuals_px: Object.fromEntries(
        Object.keys(payload.landmarks_px).map((n, i) => [n, Number((err / (i + 1)).toFixed(2))]),
      ),
    });
  },

  startProcessing(gameId) {
    log("POST", `/games/${gameId}/process`);
    const g = needGame(gameId);
    g.status = "processing";
    g.stages = stagesAt(0);
    g.progress = progressAt(0, 0);
    return delay(undefined);
  },

  listGames() {
    log("GET", "/games");
    const out: GameSummary[] = [...games.values()]
      .filter((g) => g.status === "ready" || g.status === "processing")
      .map((g) => ({
        id: g.id,
        title: g.title,
        status: g.status,
        recorded_at: g.recorded_at,
        duration_s: g.video.duration_s,
        thumb_url: g.thumb_url,
        stages: g.stages,
        ...(g.progress ? { progress: g.progress } : {}),
      }));
    return delay(out);
  },

  getGame(gameId) {
    log("GET", `/games/${gameId}`);
    const g = needGame(gameId);
    advance(g);
    return delay(structuredClone(g));
  },

  patchPlayer(gameId, pid, body) {
    log("PATCH", `/games/${gameId}/players/${pid}`, body);
    const g = needGame(gameId);
    const p = g.players.find((x) => x.id === pid);
    if (!p) throw new Error(`unknown player ${pid}`);
    if (body.merge_into) {
      if (body.merge_into === pid) throw new Error("cannot merge into self");
      g.players = g.players.filter((x) => x.id !== pid);
      for (const e of events.get(gameId) ?? [])
        if (e.player_id === pid) e.player_id = body.merge_into;
      return delay(p);
    }
    if (body.name !== undefined) {
      p.name = body.name;
      p.tagged = true;
    }
    return delay(structuredClone(p));
  },

  getEvents(game) {
    log("GET", `/media/games/${game.id}/events.json`);
    return delay(structuredClone(events.get(game.id) ?? []));
  },

  createEvent(gameId, body) {
    log("POST", `/games/${gameId}/events`, body);
    const list = events.get(gameId) ?? [];
    const t = body.t_key ?? 0;
    const e: GameEvent = {
      id: `e_${String(list.length + 900)}`,
      type: body.type ?? "bookmark",
      t_start: body.t_start ?? Math.max(0, t - 1.5),
      t_key: t,
      t_end: body.t_end ?? Math.min(DURATION, t + 1.5),
      player_id: body.player_id,
      confidence: 1,
      source: "user",
      confirmed: true,
    };
    list.push(e);
    list.sort((a, b) => a.t_key - b.t_key);
    events.set(gameId, list);
    return delay(structuredClone(e));
  },

  patchEvent(gameId, eventId, body) {
    log("PATCH", `/games/${gameId}/events/${eventId}`, body);
    const list = events.get(gameId) ?? [];
    const i = list.findIndex((e) => e.id === eventId);
    if (i < 0) throw new Error(`unknown event ${eventId}`);
    if (body.type === undefined && body.made === undefined && !body.confirmed && !body.dismissed) {
      throw new Error("nothing to patch");
    }
    const next = { ...list[i], ...body, confirmed: true, source: "user" as const };
    list[i] = next;
    return delay(structuredClone(next));
  },

  query(gameId, text) {
    log("POST", `/games/${gameId}/query`, { text });
    const g = needGame(gameId);
    const matched = matchEvents(events.get(gameId) ?? [], text, g.players);
    const result: QueryResult = {
      interpretation: matched.length ? `Showing: ${text}` : `No match for "${text}"`,
      clips: matched.map((e) => ({
        t_start: e.t_start,
        t_end: e.t_end,
        event_id: e.id,
        label: `${g.players.find((p) => p.id === e.player_id)?.name ?? e.player_id} — ${
          e.made ? "make" : "miss"
        }`,
      })),
    };
    return delay(result);
  },

  getStats(gameId) {
    log("GET", `/games/${gameId}/stats`);
    const g = needGame(gameId);
    const list = (events.get(gameId) ?? []).filter((e) => e.type === "shot" && !e.dismissed);
    const stats: Stats = {
      label: "auto-detected",
      confidence: list.length
        ? Number((list.reduce((s, e) => s + e.confidence, 0) / list.length).toFixed(2))
        : null,
      available: list.length ? ["shots"] : [],
      box_score: g.players.map((p) => {
        const mine = list.filter((e) => e.player_id === p.id);
        return {
          player_id: p.id,
          name: p.name,
          team: p.team,
          attempts: mine.length,
          makes: mine.filter((e) => e.made).length,
          points: 2 * mine.filter((e) => e.made).length,
          distance_m: distanceFor(p.id),
          confidence: mine.length
            ? Number((mine.reduce((s, e) => s + e.confidence, 0) / mine.length).toFixed(2))
            : 0,
        };
      }),
      shots: list
        .filter((e) => e.court)
        .map((e) => ({
          event_id: e.id,
          player_id: e.player_id,
          court: e.court as [number, number],
          made: !!e.made,
          outcome: e.made === true ? "make" : e.made === false ? "miss" : "unknown",
          confirmed: e.confirmed,
        })),
      heatmap: g.players.map((p) => ({
        player_id: p.id,
        cols: HEAT_COLS,
        rows: HEAT_ROWS,
        x_range: [0, 15] as [number, number],
        y_range: [0, 14] as [number, number],
        values: heatmapFor(p.id),
      })),
    };
    return delay(stats);
  },

  getTracksChunk(game, index) {
    const chunkS = game.tracks.chunk_s;
    const rate = game.tracks.rate_hz;
    const t0 = index * chunkS;
    const ids = game.players.map((p) => p.id).filter((id) => id in MOTION);
    const frames = Array.from({ length: chunkS * rate }, (_, i) => {
      const t = Number((t0 + i / rate).toFixed(3));
      return {
        t,
        p: t <= DURATION ? ids.filter((id) => tracked(id, t)).map((id) => trackAt(id, t)) : [],
      };
    });
    return delay<TracksChunk>({ schema: "replay.tracks.v1", t0, rate_hz: rate, frames });
  },

  getCropPath(game, playerId) {
    const rate = game.croppaths.rate_hz;
    const rects = Array.from({ length: Math.round(DURATION * rate) }, (_, i) => {
      const t = i / rate;
      const [x, y] = MOTION[playerId]?.(t) ?? [0.25, 0.25];
      const cx = x + BOX_W / 2;
      const cy = y + BOX_H / 2;
      const w = 0.5;
      return [
        Math.min(Math.max(cx - w / 2, 0), 1 - w),
        Math.min(Math.max(cy - w / 2, 0), 1 - w),
        w,
        w,
      ] as [number, number, number, number];
    });
    return delay<CropPath>({
      schema: "replay.crops.v1",
      player_id: playerId,
      rate_hz: rate,
      t0: 0,
      rects,
    });
  },

  createSession() {
    log("POST", "/sessions");
    return delay<Session>({ id: "s_mock", code: "4821" });
  },

  renderPlayer(gameId, playerId) {
    log("POST", `/games/${gameId}/players/${playerId}/render`);
    return delay<RenderJob>({ job_id: "j_mock", status: "queued", player_id: playerId });
  },

  listReplays(gameId) {
    log("GET", `/games/${gameId}/replays`);
    needGame(gameId);
    return delay(
      (MOCK_REPLAYS[gameId] ?? []).map((m) => ({
        play_id: m.play_id,
        label: m.label,
        t_start: m.t_start,
        t_end: m.t_end,
        angles: m.angles.length,
        manifest_url: `/games/${gameId}/replays/${m.play_id}`,
      })),
    );
  },

  getReplay(gameId, playId) {
    log("GET", `/games/${gameId}/replays/${playId}`);
    const m = MOCK_REPLAYS[gameId]?.find((r) => r.play_id === playId);
    if (!m) throw new Error(`unknown replay ${playId}`);
    return delay(structuredClone(m));
  },

  mediaUrl: (_game, path) => path,

  // ---- M13 integration wave: synthetic fixtures below (MOCK_*), all labelled mock ----

  listRenditions(gameId) {
    log("GET", `/games/${gameId}/renditions`);
    const g = needGame(gameId);
    const out: Rendition[] = [{ id: "wide", kind: "wide", url: g.renditions.wide }];
    if (MOCK_BROADCAST.has(gameId)) {
      out.push({ id: "broadcast", kind: "broadcast", url: "/mock/wide.mp4?rendition=broadcast", cuts_url: null });
    }
    return delay(out);
  },

  getCommentary(gameId) {
    log("GET", `/games/${gameId}/commentary`);
    needGame(gameId);
    return delay<Commentary>(structuredClone(MOCK_COMMENTARY[gameId] ?? { plays: [], narration_url: null }));
  },

  listClips(gameId) {
    log("GET", `/games/${gameId}/clips`);
    return delay(structuredClone(clipsOf(gameId)));
  },

  listTriggers(gameId) {
    log("GET", `/games/${gameId}/triggers`);
    return delay(structuredClone(triggersOf(gameId)));
  },

  trimClip(gameId, clipId, t_start, t_end) {
    log("PATCH", `/games/${gameId}/clips/${clipId}`, { t_start, t_end });
    const c = clipsOf(gameId).find((x) => x.id === clipId);
    if (!c) throw new Error(`clip ${clipId} not found`);
    if (t_end <= t_start || t_end > DURATION + 1e-6) throw new Error("need 0 <= t_start < t_end <= duration");
    Object.assign(c, { t_start, t_end, source: "user", edited: true });
    return delay(structuredClone(c));
  },

  tap(gameId, t) {
    log("POST", `/games/${gameId}/triggers`, { t });
    needGame(gameId);
    // D-50: the play with the latest t_end in [t - 8, t + 0.5]; clip = play ± 1 s.
    const play = (MOCK_PLAYS[gameId] ?? [])
      .filter((p) => p.t_end >= t - 8 && p.t_end <= t + 0.5)
      .sort((a, b) => b.t_end - a.t_end)[0];
    const n = triggersOf(gameId).length + 1;
    const trigger: Trigger = {
      id: `tr_u${n}`,
      type: "tap",
      t: Number(t.toFixed(3)),
      confidence: 1,
      source: "user",
      play_id: play?.id ?? null,
      clip_id: play ? `c_u${n}` : null,
    };
    triggersOf(gameId).push(trigger);
    const clip: PlayClip | null = play
      ? {
          id: `c_u${n}`,
          play_id: play.id,
          trigger_id: trigger.id,
          t_start: Math.max(0, play.t_start - 1),
          t_end: Math.min(DURATION, play.t_end + 1),
          attribution: { owner_player_id: null, by_player_id: null, subject_player_id: null },
          participants: play.participants,
          source: "user",
        }
      : null;
    if (clip) clipsOf(gameId).push(clip);
    return delay({ trigger: structuredClone(trigger), clip: structuredClone(clip) });
  },

  getHype(gameId) {
    log("GET", `/games/${gameId}/hype`);
    needGame(gameId);
    return delay<Hype>(mockHype(MOCK_HYPE_PEAKS[gameId] ?? []));
  },

  getRallies(gameId) {
    log("GET", `/games/${gameId}/rallies`);
    needGame(gameId);
    const rallies = MOCK_RALLIES[gameId] ?? [];
    const condensed = jobState(`condensed:${gameId}`, "/mock/wide.mp4?rendition=condensed");
    const done = condensed.status === "done";
    return delay<RallyDoc>({
      n: rallies.length,
      game_s: DURATION,
      rally_s: rallies.reduce((s, r) => s + r.duration_s, 0),
      longest: [...rallies].sort((a, b) => b.duration_s - a.duration_s).map((r) => r.id),
      rallies: rallies.map((r) => ({ ...r, condensed_t: done ? r.condensed_t : null })),
      condensed,
    });
  },

  renderCondensed(gameId) {
    log("POST", `/games/${gameId}/condensed`);
    if (!(MOCK_RALLIES[gameId] ?? []).length) {
      throw new Error("no rallies in this game: the condensed game is for net sports");
    }
    startJob(`condensed:${gameId}`);
    return delay<JobStatus>(jobState(`condensed:${gameId}`, "/mock/wide.mp4?rendition=condensed"));
  },

  exportVertical(gameId, body) {
    log("POST", `/games/${gameId}/exports/vertical`, body);
    const clip = body.clip_id ? clipsOf(gameId).find((c) => c.id === body.clip_id) : undefined;
    const t0 = clip?.t_start ?? body.t_start;
    const t1 = clip?.t_end ?? body.t_end;
    if (t0 === undefined || t1 === undefined || t1 <= t0) throw new Error("need a clip or a window");
    // D-47: a content-hash id — the same request is the same file.
    const vid = `v_${hex12(`${t0}|${t1}|${body.player_id ?? ""}`)}`;
    const name = (pid?: string | null) => needGame(gameId).players.find((p) => p.id === pid)?.name ?? pid;
    const pid = clip?.attribution.subject_player_id ?? clip?.attribution.by_player_id ?? body.player_id ?? null;
    verticals.set(`${gameId}/${vid}`, {
      id: vid,
      t_start: t0,
      t_end: t1,
      player_id: pid,
      caption: `${name(pid) ?? "Play"} · ${(t1 - t0).toFixed(1)} s (mock)`,
      size: [540, 960],
    });
    startJob(`vertical:${gameId}/${vid}`);
    return mockApi.getVertical(gameId, vid);
  },

  getVertical(gameId, vid) {
    const spec = verticals.get(`${gameId}/${vid}`);
    if (!spec) throw new Error(`export ${vid} not found`);
    return delay<VerticalExport>({ ...spec, ...jobState(`vertical:${gameId}/${vid}`, `/mock/wide.mp4?export=${vid}`) });
  },

  getReviewQueue(gameId) {
    log("GET", `/games/${gameId}/review/queue`);
    return delay(reviewQueue(needGame(gameId), events.get(gameId) ?? []));
  },

  async answerReview(option: ReviewOption, text?: string) {
    // patchEvent / patchPlayer log the call
    const [, , gid, kind, id] = option.path.split("/");
    if (kind === "events") await mockApi.patchEvent(gid, id, reviewBody(option, text));
    else if (kind === "players") await mockApi.patchPlayer(gid, id, reviewBody(option, text));
    else throw new Error(`unknown review route ${option.path}`);
  },

  search(gameId, text) {
    log("POST", `/games/${gameId}/search`, { text, k: 8 });
    const g = needGame(gameId);
    const plays = MOCK_PLAYS[gameId] ?? [];
    if (!plays.length) {
      // like a game without an embeddings index: the client's keyword fallback
      return mockApi.query(gameId, text).then((r) => queryAsSearch(text, r));
    }
    const words = new Set(text.toLowerCase().match(/[a-z]+/g) ?? []);
    const filtered = new Set(matchEvents(events.get(gameId) ?? [], text, g.players).map((e) => e.id));
    const hits = plays
      .map((p) => {
        const overlap = (p.text.toLowerCase().match(/[a-z]+/g) ?? []).filter((w) => words.has(w)).length;
        const filter_match = p.event_ids.some((id) => filtered.has(id));
        return { play_id: p.id, t_start: p.t_start, t_end: p.t_end, text: p.text, filter_match, score: overlap };
      })
      .sort((a, b) => Number(b.filter_match) - Number(a.filter_match) || b.score - a.score || a.t_start - b.t_start);
    return delay({
      query: text,
      interpretation: filtered.size ? `Showing: ${text}` : "No filter — ranked by similarity",
      filter_source: "rules",
      results: hits,
    });
  },

  getAdvice(gameId, playerId) {
    log("GET", `/games/${gameId}/players/${playerId}/advice`);
    const g = needGame(gameId);
    const p = g.players.find((x) => x.id === playerId);
    if (!p) throw new Error(`player ${playerId} not found`);
    const name = p.name ?? `Player ${playerId.slice(1)}`;
    const mine = (events.get(gameId) ?? []).filter((e) => e.type === "shot" && !e.dismissed && e.player_id === playerId);
    const makes = mine.filter((e) => e.made).length;
    const lines = mine.length
      ? [`${name} made ${makes} of ${mine.length} shots (mock).`, makes < mine.length ? "Work on the misses from the right side (mock)." : "Keep taking those shots (mock)."]
      : [`${name} took no shots this game (mock).`];
    return delay<Advice>({ player_id: playerId, name, lines, source: "template", auto_detected: true });
  },

  // ---- M10 profiles: synthetic fixtures (MOCK_PROFILES below), same rules as D-58 ----

  listProfiles() {
    log("GET", "/profiles");
    return delay([...profileDocs.values()].map((d) => ({ ...publicDoc(d) })));
  },

  getProfile(id) {
    log("GET", `/profiles/${id}`);
    return delay(fullProfile(needProfile(id)));
  },

  createProfile(body) {
    log("POST", "/profiles", body);
    if (!body.name?.trim()) throw new Error("name is required");
    const id = `pr_${hex12(`${body.name}|${profileDocs.size}|${Date.now()}`)}`;
    const doc: MockProfileDoc = {
      profile_id: id,
      name: body.name.trim(),
      photo_url: body.photo_url ?? null,
      sports: body.sports ?? null,
      positions: body.positions ?? [],
      stats_user: {},
      user_edited_fields: body.sports ? ["sports"] : [],
      face_enrolled: false,
    };
    profileDocs.set(id, doc);
    return delay(fullProfile(doc));
  },

  patchProfile(id, body) {
    log("PATCH", `/profiles/${id}`, body);
    const doc = needProfile(id);
    const edited = new Set(doc.user_edited_fields);
    for (const f of ["name", "photo_url", "sports", "positions"] as const) {
      if (!(f in body)) continue;
      Object.assign(doc, { [f]: f === "positions" ? (body.positions ?? []) : body[f] });
      edited.add(f);
    }
    if ("sports" in body && body.sports == null) edited.delete("sports");
    for (const [sport, vals] of Object.entries(body.stats ?? {})) {
      const mine = (doc.stats_user[sport] ??= {});
      for (const [k, v] of Object.entries(vals)) {
        if (v === null) delete mine[k];
        else mine[k] = v;
      }
      if (!Object.keys(mine).length) delete doc.stats_user[sport];
    }
    doc.user_edited_fields = [...edited].sort();
    if (body.name) for (const l of linksOf(id)) setRoster(l.game_id, l.player_id, doc.name, id);
    return delay(fullProfile(doc));
  },

  linkProfile(id, gameId, playerId) {
    log("POST", `/profiles/${id}/links`, { game_id: gameId, player_id: playerId });
    const doc = needProfile(id);
    if (!needGame(gameId).players.some((p) => p.id === playerId)) throw new Error(`player ${playerId} not found`);
    const owner = profileLinks.get(`${gameId}/${playerId}`);
    if (owner && owner !== id) throw new Error(`${gameId}/${playerId} is linked to another profile`);
    profileLinks.set(`${gameId}/${playerId}`, id);
    setRoster(gameId, playerId, doc.name, id);
    return delay(fullProfile(doc));
  },

  unlinkProfile(id, gameId, playerId) {
    log("DELETE", `/profiles/${id}/links/${gameId}/${playerId}`);
    const doc = needProfile(id);
    if (profileLinks.get(`${gameId}/${playerId}`) !== id) throw new Error("no such link");
    profileLinks.delete(`${gameId}/${playerId}`);
    setRoster(gameId, playerId, null, null);
    return delay(fullProfile(doc));
  },

  getSuggestions(id) {
    log("GET", `/profiles/${id}/suggestions`);
    const doc = needProfile(id);
    const norm = (s: string | null | undefined) => (s ?? "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
    const out: ProfileSuggestion[] = [];
    for (const g of games.values()) {
      for (const p of g.players) {
        if (profileLinks.has(`${g.id}/${p.id}`)) continue;
        const reasons: ProfileSuggestion["reasons"] = [];
        if (norm(p.name) && norm(p.name) === norm(doc.name)) reasons.push({ kind: "same_name" });
        // D-58: face matches exist only for enrolled profiles (deleting enrollment drops them)
        const face = doc.face_enrolled
          ? faceMatches.find((m) => m.profile_id === id && m.game_id === g.id && m.player_id === p.id)
          : undefined;
        if (face) reasons.push({ kind: "face", similarity: face.similarity, votes: face.votes });
        if (reasons.length) out.push({ game_id: g.id, game_title: g.title, player_id: p.id, reasons });
      }
    }
    return delay(out);
  },

  getCard(id) {
    log("GET", `/profiles/${id}/card`);
    return delay(mockCard(needProfile(id)));
  },

  renderCard(id) {
    log("POST", `/profiles/${id}/card`);
    renderedCards.add(id);
    return delay(mockCard(needProfile(id)));
  },

  getReel(id) {
    log("GET", `/profiles/${id}/reel`);
    return delay(mockReel(needProfile(id)));
  },

  uploadProfilePhoto(id, photo) {
    log("PUT", `/profiles/${id}/photo`, { size: photo.size, type: photo.type });
    const doc = needProfile(id);
    if (!photo.size) throw new Error("send one image up to 8 MB");
    doc.photo_url = URL.createObjectURL(photo);
    doc.user_edited_fields = [...new Set([...doc.user_edited_fields, "photo_url"])].sort();
    return delay(fullProfile(doc));
  },

  enrollFace(id, photos, consent) {
    log("POST", `/profiles/${id}/face`, { consent, photos: photos.length });
    const doc = needProfile(id);
    if (!consent) throw new Error("face enrollment needs consent=true from the person enrolled");
    if (photos.length < 1 || photos.length > 10) throw new Error("send 1 to 10 photos");
    doc.face_enrolled = true;
    return delay(fullProfile(doc));
  },

  deleteFace(id) {
    log("DELETE", `/profiles/${id}/face`);
    const doc = needProfile(id);
    doc.face_enrolled = false;
    faceMatches = faceMatches.filter((m) => m.profile_id !== id);
    return delay(fullProfile(doc));
  },

  profileMediaUrl: (path) => path,
};

// ---------------------------------------------------------------- M13 synthetic fixtures
// Everything below is MOCK data for the TV clients' tests and screenshots, not pipeline
// output. Video for every rendition / condensed game / export is the same 20 s
// wide.mp4 under a query string, like the replay angles.

const MOCK_BROADCAST = new Set(["g_mock01"]);

/** Mock plays (what plays.json would hold) — tap resolution and search use them. */
interface MockPlay {
  id: string;
  t_start: number;
  t_end: number;
  event_ids: string[];
  participants: string[];
  text: string;
}
const MOCK_PLAYS: Record<string, MockPlay[]> = {
  g_mock01: [
    { id: "pl_m1", t_start: 0.5, t_end: 4.5, event_ids: ["e_0001"], participants: ["p1"], text: "Marcus drives and scores two (mock)." },
    { id: "pl_m2", t_start: 5.5, t_end: 9.5, event_ids: ["e_0002"], participants: ["p2"], text: "Player 2 shoots from the wing, no good (mock)." },
    { id: "pl_m3", t_start: 11, t_end: 15.5, event_ids: ["e_0003"], participants: ["p1", "p3"], text: "Steal, then Marcus scores on the break (mock)." },
    { id: "pl_m4", t_start: 15.5, t_end: 18.5, event_ids: ["e_0004"], participants: ["p3"], text: "Player 3 hits a long jumper (mock)." },
  ],
  // M10: a second game for Marcus, so a career reel crosses games (no events: no stats)
  g_mock02: [
    { id: "pl_n1", t_start: 2, t_end: 6, event_ids: [], participants: ["p1", "p2"], text: "Marcus brings it up (mock)." },
    { id: "pl_n2", t_start: 12, t_end: 16, event_ids: [], participants: ["p1"], text: "Marcus on the break (mock)." },
  ],
};

function clip(id: string, play: string, trig: string, t0: number, t1: number, by: string | null, subject: string | null, participants: string[], source: PlayClip["source"] = "auto"): PlayClip {
  return {
    id,
    play_id: play,
    trigger_id: trig,
    t_start: t0,
    t_end: t1,
    attribution: { owner_player_id: by ?? subject, by_player_id: by, subject_player_id: subject },
    participants,
    source,
  };
}
const clips = new Map<string, PlayClip[]>([
  [
    "g_mock01",
    [
      clip("c_g1", "pl_m1", "tr_g1", 0, 5.5, "p1", null, ["p1"]),
      clip("c_t1", "pl_m2", "tr_t1", 4.5, 10.5, null, null, ["p2"], "user"),
      clip("c_v1", "pl_m3", "tr_v1", 10, 16.5, null, "p1", ["p1", "p3"]),
    ],
  ],
]);
const triggers = new Map<string, Trigger[]>([
  [
    "g_mock01",
    [
      { id: "tr_g1", type: "gesture", t: 5.2, by_player_id: "p1", confidence: 0.86, source: "auto", play_id: "pl_m1", clip_id: "c_g1" },
      { id: "tr_t1", type: "tap", t: 10, confidence: 1, source: "user", play_id: "pl_m2", clip_id: "c_t1" },
      { id: "tr_v1", type: "voice", t: 16, subject_player_id: "p1", transcript: "Replay, clip Marcus", confidence: 0.9, source: "auto", play_id: "pl_m3", clip_id: "c_v1" },
    ],
  ],
]);
function listOf<T>(m: Map<string, T[]>, gameId: string): T[] {
  needGame(gameId);
  const list = m.get(gameId) ?? [];
  m.set(gameId, list);
  return list;
}
const clipsOf = (gameId: string) => listOf(clips, gameId);
const triggersOf = (gameId: string) => listOf(triggers, gameId);

const MOCK_COMMENTARY: Record<string, Commentary> = {
  g_mock01: {
    schema: "replay.commentary.v1",
    stored: false,
    narration_url: null,
    plays: [
      { play_id: "pl_m1", source: "template", lines: [
        { t: 1, text: "Marcus brings it up the floor.", audio_t: 1, audio_s: 1.8 },
        { t: 3, text: "Marcus scores two.", audio_t: 3, audio_s: 1.5 },
      ] },
      { play_id: "pl_m2", source: "template", lines: [{ t: 8, text: "Player 2 shoots, no good.", audio_t: 8, audio_s: 1.8 }] },
      { play_id: "pl_m3", source: "template", lines: [{ t: 14, text: "Marcus scores again!", audio_t: 14, audio_s: 1.6 }] },
      { play_id: "pl_m4", source: "template", lines: [{ t: 17, text: "Player 3 scores two.", audio_t: 17, audio_s: 1.6 }] },
    ],
  },
};

/** [peak t, height, is a candidate] — bumps on a 2 Hz series like hype.json. */
const MOCK_HYPE_PEAKS: Record<string, [number, number, boolean][]> = {
  g_mock01: [
    [3.5, 0.8, true],
    [14.5, 0.95, true],
    [17.5, 0.45, false],
  ],
  g_pickle4: [[10, 0.7, true]],
};
function mockHype(peaks: [number, number, boolean][]): Hype {
  const rate = 2;
  const values = Array.from({ length: DURATION * rate }, (_, i) => {
    const t = i / rate;
    const v = Math.max(0.05, ...peaks.map(([p, h]) => h * Math.exp(-((t - p) ** 2) / 2)));
    return Number(v.toFixed(3));
  });
  return {
    schema: "replay.hype.v1",
    rate_hz: rate,
    duration_s: DURATION,
    values,
    candidates: peaks
      .filter(([, , c]) => c)
      .map(([t, score]) => ({ t, score, t_start: Math.max(0, t - 3), t_end: t + 1, reasons: ["audio"] }))
      .sort((a, b) => b.score - a.score),
  };
}

const MOCK_RALLIES: Record<string, RallyDoc["rallies"]> = {
  g_pickle4: [
    { id: "r1", n: 1, event_id: "e_r1", t_start: 1, t_end: 6, duration_s: 5, shots: 6, confidence: 0.8, condensed_t: 0 },
    { id: "r2", n: 2, event_id: "e_r2", t_start: 8, t_end: 16.5, duration_s: 8.5, shots: 11, confidence: 0.74, condensed_t: 6.5 },
    { id: "r3", n: 3, event_id: "e_r3", t_start: 17, t_end: 19.5, duration_s: 2.5, shots: 0, confidence: 0.52, condensed_t: 17.5 },
  ],
};

/** A render job: queued on start, done JOB_MS later (like AUTOCALIB_MS). */
const JOB_MS = 600;
const jobs = new Map<string, number>();
function startJob(key: string) {
  if (!jobs.has(key)) jobs.set(key, Date.now());
}
function jobState(key: string, url: string): JobStatus {
  const started = jobs.get(key);
  if (started === undefined) return { status: "none", url: null, job_id: null };
  if (Date.now() - started < JOB_MS) return { status: "queued", url: null, job_id: `j_${key}` };
  return { status: "done", url, job_id: `j_${key}` };
}
const verticals = new Map<string, Omit<VerticalExport, keyof JobStatus>>();
function hex12(s: string): string {
  let h = 2166136261;
  for (const ch of s) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  return (h.toString(16).padStart(8, "0") + "0000").slice(0, 12);
}

/** services/api stats.review_queue, same rules: unknown shot outcomes, low-confidence
 *  events, then up to 5 untagged players (name them or merge into a teammate). */
function reviewQueue(g: Game, list: GameEvent[]): ReviewQuestion[] {
  const out: ReviewQuestion[] = [];
  const opt = (label: string, path: string, body: Record<string, unknown>, text_field?: string): ReviewOption => ({
    label,
    method: "PATCH",
    path,
    body,
    ...(text_field ? { text_field } : {}),
  });
  for (const e of [...list].sort((a, b) => a.t_key - b.t_key)) {
    if (e.confirmed || e.dismissed || e.type !== "shot") continue;
    const path = `/games/${g.id}/events/${e.id}`;
    const base = { event_id: e.id, t: e.t_key, player_id: e.player_id, confidence: e.confidence };
    const no = opt("Not a shot", path, { dismissed: true, confirmed: true });
    if (e.made === undefined || e.made === null) {
      out.push({ ...base, id: `q_outcome_${e.id}`, kind: "shot_outcome", prompt: "Make or miss?", options: [
        opt("Made", path, { made: true, confirmed: true }),
        opt("Missed", path, { made: false, confirmed: true }),
        no,
      ] });
    } else if (e.confidence < REVIEW_CONFIDENCE_THRESHOLD) {
      out.push({ ...base, id: `q_conf_${e.id}`, kind: "low_confidence", prompt: "Was this a shot?", options: [
        opt("Yes", path, { confirmed: true }),
        { ...no, label: "No" },
      ] });
    }
  }
  const tagged = g.players.filter((p) => p.name);
  for (const p of g.players.filter((x) => !x.name).slice(0, 5)) {
    const path = `/games/${g.id}/players/${p.id}`;
    const mates = tagged.filter((q) => q.team === p.team);
    out.push({
      id: `q_who_${p.id}`,
      kind: "identity",
      player_id: p.id,
      prompt: `Who is #${p.id}?`,
      options: [
        opt("Type a name", path, {}, "name"),
        ...(mates.length ? mates : tagged).map((q) => opt(`Same as ${q.name}`, path, { merge_into: q.id })),
      ],
    });
  }
  return out;
}

/** M8 replay fixture (labelled mock): every angle is the same 20 s wide.mp4 under a
 *  per-angle query string, so a cut is a real src swap + reload that has to land at the
 *  same media time, without shipping more video. */
function mockAngle(id: string, tier: ReplayAngle["tier"], label: string): ReplayAngle {
  return { id, tier, label, url: `/mock/wide.mp4?angle=${id}`, duration_s: DURATION, width: 1280, height: 720 };
}
function mockReplay(play_id: string, label: string, angles: ReplayAngle[]): ReplayManifest {
  return {
    schema: "replay.replay_manifest.v1",
    game_id: "g_mock01",
    play_id,
    label,
    sport: "basketball",
    t_start: 0,
    t_end: DURATION,
    source: "synthetic_gt",
    synthetic: true,
    angles,
    commentary: null,
  };
}
const MOCK_REPLAYS: Record<string, ReplayManifest[]> = {
  g_mock01: [
    mockReplay("play_0001", "Marcus — make (mock)", [
      mockAngle("wide", "A", "Wide"),
      mockAngle("follow:p1", "A", "Follow · Marcus"),
      mockAngle("broadcast_high", "B", "Broadcast high"),
      mockAngle("orbit", "B", "Orbit"),
    ]),
    mockReplay("play_0002", "Possession 2 (mock)", [
      mockAngle("wide", "A", "Wide"),
      mockAngle("push_in", "B", "Push in"),
      mockAngle("reverse", "B", "Reverse"),
    ]),
  ],
};

// ---------------------------------------------------------------- M10 profiles (synthetic)
// MOCK profiles for the TV/phone tests and screenshots, not real people or pipeline output.
// Stats are summed from the mock events like career.stats_by_sport does (shot keys only
// for a game with shots), corrections win and stay listed, and face suggestions exist
// only for an enrolled profile. The card image is a hand-drawn SVG labelled "mock".

interface MockProfileDoc {
  profile_id: string;
  name: string;
  photo_url: string | null;
  sports: string[] | null;
  positions: string[];
  stats_user: Record<string, Record<string, number>>;
  user_edited_fields: string[];
  face_enrolled: boolean;
}

const profileDocs = new Map<string, MockProfileDoc>([
  ["pr_00000000a001", {
    profile_id: "pr_00000000a001", name: "Marcus", photo_url: null, sports: null, positions: ["guard"],
    stats_user: { basketball: { rebounds: 3 } }, user_edited_fields: ["positions"], face_enrolled: false,
  }],
  ["pr_00000000a002", {
    profile_id: "pr_00000000a002", name: "Jordan", photo_url: null, sports: ["basketball"], positions: [],
    stats_user: {}, user_edited_fields: ["sports"], face_enrolled: true,
  }],
  ["pr_00000000a003", {
    profile_id: "pr_00000000a003", name: "Sam", photo_url: null, sports: ["pickleball"], positions: [],
    stats_user: {}, user_edited_fields: ["sports"], face_enrolled: false,
  }],
]);
/** "game/player" → profile id (one owner per roster player, D-58). */
const profileLinks = new Map<string, string>([
  ["g_mock01/p1", "pr_00000000a001"],
  ["g_pickle4/p1", "pr_00000000a001"],
]);
/** What a face_match job would have written for enrolled profiles (faces.json). */
let faceMatches = [{ profile_id: "pr_00000000a002", game_id: "g_mock01", player_id: "p3", similarity: 0.58, votes: 4 }];
const renderedCards = new Set<string>();
for (const [key, id] of profileLinks) {
  const [g, p] = key.split("/");
  setRoster(g, p, profileDocs.get(id)?.name ?? null, id);
}

function needProfile(id: string): MockProfileDoc {
  const d = profileDocs.get(id);
  if (!d) throw new Error(`profile ${id} not found`);
  return d;
}

function setRoster(gameId: string, playerId: string, name: string | null, profileId: string | null) {
  const p = games.get(gameId)?.players.find((x) => x.id === playerId);
  if (!p) return;
  if (profileId === null) delete p.profile_id;
  else Object.assign(p, { name, tagged: true, profile_id: profileId });
}

/** Linked roster players, oldest game first (like career.load_links). */
function linksOf(id: string): { game_id: string; player_id: string }[] {
  return [...profileLinks]
    .filter(([, owner]) => owner === id)
    .map(([key]) => ({ game_id: key.split("/")[0], player_id: key.split("/")[1] }))
    .sort((a, b) => a.game_id.localeCompare(b.game_id) || a.player_id.localeCompare(b.player_id));
}

function mockGameStats(gameId: string, pid: string): Record<string, number> {
  const evs = (events.get(gameId) ?? []).filter((e) => !e.dismissed);
  const out: Record<string, number> = {
    games: 1,
    plays: (MOCK_PLAYS[gameId] ?? []).filter((p) => p.participants.includes(pid)).length,
    distance_m: distanceFor(pid),
  };
  if (evs.some((e) => e.type === "shot")) {
    const mine = evs.filter((e) => e.type === "shot" && e.player_id === pid);
    const made = mine.filter((e) => e.made).length;
    Object.assign(out, { points: 2 * made, shots_made: made, shots_attempted: mine.length, rebounds: 0, steals: 0 });
  }
  return out;
}

function statsBySport(doc: MockProfileDoc): Record<string, SportStats> {
  const out: Record<string, SportStats> = {};
  for (const l of linksOf(doc.profile_id)) {
    const g = games.get(l.game_id);
    if (!g) continue;
    const s = (out[g.sport] ??= { stats: {}, auto: {}, edited: [], games: [] });
    const row = mockGameStats(l.game_id, l.player_id);
    s.games = [...(s.games ?? []), { ...l, ...row }];
    for (const [k, v] of Object.entries(row)) s.auto[k] = Number(((s.auto[k] ?? 0) + v).toFixed(1));
  }
  for (const sport of Object.keys(doc.stats_user)) out[sport] ??= { stats: {}, auto: {}, edited: [], games: [] };
  for (const [sport, s] of Object.entries(out)) {
    const user = doc.stats_user[sport] ?? {};
    s.stats = { ...s.auto, ...user };
    s.edited = Object.keys(user).sort();
    s.label = "auto-detected";
  }
  return out;
}

function publicDoc(doc: MockProfileDoc): Profile {
  const { stats_user, ...rest } = doc;
  const fields = new Set(doc.user_edited_fields.filter((f) => !f.startsWith("stats_by_sport.")));
  for (const [sport, vals] of Object.entries(stats_user)) for (const k of Object.keys(vals)) fields.add(`stats_by_sport.${sport}.${k}`);
  return { schema: "replay.profile.v1", ...structuredClone(rest), user_edited_fields: [...fields].sort(), linked: linksOf(doc.profile_id) };
}

function fullProfile(doc: MockProfileDoc): Profile {
  const stats = statsBySport(doc);
  return { ...publicDoc(doc), sports: doc.sports ?? Object.keys(stats).sort(), stats_by_sport: stats, missing_links: [] };
}

function mockReel(doc: MockProfileDoc): CareerReel {
  const items = linksOf(doc.profile_id).flatMap((l) =>
    (MOCK_PLAYS[l.game_id] ?? [])
      .filter((p) => p.participants.includes(l.player_id))
      .map((p) => ({
        ...l,
        play_id: p.id,
        sport: games.get(l.game_id)?.sport,
        t_start: p.t_start,
        t_end: p.t_end,
        game_title: games.get(l.game_id)?.title ?? null,
        // every game is the same 20 s fixture; the query string makes each a distinct src
        url: `/mock/wide.mp4?game=${l.game_id}`,
      })),
  );
  return { schema: "replay.reel.v1", profile_id: doc.profile_id, items, duration_s: items.reduce((s, i) => s + i.t_end - i.t_start, 0) };
}

function mockCard(doc: MockProfileDoc): PlayerCard {
  const stats = statsBySport(doc);
  const sport = Object.keys(stats).sort((a, b) => (stats[b].stats.games ?? 0) - (stats[a].stats.games ?? 0) || a.localeCompare(b))[0] ?? null;
  const s = sport ? stats[sport] : undefined;
  const n = s?.stats.games ?? 0;
  const g = n === 1 ? "1 game" : `${n} games`;
  const title = s?.stats.points ? `${doc.name} the scorer: ${s.stats.points} points in ${g} (mock)` : `${doc.name}: ${s?.stats.plays ?? 0} plays in ${g} (mock)`;
  const TILES: [string, string][] = [["points", "PTS"], ["rebounds", "REB"], ["plays", "PLAYS"], ["distance_m", "METRES"]];
  const first = mockReel(doc).items.find((i) => i.sport === sport);
  const best: PlayerCard["best_moment"] = first
    ? { game_id: first.game_id, player_id: first.player_id, play_id: first.play_id, sport: first.sport, t_start: first.t_start, t_end: first.t_end }
    : null;
  const st = s?.stats ?? {};
  return {
    schema: "replay.card.v1",
    profile_id: doc.profile_id,
    name: doc.name,
    sport,
    sports: doc.sports ?? Object.keys(stats).sort(),
    positions: doc.positions,
    games: n,
    title,
    title_source: "template",
    stats: TILES.filter(([k]) => k in st).map(([key, label]) => ({
      key,
      label,
      value: key === "distance_m" ? Math.round(st[key]) : st[key],
      edited: !!s?.edited.includes(key),
    })),
    user_edited: !!s?.edited.length,
    label: "auto-detected",
    best_moment: best,
    photo_url: doc.photo_url,
    face_enrolled: doc.face_enrolled,
    png: "/mock/card.svg",
    thumb: null,
    rendered: renderedCards.has(doc.profile_id),
  };
}
