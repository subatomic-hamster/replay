// "On your phone" pages (`/p/:id?job=..#k=<token>`): the TV's QR hands the phone a per-game
// phone token. It goes out as X-Replay-Phone-Token on every API call (never X-Replay-Key)
// and opens only this game's clip / tag / review / search routes. Media needs no header.
import {
  ApiError,
  createHttpApi,
  queryAsSearch,
  reviewBody,
  type ReplayApi,
} from "../../../../packages/tv-core/src/api";
import { mockUploadApi } from "../../../../packages/tv-core/src/mock";
import type {
  PlayClip,
  ReviewQuestion,
  SearchResult,
  TapResult,
  VerticalExport,
} from "../../../../packages/tv-core/src/discovery";
import type { Profile } from "../../../../packages/tv-core/src/profiles";
import type { Game, Moment, QueryResult } from "./types";
import { API_BASE, MOCK_API } from "../config";

export const PHONE_HEADER = "X-Replay-Phone-Token";

/** Everything the phone page calls; nothing else is reachable with a phone token. */
export type PhoneApi = Pick<
  ReplayApi,
  | "getGame"
  | "getMoments"
  | "listClips"
  | "tap"
  | "trimClip"
  | "exportVertical"
  | "getVertical"
  | "listProfiles"
  | "createProfile"
  | "linkProfile"
  | "getReviewQueue"
  | "answerReview"
  | "search"
  | "mediaUrl"
  | "profileMediaUrl"
>;

// ponytail: a second small fetch wrapper because packages/tv-core's createHttpApi only
// knows the key and the upload token. Fold it in there once tv-core takes a phone token.
export function phoneHttpApi(apiBase: string, token: string): PhoneApi {
  const base = apiBase.replace(/\/$/, "");
  const media = createHttpApi(base); // URL building only: it never sends a request here
  const g = (id: string) => `/games/${encodeURIComponent(id)}`;

  async function req<T>(
    path: string,
    method = "GET",
    json?: unknown,
  ): Promise<T> {
    const headers: Record<string, string> = { [PHONE_HEADER]: token };
    if (json !== undefined) headers["Content-Type"] = "application/json";
    const res = await fetch(`${base}${path}`, {
      method,
      headers,
      body: json !== undefined ? JSON.stringify(json) : undefined,
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      let detail = text;
      try {
        detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
      } catch {
        /* not JSON: keep the text */
      }
      throw new ApiError(
        res.status,
        detail || `${method} ${path} → ${res.status}`,
      );
    }
    return (text ? JSON.parse(text) : undefined) as T;
  }

  return {
    mediaUrl: media.mediaUrl,
    profileMediaUrl: media.profileMediaUrl,
    getGame: (id) => req<Game>(g(id)),
    getMoments: (id) =>
      req<Moment[]>(`${g(id)}/moments`).then((ms) =>
        ms.map((m) => ({
          ...m,
          thumb_url: m.thumb_url && media.mediaUrl({ id } as Game, m.thumb_url),
        })),
      ),
    listClips: (id) =>
      req<{ clips: PlayClip[] }>(`${g(id)}/clips`).then((r) => r.clips),
    tap: (id, t) => req<TapResult>(`${g(id)}/triggers`, "POST", { t }),
    trimClip: (id, clipId, t_start, t_end) =>
      req<PlayClip>(`${g(id)}/clips/${encodeURIComponent(clipId)}`, "PATCH", {
        t_start,
        t_end,
      }),
    exportVertical: (id, body) =>
      req<VerticalExport>(`${g(id)}/exports/vertical`, "POST", body),
    getVertical: (id, vid) =>
      req<VerticalExport>(
        `${g(id)}/exports/vertical/${encodeURIComponent(vid)}`,
      ),
    listProfiles: () =>
      req<{ profiles: Profile[] }>("/profiles").then((r) => r.profiles),
    createProfile: (body) => req<Profile>("/profiles", "POST", body),
    linkProfile: (pid, game_id, player_id) =>
      req<Profile>(`/profiles/${encodeURIComponent(pid)}/links`, "POST", {
        game_id,
        player_id,
      }),
    getReviewQueue: (id) =>
      req<{ questions: ReviewQuestion[] }>(`${g(id)}/review/queue`).then(
        (r) => r.questions,
      ),
    answerReview: (option, text) =>
      req<unknown>(option.path, option.method, reviewBody(option, text)).then(
        () => undefined,
      ),
    search: (id, text) =>
      req<SearchResult>(`${g(id)}/search`, "POST", { text, k: 8 }).catch(
        (e: unknown) => {
          // no embeddings index (409) or model (503): the keyword route, as the TV does
          if (e instanceof ApiError && (e.status === 409 || e.status === 503)) {
            return req<QueryResult>(`${g(id)}/query`, "POST", { text }).then(
              (r) => queryAsSearch(text, r),
            );
          }
          throw e;
        },
      ),
  };
}

/** The mock stands in for the API: the token "expired" makes every call 401, like a stale
 *  QR; any other token opens the game. */
export function phoneApi(token: string): PhoneApi {
  return MOCK_API ? mockUploadApi(token) : phoneHttpApi(API_BASE, token);
}

const tokens: Record<string, string> = {};
const storeKey = (gameId: string) => `replay.phone.${gameId}`;

/** The token from `#k=`, taken out of the address bar (so it is not copied, bookmarked or
 *  shared with a screenshot) and kept in sessionStorage so a reload still works. */
export function phoneToken(gameId: string): string {
  const fromHash = new URLSearchParams(window.location.hash.slice(1)).get("k");
  if (fromHash) {
    tokens[gameId] = fromHash;
    try {
      sessionStorage.setItem(storeKey(gameId), fromHash);
    } catch {
      /* blocked storage: works until a reload */
    }
    window.history.replaceState(
      window.history.state,
      "",
      window.location.pathname + window.location.search,
    );
  }
  if (!tokens[gameId]) {
    try {
      tokens[gameId] = sessionStorage.getItem(storeKey(gameId)) ?? "";
    } catch {
      tokens[gameId] = "";
    }
  }
  return tokens[gameId];
}

/** 401: the link expired, or it was never a phone link for this game. */
export const isExpired = (e: unknown) =>
  e instanceof ApiError && e.status === 401;
