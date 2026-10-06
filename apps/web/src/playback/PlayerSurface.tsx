// §4.8 platform adapter: the only component that touches a media element. Screens talk
// to it through PlayerHandle. Phase 3 swaps the <video> for react-native-video / the Vega
// media player and keeps this API.
import { useCallback, useEffect, useImperativeHandle, useRef, useState, type ReactNode, type Ref } from "react";
import { createClock, type Clock } from "./clock";
import type { CropPath } from "../api/types";
import { cropRectAt, cropTransform } from "../../../../packages/tv-core/src/follow";

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
  /** Restart at the end instead of stopping (Replay view). */
  loop?: boolean;
  ref?: Ref<PlayerHandle>;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

export function PlayerSurface({ src, crop, muted, children, onEnded, loop, ref }: Props) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const transformRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const clockRef = useRef<Clock | null>(null);
  const [, setReady] = useState(0);
  // Plan task 12: a follow-cam rendition swap must land at the same media time. The
  // snapshot is taken during render, before React commits the new src and the element
  // resets currentTime to 0.
  const timeRef = useRef(0);
  const lastSrc = useRef(src);
  const resumeAt = useRef<{ t: number; playing: boolean } | null>(null);
  // A play request that has not landed yet. `play()` issued while the element is still
  // settling on its source can be aborted (a reload, or not playable yet) and `paused`
  // flips back to true; swallowing that silently lost the keypress. The request is held
  // until the element reports `playing`, re-issued on every `canplay` meanwhile (and on a
  // timer if the rejection leaves the element ready), and cancelled by pause().
  const wantPlay = useRef(false);
  const tries = useRef(0);
  const tryPlay = useCallback(() => {
    const v = videoRef.current;
    if (!v || !wantPlay.current || !v.paused) return;
    v.play().catch((err: DOMException) => {
      // NotAllowedError needs a fresh user gesture; retrying cannot fix it.
      if (err.name === "NotAllowedError" || ++tries.current > 5) {
        wantPlay.current = false;
        return;
      }
      // Still ready, so no `canplay` is coming to retry on.
      if (v.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) setTimeout(tryPlay, 100);
    });
  }, []);
  const requestPlay = useCallback(() => {
    wantPlay.current = true;
    tries.current = 0;
    tryPlay();
  }, [tryPlay]);
  // A swap that lands before the previous one has loaded keeps that one's target: the
  // element has reset to 0 and paused in between (rapid replay-angle cuts). The element
  // still holds the old src during render, so its currentTime is exact; `timeupdate` (the
  // ref) lags it by up to 250 ms and misses a seek that has not completed yet.
  if (lastSrc.current !== src) {
    lastSrc.current = src;
    resumeAt.current = resumeAt.current ?? {
      t: videoRef.current?.currentTime ?? timeRef.current,
      playing: !(videoRef.current?.paused ?? true) || wantPlay.current,
    };
  }

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const clock = createClock(v);
    clockRef.current = clock;
    setReady((n) => n + 1);
    const landed = () => {
      wantPlay.current = false;
    };
    v.addEventListener("canplay", tryPlay);
    v.addEventListener("playing", landed);
    return () => {
      clock.stop();
      clockRef.current = null;
      v.removeEventListener("canplay", tryPlay);
      v.removeEventListener("playing", landed);
    };
  }, [tryPlay]);

  useEffect(() => {
    const v = videoRef.current;
    const resume = resumeAt.current;
    if (!v || !resume) return;
    const apply = () => {
      resumeAt.current = null;
      v.currentTime = resume.t;
      if (resume.playing) requestPlay();
    };
    if (v.readyState >= 1) apply();
    else v.addEventListener("loadedmetadata", apply, { once: true });
    return () => v.removeEventListener("loadedmetadata", apply);
  }, [src, requestPlay]);

  useImperativeHandle(
    ref,
    (): PlayerHandle => ({
      play: requestPlay,
      pause: () => {
        wantPlay.current = false;
        videoRef.current?.pause();
      },
      toggle: () => {
        const v = videoRef.current;
        if (!v) return;
        // A pending request counts as playing, so a second press cancels it.
        if (v.paused && !wantPlay.current) requestPlay();
        else {
          wantPlay.current = false;
          v.pause();
        }
      },
      seek: (t) => {
        const v = videoRef.current;
        if (!v) return;
        v.currentTime = clamp(t, 0, v.duration || Number.MAX_SAFE_INTEGER);
      },
      currentTime: () => videoRef.current?.currentTime ?? 0,
      duration: () => videoRef.current?.duration ?? 0,
      paused: () => (videoRef.current?.paused ?? true) && !wantPlay.current,
      get clock() {
        return clockRef.current;
      },
    }),
    [requestPlay],
  );

  // Follow-cam: recompute the transform every animation frame from the crop rect at the
  // clock's current time. The rect [x,y,w,h] is normalized; scale (1/w, 1/h) makes it
  // fill the fixed 16:9 viewport, and transform-origin 0 0 makes the translate plain
  // arithmetic. The two axes scale independently because the crop window is 16:9 in
  // source pixels while the source itself may not be (a 2560x960 panorama): the video
  // is already object-fit:fill-stretched into the viewport, so the uneven scale is
  // exactly what undoes that for the cropped region. On a 16:9 source w === h and this
  // is a uniform scale, as before.
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
      // E-12: cropRectAt clamps past the last rect instead of reading undefined.
      const { tx, ty, sx, sy } = cropTransform(
        cropRectAt(crop, t),
        viewport.clientWidth,
        viewport.clientHeight,
      );
      box.style.transform = `translate(${tx.toFixed(2)}px, ${ty.toFixed(2)}px) scale(${sx.toFixed(
        4,
      )}, ${sy.toFixed(4)})`;
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
          loop={loop}
          playsInline
          preload="auto"
          data-testid="video"
          onTimeUpdate={(e) => {
            timeRef.current = e.currentTarget.currentTime;
          }}
          onEnded={onEnded}
        />
      </div>
      <div className="surface-overlays">{children}</div>
    </div>
  );
}
