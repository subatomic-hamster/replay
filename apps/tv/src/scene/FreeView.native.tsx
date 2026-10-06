// Free view (2.5D), Fire TV renderer: the Fabric GL view com.replaytv.scene.SceneView
// (specs/ReplaySceneViewNativeComponent.ts) — ExoPlayer decodes the atlas into an external
// GL texture, OpenGL ES draws the package (docs/scene-format.md "How to render"). Same props
// and behaviour as FreeView.web.tsx: `camera` is the target the view eases towards, the atlas
// loops, onTime fires a few times per second, on pause and once while unmounting. Metro picks
// this file on Android; Vite picks FreeView.web.tsx.
import { useEffect, useMemo, useRef } from "react";
import { StyleSheet } from "react-native";
import ReplaySceneView from "../../specs/ReplaySceneViewNativeComponent";
import type { FreeViewProps } from "./camera";

export function FreeView({ layout, camera, paused, startTimeSec, onTime, onReady, onError }: FreeViewProps) {
  // ~0.2–0.4 MB; the view parses it off the UI thread, once per package.
  const json = useMemo(() => JSON.stringify(layout), [layout]);
  const last = useRef({ sec: startTimeSec ?? 0, at: Date.now(), paused, onTime });

  useEffect(() => {
    last.current.onTime = onTime;
  });

  useEffect(() => {
    last.current.paused = paused;
    last.current.at = Date.now();
  }, [paused]);

  // Once while unmounting (the Replay screen resumes the video angle there): the last time
  // the view reported, advanced by the wall time since while playing (reports are ~10 Hz).
  useEffect(() => {
    const l = last.current;
    return () => {
      const dur = layout.n_frames / layout.fps;
      const sec = l.paused ? l.sec : l.sec + (Date.now() - l.at) / 1000;
      l.onTime?.(sec % dur);
    };
  }, [layout]);

  return (
    <ReplaySceneView
      style={StyleSheet.absoluteFill}
      testID="free-view"
      layoutJson={json}
      azimuth={camera.azimuth}
      elevation={camera.elevation}
      distance={camera.distance}
      roll={camera.roll}
      fovY={camera.fovY}
      paused={paused}
      startTimeSec={startTimeSec ?? 0}
      onSceneTime={(e) => {
        const l = last.current;
        l.sec = e.nativeEvent.sec;
        l.at = Date.now();
        onTime?.(e.nativeEvent.sec);
      }}
      onSceneReady={() => onReady?.()}
      onSceneError={(e) => onError?.(e.nativeEvent.message)}
    />
  );
}
