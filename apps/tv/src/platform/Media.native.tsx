// Fire TV media element: react-native-video (ExoPlayer/Media3 on Android). Playback is
// prop-driven (`paused`), time arrives through onProgress every 100 ms and the shared
// clock extrapolates between reports. ExoPlayer drops a seek issued before the source has
// loaded, so until onLoad a seek is held (one pending target) and the video stays paused;
// a src swap (follow-cam rendition, replay angle) queues the current time the same way.
import { useImperativeHandle, useRef, useState } from "react";
import { StyleSheet } from "react-native";
import Video, { ViewType, type VideoRef } from "react-native-video";
import { clamp, type MediaHandle, type MediaProps } from "../playback/media";

export function Media({
  src,
  muted,
  loop,
  onEnded,
  onError,
  onReady,
  onBuffering,
  ref,
}: MediaProps) {
  const video = useRef<VideoRef>(null);
  const [paused, setPaused] = useState(true);
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const state = useRef({
    t: 0,
    duration: 0,
    paused: true,
    loaded: false,
    ended: false,
    pendingSeek: null as number | null,
  });
  const lastSrc = useRef(src);

  if (lastSrc.current !== src) {
    const s = state.current;
    lastSrc.current = src;
    s.loaded = false;
    s.ended = false;
    // A second swap before the first has loaded keeps the first one's target.
    s.pendingSeek = s.pendingSeek ?? s.t;
  }

  useImperativeHandle(ref, (): MediaHandle => {
    const s = state.current;
    const seek = (t: number) => {
      const to = clamp(t, 0, s.duration || Number.MAX_SAFE_INTEGER);
      s.t = to;
      s.ended = false;
      if (s.loaded) video.current?.seek(to);
      else s.pendingSeek = to;
    };
    return {
      play: () => {
        // ExoPlayer sits in STATE_ENDED after the last frame; playWhenReady alone won't restart.
        if (s.ended) seek(0);
        s.paused = false;
        setPaused(false);
      },
      pause: () => {
        s.paused = true;
        setPaused(true);
      },
      seek,
      currentTime: () => s.t,
      duration: () => s.duration,
      paused: () => s.paused,
    };
  }, []);

  return (
    <Video
      ref={video}
      source={{ uri: src }}
      // A play request is held until the source has loaded and any pending seek landed.
      paused={paused || loadedSrc !== src}
      muted={muted}
      repeat={loop}
      resizeMode="stretch"
      // PlayerSurface translates/scales this view (follow-cam crop); a SurfaceView can't be
      // transformed or clipped by its parent, a TextureView can.
      viewType={ViewType.TEXTURE}
      progressUpdateInterval={100}
      // A source swap keeps the last frame on the TextureView (PlayerSurface spins over
      // it) instead of a shutter; the first load is covered by PlayerSurface's backdrop.
      hideShutterView
      shutterColor="transparent"
      // ExoPlayer STATE_READY: the frame is there (also after each buffer).
      onReadyForDisplay={onReady}
      onBuffer={({ isBuffering }) => onBuffering?.(isBuffering)}
      style={StyleSheet.absoluteFill}
      onLoad={(e) => {
        const s = state.current;
        s.duration = e.duration;
        s.loaded = true;
        if (s.pendingSeek !== null) {
          video.current?.seek(s.pendingSeek);
          s.pendingSeek = null;
        }
        setLoadedSrc(src);
      }}
      onProgress={(e) => {
        state.current.t = e.currentTime;
      }}
      onEnd={() => {
        // With repeat on, react-native-video still reports each wrap as an end; <video loop>
        // never fires `ended`, so mirror that.
        if (loop) return;
        const s = state.current;
        s.ended = true;
        s.paused = true;
        setPaused(true);
        onEnded?.();
      }}
      onError={({ error }) => {
        state.current.paused = true;
        setPaused(true);
        onError?.(
          error.errorString ??
            error.localizedDescription ??
            error.error ??
            "Playback failed",
        );
      }}
    />
  );
}
