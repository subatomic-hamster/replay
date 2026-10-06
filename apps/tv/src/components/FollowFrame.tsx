// W4 — the amber frame that stays on the followed player in wide playback and follow mode.
// Positioned in VIEWPORT space: in follow mode the video carries the crop transform, so
// the track box goes through the same crop rect (tv-core mapBB) or it lands on the wrong
// pixels. Rendered from the clock-driven `t` the Watch screen already re-renders on.
import { StyleSheet, View } from "react-native";
import { cropRectAt, mapBB } from "../../../../packages/tv-core/src/follow";
import type { CropPath, TrackPlayer } from "../../../../packages/tv-core/src/types";
import { color, font, px } from "../theme";
import { T } from "../ui";

interface Props {
  pid: string;
  label: string;
  /** Interpolated players at `t` (tracks cache). */
  players: TrackPlayer[];
  t: number;
  /** Non-null only while the follow-cam transform is applied. */
  crop: CropPath | null;
}

const pct = (v: number) => `${(v * 100).toFixed(3)}%` as const;

export function FollowFrame({ pid, label, players, t, crop }: Props) {
  const bb = players.find((p) => p.id === pid)?.bb;
  // Occluded or off court: hide, come back when the box does.
  const [x, y, w, h] = bb ? mapBB(bb, crop ? cropRectAt(crop, t) : null) : [0, 0, 0, 0];
  return (
    <View
      testID="follow-frame"
      dataSet={{ pid, visible: bb ? "true" : "false" }}
      style={[
        styles.frame,
        { left: pct(x), top: pct(y), width: pct(w), height: pct(h), opacity: bb ? 1 : 0 },
      ]}
    >
      <View style={styles.labelRow}>
        <T style={styles.label}>{label}</T>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { position: "absolute", borderWidth: px(4), borderColor: color.accent, borderRadius: px(4) },
  labelRow: { position: "absolute", top: "100%", left: -px(4), width: px(400), marginTop: px(4), flexDirection: "row" },
  label: {
    paddingHorizontal: px(8),
    fontSize: font.small,
    fontWeight: "700",
    backgroundColor: color.accent,
    color: color.onAccent,
  },
});
