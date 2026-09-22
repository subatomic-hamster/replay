// W1 — game library. Keyboard only (D-1): arrows move, Enter opens, Back is a no-op
// because there is nothing above the library (E-14).
import { useCallback, useMemo, useState } from "react";
import { api } from "../api/client";
import { useDpad } from "../platform/keys";
import { navigate } from "../router";
import { ApiErrorBanner, fmtDate, fmtDuration, useAsync } from "../ui";
import type { GameSummary } from "../api/types";

function statusText(g: GameSummary): string {
  if (g.status === "ready") return "ready";
  const running = Object.entries(g.stages ?? {}).find(([, v]) => v === "running");
  return running ? `${running[0]}ing…` : g.status;
}

export function Library() {
  const { data, error, reload } = useAsync(() => api.listGames(), []);
  const [focus, setFocus] = useState(0);
  const games = useMemo(() => data ?? [], [data]);

  const onAction = useCallback(
    (a: string) => {
      if (games.length === 0) return;
      if (a === "right" || a === "down") setFocus((i) => Math.min(games.length - 1, i + 1));
      else if (a === "left" || a === "up") setFocus((i) => Math.max(0, i - 1));
      else if (a === "select") {
        const g = games[focus];
        // E-02: a game still processing opens its status view, not the watch surface.
        navigate(g.status === "ready" ? `/tv/${g.id}` : `/upload/${g.id}/status`);
      }
      // "back" on the library: intentional no-op (E-14).
    },
    [games, focus],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;

  return (
    <div className="screen library">
      <h1>Replay</h1>
      {data && games.length === 0 ? (
        <p data-testid="library-empty">No games yet. Upload one from your phone at /upload.</p>
      ) : null}
      <div className="cards">
        {games.map((g, i) => (
          <div
            key={g.id}
            className={`card${i === focus ? " focused" : ""}`}
            data-testid="game-card"
            data-game-id={g.id}
            data-focused={i === focus ? "true" : "false"}
          >
            <div className="thumb">
              {g.thumb_url ? <img src={g.thumb_url} alt="" /> : null}
              <span className={`status-pill ${g.status === "ready" ? "ready" : "working"}`}>
                <span data-testid="game-status">{statusText(g)}</span>
              </span>
            </div>
            <div className="card-title" data-testid="game-card-title">
              {g.title}
            </div>
            <div className="card-meta">
              {fmtDate(g.recorded_at)} · {fmtDuration(g.duration_s)}
            </div>
          </div>
        ))}
      </div>
      <p className="hint">
        <b>Arrows</b> move · <b>Enter</b> opens a game
      </p>
    </div>
  );
}
