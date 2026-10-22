// The player's Moments layer (Down; docs/ux/redesign.md "Player"): a row of moment cards
// above the court line, cued to the moment nearest the playhead, with filter chips above
// (All N, Scores, each player, Your bookmarks). Left/Right walk (the line marks the focused
// card's time), Select jumps there and closes, Up goes to the chips and from the chips
// closes the layer, Back closes. Owns the remote while it is open (input stack).
import { useCallback, useEffect, useMemo, useState } from "react";
import { Image, StyleSheet, View } from "react-native";
import { fmtDuration } from "../../../../packages/tv-core/src/display";
import type { Moment } from "../../../../packages/tv-core/src/types";
import { useDpad, type DpadAction } from "../input";
import { nearestIndex } from "../playback/seek";
import { color, px, radius, safe, sp, type } from "../theme";
import { Chip, Focusable, SlideIn, T } from "../ui";
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
  const out: Filter[] = [
    { id: "all", label: `All ${moments.length}`, match: () => true },
  ];
  if (moments.some((m) => m.kind === "score"))
    out.push({
      id: "score",
      label: "Scores",
      match: (m) => m.kind === "score",
    });
  const seen = new Set<string>();
  for (const m of moments) {
    const p = m.player;
    if (!p || seen.has(p.id)) continue;
    seen.add(p.id);
    out.push({
      id: `p:${p.id}`,
      // An untagged player: "#23" when the jersey was read, else "Player 2" (track p2),
      // the name the commentary uses.
      label:
        p.name ??
        (p.number != null
          ? `#${p.number}`
          : `Player ${p.id.replace(/^p/, "")}`),
      match: (x) => x.player?.id === p.id,
    });
  }
  if (moments.some((m) => m.kind === "bookmark"))
    out.push({
      id: "bookmark",
      label: "Your bookmarks",
      match: (m) => m.kind === "bookmark",
    });
  return out;
}

export function MomentsLayer({
  moments,
  t,
  empty,
  onCue,
  onJump,
  onClose,
  onPlayPause,
}: {
  moments: Moment[];
  /** The playhead when the layer opened: the row starts on the nearest moment. */
  t: number;
  /** What to say when there are none ("No moments in this game", "Getting ready…"). */
  empty: string;
  onCue: (m: Moment | null) => void;
  onJump: (m: Moment) => void;
  onClose: () => void;
  onPlayPause: () => void;
}) {
  const filters = useMemo(() => filtersOf(moments), [moments]);
  const [fi, setFi] = useState(0); // the applied filter
  const [ci, setCi] = useState(0); // the focused chip
  const [zone, setZone] = useState<"cards" | "chips">("cards");
  const filter = filters[Math.min(fi, filters.length - 1)];
  const list = useMemo(() => moments.filter(filter.match), [moments, filter]);
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
        else if (a === "right")
          setCi((c) => Math.min(filters.length - 1, c + 1));
        else if (a === "up") onClose();
        else if (a === "down") setZone("cards");
        else if (a === "select") {
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
        if (!moments.length) return onClose(); // no chips to climb to
        setCi(Math.min(fi, filters.length - 1));
        setZone("chips");
      } else if (a === "select" && cur) onJump(cur);
    },
    [
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

  return (
    <SlideIn
      from="below"
      style={styles.layer}
      testID="moments-layer"
      dataSet={{ zone }}
    >
      <View style={styles.chips}>
        {(moments.length ? filters : []).map((f, k) => (
          <Chip
            key={f.id}
            label={f.label}
            focused={zone === "chips" && k === ci}
            active={f === filter}
            testID="moment-filter"
            dataSet={{ filter: f.id, active: f === filter ? "true" : "false" }}
          />
        ))}
      </View>
      {list.length === 0 ? (
        <T style={[type.body, styles.empty]} testID="moments-empty">
          {empty}
        </T>
      ) : (
        <View
          style={[
            styles.row,
            {
              transform: [
                { translateX: -Math.max(0, i - (SHOWN - 1)) * PITCH },
              ],
            },
          ]}
        >
          {list.map((m, k) => {
            const on = zone === "cards" && k === i;
            return (
              <View key={m.id} style={styles.slot}>
                <Focusable
                  focused={on}
                  testID="moment-card"
                  dataSet={{
                    momentId: m.id,
                    kind: m.kind,
                    t: m.t,
                    focused: on ? "true" : "false",
                  }}
                >
                  <View style={styles.thumb}>
                    {m.thumb_url ? (
                      <Image
                        source={{ uri: m.thumb_url }}
                        style={StyleSheet.absoluteFill}
                        resizeMode="cover"
                      />
                    ) : null}
                    <View style={styles.time}>
                      <T style={styles.timeText}>{fmtDuration(m.t)}</T>
                    </View>
                  </View>
                </Focusable>
                <T
                  style={[
                    type.meta,
                    styles.label,
                    on && { color: color.chalk },
                  ]}
                  numberOfLines={1}
                >
                  {m.label}
                </T>
              </View>
            );
          })}
        </View>
      )}
    </SlideIn>
  );
}

const styles = StyleSheet.create({
  layer: {
    position: "absolute",
    left: safe.x,
    right: 0,
    bottom: safe.y + TIMELINE_H + sp(4),
  },
  chips: { flexDirection: "row", marginLeft: px(8), marginBottom: sp(1) },
  row: { flexDirection: "row" },
  slot: { width: CARD_W + px(16), marginRight: sp(3) },
  thumb: { width: CARD_W, height: THUMB_H, backgroundColor: color.bench },
  time: {
    position: "absolute",
    left: sp(1),
    bottom: sp(1),
    paddingHorizontal: sp(1.5),
    borderRadius: radius.chip,
    backgroundColor: "rgba(18, 26, 35, 0.84)",
  },
  timeText: { ...type.figures, fontSize: px(26), lineHeight: px(34) },
  label: { color: color.bleacher, marginTop: sp(1), marginLeft: px(8) },
  empty: { color: color.bleacher, marginLeft: px(8), marginTop: sp(2) },
});
