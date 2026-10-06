// H1 per-player reel, H2 top plays, H3 query chips + free text, H4 phone companion.
// Everything goes through POST /games/{id}/query, so the TV never re-implements the
// query grammar — a chip, the on-screen keyboard and the phone all call the same route.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";
import { fmtDuration, highlightQueries } from "../../../../packages/tv-core/src/display";
import type { Clip } from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { TextEntryDialog } from "../components/TextEntryDialog";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { PlayerSurface, useClockTime, type PlayerHandle } from "../playback/PlayerSurface";
import { storedSession, useSessionMessages } from "../session";
import { color, focusRing, font, px } from "../theme";
import { ApiErrorBanner, Hint, Loading, Pill, T, styles as ui, useAsync } from "../ui";

/** H3 free text: the last chip opens the on-screen keyboard instead of running a query. */
const ASK_CHIP = "Ask…";
const PAIR_CHIP = "Pair phone";

export function Highlights({ gameId, q }: { gameId: string; q?: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [asking, setAsking] = useState(false);
  const lastPushed = useRef<string | null>(null);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [interpretation, setInterpretation] = useState("");
  const [activeChip, setActiveChip] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [row, setRow] = useState(0);
  const [col, setCol] = useState(0);
  const pending = useRef(false);

  const t = useClockTime(handle?.clock ?? null, 1 / 10);
  const queries = useMemo(() => [...highlightQueries(game), ASK_CHIP, PAIR_CHIP], [game]);

  const run = useCallback(
    (text: string) => {
      if (!game || pending.current) return;
      pending.current = true;
      setActiveChip(text);
      api
        .query(game.id, text)
        .then((r) => {
          setClips(r.clips);
          setInterpretation(r.interpretation);
          setIndex(0);
          setRow(r.clips.length ? 1 : 0);
        })
        .catch(() => {
          setClips([]);
          setInterpretation("Query failed");
        })
        .finally(() => {
          pending.current = false;
        });
    },
    [game],
  );

  const playClip = useCallback(
    (i: number) => {
      if (!handle || !clips?.[i]) return;
      setIndex(i);
      handle.seek(clips[i].t_start);
      handle.play();
    },
    [handle, clips],
  );

  // Auto-advance at each clip's t_end (S-27).
  useEffect(() => {
    if (!handle || !clips?.length) return;
    const clip = clips[index];
    if (!clip || t < clip.t_end) return;
    if (index + 1 < clips.length) playClip(index + 1);
    else handle.pause();
  }, [t, handle, clips, index, playClip]);

  const onAction = useCallback(
    (a: DpadAction) => {
      const rows = clips?.length ? 2 : 1;
      switch (a) {
        case "up":
          setRow((r) => Math.max(0, r - 1));
          break;
        case "down":
          setRow((r) => Math.min(rows - 1, r + 1));
          break;
        case "left":
          if (row === 0) setCol((c) => Math.max(0, c - 1));
          else setIndex((i) => Math.max(0, i - 1));
          break;
        case "right":
          if (row === 0) setCol((c) => Math.min(queries.length - 1, c + 1));
          else setIndex((i) => Math.min((clips?.length ?? 1) - 1, i + 1));
          break;
        case "select":
          if (row === 1) playClip(index);
          else if (queries[col] === ASK_CHIP) setAsking(true);
          else if (queries[col] === PAIR_CHIP) navigate({ name: "pair", gameId });
          else run(queries[col]);
          break;
        case "pair":
          navigate({ name: "pair", gameId });
          break;
        case "playpause":
          handle?.toggle();
          break;
        case "back":
          navigate({ name: "watch", gameId });
          break;
        default:
          break;
      }
    },
    [row, col, index, queries, clips, run, playClip, handle, gameId],
  );
  useDpad(onAction, !asking);

  // S-31: a query pushed from the paired phone, and the q the Pair screen navigates with.
  const session = storedSession();
  useSessionMessages(
    session?.id,
    useCallback(
      (msg) => {
        if (msg.type === "query" && msg.text) run(msg.text);
      },
      [run],
    ),
  );
  useEffect(() => {
    if (!game || !q || lastPushed.current === q) return;
    lastPushed.current = q;
    run(q);
  }, [game, q, run]);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <Loading />;

  return (
    <View style={ui.screen}>
      <T style={ui.h1} numberOfLines={1}>
        Highlights — {game.title}
      </T>
      <View style={styles.chips}>
        {queries.map((c, i) => (
          <Pill
            key={c}
            label={c}
            testID="query-chip"
            dataSet={{ chip: c }}
            focused={row === 0 && i === col}
            active={c === activeChip}
          />
        ))}
      </View>

      {interpretation ? (
        <T testID="query-interpretation" style={{ color: color.dim, marginVertical: px(12) }}>
          {interpretation}
        </T>
      ) : null}
      {clips && clips.length === 0 ? <T testID="no-clips">No clips match that query.</T> : null}

      {clips && clips.length > 0 ? (
        <View style={styles.reel}>
          <View style={{ width: px(1040) }}>
            <PlayerSurface ref={setHandle} src={api.mediaUrl(game, game.renditions.wide)} muted />
          </View>
          <View style={styles.list}>
            <T testID="clip-counter" style={{ marginBottom: px(12) }}>
              clip {index + 1}/{clips.length}
            </T>
            {clips.map((c, i) => {
              const on = row === 1 && i === index;
              return (
                <View
                  key={`${c.event_id ?? i}`}
                  testID="reel-clip"
                  dataSet={{ eventId: c.event_id, tStart: c.t_start, focused: on ? "true" : "false" }}
                  style={[styles.clip, focusRing(on), i === index && { backgroundColor: color.raised }]}
                >
                  <T style={styles.clipIndex}>{i + 1}</T>
                  <T style={{ flex: 1 }} numberOfLines={1}>
                    {c.label ?? "clip"}
                  </T>
                  <T style={{ color: color.dim }}>{fmtDuration(c.t_start)}</T>
                </View>
              );
            })}
          </View>
        </View>
      ) : null}

      <Hint>Arrows move · Select plays · Play/Pause toggles · Back returns to the game</Hint>

      {asking ? (
        <TextEntryDialog
          idPrefix="ask"
          title="Ask for a highlight"
          onCancel={() => setAsking(false)}
          onSubmit={(text) => {
            setAsking(false);
            run(text);
          }}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: "row", flexWrap: "wrap" },
  reel: { flexDirection: "row", marginTop: px(16) },
  list: { flex: 1, marginLeft: px(32) },
  clip: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: px(16),
    paddingVertical: px(8),
    borderRadius: px(10),
    marginBottom: px(8),
  },
  clipIndex: { width: px(48), color: color.accent, fontSize: font.body, fontWeight: "800" },
});
