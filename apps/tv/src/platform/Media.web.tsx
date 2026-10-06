// Web build media element: a plain <video> inside the react-native-web tree. Carries
// apps/web's PlayerSurface rules: a play request is held until `playing` (re-issued on
// `canplay`, cancelled by pause), and a src swap (follow-cam rendition) resumes at the
// same time and play state.
import { useCallback, useEffect, useImperativeHandle, useRef } from "react";
import { clamp, type MediaHandle, type MediaProps } from "../playback/media";

export function Media({ src, muted, loop, onEnded, ref }: MediaProps) {
  const video = useRef<HTMLVideoElement>(null);
  const wantPlay = useRef(false);
  const tries = useRef(0);
  const timeRef = useRef(0);
  const lastSrc = useRef(src);
  const resumeAt = useRef<{ t: number; playing: boolean } | null>(null);

  const tryPlay = useCallback(() => {
    const v = video.current;
    if (!v || !wantPlay.current || !v.paused) return;
    v.play().catch((err: DOMException) => {
      // NotAllowedError needs a fresh user gesture; retrying cannot fix it.
      if (err.name === "NotAllowedError" || ++tries.current > 5) {
        wantPlay.current = false;
        return;
      }
      if (v.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) setTimeout(tryPlay, 100);
    });
  }, []);
  const requestPlay = useCallback(() => {
    wantPlay.current = true;
    tries.current = 0;
    tryPlay();
  }, [tryPlay]);

  // Snapshot before React commits the new src and the element resets to 0.
  // A swap that lands before the previous one has loaded keeps that one's target: the
  // element has reset to 0 and paused in between (rapid replay-angle cuts). The element
  // still holds the old src during render, so its currentTime is exact; `timeupdate` (the
  // ref) lags it by up to 250 ms and misses a seek that has not completed yet.
  if (lastSrc.current !== src) {
    lastSrc.current = src;
    resumeAt.current = resumeAt.current ?? {
      t: video.current?.currentTime ?? timeRef.current,
      playing: !(video.current?.paused ?? true) || wantPlay.current,
    };
  }

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    const landed = () => {
      wantPlay.current = false;
    };
    v.addEventListener("canplay", tryPlay);
    v.addEventListener("playing", landed);
    return () => {
      v.removeEventListener("canplay", tryPlay);
      v.removeEventListener("playing", landed);
    };
  }, [tryPlay]);

  useEffect(() => {
    const v = video.current;
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
    (): MediaHandle => ({
      play: requestPlay,
      pause: () => {
        wantPlay.current = false;
        video.current?.pause();
      },
      seek: (t) => {
        const v = video.current;
        if (v) v.currentTime = clamp(t, 0, v.duration || Number.MAX_SAFE_INTEGER);
      },
      currentTime: () => video.current?.currentTime ?? 0,
      duration: () => video.current?.duration || 0,
      paused: () => (video.current?.paused ?? true) && !wantPlay.current,
    }),
    [requestPlay],
  );

  return (
    <video
      ref={video}
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
      // The surface is 16:9; "fill" keeps the rendered rect equal to it, which is what
      // makes the normalized box math exact.
      style={{ display: "block", width: "100%", height: "100%", objectFit: "fill" }}
    />
  );
}
