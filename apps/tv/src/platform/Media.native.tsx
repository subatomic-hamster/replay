// Fire TV media element: react-native-video (ExoPlayer/Media3 on Android). Playback is
// prop-driven (`paused`), time arrives through onProgress every 100 ms and the shared
// clock extrapolates between reports. A src swap (follow-cam rendition) resumes at the
// same time once the new source has loaded.
import { useImperativeHandle, useRef, useState } from "react";
import { StyleSheet } from "react-native";
import Video, { type VideoRef } from "react-native-video";
import { clamp, type MediaHandle, type MediaProps } from "../playback/media";

export function Media({ src, muted, loop, onEnded, ref }: MediaProps) {
  const video = useRef<VideoRef>(null);
  const [paused, setPaused] = useState(true);
  const state = useRef({ t: 0, duration: 0, paused: true });
  const lastSrc = useRef(src);
  const resumeAt = useRef<number | null>(null);

  if (lastSrc.current !== src) {
    lastSrc.current = src;
    // A second swap before the first has loaded keeps the first one's target.
    resumeAt.current = resumeAt.current ?? state.current.t;
  }

  useImperativeHandle(
    ref,
    (): MediaHandle => ({
      play: () => {
        state.current.paused = false;
        setPaused(false);
      },
      pause: () => {
        state.current.paused = true;
        setPaused(true);
      },
      seek: (t) => {
        const to = clamp(t, 0, state.current.duration || Number.MAX_SAFE_INTEGER);
        state.current.t = to;
        video.current?.seek(to);
      },
      currentTime: () => state.current.t,
      duration: () => state.current.duration,
      paused: () => state.current.paused,
    }),
    [],
  );

  return (
    <Video
      ref={video}
      source={{ uri: src }}
      paused={paused}
      muted={muted}
      repeat={loop}
      resizeMode="stretch"
      progressUpdateInterval={100}
      style={StyleSheet.absoluteFill}
      onLoad={(e) => {
        state.current.duration = e.duration;
        if (resumeAt.current !== null) {
          video.current?.seek(resumeAt.current);
          resumeAt.current = null;
        }
      }}
      onProgress={(e) => {
        state.current.t = e.currentTime;
      }}
      onEnd={() => {
        state.current.paused = true;
        setPaused(true);
        onEnded?.();
      }}
    />
  );
}
