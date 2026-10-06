// M5 "Replay, clip that" on the TV: every clip the gesture / voice / phone-tap triggers
// cut (attribution + trigger type), a D-pad trim UI, and the 9:16 share export (D-47).
//
// List: Up/Down pick a clip (it previews, looping); Enter opens the trimmer; Escape → Watch.
// Trimmer rows: START handle, END handle, actions. Up/Down move between rows, Left/Right
// nudge the handle by TRIM_STEP_S (the picture jumps to that edge, paused) or pick an
// action; Enter on a handle plays the trimmed window; Escape leaves without saving.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { useDpad, type DpadAction } from "../platform/keys";
import { PlayerSurface, type PlayerHandle } from "../playback/PlayerSurface";
import { useClockTime } from "../playback/clock";
import { navigate } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import {
  attributionText,
  clipEdited,
  exportPending,
  fmtClock,
  listWindow,
  nudgeTrim,
  TRIM_STEP_S,
  triggerLabel,
  type PlayClip,
  type Trigger,
  type VerticalExport,
} from "../../../../packages/tv-core/src/discovery";

const ACTIONS = ["Save trim", "Share 9:16", "Reset"] as const;
const actionId = (a: string) => `trim-${a.split(" ")[0].toLowerCase()}`;
const CONTEXT_S = 5;
const POLL_MS = 1000;
const VISIBLE = 5;

type Win = { t_start: number; t_end: number };

export function Clips({ gameId }: { gameId: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const { data: loaded, error: listError } = useAsync(
    () => Promise.all([api.listClips(gameId), api.listTriggers(gameId)]),
    [gameId],
  );
  const [clips, setClips] = useState<PlayClip[]>([]);
  const triggers = useMemo(
    () => Object.fromEntries((loaded?.[1] ?? []).map((t) => [t.id, t])) as Record<string, Trigger>,
    [loaded],
  );
  const [focus, setFocus] = useState(0);
  const [win, setWin] = useState<Win | null>(null); // the trimmer is open
  const [row, setRow] = useState(0);
  const [act, setAct] = useState(0);
  const [note, setNote] = useState("");
  const [exp, setExp] = useState<VerticalExport | null>(null);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const t = useClockTime(handle?.clock ?? null, 1 / 20);

  useEffect(() => {
    if (loaded) setClips([...loaded[0]].sort((a, b) => a.t_start - b.t_start));
  }, [loaded]);

  const clip = clips[focus];
  const playing: Win | null = win ?? clip ?? null;
  const duration = handle?.duration() || game?.video.duration_s || 0;
  const name = useCallback(
    (pid: string) => game?.players.find((p) => p.id === pid)?.name ?? `#${pid}`,
    [game],
  );

  // A new clip in focus previews from its start.
  const clipId = clip?.id;
  const clipStart = clip?.t_start;
  useEffect(() => {
    if (!handle || clipId === undefined || clipStart === undefined) return;
    handle.seek(clipStart);
    handle.play();
  }, [handle, clipId, clipStart]);

  // Loop the window that is on screen.
  useEffect(() => {
    if (!handle || !playing || handle.paused()) return;
    if (t >= playing.t_end || t < playing.t_start - 0.5) handle.seek(playing.t_start);
  }, [t, handle, playing]);

  // 9:16 export: poll until the render lands.
  useEffect(() => {
    if (!exp || !exportPending(exp)) return;
    const timer = setTimeout(() => {
      api.getVertical(gameId, exp.id).then(setExp, (e: Error) => setNote(`Export failed: ${e.message}`));
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [exp, gameId]);

  const save = useCallback(async (): Promise<PlayClip | null> => {
    if (!clip || !win) return null;
    const saved = await api.trimClip(gameId, clip.id, win.t_start, win.t_end);
    setClips((list) => list.map((c) => (c.id === saved.id ? saved : c)));
    return saved;
  }, [clip, win, gameId]);

  const runAction = useCallback(
    (i: number) => {
      if (!clip || !win) return;
      const a = ACTIONS[i];
      if (a === "Reset") {
        setWin({ t_start: clip.t_start, t_end: clip.t_end });
        setNote("");
      } else if (a === "Save trim") {
        save().then(
          () => setNote("Trim saved"),
          (e: Error) => setNote(`Not saved: ${e.message}`),
        );
      } else {
        // Share what is on screen: save a changed trim first, so the export (which reads
        // the clip) matches it.
        const dirty = win.t_start !== clip.t_start || win.t_end !== clip.t_end;
        (dirty ? save() : Promise.resolve(clip))
          .then(() => api.exportVertical(gameId, { clip_id: clip.id }))
          .then(setExp, (e: Error) => setNote(`Export failed: ${e.message}`));
      }
    },
    [clip, win, save, gameId],
  );

  const onAction = useCallback(
    (a: DpadAction) => {
      if (exp) {
        if (a === "back" || a === "select") setExp(null);
        return;
      }
      if (!win) {
        if (a === "back") navigate(`/tv/${gameId}`);
        else if (a === "up" || a === "left") setFocus((i) => Math.max(0, i - 1));
        else if (a === "down" || a === "right") setFocus((i) => Math.min(clips.length - 1, i + 1));
        else if (a === "select" && clip) {
          setWin({ t_start: clip.t_start, t_end: clip.t_end });
          setRow(0);
          setAct(0);
          setNote("");
        } else if (a === "playpause") handle?.toggle();
        return;
      }
      if (a === "back") setWin(null);
      else if (a === "up") setRow((r) => Math.max(0, r - 1));
      else if (a === "down") setRow((r) => Math.min(2, r + 1));
      else if ((a === "left" || a === "right") && row < 2) {
        const edge = row === 0 ? "start" : "end";
        const next = nudgeTrim(win, edge, a === "right" ? TRIM_STEP_S : -TRIM_STEP_S, duration);
        setWin(next);
        handle?.pause();
        handle?.seek(edge === "start" ? next.t_start : next.t_end - 0.1);
      } else if (a === "left") setAct((i) => Math.max(0, i - 1));
      else if (a === "right") setAct((i) => Math.min(ACTIONS.length - 1, i + 1));
      else if (a === "select" && row === 2) runAction(act);
      else if (a === "select" || a === "playpause") {
        if (a === "select") handle?.seek(win.t_start);
        handle?.toggle();
      }
    },
    [exp, win, gameId, clips.length, clip, handle, row, duration, act, runAction],
  );
  useDpad(onAction);

  if (error || listError)
    return <ApiErrorBanner error={(error ?? listError) as Error} onRetry={reload} />;
  if (!game || !loaded) return <div className="screen">Loading…</div>;

  // Trim bar context: the clip ± CONTEXT_S, widened to whatever the handles reach.
  const ctx0 = playing ? Math.max(0, Math.min(playing.t_start, (clip?.t_start ?? 0) - CONTEXT_S)) : 0;
  const ctx1 = playing
    ? Math.min(duration || playing.t_end + CONTEXT_S, Math.max(playing.t_end, (clip?.t_end ?? 0) + CONTEXT_S))
    : 1;
  const span = Math.max(1e-6, ctx1 - ctx0);
  const pct = (v: number) => `${((v - ctx0) / span) * 100}%`;
  const first = listWindow(focus, clips.length, VISIBLE);

  return (
    <div className="screen clips" data-testid="clips" data-trimming={win ? "true" : "false"}>
      <h1>Clips — {game.title}</h1>
      {clips.length === 0 ? (
        <div data-testid="clips-empty">
          <p>No clips yet.</p>
          <p className="hint">
            Cross your arms in an X overhead, say “Replay, clip that”, or tap Clip on the paired
            phone.
          </p>
        </div>
      ) : (
        <div className="clips-layout">
          <div>
            <PlayerSurface ref={setHandle} src={api.mediaUrl(game, game.renditions.wide)} muted />
            {win ? (
              <div className="trim" data-testid="trim-panel">
                <div className="trim-bar" data-testid="trim-bar">
                  <span
                    className="trim-sel"
                    style={{ left: pct(win.t_start), width: `${((win.t_end - win.t_start) / span) * 100}%` }}
                  />
                  <span className="trim-playhead" style={{ left: pct(Math.min(Math.max(t, ctx0), ctx1)) }} />
                  <span className={`trim-handle${row === 0 ? " focused" : ""}`} style={{ left: pct(win.t_start) }} />
                  <span className={`trim-handle${row === 1 ? " focused" : ""}`} style={{ left: pct(win.t_end) }} />
                </div>
                <div className="trim-row">
                  <span
                    className={`btn${row === 0 ? " focused" : ""}`}
                    data-testid="trim-start"
                    data-focused={row === 0 ? "true" : "false"}
                    data-t={win.t_start}
                  >
                    START {fmtClock(win.t_start)}
                  </span>
                  <span
                    className={`btn${row === 1 ? " focused" : ""}`}
                    data-testid="trim-end"
                    data-focused={row === 1 ? "true" : "false"}
                    data-t={win.t_end}
                  >
                    END {fmtClock(win.t_end)}
                  </span>
                  <span className="trim-length" data-testid="trim-length">
                    {(win.t_end - win.t_start).toFixed(1)} s
                  </span>
                </div>
                <div className="trim-row">
                  {ACTIONS.map((a, i) => (
                    <span
                      key={a}
                      className={`btn${row === 2 && i === act ? " focused" : ""}`}
                      data-testid={actionId(a)}
                      data-focused={row === 2 && i === act ? "true" : "false"}
                    >
                      {a}
                    </span>
                  ))}
                </div>
                {note ? (
                  <p className="dim" data-testid="trim-note">
                    {note}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
          <ol className="clip-list">
            {clips.slice(first, first + VISIBLE).map((c, k) => {
              const i = first + k;
              const tr = triggers[c.trigger_id];
              const on = i === focus;
              return (
                <li
                  key={c.id}
                  className={`clip-card${on ? " current" : ""}${on && !win ? " focused" : ""}`}
                  data-testid="clip-card"
                  data-clip-id={c.id}
                  data-trigger={tr?.type ?? ""}
                  data-focused={on && !win ? "true" : "false"}
                  data-t-start={c.t_start}
                  data-t-end={c.t_end}
                >
                  <div className="clip-card-row">
                    <span className="clip-badge" data-testid="clip-trigger">
                      {triggerLabel(tr?.type)}
                    </span>
                    <span className="clip-who" data-testid="clip-attribution">
                      {attributionText(c, name)}
                    </span>
                  </div>
                  <div className="dim">
                    {fmtClock(c.t_start)}–{fmtClock(c.t_end)} · {(c.t_end - c.t_start).toFixed(1)} s
                    {clipEdited(c) ? " · edited" : ""}
                  </div>
                  {tr?.transcript ? <div className="dim">“{tr.transcript}”</div> : null}
                </li>
              );
            })}
          </ol>
        </div>
      )}
      <p className="hint">
        {win ? (
          <>
            <b>↑/↓</b> start, end or an action · <b>←/→</b> nudge ½ s · <b>Enter</b> runs ·{" "}
            <b>Escape</b> cancels
          </>
        ) : (
          <>
            <b>↑/↓</b> pick a clip · <b>Enter</b> trims and shares · <b>Escape</b> returns to the
            game
          </>
        )}
      </p>

      {exp ? <ExportPanel exp={exp} /> : null}
    </div>
  );
}

/** The 9:16 export: status while it renders, then the portrait preview and its link. */
function ExportPanel({ exp }: { exp: VerticalExport }) {
  const done = exp.status === "done" && !!exp.url;
  const [preview, setPreview] = useState<PlayerHandle | null>(null);
  useEffect(() => preview?.play(), [preview]);
  return (
    <div className="export-scrim">
      <div className="export-panel" data-testid="export-panel" data-status={exp.status} data-export-id={exp.id}>
        <h2>Share 9:16</h2>
        {done && exp.url ? (
          <div className="export-body">
            <div className="vertical-preview" data-testid="vertical-preview">
              <PlayerSurface src={exp.url} muted loop aspect={9 / 16} ref={setPreview} />
            </div>
            <div>
              {exp.caption ? <p>{exp.caption}</p> : null}
              <p className="dim">Download on your phone:</p>
              <p className="export-url" data-testid="export-url">
                {exp.url}
              </p>
            </div>
          </div>
        ) : (
          <p data-testid="export-status">
            {exp.status === "failed" || exp.status === "error"
              ? `Export failed${exp.error ? `: ${exp.error}` : ""}`
              : exp.status === "none" || exp.status === "missing"
                ? "The exported file is gone. Escape, then Enter to render it again."
                : "Rendering the vertical cut…"}
          </p>
        )}
        <p className="hint">
          <b>Escape</b> closes
        </p>
      </div>
    </div>
  );
}
