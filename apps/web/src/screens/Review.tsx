// R5 review queue, R1 shot chart, R3 box score lite — all labelled "auto-detected".
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { courtViewBox } from "../components/CourtInset";
import { REVIEW_CONFIDENCE_THRESHOLD } from "../config";
import { useDpad, type DpadAction } from "../platform/keys";
import { navigate } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import type { GameEvent, Stats } from "../api/types";

// `source: "user"` is set by the API on any field the user changed (§4.5) — the client
// does not get to claim provenance.
const ACTIONS: { label: string; patch: Partial<GameEvent> }[] = [
  { label: "Made", patch: { made: true, confirmed: true } },
  { label: "Missed", patch: { made: false, confirmed: true } },
  // D-11 "not a shot": v1 has no delete, so the event is flagged dismissed and drops
  // out of query and stats while staying in events.json.
  { label: "Not a shot", patch: { dismissed: true, confirmed: true } },
];

const COURT_FALLBACK: [number, number] = [15, 14];

export function Review({ gameId }: { gameId: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [queue, setQueue] = useState<GameEvent[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [focus, setFocus] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!game) return;
    api.getEvents(game).then(
      (evs) =>
        setQueue(
          evs.filter((e) => !e.confirmed && e.confidence < REVIEW_CONFIDENCE_THRESHOLD),
        ),
      () => setQueue([]),
    );
  }, [game]);

  const loadStats = useCallback(() => {
    api.getStats(gameId).then(setStats, () => setStats(null));
  }, [gameId]);
  useEffect(loadStats, [loadStats]);

  const answer = useCallback(
    (i: number) => {
      const current = queue[0];
      if (!current || busy) return;
      setBusy(true);
      api
        .patchEvent(gameId, current.id, ACTIONS[i].patch)
        .then(() => {
          setQueue((q) => q.slice(1));
          loadStats();
        })
        .catch(() => {})
        .finally(() => setBusy(false));
    },
    [queue, gameId, busy, loadStats],
  );

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "left") setFocus((f) => Math.max(0, f - 1));
      else if (a === "right") setFocus((f) => Math.min(ACTIONS.length - 1, f + 1));
      else if (a === "select") answer(focus);
      else if (a === "back") navigate(`/tv/${gameId}`);
    },
    [focus, answer, gameId],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <div className="screen">Loading…</div>;

  const current = queue[0];
  const [cw, ch] = game.sport_ui?.court?.size_m ?? COURT_FALLBACK;
  const polygons = game.sport_ui?.court?.polygons;
  const viewBox = courtViewBox(game.sport_ui?.court, cw, ch);

  return (
    <div className="screen review">
      <h1>Review — {game.title}</h1>
      <p className="auto-label" data-testid="auto-detected-label">
        All numbers below are auto-detected.
      </p>

      <section className="review-queue">
        <h2>Review queue ({queue.length})</h2>
        {current ? (
          <div
            className="review-item"
            data-testid="review-item"
            data-event-id={current.id}
            data-confidence={current.confidence}
          >
            <p>
              {current.type} at {current.t_key.toFixed(1)}s ·{" "}
              {game.players.find((p) => p.id === current.player_id)?.name ?? current.player_id} ·
              confidence {current.confidence.toFixed(2)}
            </p>
            <div className="review-actions">
              {ACTIONS.map((act, i) => (
                <span
                  key={act.label}
                  className={`btn${i === focus ? " focused" : ""}`}
                  data-testid={`review-action-${act.label.toLowerCase().replace(/\s+/g, "-")}`}
                  data-focused={i === focus ? "true" : "false"}
                >
                  {act.label}
                </span>
              ))}
            </div>
          </div>
        ) : (
          <p data-testid="review-empty">Nothing left to review.</p>
        )}
      </section>

      <section className="stats">
        <h2>Shot chart</h2>
        <svg className="shot-chart" data-testid="shot-chart" viewBox={viewBox.attr}>
          <rect x={viewBox.x} y={viewBox.y} width={cw} height={ch} className="court-bg" />
          {Object.entries(polygons ?? {}).map(([name, pts]) => (
            <polygon
              key={name}
              className="court-line"
              points={pts.map((p) => p.join(",")).join(" ")}
            />
          ))}
          {(stats?.shots ?? []).map((s) => (
            <circle
              key={s.event_id}
              className={`shot ${s.made ? "made" : "missed"}`}
              data-testid="shot-marker"
              data-made={s.made ? "true" : "false"}
              cx={s.court[0]}
              cy={s.court[1]}
              r={cw / 30}
            />
          ))}
        </svg>

        <h2>Box score lite</h2>
        <table className="box-score">
          <thead>
            <tr>
              <th>Player</th>
              <th>Att</th>
              <th>Made</th>
              <th>Conf</th>
            </tr>
          </thead>
          <tbody>
            {(stats?.box_score ?? []).map((r) => (
              <tr key={r.player_id} data-testid="box-score-row" data-player-id={r.player_id}>
                <td>{r.name ?? r.player_id}</td>
                <td>{r.attempts}</td>
                <td>{r.makes}</td>
                <td>{r.confidence ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <p className="hint">Arrows pick an answer · Enter confirms · Escape goes back</p>
    </div>
  );
}
