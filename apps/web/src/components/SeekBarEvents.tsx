// W2 transport + W8 event markers.
import type { GameEvent } from "../api/types";
import { fmtDuration } from "../ui";

interface Props {
  duration: number;
  current: number;
  events: GameEvent[];
  focused?: boolean;
}

export function SeekBarEvents({ duration, current, events, focused }: Props) {
  const frac = duration > 0 ? Math.min(1, Math.max(0, current / duration)) : 0;
  return (
    <div className={`seekbar${focused ? " focused" : ""}`} data-testid="seek-bar">
      <div className="seekbar-track">
        <div className="seekbar-fill" style={{ width: `${frac * 100}%` }} />
        {events.map((e) => (
          <span
            key={e.id}
            className={`event-marker type-${e.type}${e.made ? " made" : ""}`}
            data-testid="event-marker"
            data-type={e.type}
            data-event-id={e.id}
            data-t-key={e.t_key}
            style={{ left: `${duration > 0 ? (e.t_key / duration) * 100 : 0}%` }}
            title={`${e.type} @ ${e.t_key.toFixed(1)}s`}
          />
        ))}
        <span
          className="seekbar-thumb"
          data-testid="seek-bar-thumb"
          style={{ left: `${frac * 100}%` }}
        />
      </div>
      <div className="seekbar-time">
        {fmtDuration(current)} / {fmtDuration(duration)}
      </div>
    </div>
  );
}
