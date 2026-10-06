// W5 — top-down minimap: one dot per tracked player at its court position, the selected
// player larger and ringed.
import { View } from "react-native";
import type { CourtTemplate, Player, TrackPlayer } from "../../../../packages/tv-core/src/types";
import { color, px } from "../theme";
import { CourtView, courtSize } from "./CourtView";

interface Props {
  court?: CourtTemplate;
  variant: string;
  players: TrackPlayer[];
  roster: Player[];
  selectedId: string | null;
}

export function CourtInset({ court, variant, players, roster, selectedId }: Props) {
  const [w, h] = courtSize(court, variant);
  return (
    <CourtView court={court} variant={variant} width={px(300)} maxHeight={px(300)} testID="court-inset">
      {(toPx, s) =>
        players.flatMap((p) => {
            if (!p.ct) return [];
            const sel = p.id === selectedId;
            const r = sel ? Math.max(px(12), (w * s) / 22) : Math.max(px(8), (w * s) / 32);
            // Clamp onto the drawn court (its origin may be negative: half-court x_range).
            const [x, y] = toPx(p.ct[0], p.ct[1]).map((v, i) =>
              Math.min(i ? h * s : w * s, Math.max(0, v)),
            );
            return (
              <View
                key={p.id}
                testID={`court-dot-${p.id}`}
                dataSet={{ selected: sel ? "true" : "false" }}
                style={{
                  position: "absolute",
                  left: x - r,
                  top: y - r,
                  width: 2 * r,
                  height: 2 * r,
                  borderRadius: r,
                  backgroundColor: roster.find((q) => q.id === p.id)?.color_hex ?? color.dot,
                  borderWidth: sel ? px(4) : 0,
                  borderColor: color.accent,
                }}
              />
            );
          })
      }
    </CourtView>
  );
}
