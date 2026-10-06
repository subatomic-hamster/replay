// M7 advice panel: per-player insights written only from that player's own stats in
// this game (grounded templates; an LLM rephrasing ships only when the grounding check
// passes — D-52). Left/Right pick a player; Back returns to the game.
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import { listWindow, type Advice as AdviceDoc } from "../../../../packages/tv-core/src/discovery";
import { api } from "../api";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { color, px } from "../theme";
import { ApiErrorBanner, Hint, Loading, Pill, T, styles as ui, useAsync } from "../ui";

const CHIPS = 6;

export function Advice({ gameId }: { gameId: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [focus, setFocus] = useState(0);
  const [byPlayer, setByPlayer] = useState<Record<string, AdviceDoc | string>>({});
  const players = game?.players ?? [];
  const pid = players[focus]?.id;

  useEffect(() => {
    if (!pid || byPlayer[pid]) return;
    api.getAdvice(gameId, pid).then(
      (a) => setByPlayer((m) => ({ ...m, [pid]: a })),
      (e: Error) => setByPlayer((m) => ({ ...m, [pid]: e.message })),
    );
  }, [gameId, pid, byPlayer]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") navigate({ name: "watch", gameId });
      else if (a === "left" || a === "up") setFocus((i) => Math.max(0, i - 1));
      else if (a === "right" || a === "down") setFocus((i) => Math.min(players.length - 1, i + 1));
    },
    [gameId, players.length],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <Loading />;
  const doc = pid ? byPlayer[pid] : undefined;
  const first = listWindow(focus, players.length, CHIPS);

  return (
    <View style={ui.screen} testID="advice">
      <T style={ui.h1}>Advice</T>
      <View style={styles.row}>
        {players.slice(first, first + CHIPS).map((p, k) => (
          <Pill
            key={p.id}
            label={p.name ?? `#${p.id}`}
            focused={first + k === focus}
            testID={`advice-player-${p.id}`}
          />
        ))}
      </View>
      {players.length === 0 ? <T>No players in this game.</T> : null}
      {typeof doc === "string" ? <T testID="advice-error">No advice: {doc}</T> : null}
      {doc && typeof doc !== "string" ? (
        <View style={styles.panel} testID="advice-panel" dataSet={{ playerId: doc.player_id, source: doc.source }}>
          <T style={ui.h2}>{doc.name ?? `#${doc.player_id}`}</T>
          {doc.lines.map((ln, i) => (
            <T key={i} testID="advice-line" style={styles.line}>
              • {ln}
            </T>
          ))}
          <T testID="advice-source" style={styles.source}>
            Auto-detected ·{" "}
            {doc.source === "llm"
              ? "rephrased by a local model and checked against the stats"
              : "written from this player's stats in this game"}
          </T>
        </View>
      ) : !doc && pid ? (
        <T style={{ color: color.dim }}>Loading…</T>
      ) : null}
      <Hint>Left/Right pick a player · Back returns to the game</Hint>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", flexWrap: "wrap" },
  panel: { marginTop: px(24), padding: px(32), borderRadius: px(16), backgroundColor: color.panel, maxWidth: px(1400) },
  line: { marginBottom: px(12) },
  source: { color: color.dim, marginTop: px(12) },
});
