// R5 review queue, R1 shot chart, R2 heatmap, R3 box score — all "auto-detected".
// The queue is GET /review/queue (D-48): shot outcomes the detector could not tell,
// low-confidence events and untagged players, each option naming the PATCH it sends, so
// answering needs no client-side rules. Which panels show comes from the profile
// (`sport_ui.review`), never the sport name.
import { useCallback, useEffect, useMemo, useState } from "react";
import { StyleSheet, View } from "react-native";
import { optionTestId, type ReviewOption, type ReviewQuestion } from "../../../../packages/tv-core/src/discovery";
import { autoDetectedLabel, boxColumns, courtViewBox, reviewPanels } from "../../../../packages/tv-core/src/display";
import type { Stats } from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { CourtView, courtSize } from "../components/CourtView";
import { TextEntryDialog } from "../components/TextEntryDialog";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { color, font, px } from "../theme";
import { ApiErrorBanner, Hint, Loading, Pill, T, styles as ui, useAsync } from "../ui";

const CHART_W = px(420);
const CHART_H = px(400);
const HEAT_CHIPS = 4;
const titleCase = (v: string) => v.replace(/(^|\s)\S/g, (m) => m.toUpperCase());

export function Review({ gameId }: { gameId: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [queue, setQueue] = useState<ReviewQuestion[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [focus, setFocus] = useState(0);
  const [busy, setBusy] = useState(false);
  const [typing, setTyping] = useState<ReviewOption | null>(null);
  const [row, setRow] = useState(0);
  const [heatFocus, setHeatFocus] = useState(0);
  const panels = useMemo(() => reviewPanels(game), [game]);
  const heatmap = panels.has("heatmap") ? (stats?.heatmap ?? []) : [];
  const current = queue[0];

  const load = useCallback(() => {
    api.getReviewQueue(gameId).then(setQueue, () => setQueue([]));
    api.getStats(gameId).then(setStats, () => setStats(null));
  }, [gameId]);
  useEffect(load, [load]);

  const answer = useCallback(
    (option: ReviewOption, text?: string) => {
      if (busy) return;
      setBusy(true);
      api
        .answerReview(option, text)
        .then(() => {
          setFocus(0);
          load();
        })
        .catch(() => {})
        .finally(() => setBusy(false));
    },
    [busy, load],
  );

  const onAction = useCallback(
    (a: DpadAction) => {
      const options = current?.options ?? [];
      if (a === "up") setRow(0);
      else if (a === "down") setRow(heatmap.length ? 1 : 0);
      else if (a === "left" && row === 0) setFocus((f) => Math.max(0, f - 1));
      else if (a === "left") setHeatFocus((i) => Math.max(0, i - 1));
      else if (a === "right" && row === 0) setFocus((f) => Math.min(options.length - 1, f + 1));
      else if (a === "right") setHeatFocus((i) => Math.min(heatmap.length - 1, i + 1));
      else if (a === "select" && row === 0 && options[focus]) {
        if (options[focus].text_field) setTyping(options[focus]);
        else answer(options[focus]);
      } else if (a === "back") navigate({ name: "watch", gameId });
    },
    [current, focus, answer, gameId, row, heatmap.length],
  );
  useDpad(onAction, !typing);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <Loading />;

  const court = game.sport_ui?.court;
  const [cw] = courtSize(court, game.court.variant);
  const grid = heatmap[Math.min(heatFocus, heatmap.length - 1)];
  const heatStart = Math.max(0, Math.min(heatFocus - 1, heatmap.length - HEAT_CHIPS));
  const name = (pid?: string | null) => (pid ? (game.players.find((p) => p.id === pid)?.name ?? `#${pid}`) : "");
  const columns = boxColumns(stats);

  return (
    <View style={ui.screen}>
      <T style={ui.h1} numberOfLines={1}>
        Review — {game.title}
      </T>
      <T testID="auto-detected-label" dataSet={{ confidence: stats?.confidence ?? "" }} style={{ color: color.dim }}>
        {autoDetectedLabel(stats)}
      </T>

      <View style={styles.section}>
        <T style={ui.h2}>Review queue ({queue.length})</T>
        {current ? (
          <View
            testID="review-item"
            dataSet={{ eventId: current.event_id ?? "", kind: current.kind, playerId: current.player_id ?? "", confidence: current.confidence ?? "" }}
          >
            <T>
              {current.prompt}
              {current.t != null ? ` · ${current.t.toFixed(1)} s` : ""}
              {current.player_id && current.kind !== "identity" ? ` · ${name(current.player_id)}` : ""}
              {current.confidence != null ? ` · confidence ${current.confidence.toFixed(2)}` : ""}
            </T>
            <View style={styles.row}>
              {current.options.map((opt, i) => (
                <Pill key={opt.label} label={opt.label} focused={row === 0 && i === focus} testID={optionTestId(opt.label)} />
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
                  // filled = make, ring = miss, dashed grey ring = outcome unknown
                  const unknown = sh.outcome === "unknown";
                  return (
                    <View
                      key={sh.event_id}
                      testID="shot-marker"
                      dataSet={{ made: sh.made ? "true" : "false", outcome: sh.outcome ?? "" }}
                      style={[
                        styles.dot,
                        {
                          left: x - r,
                          top: y - r,
                          width: 2 * r,
                          height: 2 * r,
                          borderRadius: r,
                          backgroundColor: sh.made ? color.made : "transparent",
                          borderColor: unknown ? color.dim : sh.made ? color.made : color.missed,
                          borderStyle: unknown ? "dashed" : "solid",
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
                  label={name(h.player_id)}
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
            <T style={ui.h2}>Box score</T>
            <View style={styles.tr}>
              <T style={[styles.td, styles.tdName, { color: color.dim }]}>Player</T>
              {columns.map((c) => (
                <T key={c.label} style={[styles.td, { color: color.dim }]}>
                  {c.label}
                </T>
              ))}
            </View>
            {(stats?.box_score ?? []).map((r) => (
              <View key={r.player_id} style={styles.tr} testID="box-score-row" dataSet={{ playerId: r.player_id }}>
                <T style={[styles.td, styles.tdName]} numberOfLines={1}>
                  {r.name ?? `#${r.player_id}`}
                </T>
                {columns.map((c) => (
                  <T key={c.label} style={styles.td} testID={`box-${c.label.split(" ")[0].toLowerCase()}`}>
                    {c.value(r)}
                  </T>
                ))}
              </View>
            ))}
          </View>
        ) : null}
      </View>

      <Hint>Left/Right pick an answer · Down switches the heatmap player · Select confirms · Back returns</Hint>

      {typing ? (
        <TextEntryDialog
          idPrefix="review-name"
          title={current?.prompt ?? "Name"}
          format={titleCase}
          onCancel={() => setTyping(null)}
          onSubmit={(text) => {
            const opt = typing;
            setTyping(null);
            answer(opt, text);
          }}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: px(16) },
  row: { flexDirection: "row", flexWrap: "wrap", marginTop: px(12) },
  panels: { flexDirection: "row", marginTop: px(16) },
  panel: { marginRight: px(40) },
  dot: { position: "absolute", borderWidth: px(4) },
  tr: { flexDirection: "row", paddingVertical: px(4) },
  td: { width: px(84), fontSize: font.body, fontVariant: ["tabular-nums"] },
  tdName: { width: px(180) },
});
