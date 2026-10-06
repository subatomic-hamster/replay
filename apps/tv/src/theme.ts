// 10-foot UI (§4.8 / NF-01..NF-04). Everything is designed in 1920x1080 "design px" and
// scaled to the window: a 1080p Fire TV reports a 960x540 dp window, so px(24) there is
// 12 dp = 24 physical pixels, and the 1920x1080 web build gets exactly 24 CSS px.
// Nothing renders below px(24); focus is a shape change (thick amber ring), never colour
// alone. Palette mirrors apps/web's app.css ("the gym after the lights go down").
import { Dimensions } from "react-native";

// ponytail: read once; a TV window does not resize. Re-read on Dimensions change if a
// phone/tablet build ever ships.
const SCALE = Dimensions.get("window").width / 1920;

export const px = (n: number) => Math.round(n * SCALE * 100) / 100;

export const color = {
  ink: "#090b0e",
  panel: "#141922",
  raised: "#1f2732",
  line: "#2c3542",
  fg: "#f4f6f9",
  dim: "#93a0b4",
  accent: "#ffb020",
  onAccent: "#1a1102",
  made: "#4ade80",
  missed: "#f2555a",
  scrim: "rgba(5, 7, 10, 0.82)",
  dot: "#8ab4ff",
};

export const font = {
  body: px(28),
  small: px(24),
  title: px(56),
  h2: px(36),
};

/** The focus ring: a thick amber border. Pair with `focusRing(false)` for a same-size
 *  transparent border so layout does not jump when focus moves. */
export const focusRing = (on: boolean) => ({
  borderWidth: px(5),
  borderColor: on ? color.accent : "transparent",
});
