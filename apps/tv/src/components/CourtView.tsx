// A top-down court drawn from the profile's sport_ui.court template (§4.8: geometry comes
// from the profile, never from the sport name). Plain Views — each polygon edge is a
// rotated 2 px bar — so the minimap, shot chart and heatmap need no SVG module on Fire TV.
// With no template, a rectangle sized by the court variant.
import type { ReactNode } from "react";
import { View } from "react-native";
import { courtViewBox } from "../../../../packages/tv-core/src/display";
import type { CourtTemplate } from "../../../../packages/tv-core/src/types";
import { px } from "../theme";

const FALLBACK: Record<string, [number, number]> = { half: [15, 14], full: [15, 28] };

export type CourtToPx = (x: number, y: number) => [number, number];

interface Props {
  court?: CourtTemplate;
  variant?: string;
  /** Max drawn size in px; the court keeps its aspect inside it. */
  width: number;
  maxHeight?: number;
  testID?: string;
  /** Overlay content in court metres: `toPx` maps metres to this view's px; `s` is px/m. */
  children?: (toPx: CourtToPx, s: number) => ReactNode;
}

export function courtSize(court: CourtTemplate | undefined, variant?: string): [number, number] {
  return court?.size_m ?? FALLBACK[variant ?? "half"] ?? FALLBACK.half;
}

export function CourtView({ court, variant, width, maxHeight = Infinity, testID, children }: Props) {
  const [w, h] = courtSize(court, variant);
  const box = courtViewBox(court, w, h);
  const s = Math.min(width / w, maxHeight / h);
  const toPx: CourtToPx = (x, y) => [(x - box.x) * s, (y - box.y) * s];
  const polygons = court?.polygons ?? { outer: [[0, 0], [w, 0], [w, h], [0, h]] };
  const thick = px(3);

  const bars: ReactNode[] = [];
  for (const [name, pts] of Object.entries(polygons)) {
    // A 2-point "polygon" (a net line) is one bar, not a closed loop.
    const n = pts.length === 2 ? 1 : pts.length;
    for (let i = 0; i < n; i++) {
      const [ax, ay] = toPx(...pts[i]);
      const [bx, by] = toPx(...pts[(i + 1) % pts.length]);
      const len = Math.hypot(bx - ax, by - ay);
      bars.push(
        <View
          key={`${name}-${i}`}
          style={{
            position: "absolute",
            left: (ax + bx) / 2 - len / 2,
            top: (ay + by) / 2 - thick / 2,
            width: len,
            height: thick,
            backgroundColor: "rgba(201, 211, 224, 0.7)",
            transform: [{ rotate: `${Math.atan2(by - ay, bx - ax)}rad` }],
          }}
        />,
      );
    }
  }

  return (
    <View
      testID={testID}
      style={{ width: w * s, height: h * s, backgroundColor: "#1b2330", overflow: "hidden" }}
    >
      {bars}
      {children?.(toPx, s)}
    </View>
  );
}
