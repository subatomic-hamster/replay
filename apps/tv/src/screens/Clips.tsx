// M5 "Replay, clip that" on the TV: every clip the gesture / voice / phone-tap triggers
// cut (attribution + trigger type), a D-pad trim UI, and the 9:16 share export (D-47).
//
// List: Up/Down pick a clip (it previews, looping); Select opens the trimmer; Back → Watch.
// Trimmer rows: START handle, END handle, actions. Up/Down move between rows, Left/Right
// nudge the handle by TRIM_STEP_S (the picture jumps to that edge, paused) or pick an
// action; Select on a handle plays the trimmed window; Back leaves without saving.
import { useCallback, useEffect, useMemo, useState } from "react";
import { StyleSheet, View } from "react-native";
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
import { api } from "../api";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import {
  PlayerSurface,
  useClockTime,
  type PlayerHandle,
} from "../playback/PlayerSurface";
import { color, focusRing, font, px, radius } from "../theme";
import {
  ApiErrorBanner,
  Hint,
  Loading,
  Pill,
  T,
  styles as ui,
  useAsync,
} from "../ui";

const ACTIONS = ["Save trim", "Share 9:16", "Reset"] as const;
const actionId = (a: string) => `trim-${a.split(" ")[0].toLowerCase()}`;
const CONTEXT_S = 5;
// a 9:16 render takes about a minute: no need to ask the API every second (D-87)
const POLL_MS = 3000;
const VISIBLE = 5;

type Win = { t_start: number; t_end: number };

export function Clips({ gameId }: { gameId: string }) {
  const {
    data: game,
    error,
    reload,
  } = useAsync(() => api.getGame(gameId), [gameId]);
  const { data: loaded, error: listError } = useAsync(
    () => Promise.all([api.listClips(gameId), api.listTriggers(gameId)]),
    [gameId],
  );
  const [clips, setClips] = useState<PlayClip[]>([]);
  const triggers = useMemo(
    () =>
      Object.fromEntries((loaded?.[1] ?? []).map((t) => [t.id, t])) as Record<
        string,
        Trigger
      >,
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
    if (t >= playing.t_end || t < playing.t_start - 0.5)
      handle.seek(playing.t_start);
  }, [t, handle, playing]);

  // 9:16 export: poll until the render lands.
  useEffect(() => {
    if (!exp || !exportPending(exp)) return;
    const timer = setTimeout(() => {
      api
        .getVertical(gameId, exp.id)
        .then(setExp, (e: Error) => setNote(`Export failed: ${e.message}`));
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
        // Share what is on screen: save a changed trim first, so the export (which
        // reads the clip) matches it.
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
        if (a === "back") navigate({ name: "watch", gameId });
        else if (a === "up" || a === "left")
          setFocus((i) => Math.max(0, i - 1));
        else if (a === "down" || a === "right")
          setFocus((i) => Math.min(clips.length - 1, i + 1));
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
        const next = nudgeTrim(
          win,
          edge,
          a === "right" ? TRIM_STEP_S : -TRIM_STEP_S,
          duration,
        );
        setWin(next);
        handle?.pause();
        handle?.seek(edge === "start" ? next.t_start : next.t_end - 0.1);
      } else if (a === "left") setAct((i) => Math.max(0, i - 1));
      else if (a === "right")
        setAct((i) => Math.min(ACTIONS.length - 1, i + 1));
      else if (a === "select" && row === 2) runAction(act);
      else if (a === "select" || a === "playpause") {
        if (a === "select") handle?.seek(win.t_start);
        handle?.toggle();
      }
    },
    [
      exp,
      win,
      gameId,
      clips.length,
      clip,
      handle,
      row,
      duration,
      act,
      runAction,
    ],
  );
  useDpad(onAction);

  if (error || listError)
    return (
      <ApiErrorBanner error={(error ?? listError) as Error} onRetry={reload} />
    );
  if (!game || !loaded) return <Loading />;

  // Trim bar context: the clip ± CONTEXT_S, widened to whatever the handles reach.
  const ctx0 = playing
    ? Math.max(0, Math.min(playing.t_start, (clip?.t_start ?? 0) - CONTEXT_S))
    : 0;
  const ctx1 = playing
    ? Math.min(
        duration || playing.t_end + CONTEXT_S,
        Math.max(playing.t_end, (clip?.t_end ?? 0) + CONTEXT_S),
      )
    : 1;
  const pct = (v: number) =>
    `${((v - ctx0) / Math.max(1e-6, ctx1 - ctx0)) * 100}%` as const;
  const first = listWindow(focus, clips.length, VISIBLE);

  return (
    <View
      style={ui.safe}
      testID="clips"
      dataSet={{ trimming: win ? "true" : "false" }}
    >
      <T style={ui.h1}>Clips</T>
      {clips.length === 0 ? (
        <View testID="clips-empty">
          <T>No clips yet.</T>
          <Hint>
            Cross your arms in an X overhead, say “Replay, clip that”, or tap
            Clip on the paired phone.
          </Hint>
        </View>
      ) : (
        <View style={styles.layout}>
          <View style={{ width: px(1000) }}>
            <PlayerSurface
              ref={setHandle}
              src={api.mediaUrl(game, game.renditions.wide)}
              muted
            />
            {win ? (
              <View style={styles.trim} testID="trim-panel">
                <View style={styles.bar} testID="trim-bar">
                  <View
                    style={[
                      styles.sel,
                      {
                        left: pct(win.t_start),
                        width: `${((win.t_end - win.t_start) / Math.max(1e-6, ctx1 - ctx0)) * 100}%`,
                      },
                    ]}
                  />
                  <View
                    style={[
                      styles.playhead,
                      { left: pct(Math.min(Math.max(t, ctx0), ctx1)) },
                    ]}
                  />
                  <View
                    style={[
                      styles.handle,
                      focusRing(row === 0),
                      { left: pct(win.t_start) },
                    ]}
                  />
                  <View
                    style={[
                      styles.handle,
                      focusRing(row === 1),
                      { left: pct(win.t_end) },
                    ]}
                  />
                </View>
                <View style={styles.handles}>
                  <Pill
                    label={`START ${fmtClock(win.t_start)}`}
                    focused={row === 0}
                    testID="trim-start"
                    dataSet={{ t: win.t_start }}
                  />
                  <Pill
                    label={`END ${fmtClock(win.t_end)}`}
                    focused={row === 1}
                    testID="trim-end"
                    dataSet={{ t: win.t_end }}
                  />
                  <T style={styles.len} testID="trim-length">
                    {(win.t_end - win.t_start).toFixed(1)} s
                  </T>
                </View>
                <View style={styles.handles}>
                  {ACTIONS.map((a, i) => (
                    <Pill
                      key={a}
                      label={a}
                      focused={row === 2 && i === act}
                      testID={actionId(a)}
                    />
                  ))}
                </View>
                {note ? (
                  <T testID="trim-note" style={{ color: color.dim }}>
                    {note}
                  </T>
                ) : null}
              </View>
            ) : null}
          </View>
          <View style={styles.list}>
            {clips.slice(first, first + VISIBLE).map((c, k) => {
              const i = first + k;
              const tr = triggers[c.trigger_id];
              const on = i === focus;
              return (
                <View
                  key={c.id}
                  testID="clip-card"
                  dataSet={{
                    clipId: c.id,
                    trigger: tr?.type ?? "",
                    focused: on && !win ? "true" : "false",
                    tStart: c.t_start,
                    tEnd: c.t_end,
                  }}
                  style={[
                    styles.card,
                    focusRing(on && !win),
                    on && { backgroundColor: color.raised },
                  ]}
                >
                  <View style={styles.cardRow}>
                    <View style={styles.badge}>
                      <T style={styles.badgeText} testID="clip-trigger">
                        {triggerLabel(tr?.type)}
                      </T>
                    </View>
                    <T
                      style={{ flex: 1 }}
                      numberOfLines={1}
                      testID="clip-attribution"
                    >
                      {attributionText(c, name)}
                    </T>
                  </View>
                  <T style={styles.meta}>
                    {fmtClock(c.t_start)}–{fmtClock(c.t_end)} ·{" "}
                    {(c.t_end - c.t_start).toFixed(1)} s
                    {clipEdited(c) ? " · edited" : ""}
                  </T>
                  {tr?.transcript ? (
                    <T style={styles.meta}>“{tr.transcript}”</T>
                  ) : null}
                </View>
              );
            })}
          </View>
        </View>
      )}
      <Hint>
        {win
          ? "Up/Down pick start, end or an action · Left/Right nudge ½ s · Select runs · Back cancels"
          : "Up/Down pick a clip · Select trims and shares · Back returns to the game"}
      </Hint>

      {exp ? <ExportPanel exp={exp} /> : null}
    </View>
  );
}

/** The 9:16 export: status while it renders, then the portrait preview and its link. */
function ExportPanel({ exp }: { exp: VerticalExport }) {
  const done = exp.status === "done" && !!exp.url;
  const [preview, setPreview] = useState<PlayerHandle | null>(null);
  useEffect(() => preview?.play(), [preview]);
  return (
    <View style={styles.exportScrim}>
      <View
        style={styles.exportPanel}
        testID="export-panel"
        dataSet={{ status: exp.status, exportId: exp.id }}
      >
        <T style={ui.h2}>Share 9:16</T>
        {done && exp.url ? (
          <View style={{ flexDirection: "row" }}>
            <View style={{ width: px(320) }} testID="vertical-preview">
              <PlayerSurface
                src={exp.url}
                muted
                loop
                aspect={9 / 16}
                ref={setPreview}
              />
            </View>
            <View style={{ marginLeft: px(32), flex: 1 }}>
              {exp.caption ? <T>{exp.caption}</T> : null}
              <T style={{ color: color.dim, marginTop: px(16) }}>
                Download on your phone:
              </T>
              <T testID="export-url" style={{ fontSize: font.small }}>
                {exp.url}
              </T>
            </View>
          </View>
        ) : (
          <T testID="export-status">
            {exp.status === "failed" || exp.status === "error"
              ? `Export failed${exp.error ? `: ${exp.error}` : ""}`
              : exp.status === "none" || exp.status === "missing"
                ? "The exported file is gone. Back, then Select to render it again."
                : "Rendering the vertical cut…"}
          </T>
        )}
        <Hint>Back closes</Hint>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  layout: { flexDirection: "row" },
  list: { flex: 1, marginLeft: px(32) },
  card: {
    paddingHorizontal: px(20),
    paddingVertical: px(10),
    borderRadius: px(12),
    marginBottom: px(12),
    backgroundColor: color.panel,
  },
  cardRow: { flexDirection: "row", alignItems: "center" },
  // the fill on a View, not the Text: T lifts its glyphs to centre the capitals, and a
  // fill on the Text would move with them
  badge: {
    backgroundColor: color.accent,
    paddingHorizontal: px(12),
    borderRadius: radius.chip,
    marginRight: px(16),
  },
  badgeText: {
    color: color.onAccent,
    fontWeight: "800",
    fontSize: font.small,
    lineHeight: px(34),
  },
  meta: { color: color.dim, fontSize: font.small, marginTop: px(4) },
  trim: { marginTop: px(20) },
  bar: {
    height: px(36),
    backgroundColor: color.raised,
    borderRadius: px(6),
    justifyContent: "center",
  },
  sel: {
    position: "absolute",
    top: 0,
    bottom: 0,
    backgroundColor: "rgba(255, 176, 32, 0.35)",
  },
  playhead: {
    position: "absolute",
    top: -px(6),
    bottom: -px(6),
    width: px(4),
    marginLeft: -px(2),
    backgroundColor: color.fg,
  },
  handle: {
    position: "absolute",
    top: -px(8),
    bottom: -px(8),
    width: px(18),
    marginLeft: -px(9),
    borderRadius: px(4),
    backgroundColor: color.accent,
  },
  handles: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: px(16),
    flexWrap: "wrap",
  },
  len: { marginLeft: px(8), fontVariant: ["tabular-nums"] },
  exportScrim: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    backgroundColor: "rgba(5, 7, 10, 0.8)",
    alignItems: "center",
    justifyContent: "center",
  },
  exportPanel: {
    width: px(1100),
    padding: px(40),
    borderRadius: px(16),
    backgroundColor: color.panel,
  },
});
