// The player's Moments layer (Down; docs/ux/redesign.md "Player"): a row of moment cards
// above the court line, cued to the moment nearest the playhead. Above the cards one short
// row: the title ("Moments", or "Moments · Player 3" for one player's), the filters (All N,
// Scores, Bookmarks; one player's moments come from their Player card) and the
// "+ Bookmark m:ss" action. Left/Right walk (the line marks the focused card's time),
// Select jumps there and closes, Up goes to the filter row and from there closes the
// layer, Down opens the replay angles of a moment's play (the focused card says
// "▼ Replay angles" when it has them), Back closes. Owns the remote while it is open.
import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { Image, StyleSheet, View } from "react-native";
import { fmtDuration } from "../../../../packages/tv-core/src/display";
import type { Moment } from "../../../../packages/tv-core/src/types";
import { useDpad, type DpadAction } from "../input";
import { nearestIndex } from "../playback/seek";
import { color, px, radius, safe, sp, type } from "../theme";
import { Chip, Focusable, KeyLegend, SlideIn, Spinner, T } from "../ui";
import { TIMELINE_H } from "./Timeline";

const CARD_W = px(336);
const THUMB_H = px(189);
const PITCH = CARD_W + px(16) + sp(3);
const SHOWN = 4;

interface Filter {
  id: string;
  label: string;
  match: (m: Moment) => boolean;
}

function filtersOf(moments: Moment[]): Filter[] {
  if (!moments.length) return [];
  const out: Filter[] = [
    { id: "all", label: `All ${moments.length}`, match: () => true },
  ];
  if (moments.some((m) => m.kind === "score"))
    out.push({
      id: "score",
      label: "Scores",
      match: (m) => m.kind === "score",
    });
  if (moments.some((m) => m.kind === "bookmark"))
    out.push({
      id: "bookmark",
      label: "Bookmarks",
      match: (m) => m.kind === "bookmark",
    });
  return out;
}

export function MomentsLayer({
  moments,
  t,
  empty,
  loading,
  onCue,
  onJump,
  onClose,
  onPlayPause,
  hasAngles,
  onAngles,
  onBookmark,
  title,
}: {
  moments: Moment[];
  /** The playhead when the layer opened: the row starts on the nearest moment. */
  t: number;
  /** What to say when there are none ("No moments in this game", "Getting ready…"). */
  empty: string;
  /** The moments are still being read: a spinner instead of `empty`. */
  loading?: boolean;
  onCue: (m: Moment | null) => void;
  onJump: (m: Moment) => void;
  onClose: () => void;
  onPlayPause: () => void;
  /** Whether a moment falls in a play with replay angles; Down opens them (`onAngles`). */
  hasAngles?: (m: Moment) => boolean;
  onAngles?: (m: Moment) => void;
  /** bookmark the playhead: the "+ Bookmark m:ss" chip at the end of the filter row (it
   *  runs this, then closes the layer) */
  onBookmark?: () => void;
  /** the row's title, "Moments · Player 3" when the moments are one player's */
  title?: string;
}) {
  const filters = useMemo(() => filtersOf(moments), [moments]);
  // the filter row's chips: the filters, then the bookmark action (index filters.length)
  const canMark = !!onBookmark;
  const nChips = filters.length + (canMark ? 1 : 0);
  const [fi, setFi] = useState(0); // the applied filter
  const [ci, setCi] = useState(0); // the focused chip
  const [zone, setZone] = useState<"cards" | "chips">("cards");
  const filter = filters[Math.min(fi, filters.length - 1)] as
    Filter | undefined;
  const list = useMemo(
    () => (filter ? moments.filter(filter.match) : moments),
    [moments, filter],
  );
  const [mi, setMi] = useState(() => Math.max(0, nearestIndex(moments, t)));
  const i = Math.min(mi, Math.max(0, list.length - 1));
  const cur = list[i] ?? null;

  useEffect(() => onCue(zone === "cards" ? cur : null), [cur, zone, onCue]);
  useEffect(() => () => onCue(null), [onCue]);

  // Steps update from the pending index, not this render's: on a Fire TV a held arrow can
  // repeat faster than the row re-renders, and every key must still move one card.
  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") onClose();
      else if (a === "playpause") onPlayPause();
      else if (zone === "chips") {
        if (a === "left") setCi((c) => Math.max(0, c - 1));
        else if (a === "right") setCi((c) => Math.min(nChips - 1, c + 1));
        else if (a === "up") onClose();
        else if (a === "down") setZone("cards");
        else if (a === "select" && ci >= filters.length) {
          onBookmark?.();
          onClose();
        } else if (a === "select") {
          // Keep the cue on the same time: the nearest moment of the new filter.
          const next = moments.filter(filters[ci].match);
          setFi(ci);
          setMi(Math.max(0, nearestIndex(next, cur?.t ?? t)));
          setZone("cards");
        }
      } else if (a === "left")
        setMi((m) => Math.max(0, Math.min(m, list.length - 1) - 1));
      else if (a === "right") setMi((m) => Math.min(list.length - 1, m + 1));
      else if (a === "up") {
        if (!nChips) return onClose(); // no chips to climb to
        setCi(Math.min(fi, nChips - 1));
        setZone("chips");
      } else if (a === "select" && cur) onJump(cur);
      else if (a === "down" && cur && hasAngles?.(cur)) onAngles?.(cur);
    },
    [
      hasAngles,
      onAngles,
      onBookmark,
      nChips,
      zone,
      ci,
      filters,
      moments,
      cur,
      t,
      list,
      fi,
      onClose,
      onJump,
      onPlayPause,
    ],
  );
  useDpad(onAction);

  // The player re-renders this layer with every clock tick (30 a second while the game
  // plays), so the chips and the row are memoised on what they draw, and the row mounts
  // only the cards around the visible ones (absolutely placed at their slot, so nothing
  // shifts): on a Fire TV Stick every card of a long game re-rendering under the video
  // was 84 % janky frames.
  // The row holds at most four chips (All, Scores, Bookmarks, the bookmark action) beside
  // the title: all of them fit on screen, nothing slides.
  const mark = fmtDuration(t);
  const chipRow = useMemo(
    () => (
      <View style={styles.chips} testID="moment-filters">
        <T style={[type.title, styles.title]} testID="moments-title">
          {title ?? "Moments"}
        </T>
        {filters.map((f, k) => (
          <Chip
            key={f.id}
            label={f.label}
            focused={zone === "chips" && k === ci}
            active={f === filter}
            testID="moment-filter"
            dataSet={{
              filter: f.id,
              active: f === filter ? "true" : "false",
            }}
          />
        ))}
        {canMark ? (
          <Chip
            // ASCII "+": Barlow has no fullwidth "＋" (it drew a missing-glyph box)
            label={`+ Bookmark ${mark}`}
            focused={zone === "chips" && ci === filters.length}
            testID="moment-bookmark"
          />
        ) : null}
      </View>
    ),
    // canMark, not onBookmark: the player passes a new function every tick
    [title, filters, zone, ci, filter, canMark, mark],
  );
  const first = Math.max(0, i - (SHOWN - 1));
  const cardRow = useMemo(() => {
    const lo = Math.max(0, first - 1);
    const hi = Math.min(list.length, first + SHOWN + 2);
    return (
      <View
        style={[styles.row, { transform: [{ translateX: -first * PITCH }] }]}
      >
        {list.slice(lo, hi).map((m, n) => (
          <MomentCard
            key={m.id}
            m={m}
            at={(lo + n) * PITCH}
            on={zone === "cards" && lo + n === i}
            angles={!!hasAngles?.(m)}
          />
        ))}
      </View>
    );
  }, [list, first, i, zone, hasAngles]);

  const legend =
    zone === "chips"
      ? [
          { k: "Select", label: "Choose" },
          { k: "Back", label: "Close" },
        ]
      : [
          ...(cur ? [{ k: "Select", label: "Play" }] : []),
          ...(cur && hasAngles?.(cur) ? [{ k: "▼", label: "Angles" }] : []),
          { k: "Back", label: "Close" },
        ];
  return (
    <>
      <SlideIn
        from="below"
        style={styles.layer}
        testID="moments-layer"
        dataSet={{ zone }}
      >
        {chipRow}
        {list.length === 0 ? (
          loading ? (
            <View style={styles.spin}>
              <Spinner testID="moments-loading" />
            </View>
          ) : (
            <T style={[type.body, styles.empty]} testID="moments-empty">
              {empty}
            </T>
          )
        ) : (
          cardRow
        )}
      </SlideIn>
      <KeyLegend items={legend} />
    </>
  );
}

const MomentCard = memo(function MomentCard({
  m,
  at,
  on,
  angles,
}: {
  m: Moment;
  at: number;
  on: boolean;
  /** the moment's play has replay angles (Down opens them) */
  angles: boolean;
}) {
  return (
    <View style={[styles.slot, { left: at }]}>
      <Focusable
        focused={on}
        clip={false}
        lift={false}
        testID="moment-card"
        dataSet={{
          momentId: m.id,
          kind: m.kind,
          t: m.t,
          focused: on ? "true" : "false",
          angles: angles ? "true" : "false",
        }}
      >
        <View style={styles.thumb}>
          {m.thumb_url ? (
            <Image
              source={{ uri: m.thumb_url }}
              // rounds itself (the card does not clip over video): square corners
              // poked out of the rounded focus ring
              style={[StyleSheet.absoluteFill, styles.round]}
              resizeMode="cover"
              resizeMethod="resize"
            />
          ) : null}
          <View style={styles.time} testID="moment-time">
            <T style={styles.timeText}>{fmtDuration(m.t)}</T>
          </View>
          {angles && on ? (
            <View style={styles.angles} testID="moment-angles">
              <T style={styles.anglesText}>▼ Replay angles</T>
            </View>
          ) : null}
        </View>
      </Focusable>
      <T
        style={[type.meta, styles.label, on && { color: color.chalk }]}
        numberOfLines={1}
      >
        {m.label}
      </T>
    </View>
  );
});

const styles = StyleSheet.create({
  layer: {
    position: "absolute",
    left: safe.x,
    right: 0,
    // the key legend's line between the card labels and the timeline
    bottom: safe.y + TIMELINE_H + sp(6),
  },
  chips: {
    flexDirection: "row",
    alignItems: "center",
    marginLeft: px(8),
    marginBottom: sp(1),
  },
  title: { marginBottom: 0, marginRight: sp(4) },
  // the card (ring box included) plus its label line
  row: { height: THUMB_H + px(16) + sp(1) + px(34) },
  slot: { position: "absolute", top: 0, width: CARD_W + px(16) },
  spin: { height: THUMB_H, justifyContent: "center", marginLeft: sp(4) },
  thumb: {
    width: CARD_W,
    height: THUMB_H,
    borderRadius: radius.card,
    backgroundColor: color.bench,
  },
  round: { borderRadius: radius.card },
  time: {
    position: "absolute",
    left: sp(1),
    bottom: sp(1),
    paddingHorizontal: sp(1.5),
    borderRadius: radius.chip,
    backgroundColor: "rgba(18, 26, 35, 0.84)",
  },
  timeText: { ...type.figures, fontSize: px(26), lineHeight: px(34) },
  angles: {
    position: "absolute",
    right: sp(1),
    bottom: sp(1),
    paddingHorizontal: sp(1.5),
    borderRadius: radius.chip,
    backgroundColor: color.scoreboard,
  },
  anglesText: { ...type.meta, color: color.floor },
  // rides the video under the scrim: on a bright floor (a real gym's, lit) Bleacher alone
  // washed out, so the same soft shadow as the seek readout
  label: {
    color: color.bleacher,
    marginTop: sp(1),
    marginLeft: px(8),
    textShadowColor: "rgba(0,0,0,0.6)",
    textShadowOffset: { width: 0, height: px(2) },
    textShadowRadius: px(8),
  },
  empty: { color: color.bleacher, marginLeft: px(8), marginTop: sp(2) },
});
