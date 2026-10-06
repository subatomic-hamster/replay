// M8 multi-angle replays. ReplayList: the game's rendered replays as cards (reached from
// the Watch action row's "Replays", shown when the game has any). Replay: one highlight
// where Left/Right cut between its pre-rendered angle videos like broadcast cameras.
// The angles are time-aligned, so a cut is just a src swap on PlayerSurface, which resumes
// at the same media time and play state; the highlight loops at the end. A cut shows the
// angle name big in the lower-left bug for ANGLE_BUG_MS, then it shrinks.
// Back: Replay → ReplayList → Watch.
import { useCallback, useEffect, useMemo, useState } from "react";
import { StyleSheet, View, useWindowDimensions } from "react-native";
import { fmtDuration } from "../../../../packages/tv-core/src/display";
import { ANGLE_BUG_MS, cycleAngle, tierBadge, type ReplayTier } from "../../../../packages/tv-core/src/replays";
import { api } from "../api";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { PlayerSurface, type PlayerHandle } from "../playback/PlayerSurface";
import { color, focusRing, font, px } from "../theme";
import { ApiErrorBanner, Hint, Loading, T, styles as ui, useAsync } from "../ui";

const TIER_COLOR: Record<ReplayTier, string> = { A: color.made, B: color.dot, C: "#c9a7ff" };

export function ReplayList({ gameId }: { gameId: string }) {
  const { data, error, reload } = useAsync(() => api.listReplays(gameId), [gameId]);
  const [focus, setFocus] = useState(0);
  const replays = useMemo(() => data ?? [], [data]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") navigate({ name: "watch", gameId });
      else if (replays.length === 0) return;
      else if (a === "down" || a === "right") setFocus((i) => Math.min(replays.length - 1, i + 1));
      else if (a === "up" || a === "left") setFocus((i) => Math.max(0, i - 1));
      else if (a === "select") navigate({ name: "replay", gameId, playId: replays[focus].play_id });
    },
    [gameId, replays, focus],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!data) return <Loading />;

  return (
    <View style={ui.screen} testID="replay-list">
      <T style={ui.h1}>Replays</T>
      {replays.length === 0 ? <T testID="replay-list-empty">No replays rendered for this game yet.</T> : null}
      {replays.map((r, i) => {
        const on = i === focus;
        return (
          <View
            key={r.play_id}
            testID="replay-card"
            dataSet={{ playId: r.play_id, focused: on ? "true" : "false" }}
            style={[styles.card, focusRing(on), on && { backgroundColor: color.raised }]}
          >
            <T style={styles.cardTitle} numberOfLines={1}>
              {r.label}
            </T>
            <T style={styles.cardMeta}>
              {r.angles} angles · {fmtDuration(r.t_end - r.t_start)}
            </T>
          </View>
        );
      })}
      <Hint>Up/Down move · Select opens a replay · Back to the game</Hint>
    </View>
  );
}

export function Replay({ gameId, playId }: { gameId: string; playId: string }) {
  const { data: m, error, reload } = useAsync(() => api.getReplay(gameId, playId), [gameId, playId]);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const [index, setIndex] = useState(0);
  const [big, setBig] = useState(true);
  const { width: winW, height: winH } = useWindowDimensions();
  const count = m?.angles.length ?? 0;

  // A replay starts playing; PlayerSurface holds the request until the media can play.
  useEffect(() => {
    if (m && handle) handle.play();
  }, [m, handle]);

  // The big label shrinks ANGLE_BUG_MS after the last cut (a new cut restarts the timer).
  useEffect(() => {
    if (!big) return;
    const timer = setTimeout(() => setBig(false), ANGLE_BUG_MS);
    return () => clearTimeout(timer);
  }, [big, index]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") navigate({ name: "replays", gameId });
      else if ((a === "left" || a === "right") && count > 1) {
        setIndex((i) => cycleAngle(i, count, a === "right" ? 1 : -1));
        setBig(true);
      } else if (a === "select" || a === "playpause") handle?.toggle();
    },
    [gameId, count, handle],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!m) return <Loading />;
  const angle = m.angles[index];
  if (!angle) {
    return (
      <View style={ui.screen} testID="replay">
        <T>This replay has no rendered angles.</T>
        <Hint>Back to replays</Hint>
      </View>
    );
  }
  const stageW = Math.min(winW, (winH * 16) / 9);

  return (
    <View style={styles.screen} testID="replay" dataSet={{ angle: angle.id, tier: angle.tier, index }}>
      <View style={{ width: stageW }}>
        <PlayerSurface ref={setHandle} src={angle.url} muted loop>
          <View style={styles.top}>
            <T style={styles.kicker}>REPLAY</T>
            <T style={styles.title} numberOfLines={1} testID="replay-title">
              {m.label}
            </T>
            {m.synthetic ? (
              <T style={styles.synthetic} testID="replay-synthetic">
                SYNTHETIC
              </T>
            ) : null}
          </View>

          <View style={styles.bug} testID="replay-bug" dataSet={{ prominent: big ? "true" : "false" }}>
            <View style={styles.bugRow}>
              <View style={[styles.tier, { backgroundColor: TIER_COLOR[angle.tier] ?? color.dim }]}>
                <T style={styles.tierText} testID="replay-tier-badge" dataSet={{ tier: angle.tier }}>
                  {tierBadge(angle.tier)}
                </T>
              </View>
              <T style={styles.arrow}>◀</T>
              <T style={styles.pos} testID="replay-angle-pos">
                {`${index + 1} / ${count}`}
              </T>
              <T style={styles.arrow}>▶</T>
            </View>
            <T style={[styles.angle, big && styles.angleBig]} testID="replay-angle-label">
              {angle.label}
            </T>
          </View>

          <View style={styles.hintBar}>
            <Hint>◀ ▶ cut between camera angles · Select plays/pauses · Back to replays</Hint>
          </View>
        </PlayerSurface>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    width: px(900),
    paddingHorizontal: px(28),
    paddingVertical: px(16),
    marginBottom: px(20),
    borderRadius: px(14),
    backgroundColor: color.panel,
  },
  cardTitle: { fontSize: font.h2, fontWeight: "700" },
  cardMeta: { color: color.dim, fontSize: font.small, marginTop: px(6) },

  screen: { flex: 1, backgroundColor: "#000", alignItems: "center", justifyContent: "center" },
  top: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: px(48),
    paddingVertical: px(24),
    backgroundColor: "rgba(5, 7, 10, 0.72)",
  },
  kicker: { color: color.accent, fontSize: font.body, fontWeight: "800", letterSpacing: px(3), marginRight: px(24) },
  title: { flex: 1, fontSize: font.body, fontWeight: "600" },
  synthetic: { color: color.dim, fontSize: font.small, fontWeight: "700", marginLeft: px(24) },

  // Broadcast-style lower-left bug: tier + position on top, the angle name below.
  bug: {
    position: "absolute",
    left: px(48),
    bottom: px(130),
    paddingHorizontal: px(24),
    paddingVertical: px(14),
    borderLeftWidth: px(8),
    borderLeftColor: color.accent,
    borderRadius: px(6),
    backgroundColor: color.scrim,
  },
  bugRow: { flexDirection: "row", alignItems: "center" },
  tier: { paddingHorizontal: px(14), paddingVertical: px(2), borderRadius: px(6), marginRight: px(18) },
  tierText: { color: color.onAccent, fontSize: font.small, fontWeight: "800" },
  arrow: { color: color.dim, fontSize: font.small },
  pos: { fontSize: font.small, fontWeight: "700", marginHorizontal: px(12) },
  angle: { fontSize: font.body, fontWeight: "700", marginTop: px(6) },
  angleBig: { fontSize: font.title },

  hintBar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: px(48),
    paddingBottom: px(28),
    backgroundColor: "rgba(5, 7, 10, 0.72)",
  },
});
