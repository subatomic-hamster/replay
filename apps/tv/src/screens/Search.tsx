// M7 semantic search on the TV: preset chips (the profile's query chips + per-player
// reels) or free text on the on-screen keyboard → POST /games/{id}/search (embeddings,
// re-ranked by the structured filter). A game without an embeddings index falls back to
// the keyword query route, and says so. Select on a hit plays that play's window.
import { useCallback, useEffect, useMemo, useState } from "react";
import { StyleSheet, View } from "react-native";
import {
  fmtClock,
  listWindow,
  type SearchResult,
} from "../../../../packages/tv-core/src/discovery";
import { highlightQueries } from "../../../../packages/tv-core/src/display";
import { api } from "../api";
import { TextEntryDialog } from "../components/TextEntryDialog";
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

const ASK_CHIP = "Type a search…";
const VISIBLE = 5;

export function Search({ gameId }: { gameId: string }) {
  const {
    data: game,
    error,
    reload,
  } = useAsync(() => api.getGame(gameId), [gameId]);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState("");
  const [typing, setTyping] = useState(false);
  const [row, setRow] = useState(0);
  const [col, setCol] = useState(0);
  const [index, setIndex] = useState(0);
  const [stopAt, setStopAt] = useState<number | null>(null);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const t = useClockTime(handle?.clock ?? null, 1 / 10);
  const chips = useMemo(() => [...highlightQueries(game), ASK_CHIP], [game]);
  const hits = useMemo(() => result?.results ?? [], [result]);

  const run = useCallback(
    (text: string) => {
      if (busy) return;
      setBusy(true);
      setFailed("");
      api
        .search(gameId, text)
        .then((r) => {
          setResult(r);
          setIndex(0);
          setRow(r.results.length ? 1 : 0);
        })
        .catch((e: Error) => setFailed(e.message))
        .finally(() => setBusy(false));
    },
    [gameId, busy],
  );

  useEffect(() => {
    if (handle && stopAt !== null && t >= stopAt) {
      handle.pause();
      setStopAt(null);
    }
  }, [t, stopAt, handle]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") navigate({ name: "watch", gameId });
      else if (a === "up") setRow(0);
      else if (a === "down") setRow(hits.length ? 1 : 0);
      else if (a === "left" && row === 0) setCol((c) => Math.max(0, c - 1));
      else if (a === "right" && row === 0)
        setCol((c) => Math.min(chips.length - 1, c + 1));
      else if (a === "left") setIndex((i) => Math.max(0, i - 1));
      else if (a === "right") setIndex((i) => Math.min(hits.length - 1, i + 1));
      else if (a === "select" && row === 0) {
        if (chips[col] === ASK_CHIP) setTyping(true);
        else run(chips[col]);
      } else if (a === "select" && hits[index] && handle) {
        handle.seek(hits[index].t_start);
        setStopAt(hits[index].t_end);
        handle.play();
      } else if (a === "playpause") handle?.toggle();
    },
    [gameId, hits, row, chips, col, index, run, handle],
  );
  useDpad(onAction, !typing);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <Loading />;
  const first = listWindow(index, hits.length, VISIBLE);

  return (
    <View style={ui.safe} testID="search">
      <T style={ui.h1}>Search this game</T>
      <View style={styles.chips}>
        {chips.map((c, i) => (
          <Pill
            key={c}
            label={c}
            focused={row === 0 && i === col}
            testID="search-chip"
            dataSet={{ chip: c }}
          />
        ))}
      </View>
      {busy ? <T style={{ color: color.dim }}>Searching…</T> : null}
      {failed ? <T testID="search-error">Search failed: {failed}</T> : null}
      {result ? (
        <T
          testID="search-interpretation"
          dataSet={{ fallback: result.fallback ? "true" : "false" }}
          style={styles.interp}
        >
          “{result.query}” — {result.interpretation}
          {result.fallback
            ? " · keyword match (no search index for this game yet)"
            : " · ranked by similarity"}
        </T>
      ) : null}
      {result && hits.length === 0 ? (
        <T testID="search-empty">Nothing in this game matches.</T>
      ) : null}
      {hits.length ? (
        <View style={styles.layout}>
          <View style={{ width: px(960) }}>
            <PlayerSurface
              ref={setHandle}
              src={api.mediaUrl(game, game.renditions.wide)}
              muted
            />
          </View>
          <View style={styles.list}>
            {hits.slice(first, first + VISIBLE).map((h, k) => {
              const i = first + k;
              const on = row === 1 && i === index;
              return (
                <View
                  key={`${h.play_id}-${i}`}
                  testID="search-hit"
                  dataSet={{
                    playId: h.play_id,
                    tStart: h.t_start,
                    focused: on ? "true" : "false",
                    match: h.filter_match ? "true" : "false",
                  }}
                  style={[
                    styles.hit,
                    focusRing(on),
                    i === index && { backgroundColor: color.raised },
                  ]}
                >
                  <View style={styles.hitHead}>
                    <T style={styles.rank}>{i + 1}</T>
                    <T style={{ color: color.dim }}>{fmtClock(h.t_start)}</T>
                    {h.filter_match ? (
                      <View style={styles.match}>
                        <T style={styles.matchText}>Match</T>
                      </View>
                    ) : null}
                  </View>
                  <T numberOfLines={2}>{h.text}</T>
                </View>
              );
            })}
          </View>
        </View>
      ) : null}
      <Hint>
        Left/Right pick · Select searches or plays · Down to the results · Back
        returns to the game
      </Hint>

      {typing ? (
        <TextEntryDialog
          idPrefix="search"
          title="Search for a moment"
          onCancel={() => setTyping(false)}
          onSubmit={(text) => {
            setTyping(false);
            run(text);
          }}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: "row", flexWrap: "wrap" },
  interp: { color: color.dim, marginVertical: px(12) },
  layout: { flexDirection: "row", marginTop: px(8) },
  list: { flex: 1, marginLeft: px(32) },
  hit: {
    paddingHorizontal: px(16),
    paddingVertical: px(8),
    borderRadius: radius.card,
    marginBottom: px(10),
    backgroundColor: color.panel,
  },
  hitHead: { flexDirection: "row", alignItems: "center" },
  rank: {
    width: px(48),
    color: color.accent,
    fontSize: font.body,
    fontWeight: "800",
  },
  // the fill on a View (T lifts its glyphs; a fill on the Text would move with them);
  // sentence case, full-round like every other tag
  match: {
    marginLeft: px(16),
    backgroundColor: color.made,
    paddingHorizontal: px(12),
    borderRadius: radius.chip,
  },
  matchText: {
    color: color.onAccent,
    fontSize: font.small,
    lineHeight: px(34),
    fontWeight: "800",
  },
});
