// §4.8 platform adapter: the only component screens use for media. The media element
// itself is platform/Media (<video> on web, react-native-video on Fire TV); this layer is
// plain RN and shared: the 16:9 viewport, the D-6 follow-cam crop transform, the shared
// media clock, and the overlay layer above the video.
import { useEffect, useImperativeHandle, useRef, useState, type ReactNode, type Ref } from "react";
import { Animated, StyleSheet, View } from "react-native";
import { createClock, type Clock } from "../../../../packages/tv-core/src/clock";
import { cropRectAt, cropTransform } from "../../../../packages/tv-core/src/follow";
import type { CropPath } from "../../../../packages/tv-core/src/types";
import { Media } from "../platform/Media";
import type { MediaHandle } from "./media";

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
  /** Restart at the end instead of stopping (Replay view). */
  loop?: boolean;
  /** Overlays, laid out over the untransformed viewport. */
  children?: ReactNode;
  ref?: Ref<PlayerHandle>;
}

export function PlayerSurface({ src, crop, muted, loop, children, ref }: Props) {
  const media = useRef<MediaHandle>(null);
  const [clock, setClock] = useState<Clock | null>(null);
  const size = useRef({ w: 0, h: 0 });
  const [anim] = useState(() => ({
    tx: new Animated.Value(0),
    ty: new Animated.Value(0),
    sx: new Animated.Value(1),
    sy: new Animated.Value(1),
  }));

  useEffect(() => {
    const c = createClock({
      currentTime: () => media.current?.currentTime() ?? 0,
      paused: () => media.current?.paused() ?? true,
    });
    setClock(c);
    return () => c.stop();
  }, []);

  useImperativeHandle(
    ref,
    (): PlayerHandle => ({
      play: () => media.current?.play(),
      pause: () => media.current?.pause(),
      toggle: () => {
        const m = media.current;
        if (!m) return;
        if (m.paused()) m.play();
        else m.pause();
      },
      seek: (t) => media.current?.seek(t),
      currentTime: () => media.current?.currentTime() ?? 0,
      duration: () => media.current?.duration() ?? 0,
      paused: () => media.current?.paused() ?? true,
      clock,
    }),
    [clock],
  );

  // Follow-cam: recompute the transform every animation frame from the crop rect at the
  // clock's time. RN scales about the view centre, so the translate is corrected by
  // c·(1−s) to get the same top-left-origin result as apps/web's CSS transform.
  useEffect(() => {
    const reset = () => {
      anim.tx.setValue(0);
      anim.ty.setValue(0);
      anim.sx.setValue(1);
      anim.sy.setValue(1);
    };
    if (!crop || crop.rects.length === 0 || !clock) {
      reset();
      return;
    }
    let raf = 0;
    const apply = () => {
      const { w, h } = size.current;
      const { tx, ty, sx, sy } = cropTransform(cropRectAt(crop, clock.now()), w, h);
      anim.tx.setValue(tx + (w / 2) * (sx - 1));
      anim.ty.setValue(ty + (h / 2) * (sy - 1));
      anim.sx.setValue(sx);
      anim.sy.setValue(sy);
      raf = requestAnimationFrame(apply);
    };
    raf = requestAnimationFrame(apply);
    return () => {
      cancelAnimationFrame(raf);
      reset();
    };
  }, [crop, clock, anim]);

  return (
    <View
      testID="player-surface"
      style={styles.surface}
      onLayout={(e) => {
        size.current = { w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height };
      }}
    >
      <Animated.View
        testID="player-transform"
        style={[
          StyleSheet.absoluteFill,
          {
            transform: [
              { translateX: anim.tx },
              { translateY: anim.ty },
              { scaleX: anim.sx },
              { scaleY: anim.sy },
            ],
          },
        ]}
      >
        <Media ref={media} src={src} muted={muted} loop={loop} />
      </Animated.View>
      <View style={StyleSheet.absoluteFill} pointerEvents="none">
        {children}
      </View>
    </View>
  );
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

const styles = StyleSheet.create({
  surface: {
    width: "100%",
    aspectRatio: 16 / 9,
    overflow: "hidden",
    backgroundColor: "#000",
  },
});
