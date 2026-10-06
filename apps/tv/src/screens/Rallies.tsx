// M11 rally browser + condensed game (D-46). Reached from Watch's "Rallies" item, which
// shows only when the game has rallies — no sport-name branch.
//
// Row 0 tabs: In order · Longest · Condensed game. Row 1: the rallies. Select on a rally
// plays it (on the condensed video when that tab is on, else on the wide shot, pausing
// at its end); Select on "Condensed game" plays it, or asks for the render first.
import { useCallback, useEffect, useMemo, useState } from "react";
import { StyleSheet, View } from "react-native";
import {
  fmtClock,
  listWindow,
  rallyAtCondensed,
  rallyOrder,
  type Rally,
  type RallyDoc,
} from "../../../../packages/tv-core/src/discovery";
import { api } from "../api";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { PlayerSurface, useClockTime, type PlayerHandle } from "../playback/PlayerSurface";
import { color, focusRing, font, px } from "../theme";
import { ApiErrorBanner, Hint, Loading, Pill, T, styles as ui, useAsync } from "../ui";

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
  const list = useMemo(() => (doc ? rallyOrder(doc, TABS[tab] === "Longest" ? "longest" : "time") : []), [doc, tab]);

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
      if (a === "back") navigate({ name: "watch", gameId });
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
  if (!game || !doc) return <Loading />;

  const n = doc.rallies.length;
  const current = condensedOn ? rallyAtCondensed(doc.rallies, t) : (list.find((r) => stopAt !== null && r.t_end === stopAt) ?? null);
  const src = condensedOn && doc.condensed.url ? doc.condensed.url : api.mediaUrl(game, game.renditions.wide);
  const first = listWindow(focus, list.length, VISIBLE);

  return (
    <View style={ui.screen} testID="rallies" dataSet={{ condensed: condensedOn ? "true" : "false" }}>
      <T style={ui.h1}>Rallies</T>
      <View style={styles.row}>
        {TABS.map((label, i) => (
          <Pill
            key={label}
            label={label}
            focused={row === 0 && i === tab}
            active={i === tab}
            testID={`rally-tab-${label.split(" ")[0].toLowerCase()}`}
          />
        ))}
        <T style={styles.summary} testID="rally-summary">
          {n} rallies · {Math.round(doc.rally_s ?? 0)} s of play in {fmtClock(doc.game_s ?? 0)}
        </T>
      </View>
      {TABS[tab] === "Condensed game" && status !== "done" ? (
        <T testID="condensed-status" dataSet={{ status }} style={{ color: color.dim }}>
          {status === "none" || status === "missing"
            ? "Not rendered yet — Select renders the condensed game (rallies only)."
            : status === "queued" || status === "running"
              ? "Rendering the condensed game…"
              : `Render failed${doc.condensed.error ? `: ${doc.condensed.error}` : ""}`}
        </T>
      ) : null}

      <View style={styles.layout}>
        <View style={{ width: px(1000) }}>
          <PlayerSurface ref={setHandle} src={src} muted>
            {current ? (
              // Broadcast-package counter (D-46): "RALLY n / N · X SHOTS · Y S".
              <View style={styles.counter} testID="rally-counter" dataSet={{ rally: current.id }}>
                <T style={styles.counterText}>
                  RALLY {current.n} / {n}
                  {current.shots ? ` · ${current.shots} SHOTS` : ""} · {Math.round(current.duration_s)} S
                </T>
              </View>
            ) : null}
          </PlayerSurface>
        </View>
        <View style={styles.list}>
          {list.slice(first, first + VISIBLE).map((r, k) => {
            const i = first + k;
            const on = row === 1 && i === focus;
            return (
              <View
                key={r.id}
                testID="rally-row"
                dataSet={{ rallyId: r.id, focused: on ? "true" : "false" }}
                style={[styles.item, focusRing(on), current?.id === r.id && { backgroundColor: color.raised }]}
              >
                <T style={styles.num}>{r.n}</T>
                <T style={{ flex: 1 }}>
                  {r.duration_s.toFixed(1)} s{r.shots ? ` · ${r.shots} shots` : ""}
                </T>
                <T style={{ color: color.dim }}>{fmtClock(r.t_start)}</T>
              </View>
            );
          })}
        </View>
      </View>
      <Hint>Left/Right pick · Down to the rallies · Select plays · Back returns to the game</Hint>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", flexWrap: "wrap" },
  summary: { color: color.dim, marginLeft: px(16) },
  layout: { flexDirection: "row", marginTop: px(16) },
  list: { flex: 1, marginLeft: px(32) },
  item: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: px(16),
    paddingVertical: px(8),
    borderRadius: px(10),
    marginBottom: px(8),
    backgroundColor: color.panel,
  },
  num: { width: px(56), color: color.accent, fontSize: font.body, fontWeight: "800" },
  counter: {
    position: "absolute",
    left: px(24),
    bottom: px(24),
    paddingHorizontal: px(18),
    paddingVertical: px(6),
    borderLeftWidth: px(8),
    borderLeftColor: color.accent,
    backgroundColor: color.scrim,
  },
  counterText: { fontSize: font.body, fontWeight: "800", letterSpacing: px(1) },
});
