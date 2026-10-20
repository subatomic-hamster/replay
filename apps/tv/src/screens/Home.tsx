// Home (route "library"): the immersive list (docs/ux/redesign.md "Home"). The hero shows
// the focused game's best-moment art, title, meta and its ways to watch; below it the
// Games row (Add game first, then games still processing, then the rest) and the Players
// row peeking at the bottom; Settings is the gear top-right, reached with Up.
// Focus zones gear / hero / games / players, moved with the D-pad. Focus starts on the
// newest finished game's card. Back is left unhandled so the remote's Back exits the app
// (Fire TV convention; E-14 on the web).
import { useCallback, useEffect, useMemo, useState } from "react";
import { Image, StyleSheet, View } from "react-native";
import { api } from "../api";
import { Avatar } from "../components/Avatar";
import {
  hasFeature,
  minutes,
  progressOf,
  shortDate,
  stageWords,
  watchable,
  type GameLike,
} from "../gameState";
import { fmtDuration } from "../../../../packages/tv-core/src/display";
import { useDpad, type DpadAction } from "../input";
import { navigate, type Route } from "../nav";
import { resumeAt } from "../resume";
import { color, px, radius, safe, sp, type } from "../theme";
import {
  ApiErrorBanner,
  Focusable,
  Hero,
  Loading,
  PillButton,
  ProgressRing,
  T,
  Title,
  useAsync,
} from "../ui";

type Zone = "gear" | "hero" | "games" | "players";
type Action = {
  id: string;
  label: string;
  to: Route;
  play?: boolean;
  resume?: number;
};

const ADD = "add";
/** Re-read the list this often while a game is processing (its ring and words move). */
const POLL_MS = 15_000;

const CARD_W = px(384);
const CARD_H = px(216);
const RING_BOX = px(8); // Focusable's ring + gap, each side
const CARD_PITCH = CARD_W + 2 * RING_BOX + sp(4);
const CARDS_SHOWN = 4;
const AVATAR = 120;
const AVATAR_PITCH = px(AVATAR) + 2 * RING_BOX + sp(6);
const AVATARS_SHOWN = 8;
/** How far the rows slide up when the Players row takes focus. */
const PLAYERS_LIFT = px(360);

/** Processing games first (they are what changes), then the rest in the API's order. */
const order = (gs: GameLike[]) => [
  ...gs.filter((g) => g.status !== "ready"),
  ...gs.filter((g) => g.status === "ready"),
];

function actionsFor(g: GameLike): Action[] {
  const out: Action[] = [];
  // Play resumes where the game was left (resume.ts), saying when; Start over is the way
  // back to the beginning.
  const at = resumeAt(g.id);
  if (watchable(g) && at !== null)
    out.push(
      {
        id: "play",
        label: `Resume ${fmtDuration(at)}`,
        to: { name: "watch", gameId: g.id, t: at },
        play: true,
        resume: at,
      },
      {
        id: "restart",
        label: "Start over",
        to: { name: "watch", gameId: g.id, t: 0 },
      },
    );
  else if (watchable(g))
    out.push({
      id: "play",
      label: "Play",
      to: { name: "watch", gameId: g.id },
      play: true,
    });
  if (hasFeature(g, "highlights", true))
    out.push({
      id: "highlights",
      label: "Highlights",
      to: { name: "watch", gameId: g.id, way: "highlights" },
    });
  // Condensed (rallies) exists only for some games, so only when the API says it is ready.
  if (hasFeature(g, "condensed", false))
    out.push({
      id: "condensed",
      label: "Condensed",
      to: { name: "watch", gameId: g.id, way: "condensed" },
    });
  return out;
}

const clamp = (i: number, n: number) => Math.max(0, Math.min(n - 1, i));
/** Scroll a row so the focused item stays among the first `shown`. */
const rowShift = (i: number, shown: number, pitch: number) =>
  -Math.max(0, i - (shown - 1)) * pitch;

export function Home() {
  const { data, error, reload } = useAsync(
    () => api.listGames() as Promise<GameLike[]>,
    [],
  );
  const { data: people } = useAsync(
    () => api.listProfiles().catch(() => []),
    [],
  );
  const games = useMemo(() => order(data ?? []), [data]);
  const players = useMemo(() => people ?? [], [people]);
  const [zone, setZone] = useState<Zone | null>(null);
  const [cardId, setCardId] = useState<string | null>(null);
  const [btn, setBtn] = useState(0);
  const [pi, setPi] = useState(0);

  const processing = games.some((g) => g.status !== "ready");
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(reload, POLL_MS);
    return () => clearInterval(t);
  }, [processing, reload]);

  const empty = data !== null && games.length === 0;
  const ids = useMemo(() => [ADD, ...games.map((g) => g.id)], [games]);
  // Focus is kept by id, so a re-read list (a game finishing moves it) keeps the card.
  // Focus starts on the newest finished game (what people come to watch); the processing
  // ones are one press Left.
  const featured =
    games.find((g) => g.status === "ready") ??
    games.find(watchable) ??
    games[0];
  const cur = cardId && ids.includes(cardId) ? cardId : (featured?.id ?? ADD);
  const gi = ids.indexOf(cur);
  const game = games.find((g) => g.id === cur) ?? null;
  const actions = useMemo<Action[]>(
    () =>
      empty
        ? [{ id: "add", label: "Add game", to: { name: "add" } }]
        : game
          ? actionsFor(game)
          : [],
    [empty, game],
  );
  const bi = clamp(btn, actions.length);
  const playersShown = players.length > 0;
  // A zone with nothing to focus falls back: the hero has no actions while a game is not
  // watchable yet, and an empty library has no Games row.
  let z: Zone = zone ?? (empty ? "hero" : "games");
  if (z === "hero" && !actions.length) z = "games";
  if (z === "games" && empty) z = "hero";
  if (z === "players" && !playersShown) z = empty ? "hero" : "games";

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") return false;
      if (z === "gear") {
        if (a === "select") navigate({ name: "settings" });
        else if (a === "down") setZone(actions.length ? "hero" : "games");
      } else if (z === "hero") {
        if (a === "left") setBtn(clamp(bi - 1, actions.length));
        else if (a === "right") setBtn(clamp(bi + 1, actions.length));
        else if (a === "up") setZone("gear");
        else if (a === "down")
          setZone(empty ? (playersShown ? "players" : "hero") : "games");
        else if (a === "select" || (a === "playpause" && actions[bi]?.play))
          navigate(actions[bi].to);
      } else if (z === "games") {
        if (a === "left" || a === "right") {
          setCardId(ids[clamp(gi + (a === "right" ? 1 : -1), ids.length)]);
          setBtn(0);
        } else if (a === "up") {
          setBtn(0);
          setZone(actions.length ? "hero" : "gear");
        } else if (a === "down" && playersShown) setZone("players");
        else if (a === "select" && cur === ADD) navigate({ name: "add" });
        else if (
          (a === "select" || a === "playpause") &&
          game &&
          watchable(game)
        ) {
          navigate({ name: "watch", gameId: game.id });
        }
      } else {
        if (a === "left" || a === "right")
          setPi(clamp(pi + (a === "right" ? 1 : -1), players.length + 1));
        else if (a === "up") setZone(empty ? "hero" : "games");
        else if (a === "select") {
          const p = players[pi];
          navigate(
            p
              ? { name: "profile", profileId: p.profile_id }
              : { name: "players" },
          );
        }
      }
    },
    [z, actions, bi, empty, playersShown, ids, gi, cur, game, pi, players],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!data) return <Loading />;

  const lifted = z === "players";
  const hero = empty
    ? {
        id: "empty",
        art: null,
        title: "Add your first game",
        meta: "Film it on your phone, then scan a code here to upload it.",
      }
    : game
      ? {
          id: game.id,
          art: game.hero_url || game.thumb_url,
          title: game.title,
          meta:
            game.status === "ready"
              ? [shortDate(game.recorded_at), minutes(game.duration_s)]
                  .filter(Boolean)
                  .join(", ")
              : stageWords(game),
        }
      : {
          id: ADD,
          art: null,
          title: "Add a game",
          meta: "Film it on your phone, then scan a code here to upload it.",
        };

  return (
    <View style={styles.root} testID="home" dataSet={{ zone: z }}>
      <Hero
        art={hero.art}
        fallback={game?.thumb_url}
        title={hero.title}
        meta={hero.meta}
        testID="hero"
        dataSet={{ gameId: hero.id }}
        textStyle={[styles.heroText, lifted && { opacity: 0 }]}
      >
        {actions.length
          ? actions.map((x, i) => (
              <PillButton
                key={x.id}
                label={x.label}
                play={x.play}
                focused={z === "hero" && i === bi}
                testID={x.id === "add" ? "library-add" : `hero-${x.id}`}
                dataSet={
                  x.resume === undefined ? undefined : { resume: x.resume }
                }
              />
            ))
          : null}
      </Hero>
      <Gear focused={z === "gear"} />

      <View
        style={[
          styles.rows,
          lifted && { transform: [{ translateY: -PLAYERS_LIFT }] },
        ]}
      >
        {empty ? null : (
          <>
            <Title style={styles.rowTitle}>Games</Title>
            <View
              style={[
                styles.row,
                {
                  transform: [
                    { translateX: rowShift(gi, CARDS_SHOWN, CARD_PITCH) },
                  ],
                },
              ]}
            >
              {ids.map((id, i) => {
                const on = z === "games" && i === gi;
                const g = games[i - 1];
                return g ? (
                  <GameCard key={id} game={g} focused={on} />
                ) : (
                  <View
                    key={id}
                    style={styles.cardSlot}
                    testID="library-add"
                    dataSet={{ focused: on ? "true" : "false" }}
                  >
                    <Focusable focused={on}>
                      <View style={[styles.art, styles.addArt]}>
                        <View style={styles.plusH} />
                        <View style={styles.plusV} />
                      </View>
                    </Focusable>
                    <T style={styles.caption}>Add game</T>
                    <T style={styles.captionMeta}>From your phone</T>
                  </View>
                );
              })}
            </View>
          </>
        )}
        {playersShown ? (
          <>
            <Title style={[styles.rowTitle, { marginTop: sp(3) }]}>
              Players
            </Title>
            <View
              style={[
                styles.row,
                {
                  transform: [
                    { translateX: rowShift(pi, AVATARS_SHOWN, AVATAR_PITCH) },
                  ],
                },
              ]}
            >
              {[...players, null].map((p, i) => {
                const on = z === "players" && i === pi;
                return (
                  <View
                    key={p?.profile_id ?? "all"}
                    style={styles.personSlot}
                    testID={p ? "home-player" : "library-players"}
                    dataSet={{
                      profileId: p?.profile_id,
                      focused: on ? "true" : "false",
                    }}
                  >
                    <Focusable focused={on} round={px(AVATAR / 2)}>
                      {p ? (
                        <Avatar
                          name={p.name}
                          photo={p.photo_url}
                          size={AVATAR}
                        />
                      ) : (
                        <View style={styles.all}>
                          <T style={type.body}>All</T>
                        </View>
                      )}
                    </Focusable>
                    <T style={styles.personName} numberOfLines={1}>
                      {p ? p.name : "All players"}
                    </T>
                  </View>
                );
              })}
            </View>
          </>
        ) : null}
      </View>
    </View>
  );
}

function GameCard({ game: g, focused }: { game: GameLike; focused: boolean }) {
  const working = g.status !== "ready";
  const art = g.thumb_url || g.hero_url;
  return (
    <View
      style={styles.cardSlot}
      testID="game-card"
      dataSet={{
        gameId: g.id,
        focused: focused ? "true" : "false",
        processing: working ? "true" : "false",
      }}
    >
      <Focusable focused={focused}>
        <View style={styles.art}>
          {art ? (
            <Image
              source={{ uri: art }}
              style={[StyleSheet.absoluteFill, working && { opacity: 0.3 }]}
              resizeMode="cover"
            />
          ) : null}
          {working ? (
            <View style={styles.center}>
              <ProgressRing
                size={px(80)}
                frac={progressOf(g)}
                testID="progress-ring"
              />
            </View>
          ) : null}
        </View>
      </Focusable>
      <T testID="game-card-title" numberOfLines={1} style={styles.caption}>
        {g.title}
      </T>
      {working ? (
        <T testID="game-status" numberOfLines={1} style={styles.captionMeta}>
          {stageWords(g)}
        </T>
      ) : (
        <T testID="game-meta" numberOfLines={1} style={styles.captionMeta}>
          {[shortDate(g.recorded_at), minutes(g.duration_s)]
            .filter(Boolean)
            .join(", ")}
        </T>
      )}
    </View>
  );
}

/** The Settings gear, drawn with Views (no icon font): four rotated bars for the teeth, a
 *  disc, and a hole in the button's colour. Chalk fill when focused, like a chip. */
function Gear({ focused }: { focused: boolean }) {
  const bg = focused ? color.chalk : color.bench;
  const ink = focused ? color.floor : color.chalk;
  const s = px(40);
  return (
    <View
      testID="library-settings"
      dataSet={{ focused: focused ? "true" : "false" }}
      style={[styles.gear, { backgroundColor: bg }]}
    >
      {[0, 45, 90, 135].map((r) => (
        <View
          key={r}
          style={{
            position: "absolute",
            width: s,
            height: s * 0.26,
            borderRadius: px(2),
            backgroundColor: ink,
            transform: [{ rotate: `${r}deg` }],
          }}
        />
      ))}
      <View
        style={{
          position: "absolute",
          width: s * 0.74,
          height: s * 0.74,
          borderRadius: s,
          backgroundColor: ink,
        }}
      />
      <View
        style={{
          position: "absolute",
          width: s * 0.32,
          height: s * 0.32,
          borderRadius: s,
          backgroundColor: bg,
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: color.floor, overflow: "hidden" },
  heroText: { bottom: px(1080 - 512) },
  gear: {
    position: "absolute",
    top: safe.y,
    right: safe.x,
    width: px(72),
    height: px(72),
    borderRadius: radius.chip,
    alignItems: "center",
    justifyContent: "center",
  },
  rows: { position: "absolute", top: px(552), left: 0, right: 0 },
  rowTitle: { marginLeft: safe.x },
  row: { flexDirection: "row", paddingLeft: safe.x - RING_BOX },
  cardSlot: { width: CARD_W + 2 * RING_BOX, marginRight: sp(4) },
  art: { width: CARD_W, height: CARD_H, backgroundColor: color.bench },
  addArt: { alignItems: "center", justifyContent: "center" },
  plusH: {
    position: "absolute",
    width: px(56),
    height: px(6),
    borderRadius: px(3),
    backgroundColor: color.chalk,
  },
  plusV: {
    position: "absolute",
    width: px(6),
    height: px(56),
    borderRadius: px(3),
    backgroundColor: color.chalk,
  },
  center: {
    ...StyleSheet.absoluteFill,
    alignItems: "center",
    justifyContent: "center",
  },
  caption: { ...type.body, marginTop: sp(2), marginLeft: RING_BOX },
  captionMeta: { ...type.meta, color: color.bleacher, marginLeft: RING_BOX },
  personSlot: {
    width: px(AVATAR) + 2 * RING_BOX,
    marginRight: sp(6),
    alignItems: "center",
  },
  all: {
    width: px(AVATAR),
    height: px(AVATAR),
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: color.bench,
  },
  personName: {
    ...type.meta,
    marginTop: sp(1.5),
    width: px(AVATAR) + px(64),
    textAlign: "center",
  },
});
