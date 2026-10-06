// §4.8 overlay sync rule: overlays read time from here. The clock polls the media source
// every animation frame and extrapolates with performance.now() between its (coarse)
// time updates — ~4 Hz `timeupdate` in some browsers, react-native-video's onProgress
// interval on a TV. Never drive an overlay from a bare JS timer.
//
// Pure on purpose: a browser <video> and a react-native-video player both adapt to
// `MediaClockSource`, so apps/web and apps/tv share one extrapolation rule.

export interface MediaClockSource {
  /** Last media time the platform reported, in seconds. */
  currentTime(): number;
  paused(): boolean;
}

export interface Clock {
  /** Best estimate of media time right now, in seconds. */
  now(): number;
  subscribe(fn: (t: number) => void): () => void;
  stop(): void;
}

export function createClock(source: MediaClockSource): Clock {
  const subs = new Set<(t: number) => void>();
  let lastCt = -1;
  let lastWall = performance.now();
  let t = 0;
  let raf = 0;

  const tick = () => {
    const ct = source.currentTime();
    if (ct !== lastCt) {
      lastCt = ct;
      lastWall = performance.now();
    }
    // Paused: currentTime is exact, so no extrapolation (NF-05).
    t = source.paused() ? ct : ct + (performance.now() - lastWall) / 1000;
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
