// W3 — focusable boxes over on-court players, plus the W6 spotlight dim. Boxes are
// percentages of the player surface, which is exactly the video's rendered rect.
import { StyleSheet, View } from "react-native";
import { inkOn } from "../../../../packages/tv-core/src/display";
import type {
  Player,
  TrackPlayer,
} from "../../../../packages/tv-core/src/types";
import { color, font, px, teamColorMap } from "../theme";
import { T } from "../ui";

interface Props {
  players: TrackPlayer[];
  roster: Player[];
  focusId: string | null;
  spotlight?: boolean;
  /** False in follow mode, where the spotlight may still be drawn (W6). */
  showBoxes?: boolean;
}

const pct = (v: number) => `${(v * 100).toFixed(3)}%` as const;

export function SelectOverlay({
  players,
  roster,
  focusId,
  spotlight,
  showBoxes = true,
}: Props) {
  if (players.length === 0) {
    if (!showBoxes) return null;
    return (
      <View style={styles.empty} testID="select-empty">
        <T>No players on court here</T>
      </View>
    );
  }
  const focused = players.find((p) => p.id === focusId);
  // in team order, so the drawn pair keeps which team is the darker one
  const ink = teamColorMap(
    [...roster]
      .sort((a, b) => (a.team ?? 0) - (b.team ?? 0))
      .map((r) => r.color_hex),
  );

  return (
    <>
      {spotlight && focused ? (
        <View style={StyleSheet.absoluteFill} testID="spotlight-overlay">
          {/* Four dim panels around the box — portable to every renderer, no masks. */}
          <View
            style={[
              styles.dim,
              { left: 0, top: 0, width: "100%", height: pct(focused.bb[1]) },
            ]}
          />
          <View
            style={[
              styles.dim,
              {
                left: 0,
                top: pct(focused.bb[1] + focused.bb[3]),
                width: "100%",
                bottom: 0,
              },
            ]}
          />
          <View
            style={[
              styles.dim,
              {
                left: 0,
                top: pct(focused.bb[1]),
                width: pct(focused.bb[0]),
                height: pct(focused.bb[3]),
              },
            ]}
          />
          <View
            style={[
              styles.dim,
              {
                left: pct(focused.bb[0] + focused.bb[2]),
                top: pct(focused.bb[1]),
                right: 0,
                height: pct(focused.bb[3]),
              },
            ]}
          />
        </View>
      ) : null}

      {showBoxes &&
        players.map((p) => {
          const info = roster.find((r) => r.id === p.id);
          const team =
            (info?.color_hex && ink.get(info.color_hex)) || color.dot;
          const isFocused = p.id === focusId;
          return (
            <View
              key={p.id}
              testID={`select-box-${p.id}`}
              dataSet={{
                playerId: p.id,
                team: info?.team,
                focused: isFocused ? "true" : "false",
              }}
              style={[
                styles.box,
                {
                  left: pct(p.bb[0]),
                  top: pct(p.bb[1]),
                  width: pct(p.bb[2]),
                  height: pct(p.bb[3]),
                  borderColor: isFocused ? color.accent : team,
                  borderWidth: isFocused ? px(6) : px(3),
                  // A wash of the team colour, so the sides read apart at 10 feet.
                  backgroundColor: `${team}22`,
                },
              ]}
            >
              {/* A wide row above the box, so the label sizes to its text, not the box. */}
              <View style={styles.labelRow}>
                <T
                  testID={`player-label-${p.id}`}
                  style={[
                    styles.label,
                    isFocused
                      ? { backgroundColor: color.accent, color: color.onAccent }
                      : { backgroundColor: team, color: inkOn(team) },
                  ]}
                >
                  {info?.name ?? p.id}
                </T>
              </View>
            </View>
          );
        })}
    </>
  );
}

const styles = StyleSheet.create({
  dim: { position: "absolute", backgroundColor: "rgba(0,0,0,0.62)" },
  box: { position: "absolute", borderRadius: px(4), overflow: "visible" },
  labelRow: {
    position: "absolute",
    bottom: "100%",
    left: -px(3),
    width: px(400),
    marginBottom: px(4),
    flexDirection: "row",
  },
  label: {
    paddingHorizontal: px(8),
    fontSize: font.small,
    fontWeight: "700",
    borderRadius: px(4),
  },
  empty: {
    position: "absolute",
    top: px(24),
    alignSelf: "center",
    backgroundColor: color.scrim,
    paddingHorizontal: px(24),
    paddingVertical: px(8),
    borderRadius: px(8),
  },
});
