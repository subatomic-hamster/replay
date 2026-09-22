// W5 — top-down minimap. Court geometry comes from the profile's sport_ui.court
// template (§4.8: the app never branches on sport name). With no template we fall back
// to a plain rectangle sized by the court variant.
import type { CourtTemplate, Player, TrackPlayer } from "../api/types";

interface Props {
  court?: CourtTemplate;
  variant: string;
  players: TrackPlayer[];
  roster: Player[];
  selectedId: string | null;
}

const FALLBACK: Record<string, [number, number]> = {
  half: [15, 14],
  full: [15, 28],
};

/** A half court's origin is the baseline centre, so x runs -7.5..7.5: the viewBox has
 *  to start at the court's real minimum, not 0. */
export function courtViewBox(court: CourtTemplate | undefined, w: number, h: number) {
  const x = court?.x_range?.[0] ?? 0;
  const y = court?.y_range?.[0] ?? 0;
  return { x, y, attr: `${x} ${y} ${w} ${h}` };
}

export function CourtInset({ court, variant, players, roster, selectedId }: Props) {
  const [w, h] = court?.size_m ?? FALLBACK[variant] ?? FALLBACK.half;
  const box = courtViewBox(court, w, h);
  const polygons = court?.polygons ?? {
    outer: [
      [0, 0],
      [w, 0],
      [w, h],
      [0, h],
    ],
  };

  return (
    <svg
      className="court-inset"
      data-testid="court-inset"
      viewBox={box.attr}
      preserveAspectRatio="xMidYMid meet"
      aria-label="Court minimap"
    >
      <rect x={box.x} y={box.y} width={w} height={h} className="court-bg" />
      {Object.entries(polygons).map(([name, pts]) => (
        <polygon key={name} className={`court-line court-${name}`} points={pts.map((p) => p.join(",")).join(" ")} />
      ))}
      {players
        .filter((p) => p.ct)
        .map((p) => {
          const info = roster.find((r) => r.id === p.id);
          const sel = p.id === selectedId;
          return (
            <circle
              key={p.id}
              className={`court-dot${sel ? " selected" : ""}`}
              data-testid={`court-dot-${p.id}`}
              data-selected={sel ? "true" : "false"}
              cx={Math.min(box.x + w, Math.max(box.x, p.ct![0]))}
              cy={Math.min(box.y + h, Math.max(box.y, p.ct![1]))}
              r={sel ? w / 22 : w / 32}
              fill={info?.color_hex ?? "#8ab4ff"}
            />
          );
        })}
    </svg>
  );
}
