// The Highlights list (Home's "Highlights"): the same plays the Highlights reel plays, in
// game order, as a row of big cards over the paused game. The first card plays them all
// back to back (the reel, ending on the best play); any other card plays that one play.
// The best play's card carries "★ Best play". Left/Right walk, Select plays, Back leaves
// (Watch sends it Home). Owns the remote while it is open.
import { useCallback, useState, type ReactNode } from "react";
import { Image, StyleSheet, View } from "react-native";
import { fmtDuration } from "../../../../packages/tv-core/src/display";
import type { Storyboard } from "../../../../packages/tv-core/src/types";
import { useDpad, type DpadAction } from "../input";
import { color, px, radius, safe, sp, type } from "../theme";
import {
  ContextChip,
  Focusable,
  KeyLegend,
  PlayGlyph,
  Spinner,
  T,
} from "../ui";
import { SpriteFrame } from "./Timeline";

export interface HighlightItem {
  t_start: number;
  t_end: number;
  /** when the play happens (its moment's time) */
  t: number;
  label: string;
  thumb: string | null;
  best: boolean;
}

const CARD_W = px(420);
const THUMB_H = px(236);
const PITCH = CARD_W + px(16) + sp(3);
const SHOWN = 3;

export function HighlightsLayer({
  title,
  items,
  loading,
  storyboard,
  start = 0,
  onPick,
  onClose,
}: {
  /** the game's title, for the breadcrumb */
  title: string;
  /** in game order */
  items: HighlightItem[];
  loading: boolean;
  storyboard: Storyboard | null;
  /** the card focused on open (the one played last, coming back to the list) */
  start?: number;
  /** card `i` chosen: 0 is "Play all", then items[i - 1] */
  onPick: (i: number) => void;
  onClose: () => void;
}) {
  const n = items.length ? items.length + 1 : 0;
  const [ci, setCi] = useState(start);
  const i = Math.min(ci, Math.max(0, n - 1));

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") onClose();
      else if (a === "left") setCi((c) => Math.max(0, c - 1));
      else if (a === "right") setCi((c) => Math.min(n - 1, c + 1));
      else if ((a === "select" || a === "playpause") && n) onPick(i);
    },
    [n, i, onPick, onClose],
  );
  useDpad(onAction);

  const total = items.reduce((s, x) => s + (x.t_end - x.t_start), 0);
  const first = Math.max(0, i - (SHOWN - 1));
  return (
    <View
      style={styles.layer}
      testID="highlights-layer"
      dataSet={{ count: items.length, focused: i }}
    >
      <ContextChip kind="room" parts={[title, "Highlights"]} />
      <View style={styles.body}>
        <T style={[type.title, styles.heading]} testID="highlights-title">
          {items.length
            ? `Highlights · ${items.length} play${items.length === 1 ? "" : "s"}`
            : "Highlights"}
        </T>
        {!n ? (
          loading ? (
            <View style={styles.spin}>
              <Spinner testID="highlights-loading" />
            </View>
          ) : (
            <T style={[type.body, styles.empty]} testID="highlights-empty">
              No highlights for this game yet
            </T>
          )
        ) : (
          <View
            style={[
              styles.row,
              { transform: [{ translateX: -first * PITCH }] },
            ]}
          >
            <Card
              at={0}
              on={i === 0}
              label="Play all"
              time={fmtDuration(total)}
            >
              <View style={styles.all} testID="highlights-play-all">
                <PlayGlyph shape="play" size={px(72)} />
              </View>
            </Card>
            {items.map((x, k) => (
              <Card
                key={`${x.t_start}`}
                at={(k + 1) * PITCH}
                on={i === k + 1}
                label={x.label}
                time={fmtDuration(x.t)}
                data={{ t: x.t, best: x.best ? "true" : "false" }}
              >
                {x.thumb ? (
                  <Image
                    source={{ uri: x.thumb }}
                    style={StyleSheet.absoluteFill}
                    resizeMode="cover"
                    resizeMethod="resize"
                  />
                ) : storyboard ? (
                  <SpriteFrame storyboard={storyboard} t={x.t} width={CARD_W} />
                ) : null}
                {x.best ? (
                  <View style={styles.best} testID="highlight-best">
                    <T style={styles.bestText}>★ Best play</T>
                  </View>
                ) : null}
              </Card>
            ))}
          </View>
        )}
      </View>
      <KeyLegend
        items={[
          { k: "◀▶", label: "Browse" },
          ...(n ? [{ k: "Select", label: "Play" }] : []),
          { k: "Back", label: "Home" },
        ]}
        style={styles.legend}
      />
    </View>
  );
}

function Card({
  at,
  on,
  label,
  time,
  data,
  children,
}: {
  at: number;
  on: boolean;
  label: string;
  time: string;
  data?: Record<string, string | number>;
  children: ReactNode;
}) {
  return (
    <View style={[styles.slot, { left: at }]}>
      {/* the video under the list is paused, so the card may clip its picture */}
      <Focusable
        focused={on}
        testID="highlight-card"
        dataSet={{ focused: on ? "true" : "false", ...data }}
      >
        <View style={styles.thumb}>
          {children}
          <View style={styles.time}>
            <T style={styles.timeText}>{time}</T>
          </View>
        </View>
      </Focusable>
      <T
        style={[type.body, styles.label, on && { color: color.chalk }]}
        numberOfLines={1}
        testID="highlight-label"
      >
        {label}
      </T>
    </View>
  );
}

const styles = StyleSheet.create({
  layer: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    backgroundColor: "rgba(18, 26, 35, 0.92)",
  },
  body: {
    position: "absolute",
    left: safe.x,
    right: 0,
    top: px(300),
  },
  heading: { marginLeft: px(8), marginBottom: sp(3) },
  row: { height: THUMB_H + px(16) + sp(1) + px(40) },
  slot: { position: "absolute", top: 0, width: CARD_W + px(16) },
  spin: { height: THUMB_H, justifyContent: "center", marginLeft: sp(4) },
  empty: { color: color.bleacher, marginLeft: px(8) },
  thumb: {
    width: CARD_W,
    height: THUMB_H,
    overflow: "hidden",
    backgroundColor: color.bench,
  },
  all: { flex: 1, alignItems: "center", justifyContent: "center" },
  time: {
    position: "absolute",
    left: sp(1),
    bottom: sp(1),
    paddingHorizontal: sp(1.5),
    borderRadius: radius.chip,
    backgroundColor: "rgba(18, 26, 35, 0.84)",
  },
  timeText: { ...type.figures, fontSize: px(26), lineHeight: px(34) },
  best: {
    position: "absolute",
    left: sp(1),
    top: sp(1),
    paddingHorizontal: sp(1.5),
    borderRadius: radius.chip,
    backgroundColor: color.scoreboard,
  },
  bestText: { ...type.meta, color: color.floor },
  label: { color: color.bleacher, marginTop: sp(1), marginLeft: px(8) },
  legend: { bottom: safe.y },
});
