// Shared screen bits: async loading, the API error banner (E-22), text and the focusable
// primitives of the redesign (docs/ux/redesign.md). Nothing here is native-focusable:
// focus is app state moved by the D-pad, so the native focus engine never fights the
// spatial algorithm. A focused thing scales 1.06 with a 4 px Chalk ring (150 ms ease-out).
import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  ActivityIndicator,
  Animated,
  Easing,
  Image,
  PixelRatio,
  Platform,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from "react-native";
import { ApiError } from "../../../packages/tv-core/src/api";
import { TIMELINE_H } from "./components/Timeline";
import { useDpad } from "./input";
import { navigate, useRoute } from "./nav";
import {
  color,
  face,
  focusRing,
  FOCUS_MS,
  FOCUS_SCALE,
  font,
  px,
  radius,
  safe,
  sp,
  type,
} from "./theme";

type DataSet = Record<string, string | number | undefined>;

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);

  useEffect(() => {
    let live = true;
    setError(null);
    // A synchronous throw (the mock's unknown game id) is an error too, not a crash.
    new Promise<T>((resolve) => resolve(run())).then(
      (v) => live && setData(v),
      (e: Error) => live && setError(e),
    );
    return () => {
      live = false;
    };
  }, [run, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, reload };
}

/** Barlow's line box (ascent 1000, descent 200 per 1000 em, every face) puts the middle of
 *  its capitals about 0.05 em below the middle of the box, so a label centred in a pill,
 *  row or circle read 1–1.5 px low at 30 px (measured from pixels on the web build and a
 *  Fire TV). T lifts its glyphs (paint only, a transform: layout is untouched) by 0.04 em,
 *  which after rounding to whole pixels lands the capitals within half a pixel of the
 *  box's middle on both (TV-33). */
const CAP_DROP = 0.04;
/** Android pads a text box with the font's extra top/bottom by default (another ~1 px low
 *  at 30 px on a Fire TV, and taller boxes than the web build's): off, so both platforms
 *  lay text out alike. */
const ANDROID_TEXT =
  Platform.OS === "android"
    ? { includeFontPadding: false, textAlignVertical: "center" as const }
    : null;

/** Text. The weight picks the Barlow face (600+ = SemiBold, else Medium) and is then
 *  dropped, so neither platform fakes a bold; an explicit fontFamily (Figures) is kept.
 *  Capitals sit on the middle of the text box (CAP_DROP). */
export function T({
  children,
  style,
  testID,
  dataSet,
  numberOfLines,
}: {
  children: ReactNode;
  style?: StyleProp<TextStyle>;
  testID?: string;
  dataSet?: DataSet;
  numberOfLines?: number;
}) {
  const flat = StyleSheet.flatten([styles.text, style]) as TextStyle;
  const { fontWeight: w, ...rest } = flat;
  const bold = w === "bold" || Number(w) >= 600;
  const family = rest.fontFamily ?? (bold ? face.semibold : face.medium);
  // A Text that paints its own fill would carry the fill along: wrap such a badge in a
  // View with the fill instead, as Clips and Search do.
  const lift = rest.backgroundColor
    ? 0
    : PixelRatio.roundToNearestPixel((rest.fontSize ?? font.body) * CAP_DROP);
  const moved = Array.isArray(rest.transform) ? rest.transform : [];
  return (
    <Text
      style={[
        rest,
        ANDROID_TEXT,
        { fontFamily: family },
        lift ? { transform: [...moved, { translateY: -lift }] } : null,
      ]}
      testID={testID}
      dataSet={dataSet}
      numberOfLines={numberOfLines}
    >
      {children}
    </Text>
  );
}

/** A section title (Title 40/600): "Games", "Players". */
export function Title({
  children,
  style,
  testID,
}: {
  children: ReactNode;
  style?: StyleProp<TextStyle>;
  testID?: string;
}) {
  return (
    <T style={[type.title, styles.title, style]} testID={testID}>
      {children}
    </T>
  );
}

// The JS driver on web (react-native-web has no native animated module).
const NATIVE_DRIVER = Platform.OS !== "web";

/** 1 → 1.06 while focused, 150 ms ease-out (instant with REDUCED_MOTION). */
function useFocusScale(on: boolean) {
  const [v] = useState(() => new Animated.Value(on ? FOCUS_SCALE : 1));
  useEffect(() => {
    Animated.timing(v, {
      toValue: on ? FOCUS_SCALE : 1,
      duration: FOCUS_MS,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: NATIVE_DRIVER,
    }).start();
  }, [on, v]);
  return v;
}

/** A player layer (Moments, Do more) arriving: fades in while sliding 24 px from `from`
 *  ("below" rises, "above" drops), 150 ms ease-out. */
export function SlideIn({
  from,
  children,
  style,
  testID,
  dataSet,
}: {
  from: "below" | "above";
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  dataSet?: DataSet;
}) {
  const [v] = useState(() => new Animated.Value(0));
  useEffect(() => {
    Animated.timing(v, {
      toValue: 1,
      duration: FOCUS_MS,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: NATIVE_DRIVER,
    }).start();
  }, [v]);
  const dy = from === "below" ? px(24) : -px(24);
  return (
    <Animated.View
      testID={testID}
      dataSet={dataSet}
      pointerEvents="none"
      style={[
        style,
        {
          opacity: v,
          transform: [
            {
              translateY: v.interpolate({
                inputRange: [0, 1],
                outputRange: [dy, 0],
              }),
            },
          ],
        },
      ]}
    >
      {children}
    </Animated.View>
  );
}

const RING = px(4);
const GAP = px(4);

/** A focusable card: the content clipped to `radius`, a 4 px gap, a 4 px Chalk ring, the
 *  one shadow, and the 1.06 scale. Unfocused it takes the same box (transparent ring), so
 *  focus never moves the layout. */
export function Focusable({
  focused,
  children,
  round = radius.card,
  clip = true,
  lift = true,
  style,
  testID,
  dataSet,
}: {
  focused: boolean;
  children: ReactNode;
  /** The content's corner radius (design px already applied). */
  round?: number;
  /** Clip the content to the rounded corners. Off for content that rounds itself (an
   *  Image with borderRadius, plain text): over playing video a rounded clip is redrawn
   *  with every video frame, and on a Fire TV Stick that alone made most frames janky. */
  clip?: boolean;
  /** The focused card's shadow. Off over playing video: on Fire OS 7 it drew as a pale
   *  rectangle around the ring and was redrawn with every video frame. */
  lift?: boolean;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  dataSet?: DataSet;
}) {
  const scale = useFocusScale(focused);
  return (
    <Animated.View
      testID={testID}
      dataSet={dataSet}
      style={[
        {
          padding: GAP,
          borderRadius: round + RING + GAP,
          ...focusRing(focused),
          transform: [{ scale }],
        },
        focused && lift && styles.shadow,
        style,
      ]}
    >
      <View
        style={{
          borderRadius: round,
          overflow: clip ? "hidden" : "visible",
          backgroundColor: color.bench,
        }}
      >
        {children}
      </View>
    </Animated.View>
  );
}

/** A small focusable pill (filters, menu items): Bench, Chalk fill when focused, Line when
 *  chosen but not focused. The old screens' `Pill`. */
export function Chip({
  label,
  focused,
  active,
  testID,
  dataSet,
  style,
}: {
  label: string;
  focused: boolean;
  active?: boolean;
  testID?: string;
  dataSet?: DataSet;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <View
      testID={testID}
      dataSet={{ focused: focused ? "true" : "false", ...dataSet }}
      style={[
        styles.chip,
        focusRing(focused),
        focused && { backgroundColor: color.chalk },
        !focused && active && { backgroundColor: color.line },
        style,
      ]}
    >
      <T style={[styles.chipText, focused && { color: color.floor }]}>
        {label}
      </T>
    </View>
  );
}

export const Pill = Chip;

/** A hero action ("Play", "Highlights"): a large full-round button that fills Chalk and
 *  scales when focused. `play` adds a play triangle. */
export function PillButton({
  label,
  focused,
  play,
  testID,
  dataSet,
}: {
  label: string;
  focused: boolean;
  play?: boolean;
  testID?: string;
  dataSet?: DataSet;
}) {
  const scale = useFocusScale(focused);
  const ink = focused ? color.floor : color.chalk;
  return (
    <Animated.View
      testID={testID}
      dataSet={{ focused: focused ? "true" : "false", ...dataSet }}
      style={[
        styles.pillButton,
        focused && styles.pillButtonOn,
        { transform: [{ scale }] },
      ]}
    >
      {play ? (
        <View style={[styles.triangle, { borderLeftColor: ink }]} />
      ) : null}
      <T style={[styles.pillButtonText, { color: ink }]}>{label}</T>
    </Animated.View>
  );
}

/** A thin progress ring drawn with Views only (no SVG): a Line track and a Scoreboard arc
 *  made of two clipped half-rings, each a circle with only its top and right borders
 *  coloured (a 180° arc) rotated into place. `frac` 0..1. */
export function ProgressRing({
  size,
  stroke = px(4),
  frac,
  testID,
}: {
  size: number;
  stroke?: number;
  frac: number;
  testID?: string;
}) {
  const deg = Math.max(0, Math.min(1, frac)) * 360;
  const circle = {
    width: size,
    height: size,
    borderRadius: size / 2,
    borderWidth: stroke,
  } as const;
  const arc = (rotate: number) => ({
    ...circle,
    position: "absolute" as const,
    borderColor: "transparent",
    borderTopColor: color.scoreboard,
    borderRightColor: color.scoreboard,
    transform: [{ rotate: `${rotate}deg` }],
  });
  return (
    <View
      testID={testID}
      dataSet={{ progress: frac.toFixed(2) }}
      style={{ width: size, height: size }}
    >
      <View
        style={[circle, { position: "absolute", borderColor: color.line }]}
      />
      {/* right half: 0..min(deg, 180) */}
      <View
        style={{
          position: "absolute",
          left: size / 2,
          width: size / 2,
          height: size,
          overflow: "hidden",
        }}
      >
        {deg > 0 ? (
          <View style={[arc(Math.min(deg, 180) - 135), { left: -size / 2 }]} />
        ) : null}
      </View>
      {/* left half: 180..deg */}
      <View
        style={{
          position: "absolute",
          left: 0,
          width: size / 2,
          height: size,
          overflow: "hidden",
        }}
      >
        {deg > 180 ? <View style={arc(deg - 135)} /> : null}
      </View>
    </View>
  );
}

/** A remote hint: an optional key cap ("Back") then what it does, in Meta. */
export function Hint({
  children,
  k,
  style,
}: {
  children: ReactNode;
  k?: string;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <View style={[styles.hintRow, style]}>
      {k ? (
        <View style={styles.keyCap} testID="hint-key">
          <T style={styles.keyText}>{k}</T>
        </View>
      ) : null}
      <T style={styles.hint}>{children}</T>
    </View>
  );
}

/** Bottom-right key legend: at most 3 entries, key caps plus short words. It replaces
 *  every prose <Hint>. `testID="key-legend"`; each entry `testID="legend-<key>"`. */
export function KeyLegend({
  items,
  style,
}: {
  items: { k: string; label: string }[]; // k: "Back" | "Select" | "◀▶" | "▲" | "▼" | "▲▼" | "◀" | "Menu"
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <View
      testID="key-legend"
      pointerEvents="none"
      style={[
        styles.legend,
        // read at render, not at load: Timeline imports this module
        { bottom: safe.y + TIMELINE_H },
        style,
      ]}
    >
      {items.slice(0, 3).map(({ k, label }) => (
        <View
          key={k}
          testID={`legend-${k}`}
          dataSet={{ label }}
          style={styles.legendItem}
        >
          <View style={styles.keyCap}>
            {/* Barlow sets ◀▶ / ▲▼ touching (one diamond): a thin space apart */}
            <T style={styles.keyText}>
              {/^[◀▶▲▼]+$/.test(k) ? [...k].join(" ") : k}
            </T>
          </View>
          <T style={styles.hint}>{label}</T>
        </View>
      ))}
    </View>
  );
}

/** Top-left context chip and breadcrumb: "Saturday pickup › Replay angles".
 *  `testID="context-chip"`, dataSet {kind}. `dot`: a team-colour dot before the text. */
export function ContextChip({
  parts,
  dot,
  kind = "title",
}: {
  parts: string[]; // joined with " › "; the last part is the brightest
  dot?: string; // colour hex
  kind?: "title" | "follow" | "pick" | "way" | "room";
}) {
  const head = parts.slice(0, -1);
  return (
    <View
      testID="context-chip"
      dataSet={{ kind }}
      pointerEvents="none"
      style={styles.context}
    >
      {dot ? (
        <View
          testID="context-dot"
          style={[styles.contextDot, { backgroundColor: dot }]}
        />
      ) : null}
      <T style={[type.meta, styles.contextText]} numberOfLines={1}>
        {head.length ? (
          <T style={[type.meta, styles.dimText]}>{head.join(" › ") + " › "}</T>
        ) : null}
        {parts[parts.length - 1] ?? ""}
      </T>
    </View>
  );
}

/** ▶ or ❚❚ from Views (Barlow has neither glyph): a `size` px square in `tint`. */
export function PlayGlyph({
  shape,
  size,
  tint = color.chalk,
}: {
  shape: "play" | "pause";
  size: number;
  tint?: string;
}) {
  const bar = {
    width: size * 0.3,
    height: size,
    borderRadius: size * 0.06,
    backgroundColor: tint,
  };
  return (
    <View
      style={{
        width: size,
        height: size,
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingHorizontal: shape === "pause" ? size * 0.1 : 0,
      }}
    >
      {shape === "pause" ? (
        <>
          <View style={bar} />
          <View style={bar} />
        </>
      ) : (
        // a triangle's mass sits left of its box: nudged right to look centred
        <View
          style={{
            width: 0,
            height: 0,
            marginLeft: size * 0.12,
            borderTopWidth: size / 2,
            borderBottomWidth: size / 2,
            borderLeftWidth: size * 0.86,
            borderTopColor: "transparent",
            borderBottomColor: "transparent",
            borderLeftColor: tint,
          }}
        />
      )}
    </View>
  );
}

/** The play state: ❚❚ while playing (what the key does), ▶ and "Paused" while paused, so a
 *  still frame never reads as a frozen app. `testID="playstate"`, dataSet {state}. */
export function PlayState({
  playing,
  style,
}: {
  playing: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <View
      testID="playstate"
      dataSet={{ state: playing ? "playing" : "paused" }}
      pointerEvents="none"
      style={[styles.playState, style]}
    >
      <PlayGlyph shape={playing ? "pause" : "play"} size={px(30)} />
      {playing ? null : <T style={styles.playStateText}>Paused</T>}
    </View>
  );
}

const FLASH_MS = 600;

/** The centred flash when playback toggles (Netflix/YouTube): `flash(playing)` shows the
 *  new state, ▶ or ❚❚, in a translucent circle that grows a little and fades over
 *  FLASH_MS. Render `node` over the video. `testID="play-flash"`, dataSet {state}. */
export function usePlayFlash() {
  const [shown, setShown] = useState<{ playing: boolean; n: number } | null>(
    null,
  );
  useEffect(() => {
    if (!shown) return;
    const t = setTimeout(() => setShown(null), FLASH_MS);
    return () => clearTimeout(t);
  }, [shown]);
  const flash = useCallback(
    (playing: boolean) => setShown((s) => ({ playing, n: (s?.n ?? 0) + 1 })),
    [],
  );
  // keyed: a second press restarts the animation
  const node = shown ? (
    <PlayFlash key={shown.n} playing={shown.playing} />
  ) : null;
  return { flash, node };
}

function PlayFlash({ playing }: { playing: boolean }) {
  const [v] = useState(() => new Animated.Value(0));
  useEffect(() => {
    Animated.timing(v, {
      toValue: 1,
      duration: FLASH_MS,
      easing: Easing.out(Easing.quad),
      useNativeDriver: NATIVE_DRIVER,
    }).start();
  }, [v]);
  return (
    <View style={[StyleSheet.absoluteFill, styles.center]} pointerEvents="none">
      <Animated.View
        testID="play-flash"
        dataSet={{ state: playing ? "playing" : "paused" }}
        style={[
          styles.flash,
          {
            opacity: v.interpolate({
              inputRange: [0, 0.4, 1],
              outputRange: [1, 0.9, 0],
            }),
            transform: [
              {
                scale: v.interpolate({
                  inputRange: [0, 1],
                  outputRange: [0.85, 1.15],
                }),
              },
            ],
          },
        ]}
      >
        <PlayGlyph shape={playing ? "play" : "pause"} size={px(84)} />
      </Animated.View>
    </View>
  );
}

/** A Floor gradient from the edge (opaque) to `length` away (clear), smoothstep, without a
 *  gradient primitive: one band per step, each its own opacity, on whole physical pixels
 *  so bands neither overlap nor leave seams. (Stacking many faint layers instead darkens:
 *  8-bit premultiplied alpha rounds their colour to 0.) */
const FADE_STEPS = 48;
const FADE_OPACITY = Array.from({ length: FADE_STEPS }, (_, k) => {
  const x = (k + 0.5) / FADE_STEPS;
  return 1 - x * x * (3 - 2 * x);
});

export function Fade({
  side,
  length,
  strength = 1,
}: {
  side: "left" | "bottom" | "top";
  length: number;
  /** Opacity at the edge (the player's scrims keep the video showing through). */
  strength?: number;
}) {
  const at = (k: number) =>
    PixelRatio.roundToNearestPixel((length * k) / FADE_STEPS);
  return (
    <>
      {FADE_OPACITY.map((a, k) => {
        const [from, size] = [at(k), at(k + 1) - at(k)];
        return (
          <View
            key={k}
            style={[
              {
                position: "absolute",
                backgroundColor: color.floor,
                opacity: a * strength,
              },
              side === "left"
                ? { left: from, top: 0, bottom: 0, width: size }
                : side === "top"
                  ? { top: from, left: 0, right: 0, height: size }
                  : { bottom: from, left: 0, right: 0, height: size },
            ]}
          />
        );
      })}
    </>
  );
}

const ART_W = px(1344);
const ART_H = px(756);

/** The immersive hero: key art bleeding off the top-right (faded into Floor on its left
 *  and bottom edges), and a text column at the left safe edge: Display title, a meta
 *  line, then `children` (the actions). `textStyle` places the column. */
export function Hero({
  art,
  fallback,
  title,
  meta,
  children,
  textStyle,
  testID,
  dataSet,
}: {
  art?: string | null;
  /** shown when `art` fails to load (the best-moment frame not made yet → the first frame) */
  fallback?: string | null;
  title: string;
  meta?: ReactNode;
  children?: ReactNode;
  textStyle?: StyleProp<ViewStyle>;
  testID?: string;
  dataSet?: DataSet;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const src =
    art && art !== failed
      ? art
      : fallback && fallback !== failed
        ? fallback
        : null;
  // The last art that finished loading stays underneath until the new one has loaded, so
  // moving between cards cross-fades instead of flashing Floor.
  const [under, setUnder] = useState<string | null>(null);
  return (
    <View
      style={StyleSheet.absoluteFill}
      testID={testID}
      dataSet={dataSet}
      pointerEvents="none"
    >
      <View style={styles.art}>
        {src && under && under !== src ? (
          <Image
            key={under}
            source={{ uri: under }}
            style={StyleSheet.absoluteFill}
            resizeMode="cover"
          />
        ) : null}
        {src ? (
          <Image
            key={src}
            source={{ uri: src }}
            style={StyleSheet.absoluteFill}
            resizeMode="cover"
            fadeDuration={FOCUS_MS}
            onLoad={() => setUnder(src)}
            onError={() => setFailed(src)}
          />
        ) : null}
        <Fade side="left" length={px(720)} />
        <Fade side="bottom" length={px(420)} />
      </View>
      <View style={[styles.heroText, textStyle]}>
        <T style={type.display} numberOfLines={2} testID="hero-title">
          {title}
        </T>
        {meta ? (
          <T
            style={[type.body, styles.heroMeta]}
            numberOfLines={1}
            testID="hero-meta"
          >
            {meta}
          </T>
        ) : null}
        {children ? <View style={styles.heroActions}>{children}</View> : null}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------- busy and error states
// One presentation for anything that waits (Netflix/YouTube style): what the person was
// just looking at (a game's hero, its frame), blurred and dimmed, with a spinner in the
// middle; never a blank page with "Loading…". Errors keep the same backdrop with calm
// words and the way out.

/** The blur is done small: the art is decoded at 1/8 of the screen (Fresco downsamples on
 *  `resizeMethod="resize"`), blurred there and scaled up 8x, which smooths it further. A
 *  full-size blur of a 1080p frame takes hundreds of ms on a 32-bit Fire TV. */
const BLUR_DOWN = 8;
const SCREEN_W = px(1920);
const SCREEN_H = px(1080);

/** A full-bleed blurred, dimmed picture of `art`; without art (or while it loads, or if it
 *  fails) a quiet Bench-to-Floor gradient. */
export function Backdrop({
  art,
  dim = 0.5,
}: {
  art?: string | null;
  /** Floor over the blurred art, 0..1 */
  dim?: number;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const src = art && art !== failed ? art : null;
  const w = SCREEN_W / BLUR_DOWN;
  const h = SCREEN_H / BLUR_DOWN;
  return (
    <View
      style={[StyleSheet.absoluteFill, styles.backdrop]}
      pointerEvents="none"
      testID="backdrop"
      dataSet={{ art: src ? "true" : "false" }}
    >
      <Fade side="bottom" length={SCREEN_H} />
      {src ? (
        <View style={[StyleSheet.absoluteFill, styles.center]}>
          <Image
            source={{ uri: src }}
            blurRadius={3}
            resizeMethod="resize"
            resizeMode="cover"
            fadeDuration={FOCUS_MS}
            onError={() => setFailed(src)}
            style={{ width: w, height: h, transform: [{ scale: BLUR_DOWN }] }}
          />
        </View>
      ) : null}
      {src ? (
        <View
          style={[
            StyleSheet.absoluteFill,
            { backgroundColor: color.floor, opacity: dim },
          ]}
        />
      ) : null}
    </View>
  );
}

/** The spinner: the platform's own (a native ProgressBar on Fire TV, animated off the JS
 *  thread), in Chalk. It fades in after `delay` ms, so a quick load never flashes it. */
export function Spinner({
  small,
  delay = 250,
  testID,
}: {
  /** inline, beside text (Settings' check, "Creating the game") */
  small?: boolean;
  delay?: number;
  testID?: string;
}) {
  // Android draws only its two named sizes (a number left a clipped speck on Fire OS):
  // large 36 dp = 72 px at 1080p, small 20 dp = 40 px. The web gets the same pixels.
  const size =
    Platform.OS === "web" ? px(small ? 40 : 72) : small ? "small" : "large";
  // Mounted after the delay, not faded in: a ProgressBar that starts at alpha 0 never drew
  // on Fire OS once the fade (native driver) brought it up.
  const [shown, setShown] = useState(!delay);
  useEffect(() => {
    if (!delay) return;
    const t = setTimeout(() => setShown(true), delay);
    return () => clearTimeout(t);
  }, [delay]);
  const box = typeof size === "number" ? size : px(small ? 40 : 72);
  return (
    <View
      style={{ width: box, height: box, justifyContent: "center" }}
      testID={testID}
    >
      {shown ? <ActivityIndicator size={size} color={color.chalk} /> : null}
    </View>
  );
}

/** Something is loading: the blurred backdrop of `art` with the spinner centred. Fills its
 *  parent (a screen, the player). */
export function Busy({
  art,
  testID = "busy",
  dim,
}: {
  art?: string | null;
  testID?: string;
  dim?: number;
}) {
  return (
    <View
      style={[StyleSheet.absoluteFill, styles.center]}
      testID={testID}
      dataSet={{ state: "loading" }}
      pointerEvents="none"
    >
      <Backdrop art={art} dim={dim} />
      <Spinner />
    </View>
  );
}

/** A screen that is still loading. `art`: what was on screen before (a game's hero). */
export function Loading({ art }: { art?: string | null }) {
  return (
    <View style={styles.fill}>
      <Busy art={art} />
    </View>
  );
}

/** E-22: every screen that fetches renders this instead of a blank screen: the same
 *  backdrop as loading, calm words, and Try again / Settings. A 404 is not a connection
 *  problem: it says the thing is gone (`gone`, else the route's game or profile) and
 *  offers only Back to Home. */
export function ApiErrorBanner({
  error,
  onRetry,
  art,
  gone,
}: {
  error: Error;
  onRetry: () => void;
  art?: string | null;
  gone?: string;
}) {
  // Right reaches Settings: a wrong API address must be fixable from here.
  const [onSettings, setOnSettings] = useState(false);
  const route = useRoute();
  const atHome = route.name === "library";
  const notFound = error instanceof ApiError && error.status === 404;
  useDpad(
    useCallback(
      (a) => {
        if (notFound) {
          if (a === "select" || a === "back") navigate({ name: "library" });
        } else if (a === "left" || a === "right") setOnSettings(a === "right");
        else if (a === "select") {
          if (onSettings) navigate({ name: "settings" });
          else onRetry();
        } else if (a === "back") {
          if (atHome) return false; // unhandled: the app exits, as from the library
          navigate({ name: "library" });
        }
      },
      [onRetry, onSettings, atHome, notFound],
    ),
  );
  if (notFound) {
    const what =
      gone ??
      (route.name === "profile"
        ? "This profile"
        : "gameId" in route && route.gameId
          ? "This game"
          : "This");
    return (
      <View
        style={[styles.fill, styles.center]}
        testID="api-error"
        dataSet={{ kind: "not-found" }}
      >
        <Backdrop art={art} dim={0.7} />
        <View style={styles.message}>
          <T style={[type.title, styles.centerText]} testID="api-error-title">
            {`${what} isn't here any more`}
          </T>
          <T style={[type.body, styles.calm]}>
            It may have been deleted. Your other games are on Home.
          </T>
          <View style={styles.actions}>
            <Pill label="Back to Home" focused testID="api-error-home" />
          </View>
        </View>
      </View>
    );
  }
  return (
    <View style={[styles.fill, styles.center]} testID="api-error">
      <Backdrop art={art} dim={0.7} />
      <View style={styles.message}>
        <T style={[type.title, styles.centerText]} testID="api-error-title">
          Replay can't connect
        </T>
        <T style={[type.body, styles.calm]}>
          Check the TV's internet, or the server address in Settings.
        </T>
        <T
          style={[type.meta, styles.calm, styles.detail]}
          numberOfLines={2}
          testID="api-error-detail"
        >
          {error.message}
        </T>
        <View style={styles.actions}>
          <Pill
            label="Try again"
            focused={!onSettings}
            testID="api-error-retry"
          />
          <Pill
            label="Settings"
            focused={onSettings}
            testID="api-error-settings"
          />
        </View>
      </View>
    </View>
  );
}

export const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: color.floor },
  center: { alignItems: "center", justifyContent: "center" },
  backdrop: { backgroundColor: color.bench, overflow: "hidden" },
  message: { alignItems: "center", maxWidth: px(1100) },
  centerText: { textAlign: "center" },
  calm: { color: color.bleacher, textAlign: "center", marginTop: sp(2) },
  detail: { marginTop: sp(1) },
  actions: { flexDirection: "row", marginTop: sp(5), marginLeft: sp(2) },
  /** The old screens' frame (Wave 2/3 move them onto `safe`). */
  screen: { flex: 1, backgroundColor: color.floor, padding: px(64) },
  /** A redesigned screen: Floor, content inside the 96/54 safe zone. */
  safe: {
    flex: 1,
    backgroundColor: color.floor,
    paddingHorizontal: safe.x,
    paddingVertical: safe.y,
  },
  text: { color: color.chalk, fontSize: font.body },
  h1: {
    color: color.chalk,
    fontSize: font.title,
    fontWeight: "600",
    marginBottom: sp(3),
  },
  h2: {
    color: color.chalk,
    fontSize: font.h2,
    fontWeight: "600",
    marginBottom: sp(1.5),
  },
  title: { color: color.chalk, marginBottom: sp(2) },
  hint: { color: color.bleacher, fontSize: font.meta, lineHeight: px(34) },
  hintRow: { flexDirection: "row", alignItems: "center", marginTop: sp(3) },
  legend: {
    position: "absolute",
    right: safe.x,
    flexDirection: "row",
    alignItems: "center",
  },
  legendItem: { flexDirection: "row", alignItems: "center", marginLeft: sp(3) },
  context: {
    position: "absolute",
    left: safe.x,
    top: safe.y,
    maxWidth: px(1100),
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: sp(2),
    borderRadius: radius.chip,
    backgroundColor: "rgba(29, 40, 52, 0.88)",
  },
  contextDot: {
    width: px(16),
    height: px(16),
    borderRadius: px(8),
    marginRight: sp(1.5),
  },
  contextText: { color: color.chalk, flexShrink: 1 },
  playState: { flexDirection: "row", alignItems: "center" },
  playStateText: {
    ...type.body,
    color: color.chalk,
    fontFamily: face.semibold,
    marginLeft: sp(1.5),
  },
  flash: {
    width: px(200),
    height: px(200),
    borderRadius: px(100),
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(18, 26, 35, 0.6)",
  },
  dimText: { color: color.bleacher },
  keyCap: {
    borderWidth: px(2),
    borderColor: color.bleacher,
    borderRadius: px(8),
    paddingHorizontal: sp(1.5),
    marginRight: sp(1.5),
  },
  keyText: {
    color: color.bleacher,
    fontSize: font.meta,
    lineHeight: px(34),
    fontWeight: "600",
  },
  chip: {
    paddingHorizontal: sp(3),
    paddingVertical: px(6),
    borderRadius: radius.chip,
    backgroundColor: color.bench,
    marginRight: sp(2),
    marginBottom: sp(1.5),
  },
  chipText: {
    color: color.chalk,
    fontSize: font.body,
    lineHeight: px(36),
    fontWeight: "600",
  },
  pillButton: {
    flexDirection: "row",
    alignItems: "center",
    height: px(72),
    paddingHorizontal: sp(4),
    borderRadius: radius.chip,
    backgroundColor: "rgba(29, 40, 52, 0.88)", // Bench, a little of the art through it
    marginRight: sp(2),
  },
  pillButtonOn: { backgroundColor: color.chalk },
  pillButtonText: {
    fontSize: font.body,
    lineHeight: px(40),
    fontWeight: "600",
  },
  triangle: {
    width: 0,
    height: 0,
    borderTopWidth: px(12),
    borderBottomWidth: px(12),
    borderLeftWidth: px(20),
    borderTopColor: "transparent",
    borderBottomColor: "transparent",
    marginRight: sp(1.5),
  },
  shadow: { boxShadow: "0px 16px 40px rgba(0, 0, 0, 0.55)" },
  art: {
    position: "absolute",
    top: 0,
    right: 0,
    width: ART_W,
    height: ART_H,
    backgroundColor: color.floor,
  },
  heroText: { position: "absolute", left: safe.x, width: px(1100) },
  heroMeta: { color: color.bleacher, marginTop: sp(1) },
  heroActions: { flexDirection: "row", marginTop: sp(4) },
});
