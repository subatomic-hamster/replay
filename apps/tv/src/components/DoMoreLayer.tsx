// The player's Do more layer (Up / Menu; UI pass §4.3): one row of at most 6 large
// actions over a soft scrim, all on screen at once (Follow a player, Replay angles,
// Highlights, Stats, Commentary, On your phone; following, the player's card and "Follow
// someone else" lead). A tile whose feature is still processing says "Getting ready, about
// N min" and cannot be chosen. A tile with `children` (Highlights' ways) opens its own row
// in place, the current child marked; Back or Down returns to the main row, and from there
// closes the layer. Menu closes it from either row.
import { useCallback, useState } from "react";
import { StyleSheet, View } from "react-native";
import { useDpad, type DpadAction } from "../input";
import { color, face, px, radius, safe, sp, type } from "../theme";
import { Fade, Focusable, KeyLegend, SlideIn, T } from "../ui";

export interface Tile {
  /** testID; the old menu's ids where the concept survives (nav-review, menu-watch…) */
  id: string;
  label: string;
  sub?: string;
  /** a team-colour dot before the label (the followed player's card) */
  dot?: string;
  /** still processing: shown, focusable, not selectable */
  pending?: boolean;
  /** a toggle's state, or the current choice in a sub-row (marked) */
  on?: boolean;
  run?: () => void;
  children?: Tile[];
}

const RING_BOX = px(8); // Focusable's ring + gap, each side
const GAP = sp(3);
/** 6 tiles fit the 1728 px safe width: 6 × (248 + 16 + 24) − 24 = 1704. Tall enough for
 *  a two-line label over a one-line sub, or the reverse. */
const TILE = { w: px(248), h: px(184) };
/** The row's clip: the safe zone, plus room for the focused tile's ring and 1.06 scale. */
const SCALE_ROOM = px(12);
const CLIP_W = px(1920) - 2 * safe.x + 2 * SCALE_ROOM;
const PITCH = TILE.w + 2 * RING_BOX + GAP;
/** Whole tiles that fit in the safe zone (a longer row scrolls with focus). */
const SHOWN = Math.max(1, Math.floor((px(1920) - 2 * safe.x + GAP) / PITCH));

export function DoMoreLayer({
  tiles,
  onClose,
  onPlayPause,
}: {
  tiles: Tile[];
  onClose: () => void;
  onPlayPause: () => void;
}) {
  // Focus is kept by tile id per row, so a tile that appears or goes (a toggle, a feature
  // finishing) never moves focus onto its neighbour.
  const [openId, setOpenId] = useState<string | null>(null);
  const [at, setAt] = useState<Record<string, string>>({});
  const open = tiles.find((t) => t.id === openId && t.children) ?? null;
  const row = open?.children ?? tiles;
  const rowKey = open?.id ?? "main";
  const k = Math.max(
    0,
    row.findIndex((t) => t.id === at[rowKey]),
  );

  const onAction = useCallback(
    (a: DpadAction) => {
      const focus = (n: number) =>
        row[n] && setAt({ ...at, [rowKey]: row[n].id });
      if (a === "menu") onClose();
      else if (a === "back" || a === "down") {
        if (open) setOpenId(null);
        else onClose();
      } else if (a === "playpause") onPlayPause();
      else if (a === "left") focus(Math.max(0, k - 1));
      else if (a === "right") focus(Math.min(row.length - 1, k + 1));
      else if (a === "select") {
        const t = row[k];
        if (!t || t.pending) return;
        if (t.children?.length) {
          const cur = t.children.find((c) => c.on) ?? t.children[0];
          setAt({ ...at, [t.id]: cur.id });
          setOpenId(t.id);
        } else t.run?.();
      }
    },
    [open, k, row, rowKey, at, onClose, onPlayPause],
  );
  useDpad(onAction);

  const shift = Math.max(0, k - (SHOWN - 1)) * PITCH;
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <Fade side="top" length={px(520)} strength={0.85} />
      <SlideIn
        from="above"
        style={styles.layer}
        testID="domore"
        dataSet={{ row: open ? open.id : "main" }}
      >
        <T style={[type.meta, styles.crumb]} testID="domore-crumb">
          {open ? `Do more › ${open.label}` : "Do more"}
        </T>
        <View style={styles.clip} testID="domore-clip">
          <View style={[styles.row, { transform: [{ translateX: -shift }] }]}>
            {row.map((t, n) => {
              const on = n === k;
              return (
                <View key={t.id} style={{ marginRight: GAP }}>
                  <Focusable
                    focused={on}
                    round={radius.card}
                    clip={false} // text needs no clip (cheaper over the video)
                    lift={false}
                    testID={t.id}
                    dataSet={{
                      focused: on ? "true" : "false",
                      pending: t.pending ? "true" : "false",
                      children: t.children?.length ?? 0,
                      ...(t.on === undefined
                        ? {}
                        : { on: t.on ? "true" : "false" }),
                    }}
                  >
                    <View
                      style={[
                        styles.tile,
                        t.on && !on && styles.current,
                        t.pending && { opacity: 0.55 },
                      ]}
                    >
                      <View style={styles.head}>
                        {t.dot ? (
                          <View
                            style={[styles.dot, { backgroundColor: t.dot }]}
                          />
                        ) : null}
                        <T
                          style={[type.body, styles.semi, styles.label]}
                          numberOfLines={2}
                        >
                          {t.label}
                        </T>
                      </View>
                      {t.sub ? (
                        <T style={[type.meta, styles.sub]} numberOfLines={2}>
                          {t.sub}
                        </T>
                      ) : null}
                    </View>
                  </Focusable>
                </View>
              );
            })}
          </View>
        </View>
      </SlideIn>
      <KeyLegend
        items={[
          { k: "Select", label: "Choose" },
          { k: "Back", label: open ? "Do more" : "Close" },
        ]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  layer: {
    position: "absolute",
    left: safe.x - SCALE_ROOM,
    top: safe.y + px(56),
  },
  crumb: {
    color: color.bleacher,
    marginLeft: SCALE_ROOM + px(8),
    marginBottom: sp(1),
  },
  clip: {
    width: CLIP_W,
    overflow: "hidden",
    paddingHorizontal: SCALE_ROOM,
    paddingVertical: SCALE_ROOM,
  },
  row: { flexDirection: "row" },
  tile: { width: TILE.w, height: TILE.h, padding: sp(2.5) },
  head: { flexDirection: "row", alignItems: "flex-start" },
  dot: {
    width: px(16),
    height: px(16),
    borderRadius: px(8),
    marginTop: px(12),
    marginRight: sp(1),
  },
  label: { flexShrink: 1 },
  current: { backgroundColor: color.line },
  semi: { fontFamily: face.semibold },
  sub: { color: color.bleacher, marginTop: sp(1) },
});
