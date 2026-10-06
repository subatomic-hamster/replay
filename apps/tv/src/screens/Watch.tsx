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
import {
  broadcastOf,
  captionAt,
  commentaryLines,
  hypeBars,
  nextPeak,
} from "../../../../packages/tv-core/src/discovery";
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
import { ProfilePicker } from "../components/ProfilePicker";
import { TextEntryDialog } from "../components/TextEntryDialog";
import { menuStep, watchMenu, type MenuAction, type MenuFocus } from "../../../../packages/tv-core/src/menu";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { FOLLOWCAM_MODE } from "../platform/config";
import { PlayerSurface, useClockTime, type PlayerHandle } from "../playback/PlayerSurface";
import { storedSession, useSessionMessages, type SessionMessage } from "../session";
import { color, font, px } from "../theme";
import { ApiErrorBanner, Hint, Loading, Pill, T, useAsync } from "../ui";

type Mode = "wide" | "select" | "follow";
const SEEK_STEP_S = 10;
const SCRUB_STEP_S = 5;
const HYPE_BARS = 96;
/** Badges and toasts sit just under the one-row action bar. */
const BELOW_BAR = px(176);
const TOAST_MS = 3000;

/** Menu actions that open a per-game screen. */
const GAME_ROUTES = ["highlights", "review", "replays", "clips", "rallies", "search", "advice"] as const;
type GameRoute = (typeof GAME_ROUTES)[number];

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
  const { data: renditions } = useAsync(() => api.listRenditions(gameId), [gameId]);
  const { data: commentary } = useAsync(() => api.getCommentary(gameId), [gameId]);
  const { data: hype } = useAsync(() => api.getHype(gameId), [gameId]);
  const { data: rallies } = useAsync(() => api.getRallies(gameId), [gameId]);
  const broadcast = broadcastOf(renditions);
  const lines = useMemo(() => commentaryLines(commentary), [commentary]);
  const hypeBarsMemo = useMemo(() => (hype ? hypeBars(hype.values, HYPE_BARS) : null), [hype]);
  const menuItems = useMemo(() => {
    const hidden = new Set<MenuAction>();
    if (!replays?.length) hidden.add("replays");
    if (!broadcast) hidden.add("broadcast");
    if (!lines.length) hidden.add("captions");
    if (!hype?.candidates.length) hidden.add("hype-peak");
    if (!rallies?.n) hidden.add("rallies");
    return watchMenu(hidden);
  }, [replays, broadcast, lines, hype, rallies]);
  const [broadcastOn, setBroadcastOn] = useState(false);
  const [captionsOn, setCaptionsOn] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
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
  const [linking, setLinking] = useState<string | null>(null);
  const [menu, setMenu] = useState<MenuFocus | null>(null);
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

  // Deep-link restore (?t=) once the media knows its duration; a failed source never will
  // (the handle changes when it fails, so this re-runs and stops).
  useEffect(() => {
    if (!handle || handle.error() || restoreT.current === null) return;
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
          // W3: pausing the wide shot is what opens select mode (not over the broadcast).
          if (mode !== "follow" && !broadcastOn) setMode(handle.paused() ? "select" : "wide");
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
    [handle, game, mode, sorted, tagTarget, broadcastOn],
  );

  const onAction = useCallback(
    (a: DpadAction) => {
      setChrome(true);
      if (!handle || !game) return;

      // The action menu (one row; a group opens its own row): Left/Right move, Select runs
      // or opens, Back/Down close the group, then the menu.
      if (menu !== null) {
        if (a === "left" || a === "right" || a === "select" || a === "back" || a === "down" || a === "up") {
          const step = menuStep(menuItems, menu, a);
          setMenu(step.focus);
          const item = step.run?.action;
          if (!item) return;
          if (item === "library") navigate({ name: "library" });
          else if (item === "players") navigate({ name: "players", from: game.id });
          else if ((GAME_ROUTES as readonly string[]).includes(item)) {
            navigate({ name: item as GameRoute, gameId: game.id });
          } else if (item === "broadcast") {
            // D-42: rendition time = source time, so the swap keeps the playback position;
            // track boxes describe the wide frame, so select/follow sit broadcast out.
            setBroadcastOn((on) => !on);
            setMode("wide");
          } else if (item === "captions") setCaptionsOn((on) => !on);
          else if (item === "hype-peak") {
            const to = nextPeak(hype?.candidates ?? [], handle.currentTime());
            if (to !== null) handle.seek(to);
          } else if (item === "link-profile") {
            setMenu(null);
            if (tagTarget) setLinking(tagTarget);
            else setToast("Pause and pick a player first");
          } else {
            setMenu(null);
            run(item as DpadAction);
          }
        } else run(a);
        return;
      }

      switch (a) {
        case "menu":
          setMenu({ group: null, i: 0 });
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
            if (a === "up" && next === from) setMenu({ group: null, i: 0 });
            else setFocusId(next);
          } else if (a === "up") {
            setMenu({ group: null, i: 0 });
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
    [handle, game, mode, focusId, players, menu, menuItems, run, hype, tagTarget],
  );
  useDpad(onAction, !tagging && !linking);

  // Paired phone: tell it what is on screen once a second (its "Clip that" posts a tap at
  // this media time), play the search hits it sends, and confirm the clips its taps cut.
  const send = useSessionMessages(
    storedSession()?.id,
    useCallback(
      (msg: SessionMessage) => {
        if (msg.type === "seek" && typeof msg.t === "number" && handle) {
          handle.seek(msg.t);
          handle.play();
          if (!broadcastOn) setMode("wide");
        } else if (msg.type === "clip") setToast(msg.label ?? "Clip saved");
      },
      [handle, broadcastOn],
    ),
  );
  useEffect(() => {
    if (!handle || !game) return;
    const timer = setInterval(
      () => send({ type: "now", game_id: game.id, title: game.title, t: handle.currentTime() }),
      1000,
    );
    return () => clearInterval(timer);
  }, [handle, game, send]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), TOAST_MS);
    return () => clearTimeout(timer);
  }, [toast]);

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
  const onBroadcast = broadcastOn && !!broadcast;
  const src = onBroadcast && broadcast ? broadcast.url : source.src;
  const showFollowFrame = !!pid && mode !== "select" && src === wideUrl;
  const stageW = Math.min(winW, (winH * 16) / 9);
  const caption = captionsOn ? captionAt(lines, t) : null;
  const shown = chrome || menu !== null;

  return (
    <View style={styles.screen} testID="watch" dataSet={{ mode, broadcast: onBroadcast ? "true" : "false" }}>
      <View style={{ width: stageW }}>
        {/* The broadcast rendition carries its own audio mix (game audio, stings, ducked
            narration — D-43), so it plays with sound; the raw wide shot stays muted. */}
        <PlayerSurface
          ref={setHandle}
          src={src}
          crop={!onBroadcast && source.useCrop ? crop : null}
          muted={!onBroadcast}
        >
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
                <View style={[styles.followBadge, { top: BELOW_BAR + px(64) }]} testID="rendering-badge">
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
          {caption ? (
            // M7 grounded commentary as captions, timed by the clock (audio_t / audio_s).
            <View style={[styles.caption, { bottom: shown ? px(250) : px(64) }]}>
              <T style={styles.captionText} testID="caption" dataSet={{ t: caption.audio_t ?? caption.t }}>
                {caption.text}
              </T>
            </View>
          ) : null}
          {toast ? (
            <View style={styles.toast} testID="toast">
              <T style={styles.badgeText}>{toast}</T>
            </View>
          ) : null}
        </PlayerSurface>

        <View
          style={[StyleSheet.absoluteFill, { opacity: shown ? 1 : 0 }]}
          pointerEvents="none"
          testID="watch-chrome"
          dataSet={{ hidden: shown ? "false" : "true" }}
        >
          <View style={styles.top}>
            {/* One row at a time: the top entries, or the open group's items. Every item
                is in the tree (hidden rows display:none) so an item's presence still says
                whether the game has that data. */}
            {[null, ...menuItems.filter((m) => m.items).map((m) => m.id)].map((group) => {
              const open = (menu?.group ?? null) === group;
              const entries = group === null ? menuItems : (menuItems.find((m) => m.id === group)?.items ?? []);
              return (
                <View
                  key={group ?? "top"}
                  style={[styles.menuRow, !open && { display: "none" }]}
                  testID={group ? `menu-row-${group}` : "menu-row"}
                  dataSet={{ open: open ? "true" : "false" }}
                >
                  {group ? (
                    <T style={styles.crumb}>{menuItems.find((m) => m.id === group)?.label.replace(" ▸", "")} ›</T>
                  ) : null}
                  {entries.map((m, i) => {
                    const on = m.action === "broadcast" ? onBroadcast : m.action === "captions" ? captionsOn : null;
                    return (
                      <Pill
                        key={m.id}
                        testID={m.id}
                        label={m.label}
                        focused={open && menu?.i === i}
                        active={!!on}
                        dataSet={{ group: group ?? "", ...(on === null ? {} : { on: on ? "true" : "false" }) }}
                      />
                    );
                  })}
                </View>
              );
            })}
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
                {mode === "select" ? "SELECT" : onBroadcast ? "BROADCAST" : "WIDE"}
              </T>
            </View>
          ) : null}

          {/* The broadcast draws its own graphics; the inset would sit on top of them. */}
          {onBroadcast ? null : (
            <View style={styles.inset}>
              <CourtInset
                court={game.sport_ui?.court}
                variant={game.court.variant}
                players={players}
                roster={roster}
                selectedId={mode === "follow" ? pid : focusId}
              />
            </View>
          )}

          <View style={styles.transport}>
            <SeekBar
              duration={duration}
              current={t}
              events={sorted}
              focused={mode !== "select" && menu === null}
              hype={hypeBarsMemo}
            />
            <Hint>
              {menu !== null
                ? menu.group
                  ? "Left/Right pick an action · Select runs it · Back returns to the menu"
                  : "Left/Right pick · Select runs or opens a group (▸) · Down or Back closes"
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

      {linking ? (
        <ProfilePicker
          gameId={game.id}
          playerId={linking}
          playerLabel={roster.find((p) => p.id === linking)?.name ?? `#${linking}`}
          onCancel={() => setLinking(null)}
          onLinked={(p) => {
            const target = linking;
            setLinking(null);
            setRoster((prev) =>
              prev.map((r) => (r.id === target ? { ...r, name: p.name, tagged: true, profile_id: p.profile_id } : r)),
            );
            setToast(`Linked to ${p.name}`);
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
  // never wraps: the menu is one row at 1080p (groups open in place of it)
  menuRow: { flexDirection: "row", alignItems: "center" },
  crumb: { color: color.accent, fontSize: font.body, fontWeight: "700", marginRight: px(16), marginBottom: px(12) },
  title: { color: color.dim, fontSize: font.body },
  modePill: {
    position: "absolute",
    right: px(48),
    top: BELOW_BAR,
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
    top: BELOW_BAR,
    backgroundColor: color.accent,
    paddingHorizontal: px(18),
    paddingVertical: px(4),
    borderRadius: px(8),
  },
  badgeText: { color: color.onAccent, fontSize: font.body, fontWeight: "800" },
  caption: {
    position: "absolute",
    left: px(240),
    right: px(240),
    alignItems: "center",
  },
  captionText: {
    fontSize: px(36),
    fontWeight: "600",
    textAlign: "center",
    paddingHorizontal: px(24),
    paddingVertical: px(10),
    borderRadius: px(8),
    backgroundColor: "rgba(5, 7, 10, 0.85)",
  },
  toast: {
    position: "absolute",
    alignSelf: "center",
    top: BELOW_BAR,
    backgroundColor: color.accent,
    paddingHorizontal: px(24),
    paddingVertical: px(8),
    borderRadius: px(8),
  },
});
