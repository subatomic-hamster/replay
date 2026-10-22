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

/** Reports come every 0.1 s (react-native-video) to ~0.25 s (`timeupdate`). */
const MAX_EXTRAPOLATE_S = 0.5;

export function createClock(source: MediaClockSource): Clock {
  const subs = new Set<(t: number) => void>();
  let lastCt = -1;
  let lastWall = performance.now();
  let t = 0;
  let raf = 0;

  const tick = () => {
    const ct = source.currentTime();
    const paused = source.paused();
    // A new report, or paused (the wall clock must not run on through a pause: on Play the
    // next report is up to one progress interval away, and extrapolating from the last
    // report before the pause jumped the time forward by the whole pause).
    if (ct !== lastCt || paused) {
      lastCt = ct;
      lastWall = performance.now();
    }
    // Paused: currentTime is exact, so no extrapolation (NF-05). Playing: never more than
    // MAX_EXTRAPOLATE_S past the last report (a stall that has not said so yet).
    t = paused
      ? ct
      : ct + Math.min((performance.now() - lastWall) / 1000, MAX_EXTRAPOLATE_S);
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
