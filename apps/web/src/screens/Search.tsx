// M7 semantic search on the TV: preset chips (the profile's query chips + per-player
// reels) or free text on the on-screen keyboard → POST /games/{id}/search (embeddings,
// re-ranked by the structured filter). A game without an embeddings index falls back to
// the keyword query route, and says so. Enter on a hit plays that play's window.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { TextEntryDialog } from "../components/TextEntryDialog";
import { useDpad, type DpadAction } from "../platform/keys";
import { PlayerSurface, type PlayerHandle } from "../playback/PlayerSurface";
import { useClockTime } from "../playback/clock";
import { navigate } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import { highlightQueries } from "../../../../packages/tv-core/src/display";
import { fmtClock, listWindow, type SearchResult } from "../../../../packages/tv-core/src/discovery";

const ASK_CHIP = "Type a search…";
const VISIBLE = 5;

export function Search({ gameId }: { gameId: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState("");
  const [typing, setTyping] = useState(false);
  const [row, setRow] = useState(0);
  const [col, setCol] = useState(0);
  const [index, setIndex] = useState(0);
  const [stopAt, setStopAt] = useState<number | null>(null);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const t = useClockTime(handle?.clock ?? null, 1 / 10);
  const chips = useMemo(() => [...highlightQueries(game), ASK_CHIP], [game]);
  const hits = useMemo(() => result?.results ?? [], [result]);

  const run = useCallback(
    (text: string) => {
      if (busy) return;
      setBusy(true);
      setFailed("");
      api
        .search(gameId, text)
        .then((r) => {
          setResult(r);
          setIndex(0);
          setRow(r.results.length ? 1 : 0);
        })
        .catch((e: Error) => setFailed(e.message))
        .finally(() => setBusy(false));
    },
    [gameId, busy],
  );

  useEffect(() => {
    if (handle && stopAt !== null && t >= stopAt) {
      handle.pause();
      setStopAt(null);
    }
  }, [t, stopAt, handle]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") navigate(`/tv/${gameId}`);
      else if (a === "up") setRow(0);
      else if (a === "down") setRow(hits.length ? 1 : 0);
      else if (a === "left" && row === 0) setCol((c) => Math.max(0, c - 1));
      else if (a === "right" && row === 0) setCol((c) => Math.min(chips.length - 1, c + 1));
      else if (a === "left") setIndex((i) => Math.max(0, i - 1));
      else if (a === "right") setIndex((i) => Math.min(hits.length - 1, i + 1));
      else if (a === "select" && row === 0) {
        if (chips[col] === ASK_CHIP) setTyping(true);
        else run(chips[col]);
      } else if (a === "select" && hits[index] && handle) {
        handle.seek(hits[index].t_start);
        setStopAt(hits[index].t_end);
        handle.play();
      } else if (a === "playpause") handle?.toggle();
    },
    [gameId, hits, row, chips, col, index, run, handle],
  );
  useDpad(onAction, !typing);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <div className="screen">Loading…</div>;
  const first = listWindow(index, hits.length, VISIBLE);

  return (
    <div className="screen search" data-testid="search">
      <h1>Search — {game.title}</h1>
      <div className="chips">
        {chips.map((c, i) => (
          <span
            key={c}
            className={`chip${row === 0 && i === col ? " focused" : ""}`}
            data-testid="search-chip"
            data-chip={c}
            data-focused={row === 0 && i === col ? "true" : "false"}
          >
            {c}
          </span>
        ))}
      </div>
      {busy ? <p className="dim">Searching…</p> : null}
      {failed ? <p data-testid="search-error">Search failed: {failed}</p> : null}
      {result ? (
        <p
          className="interpretation"
          data-testid="search-interpretation"
          data-fallback={result.fallback ? "true" : "false"}
        >
          “{result.query}” — {result.interpretation}
          {result.fallback
            ? " · keyword match (no search index for this game yet)"
            : " · ranked by similarity"}
        </p>
      ) : null}
      {result && hits.length === 0 ? <p data-testid="search-empty">Nothing in this game matches.</p> : null}
      {hits.length ? (
        <div className="clips-layout">
          <PlayerSurface ref={setHandle} src={api.mediaUrl(game, game.renditions.wide)} muted />
          <ol className="clip-list">
            {hits.slice(first, first + VISIBLE).map((h, k) => {
              const i = first + k;
              const on = row === 1 && i === index;
              return (
                <li
                  key={`${h.play_id}-${i}`}
                  className={`clip-card${on ? " focused" : ""}${i === index ? " current" : ""}`}
                  data-testid="search-hit"
                  data-play-id={h.play_id}
                  data-t-start={h.t_start}
                  data-focused={on ? "true" : "false"}
                  data-match={h.filter_match ? "true" : "false"}
                >
                  <div className="clip-card-row">
                    <span className="reel-index">{i + 1}</span>
                    <span className="dim">{fmtClock(h.t_start)}</span>
                    {h.filter_match ? <span className="match-badge">MATCH</span> : null}
                  </div>
                  <div className="hit-text">{h.text}</div>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}
      <p className="hint">
        <b>←/→</b> pick · <b>Enter</b> searches or plays · <b>↓</b> to the results ·{" "}
        <b>Escape</b> returns to the game
      </p>

      {typing ? (
        <TextEntryDialog
          idPrefix="search"
          title="Search for a moment"
          onCancel={() => setTyping(false)}
          onSubmit={(text) => {
            setTyping(false);
            run(text);
          }}
        />
      ) : null}
    </div>
  );
}
