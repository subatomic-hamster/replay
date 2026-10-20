// The player's Do more layer (Up / Menu). Wave 2 placeholder: one row of large tiles over
// a soft scrim, so every feature of the old grouped watch menu stays reachable with the
// D-pad; Wave 3 designs the real layer (follow, angles, free view, stats panel, phone).
// A tile whose feature is still processing says "Getting ready, about N min" and cannot be
// chosen. A tile with `children` (Watch) opens its own row in place; Back returns.
import { useCallback, useState } from "react";
import { StyleSheet, View } from "react-native";
import { useDpad, type DpadAction } from "../input";
import { color, face, px, safe, sp, type } from "../theme";
import { Fade, Focusable, SlideIn, T } from "../ui";

export interface Tile {
  /** testID; the old menu's ids where the concept survives (nav-review, action-tag…) */
  id: string;
  label: string;
  sub: string;
  /** still processing: shown, focusable, not selectable */
  pending?: boolean;
  /** a toggle's state */
  on?: boolean;
  run?: () => void;
  children?: Tile[];
}

const TILE_W = px(304);
const TILE_H = px(168);
const PITCH = TILE_W + px(16) + sp(3);
const SHOWN = 5;

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
      if (a === "back" || a === "down") {
        if (open) setOpenId(null);
        else onClose();
      } else if (a === "playpause") onPlayPause();
      else if (a === "left") focus(Math.max(0, k - 1));
      else if (a === "right") focus(Math.min(row.length - 1, k + 1));
      else if (a === "select") {
        const t = row[k];
        if (!t || t.pending) return;
        if (t.children) {
          const cur = t.children.find((c) => c.on) ?? t.children[0];
          setAt({ ...at, [t.id]: cur.id });
          setOpenId(t.id);
        } else t.run?.();
      }
    },
    [open, k, row, rowKey, at, onClose, onPlayPause],
  );
  useDpad(onAction);

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <Fade side="top" length={px(480)} strength={0.85} />
      <SlideIn
        from="above"
        style={styles.layer}
        testID="domore"
        dataSet={{ row: open ? open.id : "main" }}
      >
        <T style={[type.meta, styles.crumb]}>{open ? open.label : "Do more"}</T>
        <View
          style={[
            styles.row,
            {
              transform: [
                { translateX: -Math.max(0, k - (SHOWN - 1)) * PITCH },
              ],
            },
          ]}
        >
          {row.map((t, n) => (
            <View key={t.id} style={styles.slot}>
              <Focusable
                focused={n === k}
                testID={t.id}
                dataSet={{
                  focused: n === k ? "true" : "false",
                  pending: t.pending ? "true" : "false",
                  ...(t.on === undefined
                    ? {}
                    : { on: t.on ? "true" : "false" }),
                }}
              >
                <View style={[styles.tile, t.pending && { opacity: 0.55 }]}>
                  <T
                    style={[type.body, { fontFamily: face.semibold }]}
                    numberOfLines={1}
                  >
                    {t.label}
                  </T>
                  <T style={[type.meta, styles.sub]} numberOfLines={2}>
                    {t.sub}
                  </T>
                </View>
              </Focusable>
            </View>
          ))}
        </View>
      </SlideIn>
    </View>
  );
}

const styles = StyleSheet.create({
  layer: {
    position: "absolute",
    left: safe.x,
    right: 0,
    top: safe.y + px(56),
  },
  crumb: { color: color.bleacher, marginLeft: px(8), marginBottom: sp(1) },
  row: { flexDirection: "row" },
  slot: { marginRight: sp(3) },
  tile: { width: TILE_W, height: TILE_H, padding: sp(3) },
  sub: { color: color.bleacher, marginTop: sp(1) },
});
