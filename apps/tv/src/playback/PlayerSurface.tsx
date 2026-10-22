// §4.8 platform adapter: the only component screens use for media. The media element
// itself is platform/Media (<video> on web, react-native-video on Fire TV); this layer is
// plain RN and shared: the 16:9 viewport, the D-6 follow-cam crop transform, the shared
// media clock, and the overlay layer above the video.
import {
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type Ref,
} from "react";
import { Animated, StyleSheet, View } from "react-native";
import {
  createClock,
  type Clock,
} from "../../../../packages/tv-core/src/clock";
import {
  cropTransform,
  mapBB,
  type FollowCam,
} from "../../../../packages/tv-core/src/follow";
import { FollowFrame, nativeValue, newRing } from "../components/FollowFrame";
import { Media } from "../platform/Media";
import { color, px, type } from "../theme";
import { Backdrop, Busy, Spinner, T } from "../ui";
import type { MediaHandle } from "./media";

export interface PlayerHandle {
  play(): void;
  pause(): void;
  toggle(): void;
  seek(t: number): void;
  currentTime(): number;
  duration(): number;
  paused(): boolean;
  /** Why the current source failed, or null; pollers waiting on duration() can stop. */
  error(): string | null;
  clock: Clock | null;
}

/** D-82 client follow-cam: the camera, whether it follows (zoom and ring) or eases back
 *  to the wide shot with no ring (D-86), and the ring's words and team colour. */
export interface Follow {
  cam: FollowCam;
  pid: string;
  zoom: boolean;
  label: string;
  tint: string;
}

interface Props {
  src: string;
  follow?: Follow | null;
  muted?: boolean;
  /** Restart at the end instead of stopping (Replay view). */
  loop?: boolean;
  /** Viewport width / height; 16:9 except the 9:16 share-export preview. */
  aspect?: number;
  /** Overlays, laid out over the untransformed viewport. */
  children?: ReactNode;
  /** The picture blurred behind the spinner until the first frame (a game's hero). */
  poster?: string | null;
  ref?: Ref<PlayerHandle>;
}

/** The follow ring stays through a tracking dropout this short (one or two 10 Hz track
 *  frames), and eases over to the new box for this long after a track hand-off. */
const RING_GRACE_S = 0.3;
const RING_BLEND_S = 0.2;

/** A stall shorter than this shows no spinner (a seek on a warm buffer). */
const BUFFER_SHOW_MS = 400;

export function PlayerSurface({
  src,
  follow,
  muted,
  loop,
  aspect,
  children,
  poster,
  ref,
}: Props) {
  const media = useRef<MediaHandle>(null);
  const [clock, setClock] = useState<Clock | null>(null);
  const size = useRef({ w: 0, h: 0 });
  // Keyed by src, so a swap to another source clears it without an effect.
  const [failed, setFailed] = useState<{ src: string; message: string } | null>(
    null,
  );
  const error = failed?.src === src ? failed.message : null;
  // Loading: until the first source shows a frame, its poster blurred with a spinner; a
  // later source swap (way, angle, broadcast) or a stall spins over the frozen frame.
  const [readySrc, setReadySrc] = useState<string | null>(null);
  const [everReady, setEverReady] = useState(false);
  const [stalled, setStalled] = useState(false);
  useEffect(() => {
    if (!stalled) return;
    const t = setTimeout(() => setStalled(false), 30_000); // never spin forever on a lost event
    return () => clearTimeout(t);
  }, [stalled]);
  const [anim] = useState(() => ({
    tx: nativeValue(0),
    ty: nativeValue(0),
    sx: nativeValue(1),
    sy: nativeValue(1),
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
      error: () => error,
      clock,
    }),
    [clock, error],
  );

  // Follow-cam: step the camera every animation frame at the clock's time and move the
  // video and the ring in the same frame. RN scales about the view centre, so the
  // translate is corrected by c·(1−s) to get the same top-left-origin result as apps/web's
  // CSS transform. Zoom is read through a ref: Back eases out instead of restarting.
  const [ring] = useState(newRing);
  const [seen, setSeen] = useState<{ track: string; visible: boolean } | null>(
    null,
  );
  const zoom = useRef(false);
  zoom.current = !!follow?.zoom;
  const cam = follow?.cam ?? null;
  // Not following: the ring goes on the render that says so, not a frame later.
  useLayoutEffect(() => {
    if (!follow?.zoom) ring.opacity.setValue(0);
  }, [follow?.zoom, ring]);
  useEffect(() => {
    const reset = () => {
      anim.tx.setValue(0);
      anim.ty.setValue(0);
      anim.sx.setValue(1);
      anim.sy.setValue(1);
      ring.opacity.setValue(0);
    };
    if (!cam || !clock) {
      reset();
      setSeen(null);
      return;
    }
    let raf = 0;
    let wall = performance.now();
    let last = { track: "", visible: false };
    // The ring's own box (frame coordinates) and fade, so it never flickers or snaps:
    // a dropout shorter than RING_GRACE_S keeps it on, held where the player was (still
    // mapped through the moving camera); longer, it fades out; on a hand-off to another
    // track id it eases over to the new box instead of jumping.
    let ringBox: number[] | null = null;
    let ringId = "";
    let blend = 0; // seconds of easing left after a hand-off
    let lost = 0;
    let alpha = 0;
    // Animated pushes every setValue to the view, equal or not: send only real changes.
    const sent = new Map<Animated.Value, number>();
    const put = (a: Animated.Value, x: number, step = 0.1) => {
      const q = Math.round(x / step) * step;
      if (sent.get(a) === q) return;
      sent.set(a, q);
      a.setValue(q);
    };
    const apply = () => {
      const now = performance.now();
      const dt = Math.min((now - wall) / 1000, 0.1);
      const v = cam.step(clock.now(), (now - wall) / 1000, zoom.current);
      wall = now;
      const { w, h } = size.current;
      const { tx, ty, sx, sy } = cropTransform(v.rect, w, h);
      put(anim.tx, tx + (w / 2) * (sx - 1));
      put(anim.ty, ty + (h / 2) * (sy - 1));
      put(anim.sx, sx, 1e-4);
      put(anim.sy, sy, 1e-4);
      const box = v.box;
      if (box) {
        if (ringBox && ringId && v.id !== ringId) blend = RING_BLEND_S;
        ringId = v.id;
        lost = 0;
        if (ringBox && blend > 0) {
          blend -= dt;
          const k = Math.min(1, dt / Math.max(blend + dt, 1e-3));
          ringBox = ringBox.map((a, i) => a + (box[i] - a) * k);
        } else ringBox = [...box];
      } else lost += dt;
      const on = zoom.current && !!ringBox && lost < RING_GRACE_S;
      // fade in fast (the ring is the answer to Select), out gently; Back (not following
      // any more) takes it off at once while the camera eases back out
      alpha = zoom.current
        ? alpha + ((on ? 1 : 0) - alpha) * Math.min(1, dt * (on ? 25 : 6))
        : 0;
      if (ringBox) {
        const [bx, by, bw, bh] = mapBB(
          ringBox as [number, number, number, number],
          v.rect,
        );
        put(ring.x, bx * w);
        put(ring.y, by * h);
        put(ring.w, bw * w);
        put(ring.h, bh * h);
      }
      put(ring.opacity, alpha, 0.01);
      // React hears only of changes (tests and the label read these), not every frame.
      if (last.track !== v.id || last.visible !== !!v.box) {
        last = { track: v.id, visible: !!v.box };
        setSeen(last);
      }
      raf = requestAnimationFrame(apply);
    };
    apply(); // this frame, not the next: the ring is there on the render that asked
    return () => {
      cancelAnimationFrame(raf);
      reset();
    };
  }, [cam, clock, anim, ring]);

  return (
    <View
      testID="player-surface"
      style={[styles.surface, aspect ? { aspectRatio: aspect } : null]}
      onLayout={(e) => {
        size.current = {
          w: e.nativeEvent.layout.width,
          h: e.nativeEvent.layout.height,
        };
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
        <Media
          ref={media}
          src={src}
          muted={muted}
          loop={loop}
          onError={(message) => setFailed({ src, message })}
          onReady={() => {
            setReadySrc(src);
            setEverReady(true);
            setStalled(false);
          }}
          onBuffering={setStalled}
        />
      </Animated.View>
      <View style={StyleSheet.absoluteFill} pointerEvents="none">
        {children}
        {follow && seen ? (
          <FollowFrame
            pid={follow.pid}
            track={seen.track}
            label={follow.label}
            tint={follow.tint}
            visible={seen.visible}
            ring={ring}
          />
        ) : null}
      </View>
      {error ? (
        <View
          style={[StyleSheet.absoluteFill, styles.center]}
          pointerEvents="none"
          testID="player-error"
        >
          <Backdrop art={poster} dim={0.7} />
          <T style={type.title}>Video unavailable</T>
          <T style={[type.meta, styles.dim]} numberOfLines={2}>
            {error}
          </T>
        </View>
      ) : !everReady ? (
        <Busy art={poster} testID="player-loading" />
      ) : readySrc !== src || stalled ? (
        <View
          style={[StyleSheet.absoluteFill, styles.center]}
          pointerEvents="none"
          testID="player-buffering"
        >
          <Spinner delay={BUFFER_SHOW_MS} />
        </View>
      ) : null}
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
    return clock.subscribe((v) =>
      setT((prev) => (Math.abs(v - prev) >= step ? v : prev)),
    );
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
  center: { alignItems: "center", justifyContent: "center", padding: px(48) },
  dim: { color: color.bleacher, marginTop: px(16), textAlign: "center" },
});
