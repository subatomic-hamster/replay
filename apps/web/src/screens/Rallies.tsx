// M11 rally browser + condensed game (D-46). Reached from Watch's "Rallies" item, which
// shows only when the game has rallies — no sport-name branch.
//
// Row 0 tabs: In order · Longest · Condensed game. Row 1: the rallies. Enter on a rally
// plays it (on the condensed video when that tab is on, else on the wide shot, pausing at
// its end); Enter on "Condensed game" plays it, or asks for the render first.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { useDpad, type DpadAction } from "../platform/keys";
import { PlayerSurface, type PlayerHandle } from "../playback/PlayerSurface";
import { useClockTime } from "../playback/clock";
import { navigate } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import {
  fmtClock,
  listWindow,
  rallyAtCondensed,
  rallyOrder,
  type Rally,
  type RallyDoc,
} from "../../../../packages/tv-core/src/discovery";

const TABS = ["In order", "Longest", "Condensed game"] as const;
const POLL_MS = 1000;
const VISIBLE = 8;

export function Rallies({ gameId }: { gameId: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [doc, setDoc] = useState<RallyDoc | null>(null);
  const [tab, setTab] = useState(0);
  const [row, setRow] = useState(0);
  const [focus, setFocus] = useState(0);
  const [stopAt, setStopAt] = useState<number | null>(null);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const t = useClockTime(handle?.clock ?? null, 1 / 10);

  const load = useCallback(() => api.getRallies(gameId).then(setDoc, () => setDoc(null)), [gameId]);
  useEffect(() => {
    load();
  }, [load]);

  const status = doc?.condensed.status ?? "none";
  const condensedOn = TABS[tab] === "Condensed game" && status === "done" && !!doc?.condensed.url;
  const list = useMemo(
    () => (doc ? rallyOrder(doc, TABS[tab] === "Longest" ? "longest" : "time") : []),
    [doc, tab],
  );

  // The render runs as an API job: poll until it lands.
  useEffect(() => {
    if (status !== "queued" && status !== "running") return;
    const timer = setTimeout(load, POLL_MS);
    return () => clearTimeout(timer);
  }, [status, load, doc]);

  // A single rally on the wide shot stops at its end.
  useEffect(() => {
    if (handle && stopAt !== null && t >= stopAt) {
      handle.pause();
      setStopAt(null);
    }
  }, [t, stopAt, handle]);

  const play = useCallback(
    (r: Rally) => {
      if (!handle) return;
      if (condensedOn && r.condensed_t != null) {
        handle.seek(r.condensed_t);
        setStopAt(null);
      } else {
        handle.seek(r.t_start);
        setStopAt(r.t_end);
      }
      handle.play();
    },
    [handle, condensedOn],
  );

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") navigate(`/tv/${gameId}`);
      else if (a === "up") setRow(0);
      else if (a === "down") setRow(list.length ? 1 : 0);
      else if (a === "left" && row === 0) setTab((i) => Math.max(0, i - 1));
      else if (a === "right" && row === 0) setTab((i) => Math.min(TABS.length - 1, i + 1));
      else if (a === "left") setFocus((i) => Math.max(0, i - 1));
      else if (a === "right") setFocus((i) => Math.min(list.length - 1, i + 1));
      else if (a === "select" && row === 1 && list[focus]) play(list[focus]);
      else if (a === "select" && TABS[tab] === "Condensed game") {
        if (status === "done") {
          handle?.seek(0);
          handle?.play();
        } else if (status === "none" || status === "missing" || status === "failed" || status === "error") {
          api.renderCondensed(gameId).then(load, load);
        }
      } else if (a === "playpause") handle?.toggle();
    },
    [gameId, list, row, focus, tab, status, play, handle, load],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game || !doc) return <div className="screen">Loading…</div>;

  const n = doc.rallies.length;
  const current = condensedOn
    ? rallyAtCondensed(doc.rallies, t)
    : (list.find((r) => stopAt !== null && r.t_end === stopAt) ?? null);
  const src =
    condensedOn && doc.condensed.url ? doc.condensed.url : api.mediaUrl(game, game.renditions.wide);
  const first = listWindow(focus, list.length, VISIBLE);

  return (
    <div className="screen rallies" data-testid="rallies" data-condensed={condensedOn ? "true" : "false"}>
      <h1>Rallies — {game.title}</h1>
      <div className="chips">
        {TABS.map((label, i) => (
          <span
            key={label}
            className={`chip${row === 0 && i === tab ? " focused" : ""}${i === tab ? " active" : ""}`}
            data-testid={`rally-tab-${label.split(" ")[0].toLowerCase()}`}
            data-focused={row === 0 && i === tab ? "true" : "false"}
          >
            {label}
          </span>
        ))}
        <span className="dim rally-summary" data-testid="rally-summary">
          {n} rallies · {Math.round(doc.rally_s ?? 0)} s of play in {fmtClock(doc.game_s ?? 0)}
        </span>
      </div>
      {TABS[tab] === "Condensed game" && status !== "done" ? (
        <p className="dim" data-testid="condensed-status" data-status={status}>
          {status === "none" || status === "missing"
            ? "Not rendered yet — Enter renders the condensed game (rallies only)."
            : status === "queued" || status === "running"
              ? "Rendering the condensed game…"
              : `Render failed${doc.condensed.error ? `: ${doc.condensed.error}` : ""}`}
        </p>
      ) : null}

      <div className="clips-layout">
        <PlayerSurface ref={setHandle} src={src} muted>
          {current ? (
            // Broadcast-package counter (D-46): "RALLY n / N · X SHOTS · Y S".
            <div className="rally-counter" data-testid="rally-counter" data-rally={current.id}>
              RALLY {current.n} / {n}
              {current.shots ? ` · ${current.shots} SHOTS` : ""} · {Math.round(current.duration_s)} S
            </div>
          ) : null}
        </PlayerSurface>
        <ol className="clip-list">
          {list.slice(first, first + VISIBLE).map((r, k) => {
            const i = first + k;
            const on = row === 1 && i === focus;
            return (
              <li
                key={r.id}
                className={`reel-clip${on ? " focused" : ""}${current?.id === r.id ? " current" : ""}`}
                data-testid="rally-row"
                data-rally-id={r.id}
                data-focused={on ? "true" : "false"}
              >
                <span className="reel-index">{r.n}</span>
                <span>
                  {r.duration_s.toFixed(1)} s{r.shots ? ` · ${r.shots} shots` : ""}
                </span>
                <span className="reel-time">{fmtClock(r.t_start)}</span>
              </li>
            );
          })}
        </ol>
      </div>
      <p className="hint">
        <b>←/→</b> pick · <b>↓</b> to the rallies · <b>Enter</b> plays · <b>Escape</b> returns to the
        game
      </p>
    </div>
  );
}
