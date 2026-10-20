// 10-foot UI tokens (docs/ux/redesign.md "Tokens"). Everything is designed in 1920x1080
// "design px" and scaled to the window: a 1080p Fire TV reports a 960x540 dp window, so
// px(26) there is 13 dp = 26 physical pixels, and the 1920x1080 web build gets 26 CSS px.
// Nothing renders below px(24) (TV-08). Two colour meanings, never mixed: white (Chalk) is
// "selected", amber (Scoreboard) is "in the game".
import { Dimensions } from "react-native";

// ponytail: read once; a TV window does not resize. Re-read on Dimensions change if a
// phone/tablet build ever ships.
const SCALE = Dimensions.get("window").width / 1920;

export const px = (n: number) => Math.round(n * SCALE * 100) / 100;

/** The six spec colours. */
export const palette = {
  floor: "#121A23",
  bench: "#1D2834",
  line: "#3A4856",
  chalk: "#ECEFF2",
  bleacher: "#9DAAB7",
  scoreboard: "#F0B44C",
};

/** The spec palette plus the names the not-yet-redesigned screens use, mapped onto it. */
export const color = {
  ...palette,
  ink: palette.floor,
  panel: palette.bench,
  raised: palette.line,
  fg: palette.chalk,
  dim: palette.bleacher,
  accent: palette.scoreboard,
  onAccent: palette.floor,
  // Game semantics (shot made/missed, ball dot) on the old screens; Wave 2 replaces them.
  made: "#4ade80",
  missed: "#f2555a",
  scrim: "rgba(18, 26, 35, 0.84)",
  dot: "#8ab4ff",
};

/** Font files: android/app/src/main/assets/fonts/<name>.ttf on native, the same family
 *  names via @font-face on web (main.web.tsx). One face per family, so a weight is picked
 *  by family, never by fontWeight (that would fake-bold); ui.tsx's T maps weights. */
export const face = {
  medium: "Barlow-Medium",
  semibold: "Barlow-SemiBold",
  figures: "BarlowSemiCondensed-SemiBold",
};

/** Type scale. `small`/`h2` are the old names (Meta and Title). */
export const font = {
  display: px(72),
  title: px(40),
  body: px(30),
  meta: px(26),
  small: px(26),
  h2: px(40),
};

export const type = {
  display: {
    fontFamily: face.semibold,
    fontSize: font.display,
    lineHeight: px(80),
  },
  title: {
    fontFamily: face.semibold,
    fontSize: font.title,
    lineHeight: px(48),
  },
  body: { fontFamily: face.medium, fontSize: font.body, lineHeight: px(40) },
  meta: { fontFamily: face.medium, fontSize: font.meta, lineHeight: px(34) },
  figures: {
    fontFamily: face.figures,
    fontSize: font.body,
    fontVariant: ["tabular-nums" as const],
  },
};

/** 8 px grid: sp(3) = 24 design px. */
export const sp = (n: number) => px(8 * n);

export const radius = { card: px(12), chip: px(999) };

/** 5% overscan safe zone; video and key art bleed past it. */
export const safe = { x: px(96), y: px(54) };

/** Focus motion; set true to make focus changes instant. */
export const REDUCED_MOTION = false;
export const FOCUS_MS = REDUCED_MOTION ? 0 : 150;
export const FOCUS_SCALE = 1.06;

/** A 4 px Chalk ring. Pair with `focusRing(false)` for a same-size transparent border so
 *  layout does not jump when focus moves. */
export const focusRing = (on: boolean) => ({
  borderWidth: px(4),
  borderColor: on ? color.chalk : "transparent",
});
