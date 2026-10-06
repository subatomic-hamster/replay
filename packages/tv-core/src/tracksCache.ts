// §4.8: chunk fetch + prefetch (current ±1), with linear interpolation between the
// 10 Hz track frames so boxes sit right at the video's 30 fps.
import type { Game, TrackPlayer, TracksChunk } from "./types";

export interface TracksCache {
  /** Interpolated players at time t. Empty until the chunk lands. */
  playersAt(t: number): TrackPlayer[];
  /** Fetch the chunk for t and its neighbours; fires onChange when new data arrives. */
  ensure(t: number): void;
  onChange(fn: () => void): () => void;
}

function lerp(a: number, b: number, k: number) {
  return a + (b - a) * k;
}

function blend(a: TrackPlayer, b: TrackPlayer, k: number): TrackPlayer {
  return {
    id: a.id,
    bb: [
      lerp(a.bb[0], b.bb[0], k),
      lerp(a.bb[1], b.bb[1], k),
      lerp(a.bb[2], b.bb[2], k),
      lerp(a.bb[3], b.bb[3], k),
    ],
    ct:
      a.ct && b.ct ? [lerp(a.ct[0], b.ct[0], k), lerp(a.ct[1], b.ct[1], k)] : (a.ct ?? b.ct),
    c: a.c,
  };
}

export function createTracksCache(
  game: Game,
  getChunk: (game: Game, index: number) => Promise<TracksChunk>,
): TracksCache {
  const chunks = new Map<number, TracksChunk>();
  const inflight = new Set<number>();
  const subs = new Set<() => void>();
  const { chunk_s, chunks: count } = game.tracks;

  const notify = () => subs.forEach((f) => f());

  function fetchChunk(i: number) {
    if (i < 0 || i >= count || chunks.has(i) || inflight.has(i)) return;
    inflight.add(i);
    getChunk(game, i)
      .then((c) => {
        chunks.set(i, c);
        notify();
      })
      .catch(() => {
        /* ponytail: a missing chunk just means no boxes there; no retry policy yet. */
      })
      .finally(() => inflight.delete(i));
  }

  return {
    ensure(t) {
      const i = Math.floor(t / chunk_s);
      fetchChunk(i);
      fetchChunk(i - 1);
      fetchChunk(i + 1);
    },

    playersAt(t) {
      const chunk = chunks.get(Math.floor(t / chunk_s));
      if (!chunk || chunk.frames.length === 0) return [];
      const pos = (t - chunk.t0) * chunk.rate_hz;
      const i0 = Math.max(0, Math.min(chunk.frames.length - 1, Math.floor(pos)));
      const i1 = Math.min(chunk.frames.length - 1, i0 + 1);
      const k = i1 === i0 ? 0 : Math.max(0, Math.min(1, pos - i0));
      const a = chunk.frames[i0].p;
      const b = chunk.frames[i1].p;
      return a.map((pa) => {
        const pb = b.find((p) => p.id === pa.id);
        return pb ? blend(pa, pb, k) : pa;
      });
    },

    onChange(fn) {
      subs.add(fn);
      return () => subs.delete(fn);
    },
  };
}
