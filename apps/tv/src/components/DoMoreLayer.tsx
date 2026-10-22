// The player's Do more layer (Up / Menu; docs/ux/redesign.md "Do more"): one row of large
// actions over a soft scrim, in the spec's order (Follow player, Angles, Free view, Watch,
// Stats, Commentary, On your phone, then Bookmark). The row keeps inside the safe zone:
// what does not fit is clipped at its edge, the next tile peeking, and the row scrolls with
// focus. A tile whose feature is still processing says "Getting ready, about N min" and
// cannot be chosen. A tile with `children` opens its own row in place (Follow player's
// actions, Player POV's player chips, Angles' thumbnails, Watch's ways), the current child marked; Back or Down
// returns to the main row, and from there closes the layer.
import { useCallback, useState, type ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import { useDpad, type DpadAction } from "../input";
import { color, face, px, radius, safe, sp, type } from "../theme";
import { Fade, Focusable, SlideIn, T } from "../ui";
import { Avatar } from "./Avatar";

export interface Tile {
  /** testID; the old menu's ids where the concept survives (nav-review, action-tag…) */
  id: string;
  label: string;
  sub?: string;
  /** still processing: shown, focusable, not selectable */
  pending?: boolean;
  /** a toggle's state, or the current choice in a sub-row (marked) */
  on?: boolean;
  run?: () => void;
  children?: Tile[];
  /** How `children` draw: large tiles (default), player chips, or 16:9 thumbnails. */
  view?: View_;
  /** a chip's face: the profile photo, else initials */
  avatar?: { name: string; photo: string | null };
  /** a thumbnail's picture */
  art?: ReactNode;
}
type View_ = "tiles" | "chips" | "thumbs";

const RING_BOX = px(8); // Focusable's ring + gap, each side
const GAP = sp(3);
const SIZE: Record<View_, { w: number; h: number }> = {
  tiles: { w: px(280), h: px(168) },
  chips: { w: px(280), h: px(88) },
  thumbs: { w: px(304), h: px(171) },
};
/** The row's clip: the safe zone, plus room for the focused tile's ring and 1.06 scale. */
const SCALE_ROOM = px(12);
const CLIP_W = px(1920) - 2 * safe.x + 2 * SCALE_ROOM;
const pitch = (v: View_) => SIZE[v].w + 2 * RING_BOX + GAP;
/** Whole items that fit in the safe zone; the next one peeks. */
const shown = (v: View_) =>
  Math.max(1, Math.floor((px(1920) - 2 * safe.x + GAP) / pitch(v)));

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
  const view: View_ = open?.view ?? "tiles";
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

  const { w, h } = SIZE[view];
  const shift = Math.max(0, k - (shown(view) - 1)) * pitch(view);
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <Fade
        side="top"
        length={px(view === "thumbs" ? 600 : 480)}
        strength={0.85}
      />
      <SlideIn
        from="above"
        style={styles.layer}
        testID="domore"
        dataSet={{ row: open ? open.id : "main" }}
      >
        <T style={[type.meta, styles.crumb]}>{open ? open.label : "Do more"}</T>
        <View
          style={[styles.clip, view === "chips" && styles.toEdge]}
          testID="domore-clip"
        >
          <View style={[styles.row, { transform: [{ translateX: -shift }] }]}>
            {row.map((t, n) => {
              const on = n === k;
              return (
                <View key={t.id} style={{ marginRight: GAP }}>
                  <Focusable
                    focused={on}
                    round={view === "chips" ? radius.chip : radius.card}
                    // text and avatars need no clip (cheaper over the video)
                    clip={view === "thumbs"}
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
                        { width: w, height: h },
                        // a thumb's art fills the tile edge to edge (no text padding)
                        view === "chips"
                          ? styles.chip
                          : view === "tiles" && styles.tile,
                        t.on && !on && view !== "thumbs" && styles.current,
                        t.pending && { opacity: 0.55 },
                      ]}
                    >
                      {view === "thumbs" ? (
                        t.art
                      ) : view === "chips" ? (
                        <>
                          {t.avatar ? (
                            <View style={styles.face}>
                              <Avatar
                                name={t.avatar.name}
                                photo={t.avatar.photo}
                                size={56}
                              />
                            </View>
                          ) : null}
                          <T
                            style={[type.body, styles.semi, { flexShrink: 1 }]}
                            numberOfLines={1}
                          >
                            {t.label}
                          </T>
                        </>
                      ) : (
                        <>
                          <T style={[type.body, styles.semi]} numberOfLines={1}>
                            {t.label}
                          </T>
                          {t.sub ? (
                            <T
                              style={[type.meta, styles.sub]}
                              numberOfLines={2}
                            >
                              {t.sub}
                            </T>
                          ) : null}
                        </>
                      )}
                    </View>
                  </Focusable>
                  {view === "thumbs" ? (
                    <View style={[styles.caption, { width: w }]}>
                      <T
                        style={[type.body, !on && styles.dim]}
                        numberOfLines={1}
                      >
                        {t.on ? `${t.label}, now` : t.label}
                      </T>
                      {t.sub ? (
                        <T style={[type.meta, styles.dim]} numberOfLines={1}>
                          {t.sub}
                        </T>
                      ) : null}
                    </View>
                  ) : null}
                </View>
              );
            })}
          </View>
        </View>
      </SlideIn>
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
  // Chips run on off the screen edge, like Moments' filter chips: a chip cut at the safe
  // edge read as a broken label ("P6 Pla"). `shift` still keeps the focused one inside it.
  toEdge: { width: px(1920) - safe.x + SCALE_ROOM },
  row: { flexDirection: "row" },
  tile: { padding: sp(3) },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    paddingLeft: sp(2),
    paddingRight: sp(3),
  },
  face: { marginRight: sp(2) },
  current: { backgroundColor: color.line },
  semi: { fontFamily: face.semibold },
  sub: { color: color.bleacher, marginTop: sp(1) },
  dim: { color: color.bleacher },
  caption: { marginTop: sp(1), marginLeft: RING_BOX },
});
