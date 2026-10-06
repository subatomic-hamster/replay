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
}

const MARKER: Record<string, string> = { bookmark: "#8ab4ff", rally: "#c084fc", point: "#c084fc" };

export function SeekBar({ duration, current, events, focused }: Props) {
  const frac = duration > 0 ? Math.min(1, Math.max(0, current / duration)) : 0;
  return (
    <View testID="seek-bar" dataSet={{ focused: focused ? "true" : "false" }} style={styles.row}>
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
      <T style={styles.time}>
        {fmtDuration(current)} / {fmtDuration(duration)}
      </T>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center" },
  track: {
    flex: 1,
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
