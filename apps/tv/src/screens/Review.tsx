// R5 review queue, R1 shot chart, R2 heatmap, R3 box score lite — all "auto-detected".
// Which panels show comes from the profile (`sport_ui.review`), never the sport name.
import { useCallback, useEffect, useMemo, useState } from "react";
import { StyleSheet, View } from "react-native";
import {
  courtViewBox,
  REVIEW_ACTIONS,
  REVIEW_CONFIDENCE_THRESHOLD,
  reviewPanels,
} from "../../../../packages/tv-core/src/display";
import type { GameEvent, Stats } from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { CourtView, courtSize } from "../components/CourtView";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { color, font, px } from "../theme";
import { ApiErrorBanner, Hint, Loading, Pill, T, styles as ui, useAsync } from "../ui";

const CHART_W = px(440);
const CHART_H = px(420);
const HEAT_CHIPS = 4;

export function Review({ gameId }: { gameId: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [queue, setQueue] = useState<GameEvent[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [focus, setFocus] = useState(0);
  const [busy, setBusy] = useState(false);
  const [row, setRow] = useState(0);
  const [heatFocus, setHeatFocus] = useState(0);
  const panels = useMemo(() => reviewPanels(game), [game]);
  const heatmap = panels.has("heatmap") ? (stats?.heatmap ?? []) : [];

  useEffect(() => {
    if (!game) return;
    api.getEvents(game).then(
      (evs) => setQueue(evs.filter((e) => !e.confirmed && e.confidence < REVIEW_CONFIDENCE_THRESHOLD)),
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
        .patchEvent(gameId, current.id, REVIEW_ACTIONS[i].patch)
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
      else if (a === "right" && row === 0) setFocus((f) => Math.min(REVIEW_ACTIONS.length - 1, f + 1));
      else if (a === "right") setHeatFocus((i) => Math.min(heatmap.length - 1, i + 1));
      else if (a === "select" && row === 0) answer(focus);
      else if (a === "back") navigate({ name: "watch", gameId });
    },
    [focus, answer, gameId, row, heatmap.length],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <Loading />;

  const current = queue[0];
  const court = game.sport_ui?.court;
  const [cw] = courtSize(court, game.court.variant);
  const grid = heatmap[Math.min(heatFocus, heatmap.length - 1)];
  const heatStart = Math.max(0, Math.min(heatFocus - 1, heatmap.length - HEAT_CHIPS));
  const name = (pid?: string) => game.players.find((p) => p.id === pid)?.name ?? pid;

  return (
    <View style={ui.screen}>
      <T style={ui.h1} numberOfLines={1}>
        Review — {game.title}
      </T>
      <T testID="auto-detected-label" style={{ color: color.dim }}>
        All numbers below are auto-detected.
      </T>

      <View style={styles.section}>
        <T style={ui.h2}>Review queue ({queue.length})</T>
        {current ? (
          <View testID="review-item" dataSet={{ eventId: current.id, confidence: current.confidence }}>
            <T>
              {current.type} at {current.t_key.toFixed(1)}s · {name(current.player_id)} · confidence{" "}
              {current.confidence.toFixed(2)}
            </T>
            <View style={styles.row}>
              {REVIEW_ACTIONS.map((act, i) => (
                <Pill
                  key={act.label}
                  label={act.label}
                  focused={row === 0 && i === focus}
                  testID={`review-action-${act.label.toLowerCase().replace(/\s+/g, "-")}`}
                />
              ))}
            </View>
          </View>
        ) : (
          <T testID="review-empty">Nothing left to review.</T>
        )}
      </View>

      <View style={styles.panels}>
        {panels.has("shot_chart") ? (
          <View style={styles.panel}>
            <T style={ui.h2}>Shot chart</T>
            <CourtView court={court} variant={game.court.variant} width={CHART_W} maxHeight={CHART_H} testID="shot-chart">
              {(toPx, s) =>
                (stats?.shots ?? []).map((sh) => {
                  const [x, y] = toPx(sh.court[0], sh.court[1]);
                  const r = Math.max(px(8), (cw * s) / 30);
                  return (
                    <View
                      key={sh.event_id}
                      testID="shot-marker"
                      dataSet={{ made: sh.made ? "true" : "false" }}
                      style={[
                        styles.dot,
                        {
                          left: x - r,
                          top: y - r,
                          width: 2 * r,
                          height: 2 * r,
                          borderRadius: r,
                          backgroundColor: sh.made ? color.made : "transparent",
                          borderColor: sh.made ? color.made : color.missed,
                        },
                      ]}
                    />
                  );
                })
              }
            </CourtView>
          </View>
        ) : null}

        {grid ? (
          <View style={styles.panel}>
            <T style={ui.h2}>Position heatmap</T>
            {/* A sliding window of HEAT_CHIPS players around the focused one: a 10-player
                roster in one row would push the box score off a 1080p screen. */}
            <View style={styles.row}>
              {heatmap.slice(heatStart, heatStart + HEAT_CHIPS).map((h, k) => (
                <Pill
                  key={h.player_id}
                  label={name(h.player_id) ?? h.player_id}
                  focused={row === 1 && heatStart + k === heatFocus}
                  active={heatStart + k === heatFocus}
                  testID={`heatmap-player-${h.player_id}`}
                />
              ))}
            </View>
            <CourtView court={court} variant={game.court.variant} width={CHART_W} maxHeight={CHART_H} testID="heatmap">
              {(toPx) => {
                const ch = courtSize(court, game.court.variant)[1];
                const box = courtViewBox(court, cw, ch);
                const [x0, x1] = grid.x_range ?? [box.x, box.x + cw];
                const [y0, y1] = grid.y_range ?? [box.y, box.y + ch];
                const cellW = (x1 - x0) / grid.cols;
                const cellH = (y1 - y0) / grid.rows;
                const max = Math.max(1, ...grid.values);
                return grid.values.map((v, i) => {
                  if (v <= 0) return null;
                  const [ax, ay] = toPx(x0 + (i % grid.cols) * cellW, y0 + Math.floor(i / grid.cols) * cellH);
                  const [bx, by] = toPx(x0 + ((i % grid.cols) + 1) * cellW, y0 + (Math.floor(i / grid.cols) + 1) * cellH);
                  return (
                    <View
                      key={i}
                      testID="heatmap-cell"
                      dataSet={{ value: v }}
                      style={{
                        position: "absolute",
                        left: ax,
                        top: ay,
                        width: bx - ax,
                        height: by - ay,
                        backgroundColor: color.accent,
                        opacity: (0.85 * v) / max,
                      }}
                    />
                  );
                });
              }}
            </CourtView>
          </View>
        ) : null}

        {panels.has("box_score") ? (
          <View style={styles.panel}>
            <T style={ui.h2}>Box score lite</T>
            <View style={styles.tr}>
              {["Player", "Att", "Made", "Conf"].map((h, i) => (
                <T key={h} style={[styles.td, i === 0 && styles.tdName, { color: color.dim }]}>
                  {h}
                </T>
              ))}
            </View>
            {(stats?.box_score ?? []).map((r) => (
              <View key={r.player_id} style={styles.tr} testID="box-score-row" dataSet={{ playerId: r.player_id }}>
                <T style={[styles.td, styles.tdName]} numberOfLines={1}>
                  {r.name ?? r.player_id}
                </T>
                <T style={styles.td}>{r.attempts}</T>
                <T style={styles.td}>{r.makes}</T>
                <T style={styles.td}>{r.confidence ?? "—"}</T>
              </View>
            ))}
          </View>
        ) : null}
      </View>

      <Hint>Arrows pick an answer · Down switches the heatmap player · Select confirms · Back returns</Hint>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: px(24) },
  row: { flexDirection: "row", flexWrap: "wrap", marginTop: px(12) },
  panels: { flexDirection: "row", marginTop: px(24) },
  panel: { marginRight: px(48) },
  dot: { position: "absolute", borderWidth: px(4) },
  tr: { flexDirection: "row", paddingVertical: px(4) },
  td: { width: px(90), fontSize: font.body, fontVariant: ["tabular-nums"] },
  tdName: { width: px(200) },
});
