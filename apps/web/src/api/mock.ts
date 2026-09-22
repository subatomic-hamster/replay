// Dev/test double for §4.6. Enabled with VITE_MOCK_API=1 so the TV UI and the
// Playwright suite can run before services/api exists. Serves one fixture game
// backed by public/mock/wide.mp4 (20 s, 1280x720, 30 fps).
// ponytail: in-memory only — state resets on reload. Good enough; the real API is the
// persistence story.
import type {
  CalibrationResult,
  CreateGameResult,
  CropPath,
  Game,
  GameEvent,
  GameSummary,
  Player,
  QueryResult,
  Session,
  SportProfile,
  Stats,
  TracksChunk,
  TrackPlayer,
} from "./types";
import type { CalibrationPayload, ReplayApi } from "./client";

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

const BASKETBALL: SportProfile = {
  id: "basketball",
  display_name: "Basketball",
  tier: 2,
  landmarks: ["corner_nl", "corner_nr", "corner_fl", "corner_fr", "rim"],
  variants: ["half", "full"],
  sport_ui: {
    chips: ["All shots", "Makes", "Misses"],
    review: ["shot_chart", "box_score"],
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

function trackAt(id: string, t: number): TrackPlayer {
  const [x, y] = MOTION[id](t);
  return {
    id,
    bb: [x, y, BOX_W, BOX_H],
    ct: [Number(((x + BOX_W / 2) * 15).toFixed(2)), Number(((y + BOX_H) * 14).toFixed(2))],
    c: 0.9,
  };
}

function baseGame(id: string, title: string, status: Game["status"]): Game {
  const done = status === "ready";
  return {
    schema: "replay.game.v1",
    id,
    title,
    recorded_at: "2026-09-29T19:30:00-04:00",
    status,
    stages: done
      ? { ingest: "done", detect: "done", track: "done", render: "partial", label: "done" }
      : { ingest: "done", detect: "running", track: "pending", render: "pending", label: "pending" },
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
  for (const g of [g1, g2, g3]) games.set(g.id, g);
  events.set("g_mock01", [
    ev("e_0001", 3.0, "p1", true, 0.82, [4.0, 5.0]),
    ev("e_0002", 8.0, "p2", false, 0.74, [9.0, 6.5]),
    ev("e_0003", 14.0, "p1", true, 0.91, [6.5, 3.2]),
    ev("e_0004", 17.0, "p3", true, 0.55, [11.0, 4.0]),
  ]);
  events.set("g_mock02", []);
  events.set("g_proc03", []);
}
seed();

const STAGE_ORDER = ["ingest", "detect", "track", "render", "label"] as const;

/** Advance one stage per poll so the status screen finishes in a few seconds. */
function advance(g: Game) {
  if (g.status !== "processing") return;
  for (const s of STAGE_ORDER) {
    if (g.stages[s] === "pending") {
      g.stages[s] = "running";
      return;
    }
    if (g.stages[s] === "running") {
      g.stages[s] = s === "render" ? "partial" : "done";
      if (s === "label") {
        g.status = "ready";
        g.players = baseGame(g.id, g.title, "ready").players;
      }
      return;
    }
  }
}

function needGame(id: string): Game {
  const g = games.get(id);
  if (!g) throw new Error(`unknown game ${id}`);
  return g;
}

const delay = <T,>(v: T, ms = 10) => new Promise<T>((r) => setTimeout(() => r(v), ms));

function matchEvents(list: GameEvent[], text: string, players: Player[]): GameEvent[] {
  const q = text.toLowerCase();
  let out = list.filter((e) => e.type === "shot");
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
    return delay([BASKETBALL]);
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
    return delay<CalibrationResult>({ ok: true, reprojection_error_px: 3.2 });
  },

  startProcessing(gameId) {
    log("POST", `/games/${gameId}/process`);
    const g = needGame(gameId);
    g.status = "processing";
    g.stages = { ingest: "running", detect: "pending", track: "pending", render: "pending", label: "pending" };
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
    if (body.type === undefined && body.made === undefined && !body.confirmed) {
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
    const list = (events.get(gameId) ?? []).filter((e) => e.type === "shot");
    const stats: Stats = {
      box_score: g.players.map((p) => {
        const mine = list.filter((e) => e.player_id === p.id);
        return {
          player_id: p.id,
          name: p.name,
          attempts: mine.length,
          makes: mine.filter((e) => e.made).length,
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
          confirmed: e.confirmed,
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
      return { t, p: t <= DURATION ? ids.map((id) => trackAt(id, t)) : [] };
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

  mediaUrl: (_game, path) => path,
};
