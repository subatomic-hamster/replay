// H1 per-player reel, H2 top plays, H3 query chips. Everything goes through
// POST /games/{id}/query so the TV never re-implements the query grammar.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { MOCK_API } from "../config";
import { useDpad, type DpadAction } from "../platform/keys";
import { PlayerSurface, type PlayerHandle } from "../playback/PlayerSurface";
import { useClockTime } from "../playback/clock";
import { FALLBACK_CHIPS, QueryChips } from "../components/QueryChips";
import { navigate } from "../router";
import { ApiErrorBanner, fmtDuration, useAsync } from "../ui";
import type { Clip } from "../api/types";

export function Highlights({ gameId }: { gameId: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [interpretation, setInterpretation] = useState("");
  const [activeChip, setActiveChip] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [row, setRow] = useState(0);
  const [col, setCol] = useState(0);
  const pending = useRef(false);

  const t = useClockTime(handle?.clock ?? null, 1 / 10);

  const queries = useMemo(() => {
    const chips = game?.sport_ui?.chips?.length ? game.sport_ui.chips : FALLBACK_CHIPS;
    const perPlayer = (game?.players ?? [])
      .filter((p) => p.name)
      .map((p) => `${p.name} — all shots`);
    return [...perPlayer, ...chips];
  }, [game]);

  const run = useCallback(
    (text: string) => {
      if (!game || pending.current) return;
      pending.current = true;
      setActiveChip(text);
      api
        .query(game.id, text)
        .then((r) => {
          setClips(r.clips);
          setInterpretation(r.interpretation);
          setIndex(0);
          setRow(r.clips.length ? 1 : 0);
        })
        .catch(() => {
          setClips([]);
          setInterpretation("Query failed");
        })
        .finally(() => {
          pending.current = false;
        });
    },
    [game],
  );

  const playClip = useCallback(
    (i: number) => {
      if (!handle || !clips?.[i]) return;
      setIndex(i);
      handle.seek(clips[i].t_start);
      handle.play();
    },
    [handle, clips],
  );

  // Auto-advance at each clip's t_end (S-27).
  useEffect(() => {
    if (!handle || !clips?.length) return;
    const clip = clips[index];
    if (!clip || t < clip.t_end) return;
    if (index + 1 < clips.length) playClip(index + 1);
    else handle.pause();
  }, [t, handle, clips, index, playClip]);

  const onAction = useCallback(
    (a: DpadAction) => {
      const rows = clips?.length ? 2 : 1;
      switch (a) {
        case "up":
          setRow((r) => Math.max(0, r - 1));
          break;
        case "down":
          setRow((r) => Math.min(rows - 1, r + 1));
          break;
        case "left":
          if (row === 0) setCol((c) => Math.max(0, c - 1));
          else setIndex((i) => Math.max(0, i - 1));
          break;
        case "right":
          if (row === 0) setCol((c) => Math.min(queries.length - 1, c + 1));
          else setIndex((i) => Math.min((clips?.length ?? 1) - 1, i + 1));
          break;
        case "select":
          if (row === 0) run(queries[col]);
          else playClip(index);
          break;
        case "playpause":
          handle?.toggle();
          break;
        case "back":
          navigate(`/tv/${gameId}`);
          break;
        default:
          break;
      }
    },
    [row, col, index, queries, clips, run, playClip, handle, gameId],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <div className="screen">Loading…</div>;

  return (
    <div className="screen highlights">
      <h1>Highlights — {game.title}</h1>
      <QueryChips chips={queries} focusIndex={row === 0 ? col : -1} activeChip={activeChip} />

      {interpretation ? (
        <p className="interpretation" data-testid="query-interpretation">
          {interpretation}
        </p>
      ) : null}

      {clips && clips.length === 0 ? (
        <p data-testid="no-clips">No clips match that query.</p>
      ) : null}

      {clips && clips.length > 0 ? (
        <>
          <PlayerSurface
            ref={setHandle}
            src={api.mediaUrl(game, game.renditions.wide)}
            muted={MOCK_API}
          />
          <p className="clip-counter" data-testid="clip-counter">
            clip {index + 1}/{clips.length}
          </p>
          <ol className="reel">
            {clips.map((c, i) => (
              <li
                key={`${c.event_id ?? i}`}
                className={`reel-clip${i === index ? " focused" : ""}`}
                data-testid="reel-clip"
                data-event-id={c.event_id}
                data-t-start={c.t_start}
                data-focused={row === 1 && i === index ? "true" : "false"}
              >
                {i + 1}. {c.label ?? "clip"} · {fmtDuration(c.t_start)}
              </li>
            ))}
          </ol>
        </>
      ) : null}

      <p className="hint">Arrows move · Enter plays · Escape goes back</p>
    </div>
  );
}
