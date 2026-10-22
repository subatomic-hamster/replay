// W4 — the ring that stays on the followed player in wide playback and follow mode, in
// the team's colour. Positioned in VIEWPORT pixels by PlayerSurface's animation-frame
// loop (the same frame that moves the follow-cam), through Animated values, so it rides
// the player without re-rendering the Watch screen.
//
// Transforms only (D-85): four bars, each scaled along its length from its top-left
// corner, inside a translated wrapper. A width or height change would re-lay the ring out
// every frame, and the native driver cannot animate layout props at all.
import { useMemo } from "react";
import { Animated, Platform, StyleSheet } from "react-native";
import { inkOn } from "../../../../packages/tv-core/src/display";
import { font, px } from "../theme";
import { T } from "../ui";

/** A value the native driver owns: setValue goes straight to the view on the UI thread,
 *  with no React commit per frame. The web build has no native driver. */
export function nativeValue(v: number): Animated.Value {
  const a = new Animated.Value(v);
  if (Platform.OS !== "web")
    Animated.timing(a, {
      toValue: v,
      duration: 0,
      useNativeDriver: true,
    }).start();
  return a;
}

export interface RingValues {
  x: Animated.Value;
  y: Animated.Value;
  w: Animated.Value;
  h: Animated.Value;
  opacity: Animated.Value;
}

export const newRing = (): RingValues => ({
  x: nativeValue(0),
  y: nativeValue(0),
  w: nativeValue(0),
  h: nativeValue(0),
  opacity: nativeValue(0),
});

const L = 100; // a bar's unscaled length, px
const B = px(4); // the ring's line width

interface Props {
  /** The player picked (labels, tests); `track` is the id the camera is on now. */
  pid: string;
  track: string;
  label: string;
  tint: string;
  visible: boolean;
  ring: RingValues;
}

export function FollowFrame({ pid, track, label, tint, visible, ring }: Props) {
  const d = useMemo(
    () => ({
      sw: Animated.multiply(ring.w, 1 / L),
      sh: Animated.multiply(ring.h, 1 / L),
      right: Animated.add(ring.w, -B),
      bottom: Animated.add(ring.h, -B),
      under: Animated.add(ring.h, px(4)),
    }),
    [ring],
  );
  const bar = { backgroundColor: tint };
  return (
    <Animated.View
      testID="follow-frame"
      dataSet={{ pid, track, visible: visible ? "true" : "false" }}
      style={[
        styles.frame,
        {
          opacity: ring.opacity,
          transform: [{ translateX: ring.x }, { translateY: ring.y }],
        },
      ]}
    >
      <Animated.View
        testID="follow-frame-top"
        style={[styles.h, bar, { transform: [{ scaleX: d.sw }] }]}
      />
      <Animated.View
        style={[
          styles.h,
          bar,
          { transform: [{ translateY: d.bottom }, { scaleX: d.sw }] },
        ]}
      />
      <Animated.View
        style={[styles.v, bar, { transform: [{ scaleY: d.sh }] }]}
      />
      <Animated.View
        style={[
          styles.v,
          bar,
          { transform: [{ translateX: d.right }, { scaleY: d.sh }] },
        ]}
      />
      <Animated.View
        style={[styles.labelRow, { transform: [{ translateY: d.under }] }]}
      >
        <T
          style={[styles.label, { backgroundColor: tint, color: inkOn(tint) }]}
        >
          {label}
        </T>
      </Animated.View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  frame: { position: "absolute", left: 0, top: 0 },
  h: {
    position: "absolute",
    left: 0,
    top: 0,
    width: L,
    height: B,
    transformOrigin: "left top",
  },
  v: {
    position: "absolute",
    left: 0,
    top: 0,
    width: B,
    height: L,
    transformOrigin: "left top",
  },
  labelRow: {
    position: "absolute",
    top: 0,
    left: 0,
    width: px(400),
    flexDirection: "row",
  },
  label: {
    paddingHorizontal: px(8),
    fontSize: font.small,
    fontWeight: "700",
    borderRadius: px(4),
  },
});
