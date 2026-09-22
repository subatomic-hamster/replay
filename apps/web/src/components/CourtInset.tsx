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

export function CourtInset({ court, variant, players, roster, selectedId }: Props) {
  const [w, h] = court?.size_m ?? FALLBACK[variant] ?? FALLBACK.half;
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
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="xMidYMid meet"
      aria-label="Court minimap"
    >
      <rect x={0} y={0} width={w} height={h} className="court-bg" />
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
              cx={Math.min(w, Math.max(0, p.ct![0]))}
              cy={Math.min(h, Math.max(0, p.ct![1]))}
              r={sel ? w / 22 : w / 32}
              fill={info?.color_hex ?? "#8ab4ff"}
            />
          );
        })}
    </svg>
  );
}
