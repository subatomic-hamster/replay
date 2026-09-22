// §4.8 overlay sync rule: overlays read time from here. This reads the media element
// every animation frame and extrapolates with performance.now() between the (coarse,
// ~4 Hz in some browsers) currentTime updates. Never drive an overlay from a bare
// JS timer.
import { useEffect, useState } from "react";

export interface Clock {
  /** Best estimate of media time right now, in seconds. */
  now(): number;
  subscribe(fn: (t: number) => void): () => void;
  stop(): void;
}

export function createClock(video: HTMLVideoElement): Clock {
  const subs = new Set<(t: number) => void>();
  let lastCt = -1;
  let lastWall = performance.now();
  let t = 0;
  let raf = 0;

  const tick = () => {
    const ct = video.currentTime;
    if (ct !== lastCt) {
      lastCt = ct;
      lastWall = performance.now();
    }
    // Paused: currentTime is exact, so no extrapolation (NF-05).
    t = video.paused ? ct : ct + (performance.now() - lastWall) / 1000;
    for (const fn of subs) fn(t);
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);

  return {
    now: () => t,
    subscribe(fn) {
      subs.add(fn);
      return () => subs.delete(fn);
    },
    stop() {
      cancelAnimationFrame(raf);
      subs.clear();
    },
  };
}

/**
 * React-facing view of the clock, quantized so overlays re-render at most once per
 * `step` seconds of media time instead of once per frame.
 */
export function useClockTime(clock: Clock | null, step = 1 / 30): number {
  const [t, setT] = useState(0);
  useEffect(() => {
    if (!clock) return;
    return clock.subscribe((v) => setT((prev) => (Math.abs(v - prev) >= step ? v : prev)));
  }, [clock, step]);
  return t;
}
