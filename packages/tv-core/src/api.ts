// §4.6 HTTP client, shared by apps/web and apps/tv. Pure TS over fetch/XHR/WebSocket,
// which both browsers and React Native provide. Each app builds one with its own base
// URL (apps/web: VITE_REPLAY_API_BASE; apps/tv: platform/config).
import type {
  AutoCalibration,
  AutoCalibrationJob,
  CalibrationResult,
  CreateGameResult,
  CropPath,
  Game,
  GameEvent,
  GameSummary,
  MultipartInit,
  Player,
  QueryResult,
  RenderJob,
  SceneLayout,
  Session,
  SportProfile,
  Stats,
  TracksChunk,
} from "./types";
import type { ReplayManifest, ReplaySummary } from "./replays";
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
  SearchResult,
  TapResult,
  Trigger,
  VerticalExport,
  VerticalRequest,
} from "./discovery";
import type {
  CareerReel,
  PlayerCard,
  Profile,
  ProfileInput,
  ProfileSuggestion,
} from "./profiles";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface CalibrationPayload {
  sport: string;
  court_variant: string;
  landmarks_px: Record<string, [number, number]>;
  /** D-23: commit an ok=false proposal's dots unmoved; the API records the override. */
  accept_low_confidence?: boolean;
}

export interface ReplayApi {
  listSports(): Promise<SportProfile[]>;
  createGame(title: string, sport: string): Promise<CreateGameResult>;
  upload(uploadUrl: string, file: File, onProgress: (pct: number) => void): Promise<void>;
  /** D-80 phone upload: presigned part URLs (409 in local mode — use `upload`). */
  initMultipart(gameId: string, size: number, contentType: string): Promise<MultipartInit>;
  completeMultipart(gameId: string, uploadId: string, parts: { n: number; etag: string }[]): Promise<Game>;
  abortMultipart(gameId: string, uploadId: string): Promise<void>;
  calibrate(gameId: string, payload: CalibrationPayload): Promise<CalibrationResult>;
  /** D-23: queue a landmark proposal for this game's calibration frame. */
  startAutoCalibration(gameId: string, sport: string, variant: string): Promise<AutoCalibrationJob>;
  /** Poll it — the model call takes tens of seconds. */
  getAutoCalibration(gameId: string): Promise<AutoCalibration>;
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
  /** Plan task 12: queue the follow-cam rendition for one player (fire-and-forget). */
  renderPlayer(gameId: string, playerId: string): Promise<RenderJob>;
  /** M8: the game's rendered multi-angle replays ([] when none). */
  listReplays(gameId: string): Promise<ReplaySummary[]>;
  /** M8: one replay's manifest; angle URLs come back absolute. */
  getReplay(gameId: string, playId: string): Promise<ReplayManifest>;
  /** One play's 2.5D scene package layout (replay.scene_package.v1); file URLs absolute. */
  getScene(gameId: string, playId: string): Promise<SceneLayout>;
  /** Absolute URL for a media path from game.json (already-absolute passes through). */
  mediaUrl(game: Game, path: string): string;

  // ---- M13 integration wave (routes from M5/M6/M7/M11) ----
  /** M6: wide, follow-cams and (when rendered) the directed broadcast. */
  listRenditions(gameId: string): Promise<Rendition[]>;
  /** M7: the grounded commentary script (stored, else generated from templates). */
  getCommentary(gameId: string): Promise<Commentary>;
  /** M5: "Replay, clip that" clips and the triggers that cut them. */
  listClips(gameId: string): Promise<PlayClip[]>;
  listTriggers(gameId: string): Promise<Trigger[]>;
  trimClip(gameId: string, clipId: string, t_start: number, t_end: number): Promise<PlayClip>;
  /** Phone tap at media time `t`: resolves to the play that just ended. */
  tap(gameId: string, t: number): Promise<TapResult>;
  /** M11 (D-45..D-48). */
  getHype(gameId: string): Promise<Hype>;
  getRallies(gameId: string): Promise<RallyDoc>;
  renderCondensed(gameId: string): Promise<JobStatus>;
  exportVertical(gameId: string, body: VerticalRequest): Promise<VerticalExport>;
  getVertical(gameId: string, vid: string): Promise<VerticalExport>;
  getReviewQueue(gameId: string): Promise<ReviewQuestion[]>;
  /** Send one review answer: the option already names its route (D-48). */
  answerReview(option: ReviewOption, text?: string): Promise<void>;
  /** M7: semantic search; falls back to the keyword query route when the game has no
   *  embeddings index yet (409) or no embeddings model (503). */
  search(gameId: string, text: string): Promise<SearchResult>;
  getAdvice(gameId: string, playerId: string): Promise<Advice>;

  // ---- M10 profiles (D-58) ----
  listProfiles(): Promise<Profile[]>;
  getProfile(id: string): Promise<Profile>;
  createProfile(body: ProfileInput & { name: string }): Promise<Profile>;
  patchProfile(id: string, body: ProfileInput): Promise<Profile>;
  /** Names the roster player after the profile (409 when another profile owns it). */
  linkProfile(id: string, gameId: string, playerId: string): Promise<Profile>;
  unlinkProfile(id: string, gameId: string, playerId: string): Promise<Profile>;
  getSuggestions(id: string): Promise<ProfileSuggestion[]>;
  /** "Not this person": never suggested to this profile again; answers the new list. */
  declineSuggestion(id: string, gameId: string, playerId: string): Promise<ProfileSuggestion[]>;
  getCard(id: string): Promise<PlayerCard>;
  /** Renders card.png (and the best-moment thumbnail) and answers with the card JSON. */
  renderCard(id: string): Promise<PlayerCard>;
  getReel(id: string): Promise<CareerReel>;
  uploadProfilePhoto(id: string, photo: Blob): Promise<Profile>;
  /** Opt-in face enrollment. `consent` is the person's own explicit yes; the API refuses
   *  without it. 1–10 photos; they are embedded and deleted server-side. */
  enrollFace(id: string, photos: Blob[], consent: boolean): Promise<Profile>;
  deleteFace(id: string): Promise<Profile>;
  /** Absolute URL for a `/media/profiles/...` path from a profile or card. */
  profileMediaUrl(path: string): string;
}

/** The review body with the keyboard text filled into `text_field`. */
export function reviewBody(option: ReviewOption, text?: string): Record<string, unknown> {
  return option.text_field ? { ...option.body, [option.text_field]: text ?? "" } : option.body;
}

/** POST /query clips as search hits — the keyword fallback for `search`. */
export function queryAsSearch(text: string, r: QueryResult): SearchResult {
  return {
    query: text,
    interpretation: r.interpretation,
    filter_source: "rules",
    fallback: true,
    results: r.clips.map((c, i) => ({
      play_id: c.event_id ?? `q_${i}`,
      t_start: c.t_start,
      t_end: c.t_end,
      text: c.label ?? "clip",
      filter_match: true,
    })),
  };
}

/** H4: the phone companion connects with the 4-digit code, the TV with the session id —
 *  the WS route accepts either (D-16). */
export function sessionWsUrl(base: string, idOrCode: string): string {
  return `${base.replace(/^http/, "ws")}/sessions/${encodeURIComponent(idOrCode)}`;
}

/** D-80 tuning: parts in flight, and retries per part (backoff 0.5, 1, 2, 4 s). */
const PART_CONCURRENCY = 3;
const PART_RETRIES = 4;

/** PUT one part straight to its presigned URL; resolves with the part's ETag (the bucket's
 *  CORS has to expose it). */
function putPart(url: string, body: Blob, onLoaded: (bytes: number) => void, signal: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new ApiError(0, "upload cancelled"));
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    signal.addEventListener("abort", abort, { once: true });
    const settle = () => signal.removeEventListener("abort", abort);
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => onLoaded(e.loaded);
    xhr.onload = () => {
      settle();
      const etag = xhr.getResponseHeader("ETag");
      if (xhr.status >= 200 && xhr.status < 300 && etag) resolve(etag);
      else reject(new ApiError(xhr.status, etag || xhr.status >= 300 ? `part upload → ${xhr.status}` : "part upload: no ETag"));
    };
    xhr.onerror = () => {
      settle();
      reject(new ApiError(0, "part upload failed (network)"));
    };
    xhr.onabort = () => {
      settle();
      reject(new ApiError(0, "upload cancelled"));
    };
    xhr.send(body);
  });
}

const wait = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => (clearTimeout(t), resolve()), { once: true });
  });

/** D-80 phone upload: init, PUT the parts (3 in flight, each retried with backoff), complete
 *  with the ETags. Local mode answers the init with 409; then the file goes through the
 *  existing PUT route at `putUrl`. Cancelling (`signal`) or a part out of retries aborts the
 *  multipart upload server-side. */
export async function uploadVideo(
  api: ReplayApi,
  gameId: string,
  file: File,
  putUrl: string,
  onProgress: (pct: number) => void,
  signal: AbortSignal,
): Promise<void> {
  let init: MultipartInit;
  try {
    init = await api.initMultipart(gameId, file.size, file.type || "video/mp4");
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) return api.upload(putUrl, file, onProgress);
    throw e;
  }
  const stop = new AbortController();
  const onCancel = () => stop.abort();
  signal.addEventListener("abort", onCancel, { once: true });
  const loaded = new Map<number, number>();
  const report = () =>
    onProgress(Math.min(99, Math.round(([...loaded.values()].reduce((a, b) => a + b, 0) / file.size) * 100)));
  const queue = [...init.parts];
  const etags: { n: number; etag: string }[] = [];

  const worker = async () => {
    for (let p = queue.shift(); p; p = queue.shift()) {
      const part = p;
      const body = file.slice((part.n - 1) * init.part_size, part.n * init.part_size);
      for (let attempt = 0; ; attempt++) {
        try {
          const etag = await putPart(part.url, body, (b) => (loaded.set(part.n, b), report()), stop.signal);
          etags.push({ n: part.n, etag });
          break;
        } catch (e) {
          if (stop.signal.aborted || attempt >= PART_RETRIES) throw e;
          loaded.set(part.n, 0);
          report();
          await wait(500 * 2 ** attempt, stop.signal);
        }
      }
    }
  };

  try {
    await Promise.all(Array.from({ length: PART_CONCURRENCY }, worker));
    if (stop.signal.aborted) throw new ApiError(0, "upload cancelled");
    await api.completeMultipart(gameId, init.upload_id, etags.sort((a, b) => a.n - b.n));
    onProgress(100);
  } catch (e) {
    stop.abort(); // the other workers' parts too
    api.abortMultipart(gameId, init.upload_id).catch(() => {});
    throw e;
  } finally {
    signal.removeEventListener("abort", onCancel);
  }
}

/** `uploadToken`: the phone page's per-game capability (D-80), sent instead of a key. */
export function createHttpApi(apiBase: string, apiKey = "", uploadToken = ""): ReplayApi {
  const base = apiBase.replace(/\/$/, "");

  /** §4.6: game.json media URLs "resolved to absolute" — but tolerate relative ones. */
  function resolveMedia(gameId: string, path: string): string {
    if (/^(https?:)?\/\//.test(path) || path.startsWith("blob:") || path.startsWith("data:")) {
      return path;
    }
    return `${base}/media/games/${gameId}/${path.replace(/^\//, "")}`;
  }

  function headers(json: boolean): Record<string, string> {
    const h: Record<string, string> = {};
    if (json) h["Content-Type"] = "application/json";
    if (apiKey) h["X-Replay-Key"] = apiKey;
    if (uploadToken) h["X-Replay-Upload-Token"] = uploadToken;
    return h;
  }

  async function req<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
    const { json, ...rest } = init ?? {};
    const res = await fetch(`${base}${path}`, {
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

  return {
    listSports: () => req<SportProfile[]>("/sports"),
    createGame: (title, sport) =>
      req<CreateGameResult>("/games", { method: "POST", json: { title, sport } }),

    upload(uploadUrl, file, onProgress) {
      // XHR, not fetch: fetch has no upload progress events.
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("PUT", uploadUrl);
        for (const [k, v] of Object.entries(headers(false))) xhr.setRequestHeader(k, v);
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
    initMultipart: (gameId, size, content_type) =>
      req<MultipartInit>(`/games/${gameId}/upload/multipart`, { method: "POST", json: { size, content_type } }),
    completeMultipart: (gameId, upload_id, parts) =>
      req<Game>(`/games/${gameId}/upload/complete`, { method: "POST", json: { upload_id, parts } }),
    abortMultipart: (gameId, upload_id) =>
      req<void>(`/games/${gameId}/upload/abort`, { method: "POST", json: { upload_id } }),

    // The API takes `variant` and answers 200 `{court, reprojection_error_px}` /
    // 400 `{detail}`; the screens want a flat ok/error result.
    calibrate: (gameId, payload) =>
      req<{
        reprojection_error_px?: number | null;
        residuals_px?: Record<string, number> | null;
      }>(`/games/${gameId}/calibration`, {
        method: "POST",
        json: {
          sport: payload.sport,
          variant: payload.court_variant,
          landmarks_px: payload.landmarks_px,
          accept_low_confidence: payload.accept_low_confidence ?? false,
        },
      }).then(
        (r): CalibrationResult => ({
          ok: true,
          reprojection_error_px: r.reprojection_error_px ?? undefined,
          residuals_px: r.residuals_px ?? undefined,
        }),
        (e: Error) => ({ ok: false, error: e.message }),
      ),
    startAutoCalibration: (gameId, sport, variant) =>
      req<AutoCalibrationJob>(`/games/${gameId}/calibration/auto`, {
        method: "POST",
        json: { sport, variant },
      }),
    getAutoCalibration: (gameId) => req<AutoCalibration>(`/games/${gameId}/calibration/auto`),
    startProcessing: (gameId) => req<void>(`/games/${gameId}/process`, { method: "POST" }),
    listGames: () => req<GameSummary[]>("/games"),
    getGame: (gameId) => req<Game>(`/games/${gameId}`),
    // The API answers with the whole game (a merge rewrites the roster); callers want
    // the one player they touched.
    patchPlayer: (gameId, pid, body) =>
      req<Game>(`/games/${gameId}/players/${pid}`, { method: "PATCH", json: body }).then(
        (g) => g.players.find((p) => p.id === pid) ?? { id: pid, name: body.name ?? null, team: 0 },
      ),
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
    renderPlayer: (gameId, playerId) =>
      req<RenderJob>(`/games/${gameId}/players/${playerId}/render`, { method: "POST" }),
    listReplays: (gameId) =>
      req<{ replays: ReplaySummary[] }>(`/games/${gameId}/replays`).then((r) => r.replays),
    getReplay: (gameId, playId) =>
      req<ReplayManifest>(`/games/${gameId}/replays/${encodeURIComponent(playId)}`).then((m) => ({
        ...m,
        angles: m.angles.map((a) => ({ ...a, url: resolveMedia(gameId, a.url) })),
      })),
    getScene: (gameId, playId) =>
      req<SceneLayout>(`/games/${gameId}/scenes/${encodeURIComponent(playId)}`).then((s) => {
        const rel = `replays/${playId}/scene/`;
        const abs = <T extends { file: string; url?: string }>(e: T): T => ({
          ...e,
          url: resolveMedia(gameId, e.url ?? rel + e.file),
        });
        return { ...s, plates: s.plates.map(abs), atlas: abs(s.atlas) };
      }),
    mediaUrl: (game, path) => resolveMedia(game.id, path),

    listRenditions: (gameId) =>
      req<{ renditions: Rendition[] }>(`/games/${gameId}/renditions`).then((r) =>
        r.renditions.map((x) => ({ ...x, url: resolveMedia(gameId, x.url) })),
      ),
    getCommentary: (gameId) => req<Commentary>(`/games/${gameId}/commentary`),
    listClips: (gameId) => req<{ clips: PlayClip[] }>(`/games/${gameId}/clips`).then((r) => r.clips),
    listTriggers: (gameId) =>
      req<{ triggers: Trigger[] }>(`/games/${gameId}/triggers`).then((r) => r.triggers),
    trimClip: (gameId, clipId, t_start, t_end) =>
      req<PlayClip>(`/games/${gameId}/clips/${encodeURIComponent(clipId)}`, {
        method: "PATCH",
        json: { t_start, t_end },
      }),
    tap: (gameId, t) =>
      req<TapResult>(`/games/${gameId}/triggers`, { method: "POST", json: { t } }),
    getHype: (gameId) => req<Hype>(`/games/${gameId}/hype`),
    getRallies: (gameId) =>
      req<RallyDoc>(`/games/${gameId}/rallies`).then((d) => ({
        ...d,
        condensed: { ...d.condensed, url: d.condensed.url && resolveMedia(gameId, d.condensed.url) },
      })),
    renderCondensed: (gameId) => req<JobStatus>(`/games/${gameId}/condensed`, { method: "POST" }),
    exportVertical: (gameId, body) =>
      req<VerticalExport>(`/games/${gameId}/exports/vertical`, { method: "POST", json: body }),
    getVertical: (gameId, vid) => req<VerticalExport>(`/games/${gameId}/exports/vertical/${vid}`),
    getReviewQueue: (gameId) =>
      req<{ questions: ReviewQuestion[] }>(`/games/${gameId}/review/queue`).then((r) => r.questions),
    answerReview: (option, text) =>
      req<unknown>(option.path, { method: option.method, json: reviewBody(option, text) }).then(
        () => undefined,
      ),
    search: (gameId, text) =>
      req<SearchResult>(`/games/${gameId}/search`, { method: "POST", json: { text, k: 8 } }).catch(
        (e: unknown) => {
          if (e instanceof ApiError && (e.status === 409 || e.status === 503)) {
            return req<QueryResult>(`/games/${gameId}/query`, { method: "POST", json: { text } }).then(
              (r) => queryAsSearch(text, r),
            );
          }
          throw e;
        },
      ),
    getAdvice: (gameId, pid) => req<Advice>(`/games/${gameId}/players/${pid}/advice`),

    listProfiles: () => req<{ profiles: Profile[] }>("/profiles").then((r) => r.profiles),
    getProfile: (id) => req<Profile>(`/profiles/${id}`),
    createProfile: (body) => req<Profile>("/profiles", { method: "POST", json: body }),
    patchProfile: (id, body) => req<Profile>(`/profiles/${id}`, { method: "PATCH", json: body }),
    linkProfile: (id, game_id, player_id) =>
      req<Profile>(`/profiles/${id}/links`, { method: "POST", json: { game_id, player_id } }),
    unlinkProfile: (id, gameId, playerId) =>
      req<Profile>(
        `/profiles/${id}/links/${encodeURIComponent(gameId)}/${encodeURIComponent(playerId)}`,
        { method: "DELETE" },
      ),
    getSuggestions: (id) =>
      req<{ suggestions: ProfileSuggestion[] }>(`/profiles/${id}/suggestions`).then((r) => r.suggestions),
    declineSuggestion: (id, game_id, player_id) =>
      req<{ suggestions: ProfileSuggestion[] }>(`/profiles/${id}/suggestions/decline`, {
        method: "POST",
        json: { game_id, player_id },
      }).then((r) => r.suggestions),
    getCard: (id) => req<PlayerCard>(`/profiles/${id}/card`),
    renderCard: (id) => req<PlayerCard>(`/profiles/${id}/card`, { method: "POST" }),
    getReel: (id) => req<CareerReel>(`/profiles/${id}/reel`),
    uploadProfilePhoto: (id, photo) =>
      req<Profile>(`/profiles/${id}/photo`, {
        method: "PUT",
        body: photo,
        headers: { "Content-Type": photo.type || "application/octet-stream" },
      }),
    enrollFace(id, photos, consent) {
      const form = new FormData();
      form.append("consent", consent ? "true" : "false");
      photos.forEach((p, i) => form.append("photos", p, (p as File).name ?? `photo${i}.jpg`));
      return req<Profile>(`/profiles/${id}/face`, { method: "POST", body: form });
    },
    deleteFace: (id) => req<Profile>(`/profiles/${id}/face`, { method: "DELETE" }),
    profileMediaUrl: (path) => (/^(https?:)?\/\//.test(path) ? path : `${base}/${path.replace(/^\//, "")}`),
  };
}
