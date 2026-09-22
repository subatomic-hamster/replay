// W3 — focusable boxes over on-court players, plus the W6 spotlight dim.
// Positions come from interpolated tracks (data/tracksCache) and are expressed as
// percentages of the player surface, which is exactly the video's rendered rect in
// wide mode.
import type { Player, TrackPlayer } from "../api/types";

interface Props {
  players: TrackPlayer[];
  roster: Player[];
  focusId: string | null;
  spotlight?: boolean;
  /** False in follow mode, where the spotlight may still be drawn (W6 fallback). */
  showBoxes?: boolean;
}

const pct = (v: number) => `${(v * 100).toFixed(3)}%`;

/** The name label sits on the team colour, which ranges from navy to near-white, so the
 *  text colour is picked from the swatch's luminance rather than assumed. */
function inkOn(hex: string): string {
  const h = hex.replace("#", "");
  if (h.length < 6) return "#000";
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 ? "#0b0d10" : "#ffffff";
}

export function SelectOverlay({ players, roster, focusId, spotlight, showBoxes = true }: Props) {
  if (players.length === 0) {
    if (!showBoxes) return null;
    return (
      <div className="select-empty" data-testid="select-empty">
        No players on court here
      </div>
    );
  }
  const focused = players.find((p) => p.id === focusId);

  return (
    <>
      {spotlight && focused ? (
        <div className="spotlight" data-testid="spotlight-overlay" aria-hidden>
          {/* Four dim panels around the box — cheaper and more portable than a mask. */}
          <div className="dim" style={{ left: 0, top: 0, width: "100%", height: pct(focused.bb[1]) }} />
          <div
            className="dim"
            style={{
              left: 0,
              top: pct(focused.bb[1] + focused.bb[3]),
              width: "100%",
              bottom: 0,
            }}
          />
          <div
            className="dim"
            style={{
              left: 0,
              top: pct(focused.bb[1]),
              width: pct(focused.bb[0]),
              height: pct(focused.bb[3]),
            }}
          />
          <div
            className="dim"
            style={{
              left: pct(focused.bb[0] + focused.bb[2]),
              top: pct(focused.bb[1]),
              right: 0,
              height: pct(focused.bb[3]),
            }}
          />
        </div>
      ) : null}

      {showBoxes && players.map((p) => {
        const info = roster.find((r) => r.id === p.id);
        const color = info?.color_hex ?? "#8ab4ff";
        const isFocused = p.id === focusId;
        return (
          <div
            key={p.id}
            className={`select-box${isFocused ? " focused" : ""}`}
            data-testid={`select-box-${p.id}`}
            data-player-id={p.id}
            data-team={info?.team}
            data-focused={isFocused ? "true" : "false"}
            style={{
              left: pct(p.bb[0]),
              top: pct(p.bb[1]),
              width: pct(p.bb[2]),
              height: pct(p.bb[3]),
              borderColor: color,
              // A wash of the team colour, so the two sides read apart at 10 feet even
              // before you look at the border.
              backgroundColor: `${color}22`,
            }}
          >
            <span
              className="select-label"
              data-testid={`player-label-${p.id}`}
              style={{ backgroundColor: color, color: inkOn(color) }}
            >
              {info?.name ?? p.id}
            </span>
          </div>
        );
      })}
    </>
  );
}
