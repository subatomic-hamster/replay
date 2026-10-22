// The player's Stats panel (docs/ux/redesign.md "Do more": Stats, like Prime's X-Ray): the
// right third of the screen while the game keeps playing on the left. The score by team,
// a short box score and the shot chart, all labelled auto-detected (D-48), from what the
// Review screen shows. Two ways on: "Review N plays" (the Review screen) and "Tips for
// players" (Tips); Up/Down pick one, Select opens it, Left or Back closes the panel.
import { useCallback, useEffect, useMemo, useState } from "react";
import { StyleSheet, View } from "react-native";
import { reviewPanels } from "../../../../packages/tv-core/src/display";
import type {
  Game,
  Player,
  Stats,
} from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { useDpad, type DpadAction } from "../input";
import { color, face, px, safe, sp, teamColorMap, type } from "../theme";
import { Chip, KeyLegend, Spinner, T } from "../ui";
import { CourtView, courtSize } from "./CourtView";

export const PANEL_W = px(640);
const PAD = sp(6);
const INNER_W = PANEL_W - PAD - safe.x;
const ROWS = 6;
const NAME_W = INNER_W - 2 * px(96);

export type StatsExit = "review" | "advice";

export function StatsPanel({
  game,
  roster,
  onClose,
  onOpen,
  onPlayPause,
}: {
  game: Game;
  roster: Player[];
  onClose: () => void;
  onOpen: (to: StatsExit) => void;
  onPlayPause: () => void;
}) {
  // undefined while loading, null when the stats could not be read
  const [stats, setStats] = useState<Stats | null | undefined>(undefined);
  const [queue, setQueue] = useState<number | null>(null);
  const [focus, setFocus] = useState<StatsExit | null>(null);
  useEffect(() => {
    let on = true;
    api.getStats(game.id).then(
      (s) => on && setStats(s),
      () => on && setStats(null),
    );
    api.getReviewQueue(game.id).then(
      (q) => on && setQueue(q.length),
      () => on && setQueue(0),
    );
    return () => {
      on = false;
    };
  }, [game.id]);

  const panels = useMemo(() => reviewPanels(game), [game]);
  const exits = useMemo<{ id: StatsExit; label: string }[]>(
    () => [
      ...(queue
        ? [
            {
              id: "review" as const,
              label: `Review ${queue} ${queue === 1 ? "play" : "plays"}`,
            },
          ]
        : []),
      { id: "advice", label: "Tips for players" },
    ],
    [queue],
  );
  // by id: the review exit arriving with the queue never moves focus off Tips
  const k = Math.max(
    0,
    exits.findIndex((x) => x.id === focus),
  );

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back" || a === "left") onClose();
      else if (a === "playpause") onPlayPause();
      else if (a === "up") setFocus(exits[Math.max(0, k - 1)].id);
      else if (a === "down")
        setFocus(exits[Math.min(exits.length - 1, k + 1)].id);
      else if (a === "select" && exits[k]) onOpen(exits[k].id);
    },
    [k, exits, onClose, onOpen, onPlayPause],
  );
  useDpad(onAction);

  const box = stats?.box_score ?? [];
  // Players who took a shot, the most points, then makes, then attempts first. When no shot
  // went in (auto-detection found none), a column of zeros says nothing: the score and the
  // Pts column give way to one honest line.
  const rows = box
    .filter((r) => r.attempts > 0 || r.makes > 0 || (r.points ?? 0) > 0)
    .sort(
      (a, b) =>
        (b.points ?? 0) - (a.points ?? 0) ||
        b.makes - a.makes ||
        b.attempts - a.attempts,
    )
    .slice(0, ROWS);
  const made = box.some((r) => r.makes > 0 || (r.points ?? 0) > 0);
  const hasPts = made && rows.some((r) => r.points !== undefined);
  const name = (pid: string, fallback?: string | null) =>
    roster.find((p) => p.id === pid)?.name ??
    fallback ??
    `Player ${pid.replace(/^p/, "")}`;
  // The score: points by team, when the box score has them.
  const ink = teamColorMap(game.teams.map((tm) => tm.color_hex));
  const teams = hasPts
    ? game.teams.map((tm) => ({
        ...tm,
        pts: box
          .filter(
            (r) =>
              (r.team ?? roster.find((p) => p.id === r.player_id)?.team) ===
              tm.id,
          )
          .reduce((s, r) => s + (r.points ?? 0), 0),
      }))
    : [];
  const court = game.sport_ui?.court;
  const [cw] = courtSize(court, game.court.variant);
  // The chart takes the height the rest leaves (design px of the 972 inside the safe area:
  // title, label, two exits, the key legend and margins ~300; the score 88; the no-makes
  // line 56; the box score 24 + 40 a row with its header).
  const chartH = Math.max(
    200,
    670 -
      (teams.length >= 2 ? 88 : 0) -
      (made ? 0 : 56) -
      (panels.has("box_score") && rows.length
        ? 24 + 40 * (rows.length + 1)
        : 0),
  );

  if (stats === undefined) {
    return (
      <View style={[styles.panel, styles.loading]} testID="stats-panel">
        <T style={[type.title, styles.loadingTitle]}>Stats</T>
        <Spinner testID="stats-loading" />
      </View>
    );
  }

  return (
    <View style={styles.panel} testID="stats-panel">
      <T style={type.title}>Stats</T>
      <T
        style={[type.meta, styles.dim]}
        testID="auto-detected-label"
        numberOfLines={1}
      >
        {/* plain words: the mean confidence stays in the data, off the screen */}
        Auto-detected from the video
      </T>

      {teams.length >= 2 ? (
        <View style={styles.score} testID="stats-score">
          {teams.map((tm, i) => (
            <View key={tm.id} style={styles.team}>
              {i > 0 ? <T style={[styles.big, styles.dim]}> – </T> : null}
              <View
                testID="team-swatch"
                dataSet={{ color: ink.get(tm.color_hex) ?? tm.color_hex }}
                style={[
                  styles.swatch,
                  { backgroundColor: ink.get(tm.color_hex) ?? tm.color_hex },
                ]}
              />
              <T style={styles.big}>{tm.pts}</T>
            </View>
          ))}
        </View>
      ) : null}

      {!made ? (
        <T style={[type.body, styles.none]} testID="stats-no-makes">
          {stats === null
            ? "The stats could not be loaded. Close and open Stats to try again."
            : rows.length
              ? "No made shots detected yet"
              : "No shots detected in this game"}
        </T>
      ) : null}

      {panels.has("box_score") && rows.length ? (
        <View style={styles.section}>
          <View style={styles.tr}>
            <T style={[styles.td, styles.name, styles.dim]}>Player</T>
            <T style={[styles.td, styles.dim]}>FG</T>
            {hasPts ? <T style={[styles.td, styles.dim]}>Pts</T> : null}
          </View>
          {rows.map((r) => (
            <View
              key={r.player_id}
              style={styles.tr}
              testID="box-score-row"
              dataSet={{ playerId: r.player_id }}
            >
              <T style={[styles.td, styles.name]} numberOfLines={1}>
                {name(r.player_id, r.name)}
              </T>
              <T
                style={[styles.td, styles.fig]}
              >{`${r.makes}/${r.attempts}`}</T>
              {hasPts ? (
                <T style={[styles.td, styles.fig]}>{r.points ?? "–"}</T>
              ) : null}
            </View>
          ))}
        </View>
      ) : null}

      {panels.has("shot_chart") ? (
        <View style={styles.section}>
          <CourtView
            court={court}
            variant={game.court.variant}
            width={INNER_W}
            maxHeight={px(chartH)}
            testID="shot-chart"
          >
            {(toPx, s) =>
              (stats?.shots ?? []).map((sh) => {
                const [x, y] = toPx(sh.court[0], sh.court[1]);
                const r = Math.max(px(8), (cw * s) / 30);
                // filled = make, ring = miss, dashed ring = outcome unknown
                const unknown = sh.outcome === "unknown";
                return (
                  <View
                    key={sh.event_id}
                    testID="shot-marker"
                    dataSet={{
                      made: sh.made ? "true" : "false",
                      outcome: sh.outcome ?? "",
                    }}
                    style={[
                      styles.dot,
                      {
                        left: x - r,
                        top: y - r,
                        width: 2 * r,
                        height: 2 * r,
                        borderRadius: r,
                        backgroundColor: sh.made
                          ? color.scoreboard
                          : "transparent",
                        borderColor: unknown
                          ? color.bleacher
                          : sh.made
                            ? color.scoreboard
                            : color.chalk,
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

      <View style={styles.exits}>
        {exits.map((x, i) => (
          <Chip
            key={x.id}
            label={x.label}
            focused={i === k}
            active // a line fill: the chip's own Bench fill is the panel's colour
            testID={`stats-${x.id}`}
          />
        ))}
      </View>
      <KeyLegend
        items={[
          { k: "Select", label: "Open" },
          { k: "◀", label: "Close" },
        ]}
        style={styles.legend}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    width: PANEL_W,
    paddingLeft: PAD,
    paddingRight: safe.x,
    paddingTop: safe.y,
    paddingBottom: safe.y,
    backgroundColor: "rgba(29, 40, 52, 0.94)", // Bench, a little video through it
  },
  loading: { alignItems: "center", justifyContent: "center" },
  loadingTitle: { position: "absolute", top: safe.y, left: PAD },
  none: { color: color.bleacher, marginTop: sp(2) },
  dim: { color: color.bleacher },
  score: { flexDirection: "row", alignItems: "center", marginTop: sp(2) },
  team: { flexDirection: "row", alignItems: "center" },
  swatch: {
    width: px(16),
    height: px(16),
    borderRadius: px(8),
    marginRight: sp(1.5),
  },
  big: {
    fontFamily: face.figures,
    fontSize: px(56),
    lineHeight: px(64),
    fontVariant: ["tabular-nums"],
  },
  section: { marginTop: sp(3) },
  tr: { flexDirection: "row", height: px(40), alignItems: "center" },
  td: { ...type.meta, width: px(96), textAlign: "right" },
  name: { width: NAME_W, textAlign: "left" },
  fig: { fontFamily: face.figures, fontSize: px(30) },
  dot: { position: "absolute", borderWidth: px(4) },
  exits: { marginTop: "auto", alignItems: "flex-start" },
  // in the panel's flow, under the exits, right-aligned as everywhere
  legend: {
    position: "relative",
    right: 0,
    bottom: 0,
    marginTop: sp(2),
    alignSelf: "flex-end",
  },
});
