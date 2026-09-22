// §4.8 platform adapter: the only component that touches a media element. Screens talk
// to it through PlayerHandle. Phase 3 swaps the <video> for react-native-video / the Vega
// media player and keeps this API.
import { useEffect, useImperativeHandle, useRef, useState, type ReactNode, type Ref } from "react";
import { createClock, type Clock } from "./clock";
import type { CropPath } from "../api/types";

export interface PlayerHandle {
  play(): void;
  pause(): void;
  toggle(): void;
  seek(t: number): void;
  currentTime(): number;
  duration(): number;
  paused(): boolean;
  clock: Clock | null;
}

interface Props {
  src: string;
  /** D-6 client follow-cam: per-frame crop rects. null = wide shot. */
  crop?: CropPath | null;
  muted?: boolean;
  /** Overlays, rendered in the untransformed viewport layer above the video. */
  children?: ReactNode;
  onTimeUpdate?: (t: number) => void;
  onEnded?: () => void;
  ref?: Ref<PlayerHandle>;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

export function PlayerSurface({ src, crop, muted, children, onEnded, ref }: Props) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const transformRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const clockRef = useRef<Clock | null>(null);
  const [, setReady] = useState(0);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const clock = createClock(v);
    clockRef.current = clock;
    setReady((n) => n + 1);
    return () => {
      clock.stop();
      clockRef.current = null;
    };
  }, []);

  useImperativeHandle(
    ref,
    (): PlayerHandle => ({
      play: () => void videoRef.current?.play().catch(() => {}),
      pause: () => videoRef.current?.pause(),
      toggle: () => {
        const v = videoRef.current;
        if (!v) return;
        if (v.paused) void v.play().catch(() => {});
        else v.pause();
      },
      seek: (t) => {
        const v = videoRef.current;
        if (!v) return;
        v.currentTime = clamp(t, 0, v.duration || Number.MAX_SAFE_INTEGER);
      },
      currentTime: () => videoRef.current?.currentTime ?? 0,
      duration: () => videoRef.current?.duration ?? 0,
      paused: () => videoRef.current?.paused ?? true,
      get clock() {
        return clockRef.current;
      },
    }),
    [],
  );

  // Follow-cam: recompute the transform every animation frame from the crop rect at the
  // clock's current time. The rect [x,y,w,h] is normalized; scale = 1/w makes it fill the
  // fixed 16:9 viewport, and transform-origin 0 0 makes the translate plain arithmetic.
  useEffect(() => {
    const box = transformRef.current;
    const viewport = viewportRef.current;
    if (!box || !viewport) return;
    if (!crop || crop.rects.length === 0) {
      box.style.transform = "";
      return;
    }
    let raf = 0;
    const apply = () => {
      const t = clockRef.current?.now() ?? videoRef.current?.currentTime ?? 0;
      // E-12: clamp past the last rect instead of reading undefined.
      const i = clamp(Math.round((t - crop.t0) * crop.rate_hz), 0, crop.rects.length - 1);
      const [x, y, w] = crop.rects[i];
      const s = w > 0 ? 1 / w : 1;
      const W = viewport.clientWidth;
      const H = viewport.clientHeight;
      box.style.transform = `translate(${(-s * x * W).toFixed(2)}px, ${(-s * y * H).toFixed(
        2,
      )}px) scale(${s.toFixed(4)})`;
      raf = requestAnimationFrame(apply);
    };
    raf = requestAnimationFrame(apply);
    return () => {
      cancelAnimationFrame(raf);
      box.style.transform = "";
    };
  }, [crop]);

  return (
    <div className="surface" data-testid="player-surface" ref={viewportRef}>
      <div
        className="surface-transform"
        data-testid="player-transform"
        ref={transformRef}
        style={{ transformOrigin: "0 0", willChange: "transform" }}
      >
        <video
          ref={videoRef}
          src={src}
          muted={muted}
          playsInline
          preload="auto"
          data-testid="video"
          onEnded={onEnded}
        />
      </div>
      <div className="surface-overlays">{children}</div>
    </div>
  );
}
