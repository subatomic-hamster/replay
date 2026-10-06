// M10 Players (/tv/players[?from=<game>]): every profile (photo or initials, sports, linked
// games). Arrows move over the grid, Enter opens the profile, Escape returns to where it was
// opened from. Profiles are created and edited on the phone (/profiles).
import { useCallback, useMemo, useState } from "react";
import { api } from "../api/client";
import { Avatar } from "../components/Avatar";
import { useDpad, type DpadAction } from "../platform/keys";
import { navigate, useLocation } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import { listWindow } from "../../../../packages/tv-core/src/discovery";
import { sportsText } from "../../../../packages/tv-core/src/profiles";

const COLS = 5;
const ROWS = 2;

export function Players() {
  const from = useLocation().params.get("from");
  const { data, error, reload } = useAsync(() => api.listProfiles(), []);
  const [focus, setFocus] = useState(0);
  const list = useMemo(() => data ?? [], [data]);
  const back = from ? `?from=${from}` : "";

  const onAction = useCallback(
    (a: DpadAction) => {
      const n = list.length;
      if (a === "back") navigate(from ? `/tv/${from}` : "/tv");
      else if (a === "left") setFocus((i) => Math.max(0, i - 1));
      else if (a === "right") setFocus((i) => Math.max(0, Math.min(n - 1, i + 1)));
      else if (a === "up") setFocus((i) => (i - COLS >= 0 ? i - COLS : i));
      else if (a === "down") setFocus((i) => Math.max(0, Math.min(n - 1, i + COLS)));
      else if (a === "select" && list[focus]) navigate(`/tv/players/${list[focus].profile_id}${back}`);
    },
    [list, focus, from, back],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!data) return <div className="screen">Loading…</div>;

  const firstRow = listWindow(Math.floor(focus / COLS), Math.ceil(list.length / COLS), ROWS);
  return (
    <div className="screen players" data-testid="players">
      <h1>Players</h1>
      {list.length === 0 ? (
        <p data-testid="players-empty">No profiles yet. Create one on your phone at /profiles.</p>
      ) : null}
      <div className="profile-grid">
        {list.slice(firstRow * COLS, (firstRow + ROWS) * COLS).map((p, k) => {
          const on = firstRow * COLS + k === focus;
          return (
            <div
              key={p.profile_id}
              className={`profile-card${on ? " focused" : ""}`}
              data-testid="profile-card"
              data-profile-id={p.profile_id}
              data-focused={on ? "true" : "false"}
            >
              <Avatar name={p.name} photo={p.photo_url} size={160} />
              <div className="profile-card-name" data-testid="profile-card-name">
                {p.name}
              </div>
              <div className="dim">{sportsText(p)}</div>
              <div className="dim">
                {p.linked.length} {p.linked.length === 1 ? "game" : "games"}
              </div>
            </div>
          );
        })}
      </div>
      <p className="hint">
        <b>Arrows</b> move · <b>Enter</b> opens a player · <b>Escape</b> returns
      </p>
    </div>
  );
}
