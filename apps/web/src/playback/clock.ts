// §4.8 overlay sync rule: overlays read time from here. The extrapolating clock itself is
// shared with apps/tv (packages/tv-core/src/clock.ts); this binds it to a <video>.
import { useEffect, useState } from "react";
import { createClock as createCoreClock, type Clock } from "../../../../packages/tv-core/src/clock";

export type { Clock };

export function createClock(video: HTMLVideoElement): Clock {
  return createCoreClock({ currentTime: () => video.currentTime, paused: () => video.paused });
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
