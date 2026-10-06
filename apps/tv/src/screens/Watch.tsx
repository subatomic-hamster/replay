// W2 wide transport, W3 select mode, W4 follow mode, W5 court inset, W6 spotlight,
// W7 tagging, W8 event markers + jumps, H5 bookmarks — the apps/web Watch screen on RN.
//
// Remote map: Select toggles play/pause in wide/follow (pausing the wide shot opens select
// mode) and follows the focused box in select mode; Left/Right scrub ±5 s in wide/follow
// and move between boxes in select mode (repeated presses cycle overlapping boxes); Up opens
// the action row (from select mode: Up at the top edge). Every keyboard shortcut of the web
// client (b, s, t, p, [ ], , .) also lives in that row, so D-pad + Back reach everything.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, View, useWindowDimensions } from "react-native";
import { eventJump } from "../../../../packages/tv-core/src/display";
import { cropRectAt, mapBB } from "../../../../packages/tv-core/src/follow";
import { followSource } from "../../../../packages/tv-core/src/followSource";
import { nextFocus, type Direction } from "../../../../packages/tv-core/src/spatial";
import { createTracksCache } from "../../../../packages/tv-core/src/tracksCache";
import type { CropPath, GameEvent, Player } from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { CourtInset } from "../components/CourtInset";
import { FollowFrame } from "../components/FollowFrame";
import { SeekBar } from "../components/SeekBar";
import { SelectOverlay } from "../components/SelectOverlay";
import { TextEntryDialog } from "../components/TextEntryDialog";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { FOLLOWCAM_MODE } from "../platform/config";
import { PlayerSurface, useClockTime, type PlayerHandle } from "../playback/PlayerSurface";
import { color, font, px } from "../theme";
import { ApiErrorBanner, Hint, Loading, Pill, T, useAsync } from "../ui";

type Mode = "wide" | "select" | "follow";
const SEEK_STEP_S = 10;
const SCRUB_STEP_S = 5;

const MENU: { id: string; label: string; action: DpadAction | "library" | "highlights" | "review" | "replays" }[] = [
  { id: "nav-library", label: "Library", action: "library" },
  { id: "nav-highlights", label: "Highlights", action: "highlights" },
  { id: "nav-review", label: "Review", action: "review" },
  { id: "nav-pair", label: "Pair phone", action: "pair" },
  { id: "action-prev-event", label: "◀ Event", action: "prev-event" },
  { id: "action-next-event", label: "Event ▶", action: "next-event" },
  { id: "action-bookmark", label: "Bookmark", action: "bookmark" },
  { id: "action-spotlight", label: "Spotlight", action: "spotlight" },
  { id: "action-tag", label: "Tag player", action: "tag" },
  // M8: only when the game has rendered replays (filtered below). Last, so the indices
  // of the items above stay put.
  { id: "nav-replays", label: "Replays", action: "replays" },
];

// ponytail: a hardcoded list beats a contacts import for a demo (same as apps/web).
const PRESET_NAMES = ["Marcus", "Jordan", "Alex", "Sam", "Chris", "Taylor", "Zoe", "Riley"];
const titleCase = (v: string) => v.replace(/(^|\s)\S/g, (m) => m.toUpperCase());

export function Watch({
  gameId,
  initialMode,
  initialPid,
  initialT,
}: {
  gameId: string;
  initialMode?: string;
  initialPid?: string;
  initialT?: number;
}) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const { data: replays } = useAsync(() => api.listReplays(gameId), [gameId]);
  const menuItems = useMemo(
    () => (replays?.length ? MENU : MENU.filter((m) => m.action !== "replays")),
    [replays],
  );
  const [events, setEvents] = useState<GameEvent[]>([]);
  const [roster, setRoster] = useState<Player[]>([]);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const [mode, setMode] = useState<Mode>(
    initialMode === "select" || initialMode === "follow" ? initialMode : "wide",
  );
  const [pid, setPid] = useState<string | null>(initialPid ?? null);
  const [focusId, setFocusId] = useState<string | null>(initialPid ?? null);
  const [crop, setCrop] = useState<CropPath | null>(null);
  const [spotlight, setSpotlight] = useState(false);
  const [tagging, setTagging] = useState<string | null>(null);
  const [menu, setMenu] = useState<number | null>(null);
  const [chrome, setChrome] = useState(true);
  const [rendering, setRendering] = useState(false);
  const renderAsked = useRef<string | null>(null);
  const [version, bump] = useState(0);
  const restoreT = useRef<number | null>(initialT ?? null);
  const { width: winW, height: winH } = useWindowDimensions();

  const clock = handle?.clock ?? null;
  const t = useClockTime(clock);
  const duration = handle?.duration() || game?.video.duration_s || 0;

  const tracks = useMemo(() => (game ? createTracksCache(game, api.getTracksChunk) : null), [game]);

  useEffect(() => {
    if (game) setRoster(game.players);
  }, [game]);

  useEffect(() => {
    if (!game) return;
    api.getEvents(game).then(setEvents, () => setEvents([]));
  }, [game]);

  useEffect(() => tracks?.onChange(() => bump((n) => n + 1)), [tracks]);
  useEffect(() => {
    tracks?.ensure(t);
  }, [tracks, t]);

  // Deep-link restore (?t=) once the media knows its duration.
  useEffect(() => {
    if (!handle || restoreT.current === null) return;
    const target = restoreT.current;
    const timer = setInterval(() => {
      if (handle.duration() > 0) {
        handle.seek(target);
        restoreT.current = null;
        clearInterval(timer);
      }
    }, 50);
    return () => clearInterval(timer);
  }, [handle]);

  const rendition = pid ? game?.renditions?.players?.[pid] : undefined;
  const wideUrl = game ? api.mediaUrl(game, game.renditions.wide) : "";
  const source = followSource(
    FOLLOWCAM_MODE,
    wideUrl,
    mode === "follow" && !!pid,
    rendition && game ? api.mediaUrl(game, rendition) : null,
  );

  useEffect(() => {
    if (!game || !pid || !source.needsRender || renderAsked.current === pid) return;
    renderAsked.current = pid;
    api.renderPlayer(game.id, pid).then(
      (job) => setRendering(!!job.job_id),
      () => setRendering(false),
    );
  }, [game, pid, source.needsRender]);

  useEffect(() => {
    if (mode !== "follow") setRendering(false);
  }, [mode]);

  // D-6 client follow-cam: the crop path for the followed player.
  useEffect(() => {
    if (!source.useCrop || !pid || !game) {
      setCrop(null);
      return;
    }
    let live = true;
    api.getCropPath(game, pid).then((c) => live && setCrop(c), () => live && setCrop(null));
    return () => {
      live = false;
    };
  }, [source.useCrop, pid, game]);

  // `version` bumps when a tracks chunk lands; the cache reads it internally.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const players = useMemo(() => tracks?.playersAt(t) ?? [], [tracks, t, version]);
  const sorted = useMemo(() => [...events].sort((a, b) => a.t_key - b.t_key), [events]);

  const tagTarget = mode === "follow" ? pid : (focusId ?? pid);

  const run = useCallback(
    (a: DpadAction) => {
      if (!handle || !game) return;
      switch (a) {
        case "playpause":
          handle.toggle();
          // W3: pausing the wide shot is what opens select mode.
          if (mode !== "follow") setMode(handle.paused() ? "select" : "wide");
          break;
        case "seek-back":
          handle.seek(handle.currentTime() - SEEK_STEP_S);
          break;
        case "seek-fwd":
          handle.seek(handle.currentTime() + SEEK_STEP_S);
          break;
        case "prev-event":
        case "next-event": {
          const to = eventJump(sorted, handle.currentTime(), a === "next-event" ? 1 : -1);
          if (to !== null) handle.seek(to);
          break;
        }
        case "spotlight":
          setSpotlight((s) => !s);
          break;
        case "bookmark":
          api
            .createEvent(game.id, { type: "bookmark", t_key: handle.currentTime() })
            .then((e) => setEvents((prev) => [...prev, e]))
            .catch(() => {});
          break;
        case "tag":
          if (tagTarget) setTagging(tagTarget);
          break;
        case "pair":
          navigate({ name: "pair", gameId: game.id });
          break;
        default:
          break;
      }
    },
    [handle, game, mode, sorted, tagTarget],
  );

  const onAction = useCallback(
    (a: DpadAction) => {
      setChrome(true);
      if (!handle || !game) return;

      // The action row: Left/Right move, Select runs, Down/Back close it.
      if (menu !== null) {
        if (a === "left") setMenu(Math.max(0, menu - 1));
        else if (a === "right") setMenu(Math.min(menuItems.length - 1, menu + 1));
        else if (a === "down" || a === "back") setMenu(null);
        else if (a === "select") {
          const item = menuItems[menu].action;
          if (item === "library") navigate({ name: "library" });
          else if (item === "highlights") navigate({ name: "highlights", gameId: game.id });
          else if (item === "review") navigate({ name: "review", gameId: game.id });
          else if (item === "replays") navigate({ name: "replays", gameId: game.id });
          else {
            setMenu(null);
            run(item);
          }
        } else run(a);
        return;
      }

      switch (a) {
        case "menu":
          setMenu(0);
          break;
        case "up":
        case "down":
        case "left":
        case "right": {
          if (mode === "select") {
            const targets = players.map((p) => ({
              id: p.id,
              cx: p.bb[0] + p.bb[2] / 2,
              cy: p.bb[1] + p.bb[3] / 2,
              w: p.bb[2],
              h: p.bb[3],
            }));
            const from = focusId ?? targets[0]?.id ?? null;
            const next = nextFocus(targets, from, a as Direction);
            // Up against the top edge leaves the boxes for the action row.
            if (a === "up" && next === from) setMenu(0);
            else setFocusId(next);
          } else if (a === "up") {
            setMenu(0);
          } else if (a !== "down") {
            // W2/S-15: in playback the seek bar is the focused control.
            handle.seek(handle.currentTime() + (a === "right" ? SCRUB_STEP_S : -SCRUB_STEP_S));
          }
          break;
        }
        case "select":
          if (mode === "select") {
            if (!focusId) break;
            // W4: follow at the same timestamp; playback state is left as-is (S-19).
            setPid(focusId);
            setMode("follow");
          } else {
            run("playpause");
          }
          break;
        case "back":
          // W4: the followed player keeps the amber frame in the wide shot; `pid` clears
          // only on another pick or on leaving the game.
          if (mode !== "wide") setMode("wide");
          else navigate({ name: "library" });
          break;
        default:
          run(a);
      }
    },
    [handle, game, mode, focusId, players, menu, menuItems, run],
  );
  useDpad(onAction, !tagging);

  // Transport fades a few seconds into playback; any key brings it back.
  useEffect(() => {
    if (!chrome || !handle) return;
    const timer = setInterval(() => {
      if (!handle.paused()) setChrome(false);
    }, 3000);
    return () => clearInterval(timer);
  }, [chrome, handle]);

  // Select mode with nothing (or a stale id) focused: start at the leftmost box.
  useEffect(() => {
    if (mode !== "select" || players.length === 0) return;
    if (focusId && players.some((p) => p.id === focusId)) return;
    setFocusId([...players].sort((a, b) => a.bb[0] - b.bb[0])[0].id);
  }, [mode, focusId, players]);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <Loading />;

  const followName = roster.find((p) => p.id === pid);
  // W4/W6: in follow mode the video carries the crop transform, so the followed player's
  // spotlight cutout goes through the same crop rect.
  const cropRect = crop ? cropRectAt(crop, t) : null;
  const spotPlayers = players.filter((p) => p.id === pid).map((p) => ({ ...p, bb: mapBB(p.bb, cropRect) }));
  const showFollowFrame = !!pid && mode !== "select" && source.src === wideUrl;
  const stageW = Math.min(winW, (winH * 16) / 9);

  return (
    <View style={styles.screen} testID="watch" dataSet={{ mode }}>
      <View style={{ width: stageW }}>
        <PlayerSurface ref={setHandle} src={source.src} crop={source.useCrop ? crop : null} muted>
          {mode === "select" ? (
            <SelectOverlay players={players} roster={roster} focusId={focusId} spotlight={spotlight} />
          ) : null}
          {mode === "follow" ? (
            <>
              <SelectOverlay
                players={spotPlayers}
                roster={roster}
                focusId={pid}
                spotlight={spotlight}
                showBoxes={false}
              />
              <View style={styles.followBadge} testID="followcam-active" dataSet={{ playerId: pid ?? "" }}>
                <T style={styles.badgeText}>FOLLOW • {followName?.name ?? pid}</T>
              </View>
              {rendering ? (
                <View style={[styles.followBadge, { top: px(96) }]} testID="rendering-badge">
                  <T style={styles.badgeText}>rendering…</T>
                </View>
              ) : null}
            </>
          ) : null}
          {showFollowFrame && pid ? (
            <FollowFrame
              pid={pid}
              label={followName?.name ?? pid}
              players={players}
              t={t}
              crop={source.useCrop ? crop : null}
            />
          ) : null}
        </PlayerSurface>

        <View
          style={[StyleSheet.absoluteFill, { opacity: chrome || menu !== null ? 1 : 0 }]}
          pointerEvents="none"
          testID="watch-chrome"
          dataSet={{ hidden: chrome || menu !== null ? "false" : "true" }}
        >
          <View style={styles.top}>
            <View style={styles.menuRow}>
              {menuItems.map((m, i) => (
                <Pill key={m.id} testID={m.id} label={m.label} focused={menu === i} />
              ))}
            </View>
            <T style={styles.title} numberOfLines={1}>
              {game.title}
            </T>
          </View>

          {mode !== "follow" ? (
            <View style={[styles.modePill, mode === "select" && { backgroundColor: color.accent }]}>
              <T
                style={[styles.badgeText, { color: mode === "select" ? color.onAccent : color.fg }]}
                testID="mode-pill"
              >
                {mode === "select" ? "SELECT" : "WIDE"}
              </T>
            </View>
          ) : null}

          <View style={styles.inset}>
            <CourtInset
              court={game.sport_ui?.court}
              variant={game.court.variant}
              players={players}
              roster={roster}
              selectedId={mode === "follow" ? pid : focusId}
            />
          </View>

          <View style={styles.transport}>
            <SeekBar duration={duration} current={t} events={sorted} focused={mode !== "select" && menu === null} />
            <Hint>
              {menu !== null
                ? "Left/Right pick an action · Select runs it · Down or Back closes"
                : mode === "select"
                  ? "Arrows pick a player · Select follows · Up at the top opens actions · Back exits"
                  : mode === "follow"
                    ? "Select plays/pauses · Left/Right scrub · Up actions · Back returns to wide"
                    : "Select pauses to pick a player · Left/Right scrub 5 s · Up actions · Back to library"}
            </Hint>
          </View>
        </View>
      </View>

      {tagging ? (
        <TextEntryDialog
          idPrefix="tag"
          title={`Tag player ${tagging}`}
          initial={roster.find((p) => p.id === tagging)?.name}
          presets={PRESET_NAMES.filter(
            (n) => n === roster.find((p) => p.id === tagging)?.name || !roster.some((p) => p.name === n),
          )}
          format={titleCase}
          dataSet={{ playerId: tagging }}
          onCancel={() => setTagging(null)}
          onSubmit={(name) => {
            const target = tagging;
            setTagging(null);
            api
              .patchPlayer(game.id, target, { name })
              .then((p) => setRoster((prev) => prev.map((r) => (r.id === p.id ? p : r))))
              .catch(() => {});
          }}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: "#000", alignItems: "center", justifyContent: "center" },
  top: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    paddingHorizontal: px(48),
    paddingTop: px(28),
    paddingBottom: px(12),
    backgroundColor: "rgba(5, 7, 10, 0.78)",
  },
  menuRow: { flexDirection: "row", flexWrap: "wrap" },
  title: { color: color.dim, fontSize: font.body },
  modePill: {
    position: "absolute",
    right: px(48),
    top: px(170),
    backgroundColor: color.scrim,
    paddingHorizontal: px(18),
    paddingVertical: px(4),
    borderRadius: px(8),
  },
  inset: {
    position: "absolute",
    right: px(48),
    bottom: px(190),
    padding: px(10),
    backgroundColor: color.scrim,
    borderRadius: px(10),
  },
  transport: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: px(48),
    paddingTop: px(28),
    paddingBottom: px(28),
    backgroundColor: "rgba(5, 7, 10, 0.82)",
  },
  followBadge: {
    position: "absolute",
    left: px(48),
    top: px(170),
    backgroundColor: color.accent,
    paddingHorizontal: px(18),
    paddingVertical: px(4),
    borderRadius: px(8),
  },
  badgeText: { color: color.onAccent, fontSize: font.body, fontWeight: "800" },
});
