// W1 — game library. D-pad moves across cards, Select opens. Back is left unhandled so
// the remote's Back exits the app from here (Fire TV convention; E-14 on the web).
import { useCallback, useMemo, useState } from "react";
import { Image, StyleSheet, View } from "react-native";
import { fmtDate, fmtDuration, statusText } from "../../../../packages/tv-core/src/display";
import { api } from "../api";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { color, focusRing, font, px } from "../theme";
import { ApiErrorBanner, Hint, Pill, T, styles as ui, useAsync } from "../ui";

export function Library() {
  const { data, error, reload } = useAsync(() => api.listGames(), []);
  const [focus, setFocus] = useState(0);
  const games = useMemo(() => data ?? [], [data]);

  // focus -1 is the "Players" pill above the cards (Up/Left from the first card).
  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") return false;
      if (a === "select" && focus === -1) navigate({ name: "players" });
      else if (a === "right" || a === "down") setFocus((i) => Math.min(games.length - 1, i + 1));
      else if (a === "left" || a === "up") setFocus((i) => Math.max(-1, i - 1));
      else if (a === "select" && games[focus]) {
        const g = games[focus];
        // E-02: a game still processing is not watchable yet; the phone shows its status.
        if (g.status === "ready") navigate({ name: "watch", gameId: g.id });
      }
    },
    [games, focus],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;

  return (
    <View style={ui.screen}>
      <View style={styles.head}>
        <T style={[ui.h1, { marginBottom: 0, marginRight: px(32) }]}>Replay</T>
        <Pill label="Players" focused={focus === -1} testID="library-players" />
      </View>
      {data && games.length === 0 ? (
        <T testID="library-empty">No games yet. Upload one from your phone at /upload.</T>
      ) : null}
      <View style={styles.cards}>
        {games.map((g, i) => {
          const on = i === focus;
          return (
            <View
              key={g.id}
              testID="game-card"
              dataSet={{ gameId: g.id, focused: on ? "true" : "false" }}
              style={[styles.card, focusRing(on), on && styles.cardOn]}
            >
              <View style={styles.thumb}>
                {g.thumb_url ? (
                  <Image source={{ uri: g.thumb_url }} style={StyleSheet.absoluteFill} resizeMode="cover" />
                ) : null}
                <View style={[styles.status, g.status === "ready" ? styles.ready : styles.working]}>
                  <T testID="game-status" style={styles.statusText}>
                    {statusText(g)}
                  </T>
                </View>
              </View>
              <T testID="game-card-title" numberOfLines={1} style={[styles.title, !on && { color: color.dim }]}>
                {g.title}
              </T>
              <T style={styles.meta}>
                {fmtDate(g.recorded_at)} · {fmtDuration(g.duration_s)}
              </T>
            </View>
          );
        })}
      </View>
      <Hint>Arrows move · Select opens a game · Up reaches Players · Back exits</Hint>
    </View>
  );
}

const styles = StyleSheet.create({
  head: { flexDirection: "row", alignItems: "center", marginBottom: px(24) },
  cards: { flexDirection: "row", flexWrap: "wrap" },
  card: {
    width: px(420),
    marginRight: px(32),
    marginBottom: px(32),
    borderRadius: px(14),
    backgroundColor: color.panel,
    overflow: "hidden",
  },
  cardOn: { transform: [{ scale: 1.04 }] },
  thumb: { width: "100%", aspectRatio: 16 / 9, backgroundColor: color.raised },
  status: {
    position: "absolute",
    left: px(12),
    top: px(12),
    paddingHorizontal: px(12),
    borderRadius: px(20),
  },
  ready: { backgroundColor: color.made },
  working: { backgroundColor: color.accent },
  statusText: { color: color.onAccent, fontSize: font.small, fontWeight: "700" },
  title: { fontSize: font.body, fontWeight: "700", marginHorizontal: px(16), marginTop: px(12) },
  meta: { color: color.dim, fontSize: font.small, marginHorizontal: px(16), marginBottom: px(14) },
});
