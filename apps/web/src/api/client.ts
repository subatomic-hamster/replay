import { API_BASE, API_KEY, MOCK_API } from "../config";
import { mockApi } from "./mock";
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
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export interface CalibrationPayload {
  sport: string;
  court_variant: string;
  landmarks_px: Record<string, [number, number]>;
}

export interface ReplayApi {
  listSports(): Promise<SportProfile[]>;
  createGame(title: string, sport: string): Promise<CreateGameResult>;
  upload(uploadUrl: string, file: File, onProgress: (pct: number) => void): Promise<void>;
  calibrate(gameId: string, payload: CalibrationPayload): Promise<CalibrationResult>;
  startProcessing(gameId: string): Promise<void>;
  listGames(): Promise<GameSummary[]>;
  getGame(gameId: string): Promise<Game>;
  patchPlayer(
    gameId: string,
    pid: string,
    body: { name?: string; merge_into?: string },
  ): Promise<Player>;
  getEvents(game: Game): Promise<GameEvent[]>;
  createEvent(gameId: string, body: Partial<GameEvent>): Promise<GameEvent>;
  patchEvent(gameId: string, eventId: string, body: Partial<GameEvent>): Promise<GameEvent>;
  query(gameId: string, text: string): Promise<QueryResult>;
  getStats(gameId: string): Promise<Stats>;
  getTracksChunk(game: Game, index: number): Promise<TracksChunk>;
  getCropPath(game: Game, playerId: string): Promise<CropPath>;
  createSession(): Promise<Session>;
  /** Absolute URL for a media path from game.json (already-absolute passes through). */
  mediaUrl(game: Game, path: string): string;
}

/** §4.6: game.json media URLs "resolved to absolute" — but tolerate relative ones. */
function resolveMedia(gameId: string, path: string): string {
  if (/^(https?:)?\/\//.test(path) || path.startsWith("blob:") || path.startsWith("data:")) {
    return path;
  }
  return `${API_BASE}/media/games/${gameId}/${path.replace(/^\//, "")}`;
}

function headers(json: boolean): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  if (API_KEY) h["X-Replay-Key"] = API_KEY;
  return h;
}

async function req<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: { ...headers(json !== undefined), ...(rest.headers as object) },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    // The API reports failures as {"detail": "..."} — surface that, not just the code.
    const detail = await res.text().then(
      (t) => (t ? ((JSON.parse(t) as { detail?: string }).detail ?? t) : ""),
      () => "",
    );
    throw new ApiError(res.status, detail || `${init?.method ?? "GET"} ${path} → ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

async function fetchUrl<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: headers(false) });
  if (!res.ok) throw new ApiError(res.status, `GET ${url} → ${res.status}`);
  return (await res.json()) as T;
}

function chunkUrl(game: Game, index: number): string {
  // url_template uses a python-style {chunk:05d} placeholder (§4.5).
  const path = game.tracks.url_template.replace(
    /\{chunk(?::0(\d+)d)?\}/,
    (_m, width?: string) => String(index).padStart(Number(width ?? 0), "0"),
  );
  return resolveMedia(game.id, path);
}

export const httpApi: ReplayApi = {
  listSports: () => req<SportProfile[]>("/sports"),
  createGame: (title, sport) =>
    req<CreateGameResult>("/games", { method: "POST", json: { title, sport } }),

  upload(uploadUrl, file, onProgress) {
    // XHR, not fetch: fetch has no upload progress events.
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", uploadUrl);
      if (API_KEY) xhr.setRequestHeader("X-Replay-Key", API_KEY);
      xhr.setRequestHeader("Content-Type", file.type || "video/mp4");
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          onProgress(100);
          resolve();
        } else {
          reject(new ApiError(xhr.status, `upload → ${xhr.status}`));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, "upload failed"));
      xhr.send(file);
    });
  },

  // The API takes `variant` and answers 200 `{court, reprojection_error_px}` /
  // 400 `{detail}`; the screens want a flat ok/error result.
  calibrate: (gameId, payload) =>
    req<{ reprojection_error_px?: number | null }>(`/games/${gameId}/calibration`, {
      method: "POST",
      json: {
        sport: payload.sport,
        variant: payload.court_variant,
        landmarks_px: payload.landmarks_px,
      },
    }).then(
      (r): CalibrationResult => ({ ok: true, reprojection_error_px: r.reprojection_error_px ?? undefined }),
      (e: Error) => ({ ok: false, error: e.message }),
    ),
  startProcessing: (gameId) => req<void>(`/games/${gameId}/process`, { method: "POST" }),
  listGames: () => req<GameSummary[]>("/games"),
  getGame: (gameId) => req<Game>(`/games/${gameId}`),
  // The API answers with the whole game (a merge rewrites the roster); callers want
  // the one player they touched.
  patchPlayer: (gameId, pid, body) =>
    req<Game>(`/games/${gameId}/players/${pid}`, { method: "PATCH", json: body })
      .then((g) => g.players.find((p) => p.id === pid) ?? { id: pid, name: body.name ?? null, team: 0 }),
  getEvents: (game) =>
    fetchUrl<{ events: GameEvent[] }>(resolveMedia(game.id, game.events_url)).then(
      (f) => f.events,
    ),
  // §4.6 "create bookmark": the API only takes the timestamp and derives the window.
  createEvent: (gameId, body) =>
    req<GameEvent>(`/games/${gameId}/events`, { method: "POST", json: { t: body.t_key ?? 0 } }),
  patchEvent: (gameId, eventId, body) =>
    req<GameEvent>(`/games/${gameId}/events/${eventId}`, { method: "PATCH", json: body }),
  query: (gameId, text) =>
    req<QueryResult>(`/games/${gameId}/query`, { method: "POST", json: { text } }),
  getStats: (gameId) => req<Stats>(`/games/${gameId}/stats`),
  getTracksChunk: (game, index) => fetchUrl<TracksChunk>(chunkUrl(game, index)),
  getCropPath: (game, playerId) =>
    fetchUrl<CropPath>(
      resolveMedia(game.id, game.croppaths.url_template.replace("{player_id}", playerId)),
    ),
  createSession: () => req<Session>("/sessions", { method: "POST" }),
  mediaUrl: (game, path) => resolveMedia(game.id, path),
};

export const api: ReplayApi = MOCK_API ? mockApi : httpApi;
