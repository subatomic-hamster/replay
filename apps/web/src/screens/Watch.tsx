// W2 wide transport, W3 select mode, W4 follow mode, W5 court inset, W6 spotlight,
// W7 tagging, W8 event markers + jumps, H5 bookmarks.
//
// Mode and selected player live in the URL query (?mode=&pid=&t=) so a reload restores
// the session — this is the E-21 behaviour this implementation commits to.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { FORCE_SPOTLIGHT, SEEK_STEP_S, followcam } from "../config";
import { createTracksCache } from "../data/tracksCache";
import { nextFocus, type Direction } from "../focus/spatial";
import { useDpad, type DpadAction } from "../platform/keys";
import { PlayerSurface, type PlayerHandle } from "../playback/PlayerSurface";
import { followSource } from "../playback/followSource";
import { useClockTime } from "../playback/clock";
import { CourtInset } from "../components/CourtInset";
import { FollowFrame, cropRectAt, mapBB } from "../components/FollowFrame";
import { SeekBarEvents } from "../components/SeekBarEvents";
import { SelectOverlay } from "../components/SelectOverlay";
import { TagDialog } from "../components/TagDialog";
import { navigate, setQuery, useLocation } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import { storedSession, useSessionMessages, type SessionMessage } from "../session";
import type { CropPath, GameEvent, Player } from "../api/types";
import { eventJump } from "../../../../packages/tv-core/src/display";
import {
  broadcastOf,
  captionAt,
  commentaryLines,
  hypeBars,
  nextPeak,
} from "../../../../packages/tv-core/src/discovery";

type Mode = "wide" | "select" | "follow";
const SCRUB_STEP_S = 5;
const HYPE_BARS = 96;
const TOAST_MS = 3000;

type Toggle = "broadcast" | "captions" | "hype-peak";
const NAV: { id: string; label: string; to?: (id: string) => string; toggle?: Toggle }[] = [
  { id: "nav-library", label: "Library", to: () => "/tv" },
  { id: "nav-highlights", label: "Highlights", to: (id) => `/tv/${id}/highlights` },
  { id: "nav-review", label: "Review", to: (id) => `/tv/${id}/review` },
  // M8: only when the game has rendered replays (filtered in Watch).
  { id: "nav-replays", label: "Replays", to: (id) => `/tv/${id}/replays` },
  // M13 — each data-driven item shows only when the game has that data (no sport branch).
  { id: "action-broadcast", label: "Broadcast", toggle: "broadcast" },
  { id: "action-captions", label: "Commentary", toggle: "captions" },
  { id: "action-hype-peak", label: "Hype peak", toggle: "hype-peak" },
  { id: "nav-clips", label: "Clips", to: (id) => `/tv/${id}/clips` },
  { id: "nav-rallies", label: "Rallies", to: (id) => `/tv/${id}/rallies` },
  { id: "nav-search", label: "Search", to: (id) => `/tv/${id}/search` },
  { id: "nav-advice", label: "Advice", to: (id) => `/tv/${id}/advice` },
];

export function Watch({ gameId }: { gameId: string }) {
  const { params } = useLocation();
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const { data: replays } = useAsync(() => api.listReplays(gameId), [gameId]);
  const { data: renditions } = useAsync(() => api.listRenditions(gameId), [gameId]);
  const { data: commentary } = useAsync(() => api.getCommentary(gameId), [gameId]);
  const { data: hype } = useAsync(() => api.getHype(gameId), [gameId]);
  const { data: rallies } = useAsync(() => api.getRallies(gameId), [gameId]);
  const broadcast = broadcastOf(renditions);
  const lines = useMemo(() => commentaryLines(commentary), [commentary]);
  const hypeMeter = useMemo(() => (hype ? hypeBars(hype.values, HYPE_BARS) : null), [hype]);
  const nav = useMemo(() => {
    const hidden = new Set<string>();
    if (!replays?.length) hidden.add("nav-replays");
    if (!broadcast) hidden.add("action-broadcast");
    if (!lines.length) hidden.add("action-captions");
    if (!hype?.candidates.length) hidden.add("action-hype-peak");
    if (!rallies?.n) hidden.add("nav-rallies");
    return NAV.filter((n) => !hidden.has(n.id));
  }, [replays, broadcast, lines, hype, rallies]);
  const [broadcastOn, setBroadcastOn] = useState(false);
  const [captionsOn, setCaptionsOn] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [events, setEvents] = useState<GameEvent[]>([]);
  const [roster, setRoster] = useState<Player[]>([]);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const [mode, setMode] = useState<Mode>((params.get("mode") as Mode) ?? "wide");
  const [pid, setPid] = useState<string | null>(params.get("pid"));
  const [focusId, setFocusId] = useState<string | null>(params.get("pid"));
  const [crop, setCrop] = useState<CropPath | null>(null);
  const [spotlight, setSpotlight] = useState(false);
  const [tagging, setTagging] = useState<string | null>(null);
  const [navFocus, setNavFocus] = useState<number | null>(null);
  const [rendering, setRendering] = useState(false);
  const renderAsked = useRef<string | null>(null);
  const [version, bump] = useState(0);
  const restoreT = useRef<number | null>(Number(params.get("t")) || null);

  const clock = handle?.clock ?? null;
  const t = useClockTime(clock);
  // `||`, not `??`: an element with no metadata yet reports NaN, and the clock does not
  // tick while paused, so a `??` here left the seek bar stuck at a zero-length timeline
  // until some unrelated state change forced a re-render.
  const duration = handle?.duration() || game?.video.duration_s || 0;

  const tracks = useMemo(() => (game ? createTracksCache(game) : null), [game]);

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

  // Restore ?t= once the media knows its duration.
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

  // Keep the URL in sync at 1 Hz — enough to restore, cheap enough to ignore.
  useEffect(() => {
    const timer = setInterval(() => {
      if (!handle) return;
      setQuery({
        mode: mode === "wide" ? null : mode,
        pid: pid,
        t: handle.currentTime().toFixed(1),
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [handle, mode, pid]);

  // Plan task 12: `rendition` mode plays the pre-rendered per-player MP4 when the game
  // has one; otherwise it falls back to the client transform and queues the render.
  const rendition = pid ? game?.renditions?.players?.[pid] : undefined;
  const wideUrl = game ? api.mediaUrl(game, game.renditions.wide) : "";
  const source = followSource(
    followcam.mode,
    wideUrl,
    mode === "follow" && !!pid && !FORCE_SPOTLIGHT,
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

  // D-6 client follow-cam: fetch the crop path for the followed player.
  useEffect(() => {
    if (!source.useCrop || !pid || !game) {
      setCrop(null);
      return;
    }
    let live = true;
    api.getCropPath(game, pid).then((c) => live && setCrop(c), () => setCrop(null));
    return () => {
      live = false;
    };
  }, [source.useCrop, pid, game]);

  // `version` is bumped when a tracks chunk lands — it is a real dependency even though
  // the cache reads it internally.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const players = useMemo(() => tracks?.playersAt(t) ?? [], [tracks, t, version]);
  const sorted = [...events].sort((a, b) => a.t_key - b.t_key);

  const jumpEvent = useCallback(
    (dir: 1 | -1) => {
      if (!handle) return;
      const next = eventJump(sorted, handle.currentTime(), dir);
      if (next !== null) handle.seek(next);
    },
    [handle, sorted],
  );

  const [chrome, setChrome] = useState(true);

  const onAction = useCallback(
    (a: DpadAction) => {
      setChrome(true);
      if (!handle || !game) return;
      // Top nav row: reachable with ArrowUp, so every screen is D-pad reachable (NF-03).
      if (navFocus !== null) {
        if (a === "left") setNavFocus((i) => Math.max(0, (i ?? 0) - 1));
        else if (a === "right") setNavFocus((i) => Math.min(nav.length - 1, (i ?? 0) + 1));
        else if (a === "down" || a === "back") setNavFocus(null);
        else if (a === "select") {
          const item = nav[navFocus];
          if (item.to) navigate(item.to(game.id));
          else if (item.toggle === "broadcast") {
            // D-42: rendition time = source time, so the swap keeps the playback position;
            // track boxes describe the wide frame, so select/follow sit broadcast out.
            setBroadcastOn((on) => !on);
            setMode("wide");
            setQuery({ mode: null });
          } else if (item.toggle === "captions") setCaptionsOn((on) => !on);
          else if (item.toggle === "hype-peak") {
            const to = nextPeak(hype?.candidates ?? [], handle.currentTime());
            if (to !== null) handle.seek(to);
          }
        } else if (a === "playpause") handle.toggle();
        return;
      }

      switch (a) {
        case "playpause": {
          handle.toggle();
          // W3: pausing the wide shot is what opens select mode (not over the broadcast).
          if (mode !== "follow" && !broadcastOn) setMode(handle.paused() ? "select" : "wide");
          break;
        }
        case "seek-back":
          handle.seek(handle.currentTime() - SEEK_STEP_S);
          break;
        case "seek-fwd":
          handle.seek(handle.currentTime() + SEEK_STEP_S);
          break;
        case "prev-event":
          jumpEvent(-1);
          break;
        case "next-event":
          jumpEvent(1);
          break;
        case "spotlight":
          setSpotlight((s) => !s);
          break;
        case "bookmark": {
          const at = handle.currentTime();
          api
            .createEvent(game.id, { type: "bookmark", t_key: at })
            .then((e) => setEvents((prev) => [...prev, e]))
            .catch(() => {});
          break;
        }
        case "tag":
          if (mode === "select" && focusId) setTagging(focusId);
          else if (mode === "follow" && pid) setTagging(pid);
          break;
        case "pair":
          navigate(`/tv/pair?game=${game.id}`);
          break;
        case "up":
        case "left":
        case "right":
        case "down": {
          if (mode === "select") {
            // In select mode every arrow belongs to the boxes; the menu is one Back away.
            const targets = players.map((p) => ({
              id: p.id,
              cx: p.bb[0] + p.bb[2] / 2,
              cy: p.bb[1] + p.bb[3] / 2,
            }));
            setFocusId(nextFocus(targets, focusId ?? targets[0]?.id ?? null, a as Direction));
          } else if (a === "up") {
            setNavFocus(0);
          } else if (a !== "down") {
            // W2/S-15: in wide playback the seek bar is the focused control.
            handle.seek(handle.currentTime() + (a === "right" ? SCRUB_STEP_S : -SCRUB_STEP_S));
          }
          break;
        }
        case "select":
          if (mode === "select" && focusId) {
            // W4: follow at the same timestamp. Playback state is left as-is on
            // purpose — the user pressed Space to get here, Space resumes.
            setPid(focusId);
            setMode("follow");
            setQuery({ mode: "follow", pid: focusId });
          }
          break;
        case "back":
          if (mode === "follow") {
            // W4: the wide shot keeps the amber frame on whoever was being followed,
            // so `pid` survives the way back out — it clears only on another pick or
            // on leaving the game.
            setMode("wide");
            setQuery({ mode: null });
          } else if (mode === "select") {
            setMode("wide");
            setQuery({ mode: null });
          } else {
            navigate("/tv");
          }
          break;
        case "delete":
          break;
      }
    },
    [handle, game, mode, focusId, pid, players, jumpEvent, navFocus, nav, hype, broadcastOn],
  );
  useDpad(onAction, !tagging);

  // Paired phone: tell it what is on screen once a second (its "Clip that" posts a tap at
  // this media time), play the search hits it sends, and confirm the clips its taps cut.
  const send = useSessionMessages(
    storedSession()?.id,
    useCallback(
      (msg: SessionMessage) => {
        if (msg.type === "seek" && typeof msg.t === "number" && handle) {
          handle.seek(msg.t);
          handle.play();
          setMode("wide");
          setQuery({ mode: null });
        } else if (msg.type === "clip") setToast(msg.label ?? "Clip saved");
      },
      [handle],
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

  // The transport fades out a few seconds into playback and comes back on the next key, so
  // a lean-back watch is just the game. Paused (and so all of select mode) keeps it up.
  // The wake-up rides on `onAction` rather than its own window listener: a second listener
  // that sets state re-registers useDpad's handler mid-dispatch, and the DOM then skips the
  // removed entry — the keypress that woke the chrome would be eaten.
  useEffect(() => {
    if (!chrome || !handle) return;
    const timer = setInterval(() => {
      if (!handle.paused()) setChrome(false);
    }, 3000);
    return () => clearInterval(timer);
  }, [chrome, handle]);

  // Entering select mode with nothing focused: start at the leftmost box. Also covers
  // a focus that went stale — seek past the end of a player's track (or come back from
  // following one who has left) and the id no longer matches any box, which left select
  // mode with no focus ring and nothing for Enter to act on.
  useEffect(() => {
    if (mode !== "select" || players.length === 0) return;
    if (focusId && players.some((p) => p.id === focusId)) return;
    setFocusId([...players].sort((a, b) => a.bb[0] - b.bb[0])[0].id);
  }, [mode, focusId, players]);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <div className="screen">Loading…</div>;

  const followName = roster.find((p) => p.id === pid);
  const spotlightOn = spotlight || (mode === "follow" && FORCE_SPOTLIGHT);
  // W4/W6: in follow mode the video carries the crop transform, so the followed player's
  // box — the amber frame and the spotlight cutout alike — has to be mapped through the
  // same crop rect before it can be placed in the (untransformed) overlay layer.
  const cropRect = crop ? cropRectAt(crop, t) : null;
  const spotPlayers = players
    .filter((p) => p.id === pid)
    .map((p) => ({ ...p, bb: mapBB(p.bb, cropRect) }));
  // Track boxes describe the wide frame; a pre-rendered per-player rendition is a
  // different picture entirely, so the frame sits that one case out.
  const onBroadcast = broadcastOn && !!broadcast;
  const src = onBroadcast && broadcast ? broadcast.url : source.src;
  const showFollowFrame = !!pid && mode !== "select" && src === wideUrl;
  const caption = captionsOn ? captionAt(lines, t) : null;

  return (
    <div
      className="screen watch"
      data-testid="watch"
      data-mode={mode}
      data-broadcast={onBroadcast ? "true" : "false"}
    >
      <div className="watch-stage">
        {/* The broadcast rendition carries its own audio mix (game audio, stings, ducked
            narration — D-43), so it plays with sound; the raw wide shot stays muted. */}
        <PlayerSurface
          ref={setHandle}
          src={src}
          crop={!onBroadcast && source.useCrop ? crop : null}
          muted={!onBroadcast}
        >
          {mode === "select" ? (
            <SelectOverlay
              players={players}
              roster={roster}
              focusId={focusId}
              spotlight={spotlightOn}
            />
          ) : null}
          {mode === "follow" ? (
            <>
              <SelectOverlay
                players={spotPlayers}
                roster={roster}
                focusId={pid}
                spotlight={spotlightOn}
                showBoxes={false}
              />
              <div className="followcam-badge" data-testid="followcam-active" data-player-id={pid}>
                FOLLOW • {followName?.name ?? pid}
              </div>
              {rendering ? (
                <div className="rendering-badge" data-testid="rendering-badge">
                  rendering…
                </div>
              ) : null}
            </>
          ) : null}
          {showFollowFrame && pid ? (
            <FollowFrame
              pid={pid}
              label={followName?.name ?? pid}
              tracks={tracks}
              clock={clock}
              crop={source.useCrop ? crop : null}
            />
          ) : null}
          {caption ? (
            // M7 grounded commentary as captions, timed by the clock (audio_t / audio_s).
            <div
              className={`caption${chrome || navFocus !== null ? " raised" : ""}`}
              data-testid="caption"
              data-t={caption.audio_t ?? caption.t}
            >
              {caption.text}
            </div>
          ) : null}
          {toast ? (
            <div className="toast" data-testid="toast">
              {toast}
            </div>
          ) : null}
        </PlayerSurface>

        <div className="watch-chrome" data-hidden={chrome ? "false" : "true"}>
          <nav className="topnav">
            {nav.map((n, i) => {
              const on =
                n.toggle === "broadcast" ? onBroadcast : n.toggle === "captions" ? captionsOn : null;
              return (
                <span
                  key={n.id}
                  className={`navitem${navFocus === i ? " focused" : ""}${on ? " on" : ""}`}
                  data-testid={n.id}
                  data-focused={navFocus === i ? "true" : "false"}
                  data-on={on === null ? undefined : on ? "true" : "false"}
                >
                  {n.label}
                </span>
              );
            })}
            <span className="title">{game.title}</span>
          </nav>

          {mode !== "follow" ? (
            <div className={`mode-pill ${mode}`} data-testid="mode-pill">
              {mode === "select" ? "SELECT" : onBroadcast ? "BROADCAST" : "WIDE"}
            </div>
          ) : null}

          {/* The broadcast draws its own graphics; the inset would sit on top of them. */}
          {onBroadcast ? null : (
            <CourtInset
              court={game.sport_ui?.court}
              variant={game.court.variant}
              players={players}
              roster={roster}
              selectedId={mode === "follow" ? pid : focusId}
            />
          )}

          <div className="watch-transport">
            <SeekBarEvents
              duration={duration}
              current={t}
              events={sorted}
              focused={mode === "wide"}
              hype={hypeMeter}
            />
            <p className="hint">
              {mode === "select" ? (
                <>
                  <b>Arrows</b> pick a player · <b>Enter</b> follows · <b>t</b> tags ·{" "}
                  <b>s</b> spotlight · <b>Escape</b> exits
                </>
              ) : mode === "follow" ? (
                <>
                  <b>Space</b> plays · <b>Escape</b> returns to the wide shot
                </>
              ) : (
                <>
                  <b>Space</b> pauses to select · <b>,</b> / <b>.</b> ±10 s · <b>[</b> /{" "}
                  <b>]</b> events · <b>b</b> bookmark · <b>↑</b> menu
                </>
              )}
            </p>
          </div>
        </div>
      </div>

      {tagging ? (
        <TagDialog
          playerId={tagging}
          initial={roster.find((p) => p.id === tagging)?.name}
          taken={roster.map((p) => p.name).filter((n): n is string => !!n)}
          onCancel={() => setTagging(null)}
          onSave={(name) => {
            const target = tagging;
            setTagging(null);
            api
              .patchPlayer(game.id, target, { name })
              .then((p) => setRoster((prev) => prev.map((r) => (r.id === p.id ? p : r))))
              .catch(() => {});
          }}
        />
      ) : null}
    </div>
  );
}
