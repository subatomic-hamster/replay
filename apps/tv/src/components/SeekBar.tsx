// W2 transport + W8 event markers on the scrubber.
import { StyleSheet, View } from "react-native";
import { fmtDuration } from "../../../../packages/tv-core/src/display";
import type { GameEvent } from "../../../../packages/tv-core/src/types";
import { color, font, px } from "../theme";
import { T } from "../ui";

interface Props {
  duration: number;
  current: number;
  events: GameEvent[];
  focused?: boolean;
  /** D-45 hype meter, already pooled to bars (tv-core hypeBars), 0..1 each. */
  hype?: number[] | null;
}

const MARKER: Record<string, string> = { bookmark: "#8ab4ff", rally: "#c084fc", point: "#c084fc" };
const HYPE_H = px(40);

export function SeekBar({ duration, current, events, focused, hype }: Props) {
  const frac = duration > 0 ? Math.min(1, Math.max(0, current / duration)) : 0;
  return (
    <View testID="seek-bar" dataSet={{ focused: focused ? "true" : "false" }} style={styles.row}>
      <View style={{ flex: 1 }}>
      {hype?.length ? (
        // The meter sits on the scrubber's own time axis: bar i covers the i-th slice.
        <View style={styles.hype} testID="hype-meter" dataSet={{ bars: hype.length }}>
          {hype.map((v, i) => (
            <View key={i} style={styles.hypeSlot}>
              <View
                testID="hype-bar"
                dataSet={{ value: v }}
                style={[styles.hypeBar, { height: Math.max(px(2), v * HYPE_H), opacity: 0.35 + 0.65 * v }]}
              />
            </View>
          ))}
        </View>
      ) : null}
      <View style={[styles.track, focused && { height: px(14) }]}>
        <View style={[styles.fill, { width: `${frac * 100}%` }]} />
        {events.map((e) => (
          <View
            key={e.id}
            testID="event-marker"
            dataSet={{ type: e.type, eventId: e.id, tKey: e.t_key }}
            style={[
              styles.marker,
              {
                left: `${duration > 0 ? (e.t_key / duration) * 100 : 0}%`,
                backgroundColor:
                  MARKER[e.type] ?? (e.made ? color.made : e.made === false ? color.missed : color.fg),
              },
            ]}
          />
        ))}
        <View
          testID="seek-bar-thumb"
          style={[styles.thumb, { left: `${frac * 100}%` }, focused && styles.thumbFocused]}
        />
      </View>
      </View>
      <T style={styles.time}>
        {fmtDuration(current)} / {fmtDuration(duration)}
      </T>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-end" },
  hype: { flexDirection: "row", alignItems: "flex-end", height: HYPE_H, marginBottom: px(8) },
  hypeSlot: { flex: 1, alignItems: "center", justifyContent: "flex-end" },
  hypeBar: { width: "70%", backgroundColor: color.accent, borderTopLeftRadius: px(2), borderTopRightRadius: px(2) },
  track: {
    height: px(10),
    borderRadius: px(6),
    backgroundColor: color.raised,
    justifyContent: "center",
  },
  fill: { position: "absolute", left: 0, top: 0, bottom: 0, backgroundColor: color.dim, borderRadius: px(6) },
  marker: {
    position: "absolute",
    width: px(10),
    height: px(28),
    marginLeft: -px(5),
    borderRadius: px(3),
  },
  thumb: {
    position: "absolute",
    width: px(20),
    height: px(20),
    marginLeft: -px(10),
    borderRadius: px(10),
    backgroundColor: color.fg,
  },
  thumbFocused: {
    width: px(32),
    height: px(32),
    marginLeft: -px(16),
    borderRadius: px(16),
    backgroundColor: color.accent,
  },
  time: { marginLeft: px(24), fontSize: font.body, fontVariant: ["tabular-nums"] },
});
