// M7 advice panel: per-player insights written only from that player's own stats in this
// game (grounded templates; an LLM rephrasing ships only when the grounding check passes —
// D-52). Left/Right pick a player; Escape returns to the game.
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { useDpad, type DpadAction } from "../platform/keys";
import { navigate } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import { listWindow, type Advice as AdviceDoc } from "../../../../packages/tv-core/src/discovery";

const CHIPS = 6;

export function Advice({ gameId }: { gameId: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [focus, setFocus] = useState(0);
  const [byPlayer, setByPlayer] = useState<Record<string, AdviceDoc | string>>({});
  const players = game?.players ?? [];
  const pid = players[focus]?.id;

  useEffect(() => {
    if (!pid || byPlayer[pid]) return;
    api.getAdvice(gameId, pid).then(
      (a) => setByPlayer((m) => ({ ...m, [pid]: a })),
      (e: Error) => setByPlayer((m) => ({ ...m, [pid]: e.message })),
    );
  }, [gameId, pid, byPlayer]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") navigate(`/tv/${gameId}`);
      else if (a === "left" || a === "up") setFocus((i) => Math.max(0, i - 1));
      else if (a === "right" || a === "down") setFocus((i) => Math.min(players.length - 1, i + 1));
    },
    [gameId, players.length],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <div className="screen">Loading…</div>;
  const doc = pid ? byPlayer[pid] : undefined;
  const first = listWindow(focus, players.length, CHIPS);

  return (
    <div className="screen advice" data-testid="advice">
      <h1>Advice — {game.title}</h1>
      <div className="chips">
        {players.slice(first, first + CHIPS).map((p, k) => (
          <span
            key={p.id}
            className={`chip${first + k === focus ? " focused active" : ""}`}
            data-testid={`advice-player-${p.id}`}
            data-focused={first + k === focus ? "true" : "false"}
          >
            {p.name ?? `#${p.id}`}
          </span>
        ))}
      </div>
      {players.length === 0 ? <p>No players in this game.</p> : null}
      {typeof doc === "string" ? <p data-testid="advice-error">No advice: {doc}</p> : null}
      {doc && typeof doc !== "string" ? (
        <section
          className="advice-panel"
          data-testid="advice-panel"
          data-player-id={doc.player_id}
          data-source={doc.source}
        >
          <h2>{doc.name ?? `#${doc.player_id}`}</h2>
          <ul>
            {doc.lines.map((ln, i) => (
              <li key={i} data-testid="advice-line">
                {ln}
              </li>
            ))}
          </ul>
          <p className="dim" data-testid="advice-source">
            Auto-detected ·{" "}
            {doc.source === "llm"
              ? "rephrased by a local model and checked against the stats"
              : "written from this player's stats in this game"}
          </p>
        </section>
      ) : !doc && pid ? (
        <p className="dim">Loading…</p>
      ) : null}
      <p className="hint">
        <b>←/→</b> pick a player · <b>Escape</b> returns to the game
      </p>
    </div>
  );
}
