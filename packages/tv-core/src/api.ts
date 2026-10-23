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
  Moment,
  MultipartInit,
  MultipartParts,
  PhoneJob,
  PhoneLink,
  Player,
  PublicConfig,
  QueryResult,
  RenderJob,
  SceneLayout,
  Session,
  SportProfile,
  Stats,
  Storyboard,
  TracksChunk,
  TvCommand,
} from "./types";
import type { ReplayManifest, ReplaySummary } from "./replays";
import { fetchRetrying, idempotent } from "./retry";
import type {
  Advice,
  BestPlay,
  BestPlayPick,
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
  ReelExport,
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
  upload(
    uploadUrl: string,
    file: File,
    onProgress: (pct: number) => void,
  ): Promise<void>;
  /** D-80 phone upload: presigned part URLs (409 in local mode — use `upload`). */
  initMultipart(
    gameId: string,
    size: number,
    contentType: string,
  ): Promise<MultipartInit>;
  completeMultipart(
    gameId: string,
    uploadId: string,
    parts: { n: number; etag: string }[],
  ): Promise<Game>;
  abortMultipart(gameId: string, uploadId: string): Promise<void>;
  /** Resume: the parts S3 already holds and fresh URLs for the rest (404: upload gone). */
  listMultipartParts(
    gameId: string,
    uploadId: string,
    size: number,
  ): Promise<MultipartParts>;
  /** TV redesign: detected events worth jumping to, with labels and thumbs (sorted by t). */
  getMoments(gameId: string): Promise<Moment[]>;
  /** Seek previews from `game.storyboard_url` (rejects when the game has none). */
  getStoryboard(game: Game): Promise<Storyboard>;
  calibrate(
    gameId: string,
    payload: CalibrationPayload,
  ): Promise<CalibrationResult>;
  /** D-23: queue a landmark proposal for this game's calibration frame. */
  startAutoCalibration(
    gameId: string,
    sport: string,
    variant: string,
  ): Promise<AutoCalibrationJob>;
  /** Poll it — the model call takes tens of seconds. */
  getAutoCalibration(gameId: string): Promise<AutoCalibration>;
  startProcessing(gameId: string): Promise<void>;
  listGames(): Promise<GameSummary[]>;
  getGame(gameId: string): Promise<Game>;
  patchPlayer(
    gameId: string,
    pid: string,
    body: { name?: string; merge_into?: string; team?: number },
  ): Promise<Player>;
  getEvents(game: Game): Promise<GameEvent[]>;
  createEvent(gameId: string, body: Partial<GameEvent>): Promise<GameEvent>;
  patchEvent(
    gameId: string,
    eventId: string,
    body: Partial<GameEvent>,
  ): Promise<GameEvent>;
  query(gameId: string, text: string): Promise<QueryResult>;
  getStats(gameId: string): Promise<Stats>;
  getTracksChunk(game: Game, index: number): Promise<TracksChunk>;
  getCropPath(game: Game, playerId: string): Promise<CropPath>;
  createSession(): Promise<Session>;
  /** Public: where apps/web's phone pages live. */
  getConfig(): Promise<PublicConfig>;
  /** A phone page link for one job at game time `t`, with its own short-lived token. */
  phoneLink(
    gameId: string,
    job: PhoneJob,
    t: number | null,
  ): Promise<PhoneLink>;
  /** The phone's "Play on the TV": queue a `play` command for this game at `t`. True when
   *  a TV is showing this game now (its `tvState` heartbeat), so it plays there. */
  playOnTv(gameId: string, t: number): Promise<boolean>;
  /** The open Watch's heartbeat (POST /tv/state): which game, where, playing or not. */
  tvState(gameId: string, t: number, playing: boolean): Promise<void>;
  /** The TV's command queue, newer than `after` (a cursor from the previous answer). */
  tvCommands(after: string): Promise<{ commands: TvCommand[]; cursor: string }>;
  ackTvCommand(id: string): Promise<void>;
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
  trimClip(
    gameId: string,
    clipId: string,
    t_start: number,
    t_end: number,
  ): Promise<PlayClip>;
  /** Phone tap at media time `t`: resolves to the play that just ended. */
  tap(gameId: string, t: number): Promise<TapResult>;
  /** M11 (D-45..D-48). */
  getHype(gameId: string): Promise<Hype>;
  /** The game's best play (the user's pick, else the game winner, else the top hype
   *  play); null when nothing qualifies. */
  getBestPlay(gameId: string): Promise<BestPlay | null>;
  /** "Make this the best play": one per game, replacing an earlier pick. */
  setBestPlay(gameId: string, pick: BestPlayPick): Promise<BestPlay | null>;
  getRallies(gameId: string): Promise<RallyDoc>;
  renderCondensed(gameId: string): Promise<JobStatus>;
  exportVertical(
    gameId: string,
    body: VerticalRequest,
  ): Promise<VerticalExport>;
  getVertical(gameId: string, vid: string): Promise<VerticalExport>;
  /** The game's highlight reel (16:9 or 9:16); asking again is the same reel. */
  exportGameReel(
    gameId: string,
    aspect: ReelExport["aspect"],
  ): Promise<ReelExport>;
  getGameReel(gameId: string, rid: string): Promise<ReelExport>;
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
  declineSuggestion(
    id: string,
    gameId: string,
    playerId: string,
  ): Promise<ProfileSuggestion[]>;
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
export function reviewBody(
  option: ReviewOption,
  text?: string,
): Record<string, unknown> {
  return option.text_field
    ? { ...option.body, [option.text_field]: text ?? "" }
    : option.body;
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
function putPart(
  url: string,
  body: Blob,
  onLoaded: (bytes: number) => void,
  signal: AbortSignal,
): Promise<string> {
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
      else
        reject(
          new ApiError(
            xhr.status,
            etag || xhr.status >= 300
              ? `part upload → ${xhr.status}`
              : "part upload: no ETag",
          ),
        );
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
    signal.addEventListener("abort", () => (clearTimeout(t), resolve()), {
      once: true,
    });
  });

/** What a phone keeps between page loads to resume an upload (D-80 resumable upload). */
export interface SavedUpload {
  upload_id: string;
  part_size: number;
  /** The file it belongs to: re-picking the same name and size resumes. */
  name: string;
  size: number;
  modified: number;
  /** Part number -> ETag of every part that finished. */
  etags: Record<number, string>;
}

/** The subset of Web Storage the uploader uses (localStorage by default). */
export type UploadStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const uploadKey = (gameId: string) => `replay.upload.${gameId}`;

function defaultStore(): UploadStore | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null; // private mode / blocked storage: uploads still work, just not resumable
  }
}

/** The unfinished upload this phone started for `gameId`, if any. */
export function savedUpload(
  gameId: string,
  store = defaultStore(),
): SavedUpload | null {
  try {
    const raw = store?.getItem(uploadKey(gameId));
    return raw ? (JSON.parse(raw) as SavedUpload) : null;
  } catch {
    return null;
  }
}

function saveUpload(
  gameId: string,
  up: SavedUpload | null,
  store: UploadStore | null,
) {
  try {
    if (up) store?.setItem(uploadKey(gameId), JSON.stringify(up));
    else store?.removeItem(uploadKey(gameId));
  } catch {
    /* storage full or blocked: the upload goes on, it just cannot resume */
  }
}

// ponytail: name + size, not the date: some phone pickers stamp `lastModified` with the
// pick time. A content fingerprint (hash of the first part) if two same-sized files ever
// share a name.
const sameFile = (up: SavedUpload, f: File) =>
  up.name === f.name && up.size === f.size;

/** Forget (and abort server-side) this phone's unfinished upload for `gameId`. */
export async function discardUpload(
  api: ReplayApi,
  gameId: string,
  store = defaultStore(),
) {
  const up = savedUpload(gameId, store);
  saveUpload(gameId, null, store);
  if (up) await api.abortMultipart(gameId, up.upload_id).catch(() => {});
}

/** D-80 phone upload: init, PUT the parts (3 in flight, each retried with backoff), complete
 *  with the ETags. Local mode answers the init with 409; then the file goes through the
 *  existing PUT route at `putUrl`.
 *
 *  Resumable: the upload id and every finished part's ETag are kept in `store`
 *  (localStorage) under the game. Calling again with the same file — after a reload, or
 *  after a part ran out of retries on a dropped connection — asks the API which parts S3
 *  holds and sends only the rest (`onResume` gets the share already sent). Only Cancel
 *  (`signal`) aborts the multipart upload server-side and forgets it. */
export async function uploadVideo(
  api: ReplayApi,
  gameId: string,
  file: File,
  putUrl: string,
  onProgress: (pct: number) => void,
  signal: AbortSignal,
  opts: { store?: UploadStore | null; onResume?: (pct: number) => void } = {},
): Promise<void> {
  const store = opts.store === undefined ? defaultStore() : opts.store;
  let init: MultipartInit | null = null;
  const loaded = new Map<number, number>();
  const etags: { n: number; etag: string }[] = [];
  let saved = savedUpload(gameId, store);
  if (saved && !sameFile(saved, file)) {
    await discardUpload(api, gameId, store); // another file: the old parts are useless
    saved = null;
  }
  if (saved) {
    try {
      const got = await api.listMultipartParts(
        gameId,
        saved.upload_id,
        file.size,
      );
      init = {
        upload_id: got.upload_id,
        part_size: got.part_size,
        parts: got.parts,
      };
      for (const p of got.done) {
        etags.push({ n: p.n, etag: p.etag });
        loaded.set(p.n, p.size);
      }
      saved = {
        ...saved,
        etags: Object.fromEntries(got.done.map((p) => [p.n, p.etag])),
      };
      saveUpload(gameId, saved, store);
      opts.onResume?.(
        Math.round(
          (got.done.reduce((a, p) => a + p.size, 0) / file.size) * 100,
        ),
      );
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) throw e;
      saveUpload(gameId, null, store); // S3 no longer has it: start over
      saved = null;
    }
  }
  if (!init || !saved) {
    try {
      init = await api.initMultipart(
        gameId,
        file.size,
        file.type || "video/mp4",
      );
    } catch (e) {
      if (e instanceof ApiError && e.status === 409)
        return api.upload(putUrl, file, onProgress);
      throw e;
    }
    saved = {
      upload_id: init.upload_id,
      part_size: init.part_size,
      name: file.name,
      size: file.size,
      modified: file.lastModified,
      etags: {},
    };
    saveUpload(gameId, saved, store);
  }
  const up = init;
  const record = saved;
  const stop = new AbortController();
  const onCancel = () => stop.abort();
  signal.addEventListener("abort", onCancel, { once: true });
  const report = () =>
    onProgress(
      Math.min(
        99,
        Math.round(
          ([...loaded.values()].reduce((a, b) => a + b, 0) / file.size) * 100,
        ),
      ),
    );
  report();
  const queue = [...up.parts];

  const worker = async () => {
    for (let p = queue.shift(); p; p = queue.shift()) {
      const part = p;
      const body = file.slice(
        (part.n - 1) * up.part_size,
        part.n * up.part_size,
      );
      for (let attempt = 0; ; attempt++) {
        try {
          const etag = await putPart(
            part.url,
            body,
            (b) => (loaded.set(part.n, b), report()),
            stop.signal,
          );
          etags.push({ n: part.n, etag });
          record.etags[part.n] = etag;
          saveUpload(gameId, record, store);
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
    try {
      await api.completeMultipart(
        gameId,
        up.upload_id,
        etags.sort((a, b) => a.n - b.n),
      );
    } catch (e) {
      // refused by S3 / not a video: these parts can never complete, so do not resume them
      if (e instanceof ApiError && e.status >= 400 && e.status !== 401) {
        await discardUpload(api, gameId, store);
      }
      throw e;
    }
    saveUpload(gameId, null, store);
    onProgress(100);
  } catch (e) {
    stop.abort(); // the other workers' parts too
    // Cancel forgets the upload; anything else (a dropped connection, a part out of
    // retries) keeps it, so the next call resumes instead of starting over
    if (signal.aborted) await discardUpload(api, gameId, store);
    throw e;
  } finally {
    signal.removeEventListener("abort", onCancel);
  }
}

/** `uploadToken`: the phone page's per-game capability (D-80), sent instead of a key. */
export function createHttpApi(
  apiBase: string,
  apiKey = "",
  uploadToken = "",
): ReplayApi {
  const base = apiBase.replace(/\/$/, "");

  /** §4.6: game.json media URLs "resolved to absolute" — but tolerate relative ones. */
  function resolveMedia(gameId: string, path: string): string {
    if (
      /^(https?:)?\/\//.test(path) ||
      path.startsWith("blob:") ||
      path.startsWith("data:")
    ) {
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

  async function req<T>(
    path: string,
    /** `idempotent`: a POST the API makes safe to repeat (a read, a hashed export) */
    init?: RequestInit & { json?: unknown; idempotent?: boolean },
  ): Promise<T> {
    const { json, idempotent: safePost, ...rest } = init ?? {};
    const res = await fetchRetrying(
      `${base}${path}`,
      {
        ...rest,
        headers: {
          ...headers(json !== undefined),
          ...(rest.headers as object),
        },
        body: json !== undefined ? JSON.stringify(json) : rest.body,
      },
      idempotent(rest.method) || !!safePost, // D-87: a throttle is tried again
    );
    if (!res.ok) {
      // The API reports failures as {"detail": "..."} — surface that, not just the code.
      const detail = await res.text().then(
        (t) => (t ? ((JSON.parse(t) as { detail?: string }).detail ?? t) : ""),
        () => "",
      );
      throw new ApiError(
        res.status,
        detail || `${init?.method ?? "GET"} ${path} → ${res.status}`,
      );
    }
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }

  // D-87: a route the server cannot serve at all (503 "... is not available": the cloud
  // API has no replay_render to compute hype or rallies live) is not asked again while
  // this client lives; the same error comes back at once. A throttle 503 is not kept.
  const unavailable = new Map<string, ApiError>();
  async function reqUnlessUnavailable<T>(path: string): Promise<T> {
    const known = unavailable.get(path);
    if (known) throw known;
    try {
      return await req<T>(path);
    } catch (e) {
      if (
        e instanceof ApiError &&
        e.status === 503 &&
        /not available/i.test(e.message)
      )
        unavailable.set(path, e);
      throw e;
    }
  }

  async function fetchUrl<T>(url: string): Promise<T> {
    const res = await fetchRetrying(url, { headers: headers(false) }, true);
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
      req<CreateGameResult>("/games", {
        method: "POST",
        json: { title, sport },
      }),

    upload(uploadUrl, file, onProgress) {
      // XHR, not fetch: fetch has no upload progress events.
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("PUT", uploadUrl);
        for (const [k, v] of Object.entries(headers(false)))
          xhr.setRequestHeader(k, v);
        xhr.setRequestHeader("Content-Type", file.type || "video/mp4");
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable)
            onProgress(Math.round((e.loaded / e.total) * 100));
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
      req<MultipartInit>(`/games/${gameId}/upload/multipart`, {
        method: "POST",
        json: { size, content_type },
      }),
    completeMultipart: (gameId, upload_id, parts) =>
      req<Game>(`/games/${gameId}/upload/complete`, {
        method: "POST",
        json: { upload_id, parts },
      }),
    abortMultipart: (gameId, upload_id) =>
      req<void>(`/games/${gameId}/upload/abort`, {
        method: "POST",
        json: { upload_id },
      }),
    listMultipartParts: (gameId, uploadId, size) =>
      req<MultipartParts>(
        `/games/${gameId}/upload/parts?upload_id=${encodeURIComponent(uploadId)}&size=${size}`,
      ),
    getMoments: (gameId) =>
      req<Moment[]>(`/games/${gameId}/moments`).then((ms) =>
        ms.map((m) => ({
          ...m,
          thumb_url: m.thumb_url && resolveMedia(gameId, m.thumb_url),
        })),
      ),
    getStoryboard: (game) =>
      game.storyboard_url
        ? fetchUrl<Storyboard>(game.storyboard_url).then((s) => ({
            ...s,
            sheets: s.sheets.map((u) => resolveMedia(game.id, u)),
          }))
        : Promise.reject(new ApiError(404, "no storyboard for this game yet")),

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
    getAutoCalibration: (gameId) =>
      req<AutoCalibration>(`/games/${gameId}/calibration/auto`),
    startProcessing: (gameId) =>
      req<void>(`/games/${gameId}/process`, { method: "POST" }),
    listGames: () => req<GameSummary[]>("/games"),
    getGame: (gameId) => req<Game>(`/games/${gameId}`),
    // The API answers with the whole game (a merge rewrites the roster); callers want
    // the one player they touched.
    patchPlayer: (gameId, pid, body) =>
      req<Game>(`/games/${gameId}/players/${pid}`, {
        method: "PATCH",
        json: body,
      }).then(
        (g) =>
          g.players.find((p) => p.id === pid) ?? {
            id: pid,
            name: body.name ?? null,
            team: 0,
          },
      ),
    getEvents: (game) =>
      fetchUrl<{ events: GameEvent[] }>(
        resolveMedia(game.id, game.events_url),
      ).then((f) => f.events),
    // §4.6 "create bookmark": the API only takes the timestamp and derives the window.
    createEvent: (gameId, body) =>
      req<GameEvent>(`/games/${gameId}/events`, {
        method: "POST",
        json: { t: body.t_key ?? 0 },
      }),
    patchEvent: (gameId, eventId, body) =>
      req<GameEvent>(`/games/${gameId}/events/${eventId}`, {
        method: "PATCH",
        json: body,
      }),
    query: (gameId, text) =>
      req<QueryResult>(`/games/${gameId}/query`, {
        method: "POST",
        json: { text },
        idempotent: true, // a read
      }),
    getStats: (gameId) => req<Stats>(`/games/${gameId}/stats`),
    getTracksChunk: (game, index) =>
      fetchUrl<TracksChunk>(chunkUrl(game, index)),
    getCropPath: (game, playerId) =>
      fetchUrl<CropPath>(
        resolveMedia(
          game.id,
          game.croppaths.url_template.replace("{player_id}", playerId),
        ),
      ),
    createSession: () => req<Session>("/sessions", { method: "POST" }),
    getConfig: () => req<PublicConfig>("/config"),
    phoneLink: (gameId, job, t) =>
      req<PhoneLink>(`/games/${gameId}/phone-link`, {
        method: "POST",
        json: { job, t },
      }),
    playOnTv: (gameId, t) =>
      req<unknown>(`/games/${gameId}/tv/play`, {
        method: "POST",
        json: { t },
      }).then((r) => (r as { tv?: boolean } | undefined)?.tv === true),
    tvState: (gameId, t, playing) =>
      req<unknown>("/tv/state", {
        method: "POST",
        json: { game_id: gameId, t: Math.max(0, t), playing },
        idempotent: true, // the latest heartbeat wins
      }).then(() => undefined),
    tvCommands: (after) =>
      req<{ commands: TvCommand[]; cursor: string }>(
        `/tv/commands?after=${encodeURIComponent(after)}`,
      ),
    ackTvCommand: (id) =>
      req<unknown>(`/tv/commands/${encodeURIComponent(id)}/ack`, {
        method: "POST",
        idempotent: true, // acking twice is the same ack
      }).then(() => undefined),
    renderPlayer: (gameId, playerId) =>
      req<RenderJob>(`/games/${gameId}/players/${playerId}/render`, {
        method: "POST",
      }),
    listReplays: (gameId) =>
      req<{ replays: ReplaySummary[] }>(`/games/${gameId}/replays`).then(
        (r) => r.replays,
      ),
    getReplay: (gameId, playId) =>
      req<ReplayManifest>(
        `/games/${gameId}/replays/${encodeURIComponent(playId)}`,
      ).then((m) => ({
        ...m,
        angles: m.angles.map((a) => ({
          ...a,
          url: resolveMedia(gameId, a.url),
        })),
      })),
    getScene: (gameId, playId) =>
      req<SceneLayout>(
        `/games/${gameId}/scenes/${encodeURIComponent(playId)}`,
      ).then((s) => {
        const rel = `replays/${playId}/scene/`;
        const abs = <T extends { file: string; url?: string }>(e: T): T => ({
          ...e,
          url: resolveMedia(gameId, e.url ?? rel + e.file),
        });
        return { ...s, plates: s.plates.map(abs), atlas: abs(s.atlas) };
      }),
    mediaUrl: (game, path) => resolveMedia(game.id, path),

    listRenditions: (gameId) =>
      req<{ renditions: Rendition[] }>(`/games/${gameId}/renditions`).then(
        (r) =>
          r.renditions.map((x) => ({ ...x, url: resolveMedia(gameId, x.url) })),
      ),
    getCommentary: (gameId) => req<Commentary>(`/games/${gameId}/commentary`),
    listClips: (gameId) =>
      req<{ clips: PlayClip[] }>(`/games/${gameId}/clips`).then((r) => r.clips),
    listTriggers: (gameId) =>
      req<{ triggers: Trigger[] }>(`/games/${gameId}/triggers`).then(
        (r) => r.triggers,
      ),
    trimClip: (gameId, clipId, t_start, t_end) =>
      req<PlayClip>(`/games/${gameId}/clips/${encodeURIComponent(clipId)}`, {
        method: "PATCH",
        json: { t_start, t_end },
      }),
    tap: (gameId, t) =>
      req<TapResult>(`/games/${gameId}/triggers`, {
        method: "POST",
        json: { t },
      }),
    getHype: (gameId) => reqUnlessUnavailable<Hype>(`/games/${gameId}/hype`),
    getBestPlay: (gameId) =>
      req<{ best_play: BestPlay | null }>(`/games/${gameId}/best-play`).then(
        (r) => r.best_play,
      ),
    setBestPlay: (gameId, pick) =>
      req<{ best_play: BestPlay | null }>(`/games/${gameId}/best-play`, {
        method: "PUT",
        json: pick,
      }).then((r) => r.best_play),
    getRallies: (gameId) =>
      reqUnlessUnavailable<RallyDoc>(`/games/${gameId}/rallies`).then((d) => ({
        ...d,
        condensed: {
          ...d.condensed,
          url: d.condensed.url && resolveMedia(gameId, d.condensed.url),
        },
      })),
    renderCondensed: (gameId) =>
      // the running or finished job when there is one: safe to repeat. Its doc makes
      // /rallies servable on the cloud, so ask for that again afterwards
      req<JobStatus>(`/games/${gameId}/condensed`, {
        method: "POST",
        idempotent: true,
      }).finally(() => unavailable.delete(`/games/${gameId}/rallies`)),
    exportVertical: (gameId, body) =>
      req<VerticalExport>(`/games/${gameId}/exports/vertical`, {
        method: "POST",
        json: body,
        idempotent: true, // the export's id hashes its spec
      }),
    getVertical: (gameId, vid) =>
      req<VerticalExport>(`/games/${gameId}/exports/vertical/${vid}`),
    exportGameReel: (gameId, aspect) =>
      req<ReelExport>(`/games/${gameId}/exports/reel`, {
        method: "POST",
        json: { aspect },
        idempotent: true, // the reel's id hashes its aspect and inputs
      }),
    getGameReel: (gameId, rid) =>
      req<ReelExport>(`/games/${gameId}/exports/reel/${rid}`),
    getReviewQueue: (gameId) =>
      req<{ questions: ReviewQuestion[] }>(
        `/games/${gameId}/review/queue`,
      ).then((r) => r.questions),
    answerReview: (option, text) =>
      req<unknown>(option.path, {
        method: option.method,
        json: reviewBody(option, text),
      }).then(() => undefined),
    search: (gameId, text) =>
      req<SearchResult>(`/games/${gameId}/search`, {
        method: "POST",
        json: { text, k: 8 },
        idempotent: true, // a read
      }).catch((e: unknown) => {
        if (e instanceof ApiError && (e.status === 409 || e.status === 503)) {
          return req<QueryResult>(`/games/${gameId}/query`, {
            method: "POST",
            json: { text },
            idempotent: true,
          }).then((r) => queryAsSearch(text, r));
        }
        throw e;
      }),
    getAdvice: (gameId, pid) =>
      req<Advice>(`/games/${gameId}/players/${pid}/advice`),

    listProfiles: () =>
      req<{ profiles: Profile[] }>("/profiles").then((r) => r.profiles),
    getProfile: (id) => req<Profile>(`/profiles/${id}`),
    createProfile: (body) =>
      req<Profile>("/profiles", { method: "POST", json: body }),
    patchProfile: (id, body) =>
      req<Profile>(`/profiles/${id}`, { method: "PATCH", json: body }),
    linkProfile: (id, game_id, player_id) =>
      req<Profile>(`/profiles/${id}/links`, {
        method: "POST",
        json: { game_id, player_id },
      }),
    unlinkProfile: (id, gameId, playerId) =>
      req<Profile>(
        `/profiles/${id}/links/${encodeURIComponent(gameId)}/${encodeURIComponent(playerId)}`,
        { method: "DELETE" },
      ),
    getSuggestions: (id) =>
      req<{ suggestions: ProfileSuggestion[] }>(
        `/profiles/${id}/suggestions`,
      ).then((r) => r.suggestions),
    declineSuggestion: (id, game_id, player_id) =>
      req<{ suggestions: ProfileSuggestion[] }>(
        `/profiles/${id}/suggestions/decline`,
        {
          method: "POST",
          json: { game_id, player_id },
        },
      ).then((r) => r.suggestions),
    getCard: (id) => req<PlayerCard>(`/profiles/${id}/card`),
    renderCard: (id) =>
      req<PlayerCard>(`/profiles/${id}/card`, { method: "POST" }),
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
      photos.forEach((p, i) =>
        form.append("photos", p, (p as File).name ?? `photo${i}.jpg`),
      );
      return req<Profile>(`/profiles/${id}/face`, {
        method: "POST",
        body: form,
      });
    },
    deleteFace: (id) =>
      req<Profile>(`/profiles/${id}/face`, { method: "DELETE" }),
    profileMediaUrl: (path) =>
      /^(https?:)?\/\//.test(path)
        ? path
        : `${base}/${path.replace(/^\//, "")}`,
  };
}
