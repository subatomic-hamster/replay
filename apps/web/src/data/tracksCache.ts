// §4.8 chunk fetch + interpolation — shared with apps/tv
// (packages/tv-core/src/tracksCache.ts); this binds it to the app's API client.
import { api } from "../api/client";
import type { Game } from "../api/types";
import {
  createTracksCache as createCore,
  type TracksCache,
} from "../../../../packages/tv-core/src/tracksCache";

export type { TracksCache };

export function createTracksCache(game: Game): TracksCache {
  return createCore(game, api.getTracksChunk);
}
