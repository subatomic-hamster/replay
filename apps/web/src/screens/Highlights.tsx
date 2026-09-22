// H1 per-player reel, H2 top plays, H3 query chips + free text, H4 phone companion.
// Everything goes through POST /games/{id}/query so the TV never re-implements the
// query grammar — a chip, the on-screen keyboard and the phone all call the same route.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { useDpad, type DpadAction } from "../platform/keys";
import { PlayerSurface, type PlayerHandle } from "../playback/PlayerSurface";
import { useClockTime } from "../playback/clock";
import { FALLBACK_CHIPS, QueryChips } from "../components/QueryChips";
import { TextEntryDialog } from "../components/TextEntryDialog";
import { navigate, useLocation } from "../router";
import { storedSession, useSessionMessages } from "../session";
import { ApiErrorBanner, fmtDuration, useAsync } from "../ui";
import type { Clip } from "../api/types";

/** H3 free text: the last chip opens the on-screen keyboard instead of running a query. */
const ASK_CHIP = "Ask…";

export function Highlights({ gameId }: { gameId: string }) {
  const { params } = useLocation();
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [session] = useState(storedSession);
  const [asking, setAsking] = useState(false);
  const lastPushed = useRef<string | null>(null);
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
    return [...perPlayer, ...chips, ASK_CHIP];
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
          if (row === 0 && queries[col] === ASK_CHIP) setAsking(true);
          else if (row === 0) run(queries[col]);
          else playClip(index);
          break;
        case "pair":
          navigate(`/tv/pair?game=${gameId}`);
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
  useDpad(onAction, !asking);

  // S-31: a query pushed from the paired phone, and the ?q= the Pair screen navigates
  // with. Both land here so the phone needs no knowledge of the query grammar.
  useSessionMessages(
    session?.id,
    useCallback(
      (msg) => {
        if (msg.type === "query" && msg.text) run(msg.text);
      },
      [run],
    ),
  );

  const pushed = params.get("q");
  useEffect(() => {
    if (!game || !pushed || lastPushed.current === pushed) return;
    lastPushed.current = pushed;
    run(pushed);
  }, [game, pushed, run]);

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
        <div className="reel-layout">
          <PlayerSurface
            ref={setHandle}
            src={api.mediaUrl(game, game.renditions.wide)}
            muted
          />
          <div>
            <span className="clip-counter" data-testid="clip-counter">
              clip <b>{index + 1}</b>/<b>{clips.length}</b>
            </span>
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
                  <span className="reel-index">{i + 1}</span>
                  <span className="reel-label">{c.label ?? "clip"}</span>
                  <span className="reel-time">{fmtDuration(c.t_start)}</span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      ) : null}

      <p className="hint">
        <b>Arrows</b> move · <b>Enter</b> plays · <b>p</b> pairs a phone · <b>Escape</b> goes back
      </p>

      {asking ? (
        <TextEntryDialog
          idPrefix="ask"
          title="Ask for a highlight"
          onCancel={() => setAsking(false)}
          onSubmit={(text) => {
            setAsking(false);
            run(text);
          }}
        />
      ) : null}
    </div>
  );
}
