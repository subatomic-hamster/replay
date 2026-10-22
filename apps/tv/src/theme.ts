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

// ---------------------------------------------------------------- team colours
type Hsl = [number, number, number];

function toHsl(hex: string): Hsl {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16) || 0;
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(
    (v) => v / 255,
  );
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  if (!d) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h =
    max === r
      ? ((g - b) / d + 6) % 6
      : max === g
        ? (b - r) / d + 2
        : (r - g) / d + 4;
  return [h * 60, s, l];
}

function toHex([h, s, l]: Hsl): string {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const [r, g, b] =
    h < 60
      ? [c, x, 0]
      : h < 120
        ? [x, c, 0]
        : h < 180
          ? [0, c, x]
          : h < 240
            ? [0, x, c]
            : h < 300
              ? [x, 0, c]
              : [c, 0, x];
  return `#${[r, g, b]
    .map((v) =>
      Math.round((v + m) * 255)
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`.toUpperCase();
}

/** Team colours as drawn on the dark chrome, in the same order. Jersey colours read off
 *  footage are often dark and alike (#57282A vs #402B28): each is lifted to at least half
 *  lightness so it shows on Bench, and two teams still too alike (hue within 40°, or both
 *  near grey, and lightness within 0.3) are split by lightness, the darker jersey staying
 *  the darker swatch. Hue is kept, so the swatch still looks like the jersey. */
export function teamColors(raw: string[]): string[] {
  const c = raw.map((h) => {
    const [hh, s, l] = toHsl(h);
    return [hh, s, Math.max(l, 0.5)] as Hsl;
  });
  if (c.length === 2) {
    const [a, b] = c;
    const gap = Math.abs(a[0] - b[0]);
    const hueGap = Math.min(gap, 360 - gap);
    const alike =
      (hueGap < 40 || (a[1] < 0.15 && b[1] < 0.15)) &&
      Math.abs(a[2] - b[2]) < 0.3;
    if (alike) {
      const aDarker = toHsl(raw[0])[2] <= toHsl(raw[1])[2];
      a[2] = aDarker ? 0.45 : 0.82;
      b[2] = aDarker ? 0.82 : 0.45;
    }
  }
  return c.map(toHex);
}

/** raw team hex → the drawn one, for the distinct colours in `raw` (first seen first). */
export function teamColorMap(
  raw: (string | null | undefined)[],
): Map<string, string> {
  const uniq = [...new Set(raw.filter((h): h is string => !!h))];
  const drawn = teamColors(uniq);
  return new Map(uniq.map((h, i) => [h, drawn[i]]));
}

/** A 4 px Chalk ring. Pair with `focusRing(false)` for a same-size transparent border so
 *  layout does not jump when focus moves. */
export const focusRing = (on: boolean) => ({
  borderWidth: px(4),
  borderColor: on ? color.chalk : "transparent",
});
