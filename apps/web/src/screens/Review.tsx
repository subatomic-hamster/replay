// R5 review queue, R1 shot chart, R2 heatmap, R3 box score lite — all "auto-detected".
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { courtViewBox } from "../components/CourtInset";
import { REVIEW_CONFIDENCE_THRESHOLD } from "../config";
import { useDpad, type DpadAction } from "../platform/keys";
import { navigate } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import { REVIEW_ACTIONS, reviewPanels } from "../../../../packages/tv-core/src/display";
import type { GameEvent, Stats } from "../api/types";

type HeatGrid = NonNullable<Stats["heatmap"]>[number];

/** R2 (S-34) — one SVG rect per occupied cell, opacity proportional to the count, drawn
 *  in court metres so it lines up with the same court outline the shot chart uses. */
function Heatmap({ grid, viewBox, size, polygons }: {
  grid: HeatGrid;
  viewBox: { x: number; y: number; attr: string };
  size: [number, number];
  polygons?: Record<string, [number, number][]>;
}) {
  const [x0, x1] = grid.x_range ?? [viewBox.x, viewBox.x + size[0]];
  const [y0, y1] = grid.y_range ?? [viewBox.y, viewBox.y + size[1]];
  const cw = (x1 - x0) / grid.cols;
  const chh = (y1 - y0) / grid.rows;
  const max = Math.max(1, ...grid.values);
  return (
    <svg
      className="heatmap"
      data-testid="heatmap"
      data-player-id={grid.player_id}
      viewBox={viewBox.attr}
      aria-label="Position heatmap"
    >
      <rect x={viewBox.x} y={viewBox.y} width={size[0]} height={size[1]} className="court-bg" />
      {grid.values.map((v, i) =>
        v > 0 ? (
          <rect
            key={i}
            className="heat-cell"
            data-testid="heatmap-cell"
            data-value={v}
            x={x0 + (i % grid.cols) * cw}
            y={y0 + Math.floor(i / grid.cols) * chh}
            width={cw}
            height={chh}
            fillOpacity={v / max}
          />
        ) : null,
      )}
      {/* Drawn last so the court outline stays readable through the densest cells. */}
      {Object.entries(polygons ?? {}).map(([name, pts]) => (
        <polygon
          key={name}
          className="court-line"
          points={pts.map((p) => p.join(",")).join(" ")}
        />
      ))}
    </svg>
  );
}

const ACTIONS = REVIEW_ACTIONS;

const COURT_FALLBACK: [number, number] = [15, 14];

export function Review({ gameId }: { gameId: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [queue, setQueue] = useState<GameEvent[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [focus, setFocus] = useState(0);
  const [busy, setBusy] = useState(false);
  // Two focusable rows: the review answers, then the heatmap's player picker.
  const [row, setRow] = useState(0);
  const [heatFocus, setHeatFocus] = useState(0);
  // §4.8: no sport-name branching — the profile says which panels this sport has
  // (`sport_ui.review`). The review queue is not in that list: every sport has events.
  const panels = useMemo(() => reviewPanels(game), [game]);
  // Empty when the sport has no heatmap panel, so the D-pad's second row disappears too.
  const heatmap = panels.has("heatmap") ? (stats?.heatmap ?? []) : [];

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
      if (a === "up") setRow(0);
      else if (a === "down") setRow(heatmap.length ? 1 : 0);
      else if (a === "left" && row === 0) setFocus((f) => Math.max(0, f - 1));
      else if (a === "left") setHeatFocus((i) => Math.max(0, i - 1));
      else if (a === "right" && row === 0)
        setFocus((f) => Math.min(ACTIONS.length - 1, f + 1));
      else if (a === "right") setHeatFocus((i) => Math.min(heatmap.length - 1, i + 1));
      else if (a === "select" && row === 0) answer(focus);
      else if (a === "back") navigate(`/tv/${gameId}`);
    },
    [focus, answer, gameId, row, heatmap.length],
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

      <section className="stats stats-grid">
        {panels.has("shot_chart") ? (
        <div className="stats-panel">
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
        </div>
        ) : null}

        {heatmap.length ? (
          <div className="stats-panel">
            <h2>Position heatmap</h2>
            <div className="heat-players" role="listbox" aria-label="Heatmap player">
              {heatmap.map((h, i) => (
                <span
                  key={h.player_id}
                  role="option"
                  aria-selected={i === heatFocus}
                  className={`chip${row === 1 && i === heatFocus ? " focused" : ""}${
                    i === heatFocus ? " active" : ""
                  }`}
                  data-testid={`heatmap-player-${h.player_id}`}
                  data-focused={row === 1 && i === heatFocus ? "true" : "false"}
                >
                  {game.players.find((p) => p.id === h.player_id)?.name ?? h.player_id}
                </span>
              ))}
            </div>
            <Heatmap
              grid={heatmap[Math.min(heatFocus, heatmap.length - 1)]}
              viewBox={viewBox}
              size={[cw, ch]}
              polygons={polygons}
            />
          </div>
        ) : null}

        {panels.has("box_score") ? (
        <div className="stats-panel">
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
        </div>
        ) : null}
      </section>

      <p className="hint">
        <b>Arrows</b> pick an answer · <b>↓</b> switches the heatmap player · <b>Enter</b> confirms
        · <b>Escape</b> goes back
      </p>
    </div>
  );
}
