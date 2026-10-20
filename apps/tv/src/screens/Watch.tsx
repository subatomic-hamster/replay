// The player (route "watch"; docs/ux/redesign.md "Player"). Layers stack over full-bleed
// video and Back peels one: bare video → transport → Moments (Down) or Do more (Up/Menu);
// Back on bare video goes Home. Following a player and picking one (select mode) sit
// between the layers and the bare video in that chain.
//
// Transport: the title (or the followed player's chip) top-left and the court-line
// timeline; it shows on any key and hides after 5 s of playback (pausing keeps it).
// Seeking (Left/Right): a tap moves 10 s, holding accelerates (playback/seek.ts), the video
// pauses while a storyboard preview rides the playhead, snaps to a moment within 3 s, and
// playback resumes from the new point after the release. Rew/FF scrub at 2/4/8/16×,
// Select or Play commits. Prev/Next jump moments (or a reel's plays).
//
// Ways to watch: Full game, Highlights (the top hype candidates, ≤13, back to back, or a
// highlight query's clips) and Condensed (the condensed rendition, or the rallies back to
// back while it renders). Everything polls every 10 s while the game is still processing,
// so moments arrive on the line and Do more's tiles light up.
//
// Do more (Wave 3): Follow player (player chips; pick on screen; Spotlight, Tag, Link once
// a player is picked), Angles and Free view of the nearest play (AngleView replaces the
// game video until Back, which resumes the game where it was), Watch (the ways), Stats
// (StatsPanel, the right third), Commentary, On your phone (PhonePanel's QR handoff) and
// Bookmark. Where the game was is remembered (resume.ts) every second and before leaving
// (stored every 5 s, and at once on leaving), so a sub-screen's Back or Home's Resume
// comes back to the same time and play state, also after an app restart.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Animated, StyleSheet, View, useWindowDimensions } from "react-native";
import {
  broadcastOf,
  captionAt,
  commentaryLines,
  rallyAtCondensed,
  rallyOrder,
  type RallyDoc,
} from "../../../../packages/tv-core/src/discovery";
import { fmtDuration } from "../../../../packages/tv-core/src/display";
import { cropRectAt, mapBB } from "../../../../packages/tv-core/src/follow";
import { followSource } from "../../../../packages/tv-core/src/followSource";
import {
  nextFocus,
  type Direction,
} from "../../../../packages/tv-core/src/spatial";
import {
  tierBadge,
  type ReplayManifest,
} from "../../../../packages/tv-core/src/replays";
import { createTracksCache } from "../../../../packages/tv-core/src/tracksCache";
import type {
  CropPath,
  FeatureKey,
  Game,
  Moment,
  Player,
  Storyboard,
} from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { AngleView } from "../components/AngleView";
import { DoMoreLayer, type Tile } from "../components/DoMoreLayer";
import { FollowFrame } from "../components/FollowFrame";
import { MomentsLayer } from "../components/MomentsLayer";
import { PhonePanel } from "../components/PhonePanel";
import { ProfilePicker } from "../components/ProfilePicker";
import { SelectOverlay } from "../components/SelectOverlay";
import { StatsPanel, type StatsExit } from "../components/StatsPanel";
import { TextEntryDialog } from "../components/TextEntryDialog";
import {
  SpriteFrame,
  Timeline,
  TIMELINE_H,
  type SeekView,
} from "../components/Timeline";
import { etaText } from "../gameState";
import { useDpad, type DpadAction } from "../input";
import { navigate, type Way } from "../nav";
import { FOLLOWCAM_MODE } from "../platform/config";
import {
  PlayerSurface,
  useClockTime,
  type PlayerHandle,
} from "../playback/PlayerSurface";
import {
  HIDE_MS,
  holdStep,
  jumpMoment,
  LINGER_MS,
  nextScrub,
  REPEAT_FLOOR_MS,
  snapTo,
} from "../playback/seek";
import { rememberSpot, resumeSpot } from "../resume";
import {
  storedSession,
  useSessionMessages,
  type SessionMessage,
} from "../session";
import { color, px, radius, safe, sp, type } from "../theme";
import { ApiErrorBanner, Fade, Hint, Loading, T, useAsync } from "../ui";

type Mode = "wide" | "select" | "follow";
type Layer = "moments" | "domore" | "stats" | "phone" | null;
/** A play's replay angles in place of the game video: the angle to open, or Free view. */
interface Angle {
  playId: string;
  start: number | "free";
}
interface Seg {
  t_start: number;
  t_end: number;
}
/** A way to watch played as back-to-back segments of the game. */
interface Reel {
  way: Way;
  name: string;
  segs: Seg[];
  i: number;
}
interface SeekState {
  from: number;
  target: number;
  wasPlaying: boolean;
  /** when the current hold began (a new tap after a release starts a new hold) */
  holdStart: number;
  lastStep: number;
  step: number;
  released: boolean;
  scrub: { dir: 1 | -1; speed: number } | null;
}

const POLL_MS = 10_000;
const TOAST_MS = 3000;
/** Highlights stay short, like Prime's Rapid Recap. */
const REEL_MAX = 13;
const WAY_NAMES: Record<Way, string> = {
  full: "Full game",
  highlights: "Highlights",
  condensed: "Condensed",
};

// ponytail: a hardcoded list beats a contacts import for a demo (same as apps/web).
const PRESET_NAMES = [
  "Marcus",
  "Jordan",
  "Alex",
  "Sam",
  "Chris",
  "Taylor",
  "Zoe",
  "Riley",
];
const titleCase = (v: string) => v.replace(/(^|\s)\S/g, (m) => m.toUpperCase());
const clamp = (v: number, lo: number, hi: number) =>
  Math.min(Math.max(v, lo), hi);

/** Segments in time order with overlaps merged (the reel never plays a second twice). */
function mergeSegs(segs: Seg[]): Seg[] {
  const out: Seg[] = [];
  for (const s of [...segs].sort((a, b) => a.t_start - b.t_start)) {
    const last = out[out.length - 1];
    if (last && s.t_start <= last.t_end)
      last.t_end = Math.max(last.t_end, s.t_end);
    else out.push({ ...s });
  }
  return out;
}

export function Watch({
  gameId,
  initialMode,
  initialPid,
  initialT,
  initialWay,
  initialPlay,
  q,
}: {
  gameId: string;
  initialMode?: string;
  initialPid?: string;
  initialT?: number;
  initialWay?: Way;
  /** open this play's replay angles first (a `/tv/:id/replays/:playId` deep link) */
  initialPlay?: string;
  q?: string;
}) {
  const {
    data: game,
    error,
    reload,
  } = useAsync(() => api.getGame(gameId), [gameId]);
  const { data: replays } = useAsync(() => api.listReplays(gameId), [gameId]);
  const { data: renditions } = useAsync(
    () => api.listRenditions(gameId),
    [gameId],
  );
  const { data: commentary } = useAsync(
    () => api.getCommentary(gameId),
    [gameId],
  );
  const { data: hype, error: hypeError } = useAsync(
    () => api.getHype(gameId),
    [gameId],
  );
  // The game re-read while it is processing: readiness, features, the storyboard URL.
  const [live, setLive] = useState<Game | null>(null);
  const info = live ?? game;
  const [moments, setMoments] = useState<Moment[]>([]);
  const [storyboard, setStoryboard] = useState<Storyboard | null>(null);
  const [rallies, setRallies] = useState<RallyDoc | null>(null);
  const broadcast = broadcastOf(renditions);
  const lines = useMemo(() => commentaryLines(commentary), [commentary]);

  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const [mode, setMode] = useState<Mode>(
    initialMode === "select" || initialMode === "follow" ? initialMode : "wide",
  );
  const [layer, setLayer] = useState<Layer>(null);
  const [layerT, setLayerT] = useState(0); // media time when the layer opened
  const [chrome, setChrome] = useState(true);
  const [way, setWay] = useState<Way>(
    initialWay ?? (q ? "highlights" : "full"),
  );
  const [reel, setReel] = useState<Reel | null>(null);
  const [condensedSrc, setCondensedSrc] = useState<string | null>(null);
  const [cue, setCue] = useState<Moment | null>(null);
  const [seekV, setSeekV] = useState<SeekView | null>(null);
  const [commentaryOn, setCommentaryOn] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [roster, setRoster] = useState<Player[]>([]);
  const [pid, setPid] = useState<string | null>(initialPid ?? null);
  const [focusId, setFocusId] = useState<string | null>(initialPid ?? null);
  const [crop, setCrop] = useState<CropPath | null>(null);
  const [spotlight, setSpotlight] = useState(false);
  const [tagging, setTagging] = useState<string | null>(null);
  const [linking, setLinking] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);
  const renderAsked = useRef<string | null>(null);
  const [version, bump] = useState(0);
  const [angle, setAngle] = useState<Angle | null>(
    initialPlay ? { playId: initialPlay, start: 0 } : null,
  );
  /** Where the game was when an angle opened (Back resumes it there). */
  const angleReturn = useRef<{ t: number; play: boolean } | null>(null);
  const [near, setNear] = useState<ReplayManifest | null>(null);
  const { data: profiles } = useAsync(
    () => api.listProfiles().catch(() => []),
    [],
  );
  /** Seek + play once the (next) source knows its duration: deep link, a way's first
   *  play, the swap to or from the condensed rendition, the return from an angle. A plain
   *  open of the full game starts where it was left (resume.ts). */
  const pending = useRef<{ t: number | null; play: boolean } | null>(
    (() => {
      const play = initialMode !== "select";
      if (initialT !== undefined) return { t: initialT, play };
      const spot =
        (initialWay ?? "full") === "full" && !q && !initialPlay
          ? resumeSpot(gameId)
          : null;
      return spot
        ? { t: spot.t, play: play && spot.playing }
        : { t: null, play };
    })(),
  );
  const seekRef = useRef<SeekState | null>(null);
  const linger = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastKey = useRef(Date.now());
  const { width: winW, height: winH } = useWindowDimensions();

  const t = useClockTime(handle?.clock ?? null);
  const duration =
    handle?.duration() || (condensedSrc ? 0 : info?.video.duration_s) || 0;
  // Moments are game time: the condensed rendition has its own clock.
  const lineMoments = useMemo(
    () => (condensedSrc ? [] : moments),
    [condensedSrc, moments],
  );

  // ---------------------------------------------------------------- data
  const loadMoments = useCallback(
    () => api.getMoments(gameId).then(setMoments, () => {}),
    [gameId],
  );
  useEffect(() => {
    loadMoments();
    api.getRallies(gameId).then(setRallies, () => setRallies(null));
  }, [gameId, loadMoments]);

  const processing = !!info && info.status !== "ready";
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => {
      api.getGame(gameId).then(setLive, () => {});
      loadMoments();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [processing, gameId, loadMoments]);
  // Processing finished: re-read the game once so the roster and tracks arrive.
  useEffect(() => {
    if (live?.status === "ready" && game && game.status !== "ready") reload();
  }, [live, game, reload]);

  const sbUrl = info?.storyboard_url;
  useEffect(() => {
    if (!info || !sbUrl) return;
    let on = true;
    api.getStoryboard(info).then(
      (s) => on && setStoryboard(s),
      () => on && setStoryboard(null),
    );
    return () => {
      on = false;
    };
    // the URL, not every re-read of the game
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sbUrl]);

  useEffect(() => {
    if (game) setRoster(game.players);
  }, [game]);

  const tracks = useMemo(
    () => (game ? createTracksCache(game, api.getTracksChunk) : null),
    [game],
  );
  useEffect(() => tracks?.onChange(() => bump((n) => n + 1)), [tracks]);
  useEffect(() => {
    tracks?.ensure(t);
  }, [tracks, t]);

  // A pending seek/play lands once the media knows its duration; a failed source never
  // will (the handle changes when it fails, so this re-runs and stops).
  useEffect(() => {
    if (!handle || handle.error() || pending.current === null) return;
    const timer = setInterval(() => {
      const p = pending.current;
      if (!p) return clearInterval(timer);
      if (handle.duration() > 0) {
        pending.current = null;
        clearInterval(timer);
        if (p.t !== null) handle.seek(p.t);
        if (p.play) handle.play();
      }
    }, 50);
    return () => clearInterval(timer);
  }, [handle, condensedSrc]);

  /** Seek and play now, or as soon as the source can. */
  const goTo = useCallback(
    (to: number | null, play = true) => {
      if (handle && handle.duration() > 0 && !handle.error()) {
        pending.current = null; // newer than anything still queued
        if (to !== null) handle.seek(to);
        if (play) handle.play();
      } else pending.current = { t: to, play };
    },
    [handle],
  );

  /**
   * The viewer acted (play/pause, seek, jump): a queued start must not land later on top of
   * them. Its start point lands now if the source can take it (else stays queued, without
   * the play); returns whether it was about to play, which counts as playing. The poll
   * above ticks every 50 ms, so a key in that window used to be undone. Web and native.
   */
  const settle = useCallback((h: PlayerHandle | null): boolean => {
    const p = pending.current;
    if (!p) return false;
    if (h && h.duration() > 0 && !h.error()) {
      pending.current = null;
      if (p.t !== null) h.seek(p.t);
    } else pending.current = p.t === null ? null : { t: p.t, play: false };
    return p.play;
  }, []);
  const toggle = useCallback(() => {
    if (settle(handle)) handle?.pause();
    else handle?.toggle();
  }, [handle, settle]);
  const pause = useCallback(() => {
    settle(handle);
    handle?.pause();
  }, [handle, settle]);

  /** Note where the game is (resume.ts): a queued start while one is pending, a seek's
   *  target while seeking. Game time only (not the condensed rendition's clock). */
  const gameLength = info?.video.duration_s ?? 0;
  const remember = useCallback(
    /** `now`: persist at once (leaving), not on resume.ts's save cadence */
    (now = false) => {
      if (!handle || condensedSrc || handle.error()) return;
      const p = pending.current;
      const s = seekRef.current;
      const spot = p
        ? p.t === null
          ? null
          : { t: p.t, playing: p.play }
        : s
          ? { t: s.target, playing: s.wasPlaying }
          : { t: handle.currentTime(), playing: !handle.paused() };
      if (spot) rememberSpot(gameId, { ...spot, duration: gameLength }, now);
    },
    [handle, condensedSrc, gameId, gameLength],
  );

  // ---------------------------------------------------------------- follow-cam
  const rendition = pid ? game?.renditions?.players?.[pid] : undefined;
  const wideUrl = game ? api.mediaUrl(game, game.renditions.wide) : "";
  const source = followSource(
    FOLLOWCAM_MODE,
    wideUrl,
    mode === "follow" && !!pid,
    rendition && game ? api.mediaUrl(game, rendition) : null,
  );

  useEffect(() => {
    if (!game || !pid || !source.needsRender || renderAsked.current === pid)
      return;
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
    let on = true;
    api.getCropPath(game, pid).then(
      (c) => on && setCrop(c),
      () => on && setCrop(null),
    );
    return () => {
      on = false;
    };
  }, [source.useCrop, pid, game]);

  // `version` bumps when a tracks chunk lands; the cache reads it internally.
  const players = useMemo(
    () => tracks?.playersAt(t) ?? [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tracks, t, version],
  );
  const tagTarget = mode === "follow" ? pid : (focusId ?? pid);

  // Select mode with nothing (or a stale id) focused: start at the leftmost box.
  useEffect(() => {
    if (mode !== "select" || players.length === 0) return;
    if (focusId && players.some((p) => p.id === focusId)) return;
    setFocusId([...players].sort((a, b) => a.bb[0] - b.bb[0])[0].id);
  }, [mode, focusId, players]);

  // ---------------------------------------------------------------- ways to watch
  const startWay = useCallback(
    (w: Way) => {
      setLayer(null);
      setWay(w);
      if (w === "full") {
        setReel(null);
        if (condensedSrc) {
          // Back to game time: the rally on screen, at the same point in it.
          const r = rallyAtCondensed(
            rallies?.rallies ?? [],
            handle?.currentTime() ?? 0,
          );
          const at = r
            ? r.t_start + (handle?.currentTime() ?? 0) - (r.condensed_t ?? 0)
            : 0;
          pending.current = { t: at, play: true };
          setCondensedSrc(null);
        }
        return;
      }
      const play = (name: string, segs: Seg[]) => {
        const list = mergeSegs(segs);
        if (!list.length) {
          setWay("full");
          setReel(null);
          setToast(`No ${name.toLowerCase()} for this game yet`);
          return;
        }
        setReel({ way: w, name, segs: list, i: 0 });
        goTo(list[0].t_start);
      };
      if (w === "highlights") {
        if (q) {
          api.query(gameId, q).then(
            (r) => play(q, r.clips),
            () => play(q, []),
          );
          return;
        }
        const top = [...(hype?.candidates ?? [])]
          .sort((a, b) => b.score - a.score)
          .slice(0, REEL_MAX)
          .map((c) => ({
            t_start: c.t_start ?? Math.max(0, c.t - 3),
            t_end: c.t_end ?? c.t + 1,
          }));
        play("Highlights", top);
        return;
      }
      // Condensed: the rendition when it exists; else the rallies back to back, and ask
      // for the render so it is there next time.
      api.getRallies(gameId).then(
        (doc) => {
          setRallies(doc);
          if (doc.condensed.status === "done" && doc.condensed.url) {
            setReel(null);
            pending.current = { t: 0, play: true };
            setCondensedSrc(doc.condensed.url);
            return;
          }
          if (
            ["none", "missing", "failed", "error"].includes(
              doc.condensed.status,
            )
          ) {
            api.renderCondensed(gameId).catch(() => {});
          }
          play("Condensed", rallyOrder(doc, "time"));
        },
        () => play("Condensed", []),
      );
    },
    [condensedSrc, rallies, handle, goTo, gameId, q, hype],
  );

  // The way the route asked for, once its data is in (hype answers or fails).
  const started = useRef(false);
  useEffect(() => {
    if (started.current || !game || !handle) return;
    if (way === "highlights" && !q && !hype && !hypeError) return;
    started.current = true;
    if (way !== "full") startWay(way);
  }, [game, handle, way, q, hype, hypeError, startWay]);

  // A reel plays its segments back to back, then hands over to the full game.
  useEffect(() => {
    if (!reel || !handle || seekV) return;
    const seg = reel.segs[reel.i];
    // Only just past the end: a clock still reporting the time before the reel's own
    // seek landed (far past it) is not an end.
    if (!seg || t < seg.t_end || t > seg.t_end + 2) return;
    if (reel.i + 1 < reel.segs.length) {
      setReel({ ...reel, i: reel.i + 1 });
      handle.seek(reel.segs[reel.i + 1].t_start);
    } else {
      handle.pause();
      setReel(null);
      setWay("full");
      setChrome(true);
    }
  }, [t, reel, handle, seekV]);

  /** Where a seek to `to` lands in a reel: inside a segment, else the next one's start. */
  const inReel = useCallback(
    (to: number): number => {
      if (!reel) return to;
      const i = reel.segs.findIndex((s) => to < s.t_end);
      if (i < 0) {
        setReel(null);
        setWay("full");
        return to;
      }
      setReel({ ...reel, i });
      return Math.max(to, reel.segs[i].t_start);
    },
    [reel],
  );

  // ---------------------------------------------------------------- transport + seek
  // Seek helpers run from timers too, so they read the latest render through a ref.
  const latest = useRef({ handle, duration, moments: lineMoments, inReel });
  latest.current = { handle, duration, moments: lineMoments, inReel };

  const poke = useCallback(() => {
    lastKey.current = Date.now();
    setChrome(true);
  }, []);

  const publish = useCallback(() => {
    const s = seekRef.current;
    const snapped =
      s && !s.scrub ? snapTo(latest.current.moments, s.target) : null;
    setSeekV(
      s
        ? {
            target: s.target,
            // the readout agrees with the time chip: measured to the snapped moment
            delta: (snapped?.t ?? s.target) - s.from,
            step: s.step,
            scrub: s.scrub,
            snapped,
          }
        : null,
    );
  }, []);

  const clearLinger = useCallback(() => {
    if (linger.current) clearTimeout(linger.current);
    linger.current = null;
  }, []);

  const beginSeek = useCallback((): SeekState | null => {
    const h = latest.current.handle;
    if (!h) return null;
    const queued = settle(h); // a queued autoplay counts as playing
    const now = h.currentTime();
    const s: SeekState = {
      from: now,
      target: now,
      wasPlaying: queued || !h.paused(),
      holdStart: Date.now(),
      lastStep: 0,
      step: holdStep(0),
      released: false,
      scrub: null,
    };
    h.pause();
    seekRef.current = s;
    return s;
  }, [settle]);

  const commit = useCallback(
    (play?: boolean) => {
      clearLinger();
      const s = seekRef.current;
      const { handle: h, moments: ms, inReel: land } = latest.current;
      seekRef.current = null;
      publish();
      if (!s || !h) return;
      const snapped = s.scrub ? null : snapTo(ms, s.target);
      h.seek(land(snapped ? snapped.t_start : s.target));
      if (play ?? (s.wasPlaying || !!s.scrub)) h.play();
      lastKey.current = Date.now();
    },
    [clearLinger, publish],
  );

  const cancelSeek = useCallback(() => {
    clearLinger();
    const s = seekRef.current;
    seekRef.current = null;
    publish();
    if (s?.wasPlaying) latest.current.handle?.play();
  }, [clearLinger, publish]);

  const holdSeek = useCallback(
    (dir: 1 | -1) => {
      const now = Date.now();
      const s = seekRef.current ?? beginSeek();
      if (!s) return;
      if (s.released || s.scrub) {
        clearLinger();
        s.released = false;
        s.scrub = null;
        s.holdStart = now;
        s.lastStep = 0;
      }
      if (now - s.lastStep < REPEAT_FLOOR_MS) return;
      s.lastStep = now;
      s.step = holdStep(now - s.holdStart);
      s.target = clamp(s.target + dir * s.step, 0, latest.current.duration);
      publish();
    },
    [beginSeek, clearLinger, publish],
  );

  const releaseSeek = useCallback(() => {
    const s = seekRef.current;
    if (!s || s.scrub) return;
    s.released = true;
    clearLinger();
    linger.current = setTimeout(() => commit(), LINGER_MS);
  }, [clearLinger, commit]);

  const scrubPress = useCallback(
    (dir: 1 | -1) => {
      const s = seekRef.current ?? beginSeek();
      if (!s) return;
      clearLinger();
      s.released = false;
      s.scrub = nextScrub(s.scrub, dir);
      publish();
    },
    [beginSeek, clearLinger, publish],
  );

  // Rew/FF: the seek point moves at speed × real time until Select/Play commits.
  const scrubbing = !!seekV?.scrub;
  useEffect(() => {
    if (!scrubbing) return;
    let last = Date.now();
    const timer = setInterval(() => {
      const s = seekRef.current;
      if (!s?.scrub) return;
      const now = Date.now();
      s.target = clamp(
        s.target + (s.scrub.dir * s.scrub.speed * (now - last)) / 1000,
        0,
        latest.current.duration,
      );
      last = now;
      publish();
    }, 100);
    return () => clearInterval(timer);
  }, [scrubbing, publish]);
  useEffect(() => clearLinger, [clearLinger]);

  // Transport hides after HIDE_MS of playback without a key; paused, a layer, a seek or
  // picking a player keep it.
  useEffect(() => {
    if (!chrome || !handle || layer || seekV || mode === "select") return;
    const timer = setInterval(() => {
      if (!handle.paused() && Date.now() - lastKey.current >= HIDE_MS)
        setChrome(false);
    }, 250);
    return () => clearInterval(timer);
  }, [chrome, handle, layer, seekV, mode]);

  // The Stats panel and the phone layer cover the transport's corners: it steps aside.
  const overlay = layer === "stats" || layer === "phone";
  const shown =
    !overlay &&
    (chrome || layer !== null || seekV !== null || mode === "select");
  const [fade] = useState(() => new Animated.Value(1));
  useEffect(() => {
    Animated.timing(fade, {
      toValue: shown ? 1 : 0,
      duration: shown ? 150 : 300,
      useNativeDriver: false,
    }).start();
  }, [shown, fade]);

  // ---------------------------------------------------------------- actions
  const openLayer = useCallback(
    (l: Layer) => {
      if (seekRef.current) commit();
      // Moments cue to the media's own time: the clock lags a seek that has not reported yet.
      if (handle) {
        if (settle(handle)) handle.play();
        setLayerT(handle.currentTime());
      }
      setLayer(l);
    },
    [commit, handle, settle],
  );

  /** A play's angles (or Free view) in place of the game video; the game pauses where it
   *  is and its player unmounts (one decoder at a time on the Fire TV). */
  const openAngle = useCallback(
    (playId: string, start: number | "free") => {
      if (handle) {
        const queued = settle(handle);
        remember(true);
        angleReturn.current = {
          t: handle.currentTime(),
          play: queued || !handle.paused(),
        };
        handle.pause();
      }
      setLayer(null);
      setAngle({ playId, start });
    },
    [handle, settle, remember],
  );
  /** Back from an angle: the game where it was (a deep link: from the play's start). */
  const closeAngle = useCallback((m: ReplayManifest | null) => {
    pending.current = angleReturn.current ?? {
      t: m?.t_start ?? null,
      play: true,
    };
    angleReturn.current = null;
    setAngle(null);
    setChrome(true);
    lastKey.current = Date.now();
  }, []);

  /** Follow a player from Do more's chips: in place, playback as it was. */
  const follow = useCallback(
    (id: string) => {
      setLayer(null);
      setPid(id);
      setFocusId(id);
      setMode("follow");
      poke();
    },
    [poke],
  );

  const leave = useCallback(
    (to: StatsExit | "library") => {
      remember(true);
      navigate(to === "library" ? { name: to } : { name: to, gameId });
    },
    [remember, gameId],
  );

  const jump = useCallback(
    (dir: 1 | -1) => {
      if (!handle) return;
      if (settle(handle)) handle.play(); // jump from the start point; a queued autoplay still plays
      const now = handle.currentTime();
      if (reel) {
        const i = clamp(reel.i + dir, 0, reel.segs.length - 1);
        setReel({ ...reel, i });
        handle.seek(reel.segs[i].t_start);
        return;
      }
      const m = jumpMoment(lineMoments, now, dir);
      if (m) handle.seek(m.t_start);
    },
    [handle, reel, lineMoments, settle],
  );

  const toMoment = useCallback(
    (m: Moment) => {
      setLayer(null);
      poke();
      if (condensedSrc) {
        setWay("full");
        pending.current = { t: m.t_start, play: true };
        setCondensedSrc(null);
        return;
      }
      goTo(inReel(m.t_start));
    },
    [condensedSrc, goTo, inReel, poke],
  );

  const bookmark = useCallback(() => {
    if (!game || !handle) return;
    const at = handle.currentTime();
    api
      .createEvent(game.id, { type: "bookmark", t_key: at })
      .then(() => {
        setToast(`Bookmarked ${fmtDuration(at)}`);
        loadMoments();
      })
      .catch(() => setToast("Could not save the bookmark"));
  }, [game, handle, loadMoments]);

  const toggleCommentary = useCallback(() => {
    // D-42: rendition time = source time, so the swap keeps the playback position; track
    // boxes describe the wide frame, so select/follow sit the broadcast out.
    setCommentaryOn((on) => !on);
    if (broadcast) setMode("wide");
  }, [broadcast]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (!handle || !game) return;
      const seeking = seekRef.current;
      if (a !== "back" && a !== "release") poke();
      switch (a) {
        case "left":
        case "right":
        case "up":
        case "down": {
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
            // Up against the top edge leaves the boxes for Do more.
            if (a === "up" && next === from) openLayer("domore");
            else setFocusId(next);
          } else if (a === "up") openLayer("domore");
          else if (a === "down") openLayer("moments");
          else holdSeek(a === "right" ? 1 : -1);
          break;
        }
        case "release":
          releaseSeek();
          break;
        case "seek-back":
        case "seek-fwd":
          if (mode !== "select") scrubPress(a === "seek-fwd" ? 1 : -1);
          break;
        case "menu":
          openLayer("domore");
          break;
        case "select":
          if (seeking) commit();
          else if (mode === "select") {
            if (!focusId) break;
            // W4: follow at the same timestamp; playback state is left as-is (S-19).
            setPid(focusId);
            setMode("follow");
          } else toggle();
          break;
        case "playpause":
          if (seeking) commit(true);
          else toggle();
          break;
        case "prev-event":
        case "next-event":
          if (seeking) commit();
          jump(a === "next-event" ? 1 : -1);
          break;
        case "back":
          if (seeking) cancelSeek();
          else if (mode !== "wide") setMode("wide");
          else if (chrome) setChrome(false);
          else leave("library");
          break;
        case "bookmark":
          bookmark();
          break;
        case "spotlight":
          setSpotlight((s) => !s);
          break;
        case "tag":
          if (tagTarget) setTagging(tagTarget);
          break;
        case "pair":
          remember(true);
          navigate({ name: "pair", gameId: game.id });
          break;
        default:
          break;
      }
    },
    [
      handle,
      game,
      mode,
      players,
      focusId,
      chrome,
      tagTarget,
      poke,
      openLayer,
      holdSeek,
      releaseSeek,
      scrubPress,
      commit,
      cancelSeek,
      jump,
      bookmark,
      toggle,
      leave,
      remember,
    ],
  );
  useDpad(onAction, !tagging && !linking && layer === null && !angle);

  // Paired phone: tell it what is on screen once a second (its "Clip that" posts a tap at
  // this media time), play the search hits it sends, confirm the clips its taps cut, and
  // play a highlight query it pushes as a reel.
  const send = useSessionMessages(
    storedSession()?.id,
    useCallback(
      (msg: SessionMessage) => {
        if (msg.type === "seek" && typeof msg.t === "number") {
          goTo(msg.t);
          if (!commentaryOn) setMode("wide");
        } else if (msg.type === "clip") setToast(msg.label ?? "Clip saved");
        else if (msg.type === "query" && msg.text)
          navigate({ name: "watch", gameId, q: msg.text });
      },
      [goTo, commentaryOn, gameId],
    ),
  );
  useEffect(() => {
    if (!handle || !game) return;
    const timer = setInterval(() => {
      remember();
      send({
        type: "now",
        game_id: game.id,
        title: game.title,
        t: handle.currentTime(),
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [handle, game, send, remember]);

  // The nearest play's angles (Do more's Angles and Free view), read when it changes so
  // they are in before Do more opens.
  const nearestReplay = [...(replays ?? [])].sort(
    (a, b) =>
      Math.abs((a.t_start + a.t_end) / 2 - t) -
      Math.abs((b.t_start + b.t_end) / 2 - t),
  )[0];
  const nearId = nearestReplay?.play_id;
  useEffect(() => {
    if (!nearId) return;
    let on = true;
    api.getReplay(gameId, nearId).then(
      (m) => on && setNear(m),
      () => on && setNear(null),
    );
    return () => {
      on = false;
    };
  }, [gameId, nearId]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), TOAST_MS);
    return () => clearTimeout(timer);
  }, [toast]);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game || !info) return <Loading />;

  // ---------------------------------------------------------------- Do more tiles
  const feature = (k: FeatureKey) => info.features?.[k];
  /** A tile when its data is here; "Getting ready" while its stage runs; else none. */
  const tile = (key: FeatureKey | null, ok: boolean, t0: Tile): Tile[] => {
    if (ok) return [t0];
    const f = key ? feature(key) : undefined;
    return f?.state === "pending"
      ? [
          {
            ...t0,
            // the ETA keeps together, so a wrap never strands "min" on its own line
            sub: `Getting ready, ${(etaText(f.eta_s) || "soon").replace(/ /g, " ")}`,
            pending: true,
            run: undefined,
          },
        ]
      : [];
  };
  const close = (fn: () => void) => () => {
    setLayer(null);
    fn();
  };
  const closeLayer = () => {
    setLayer(null);
    poke();
  };
  const followName = roster.find((p) => p.id === pid);
  // An untagged player reads "Player 3" (track p3), as on the Moments chips.
  const targetName = (id: string) =>
    roster.find((p) => p.id === id)?.name ?? `Player ${id.replace(/^p/, "")}`;
  const photo = (p: Player) =>
    (p.profile_id &&
      profiles?.find((x) => x.profile_id === p.profile_id)?.photo_url) ||
    null;
  const nHype = hype?.candidates.length ?? 0;
  const hasRallies =
    (rallies?.n ?? 0) > 0 || rallies?.condensed.status === "done";
  const wayTiles: Tile[] = [
    {
      id: "way-full",
      label: "Full game",
      sub: fmtDuration(info.video.duration_s),
      on: way === "full",
      run: () => startWay("full"),
    },
    ...tile(q ? null : "highlights", nHype > 0 || !!q, {
      id: "way-highlights",
      label: "Highlights",
      sub: q ? `“${q}”` : `Top ${Math.min(REEL_MAX, nHype)} plays`,
      on: way === "highlights",
      run: () => startWay("highlights"),
    }),
    ...tile("condensed", hasRallies, {
      id: "way-condensed",
      label: "Condensed",
      sub:
        rallies?.condensed.status === "done"
          ? "Dead time cut"
          : `${rallies?.n ?? 0} rallies`,
      on: way === "condensed",
      run: () => startWay("condensed"),
    }),
  ];
  const pickOnScreen = close(() => {
    pause();
    setMode("select");
  });
  // Follow player: the roster as chips, picking on screen, and once a player is picked
  // (followed, or the focused box) Spotlight, Tag and Link for them.
  const followRow: Tile[] = [
    ...roster.map((p) => ({
      id: `follow-${p.id}`,
      label: targetName(p.id),
      avatar: { name: targetName(p.id), photo: photo(p) },
      on: mode === "follow" && pid === p.id,
      run: () => follow(p.id),
    })),
    { id: "follow-pick", label: "Pick on screen", run: pickOnScreen },
    ...(tagTarget
      ? [
          {
            id: "action-spotlight",
            label: spotlight ? "Spotlight on" : "Spotlight off",
            on: spotlight,
            run: () => setSpotlight((s) => !s),
          },
          {
            id: "action-tag",
            label: `Tag ${targetName(tagTarget)}`,
            run: close(() => setTagging(tagTarget)),
          },
          {
            id: "action-link-profile",
            label: "Link profile",
            run: close(() => setLinking(tagTarget)),
          },
        ]
      : []),
  ];
  // Angles: the nearest play's angles as thumbnails (the play's frame; the API has no
  // per-angle poster yet), Free view last when the play has a scene.
  const play = near && near.play_id === nearestReplay?.play_id ? near : null;
  const playT = nearestReplay
    ? (nearestReplay.t_start + nearestReplay.t_end) / 2
    : 0;
  const frame = (
    <View style={styles.thumb}>
      {storyboard ? (
        <SpriteFrame storyboard={storyboard} t={playT} width={px(304)} />
      ) : null}
    </View>
  );
  const angleRow: Tile[] = play
    ? [
        ...play.angles.map((a, i) => ({
          id: `angle-${a.id}`,
          label: a.label,
          sub: tierBadge(a.tier),
          art: frame,
          run: () => openAngle(play.play_id, i),
        })),
        ...(play.scene_url
          ? [
              {
                id: "angle-free",
                label: "Free view",
                sub: "Orbit the play",
                art: frame,
                run: () => openAngle(play.play_id, "free"),
              },
            ]
          : []),
      ]
    : [];
  const tiles: Tile[] = [
    ...tile(
      "follow",
      roster.length > 0 && game.tracks.chunks > 0 && !commentaryOn,
      {
        id: "action-follow",
        label: "Follow player",
        sub:
          mode === "follow" && pid
            ? `Following ${targetName(pid)}`
            : "Pick a player",
        view: "chips",
        children: followRow,
      },
    ),
    ...tile("angles", !!nearestReplay, {
      id: "nav-replays",
      label: "Angles",
      sub: nearestReplay?.label ?? "Replays of a play",
      view: "thumbs",
      children: angleRow,
      run: () => nearestReplay && openAngle(nearestReplay.play_id, 0),
    }),
    ...tile("free_view", !!play?.scene_url, {
      id: "action-free-view",
      label: "Free view",
      sub: "Orbit this play",
      run: () => play && openAngle(play.play_id, "free"),
    }),
    ...(wayTiles.length > 1
      ? [
          {
            id: "menu-watch",
            label: "Watch",
            sub: WAY_NAMES[way],
            children: wayTiles,
          },
        ]
      : []),
    ...tile(
      "stats",
      feature("stats")
        ? feature("stats")?.state === "ready"
        : info.status === "ready",
      {
        id: "nav-review",
        label: "Stats",
        sub: "Box score and shots",
        run: () => openLayer("stats"),
      },
    ),
    ...tile("commentary", lines.length > 0 || !!broadcast, {
      id: "action-captions",
      label: "Commentary",
      sub: commentaryOn ? "On" : "Off",
      on: commentaryOn,
      run: toggleCommentary,
    }),
    {
      id: "nav-phone",
      label: "On your phone",
      sub: "Clip, tag, review, search",
      run: () => openLayer("phone"),
    },
    {
      id: "action-bookmark",
      label: "Bookmark",
      sub: "Mark this moment",
      run: close(bookmark),
    },
  ];

  // ---------------------------------------------------------------- render
  if (angle) {
    return (
      <AngleView
        key={`${angle.playId}/${angle.start}`}
        gameId={gameId}
        playId={angle.playId}
        start={angle.start}
        onBack={closeAngle}
      />
    );
  }
  const cropRect = crop ? cropRectAt(crop, t) : null;
  const spotPlayers = players
    .filter((p) => p.id === pid)
    .map((p) => ({ ...p, bb: mapBB(p.bb, cropRect) }));
  const onBroadcast = commentaryOn && !!broadcast && !condensedSrc;
  const src =
    condensedSrc ?? (onBroadcast && broadcast ? broadcast.url : source.src);
  const showFollowFrame = !!pid && mode !== "select" && src === wideUrl;
  const stageW = Math.min(winW, (winH * 16) / 9);
  const caption = commentaryOn && !layer ? captionAt(lines, t) : null;
  const rally = condensedSrc
    ? rallyAtCondensed(rallies?.rallies ?? [], t)
    : null;
  const indicator = reel
    ? {
        text: `${reel.name}, ${reel.i + 1} of ${reel.segs.length}`,
        index: reel.i + 1,
        count: reel.segs.length,
      }
    : condensedSrc
      ? {
          text: rally
            ? `Condensed, rally ${rally.n} of ${rallies?.n ?? 0}`
            : "Condensed",
          index: rally?.n ?? 0,
          count: rallies?.n ?? 0,
        }
      : null;
  const playhead = cue ? cue.t : t;

  return (
    <View
      style={styles.screen}
      testID="watch"
      dataSet={{
        mode,
        layer: layer ?? "",
        way,
        broadcast: onBroadcast ? "true" : "false",
      }}
    >
      <View style={{ width: stageW }}>
        {/* The broadcast rendition carries its own audio mix (game audio, stings, ducked
            narration — D-43), so it plays with sound; the raw wide shot stays muted. */}
        <PlayerSurface
          key={condensedSrc ? "condensed" : "game"}
          ref={setHandle}
          src={src}
          crop={!onBroadcast && !condensedSrc && source.useCrop ? crop : null}
          muted={!onBroadcast}
        >
          {mode === "select" ? (
            <SelectOverlay
              players={players}
              roster={roster}
              focusId={focusId}
              spotlight={spotlight}
            />
          ) : null}
          {mode === "follow" ? (
            <SelectOverlay
              players={spotPlayers}
              roster={roster}
              focusId={pid}
              spotlight={spotlight}
              showBoxes={false}
            />
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

        <Animated.View
          style={[StyleSheet.absoluteFill, { opacity: fade }]}
          pointerEvents="none"
          testID="transport"
          dataSet={{ hidden: shown ? "false" : "true" }}
        >
          <Fade side="top" length={px(240)} strength={0.7} />
          <Fade side="bottom" length={px(420)} strength={0.85} />
          <View style={styles.top}>
            {mode === "select" ? (
              <T style={type.meta} testID="select-hint">
                Pick a player, then Select to follow
              </T>
            ) : mode === "follow" ? null : (
              <T
                style={[type.meta, { maxWidth: px(1100) }]}
                numberOfLines={1}
                testID="watch-title"
              >
                {info.title}
              </T>
            )}
          </View>
          <Timeline
            duration={duration}
            t={playhead}
            moments={lineMoments}
            seek={seekV}
            storyboard={condensedSrc ? null : storyboard}
          />
        </Animated.View>

        {mode === "follow" && !overlay ? (
          // Stays while following, transport or not: who the camera is on; with the
          // transport, how to stop.
          <View style={styles.followRow}>
            <View
              style={styles.followChip}
              testID="followcam-active"
              dataSet={{ playerId: pid ?? "" }}
            >
              <View
                style={[
                  styles.teamDot,
                  { backgroundColor: followName?.color_hex ?? color.chalk },
                ]}
              />
              <T style={type.meta}>
                {pid ? `Following ${targetName(pid)}` : ""}
              </T>
              {rendering ? (
                <T style={[type.meta, styles.dim]} testID="rendering-badge">
                  , getting the view ready
                </T>
              ) : null}
            </View>
            {shown ? (
              <Hint k="Back" style={styles.stopHint}>
                Stop following
              </Hint>
            ) : null}
          </View>
        ) : null}

        {indicator && !overlay ? (
          <View
            style={styles.indicator}
            testID="way-indicator"
            dataSet={{ way, index: indicator.index, count: indicator.count }}
          >
            <T style={type.meta}>{indicator.text}</T>
          </View>
        ) : null}

        {caption ? (
          // M7 grounded commentary as captions, timed by the clock (audio_t / audio_s).
          <View
            style={[
              styles.caption,
              { bottom: shown ? safe.y + TIMELINE_H + sp(4) : safe.y },
            ]}
          >
            <T
              style={[type.body, styles.captionText]}
              testID="caption"
              dataSet={{ t: caption.audio_t ?? caption.t }}
            >
              {caption.text}
            </T>
          </View>
        ) : null}

        {toast ? (
          <View style={styles.toast} testID="toast">
            <T style={type.body}>{toast}</T>
          </View>
        ) : null}

        {layer === "moments" ? (
          <MomentsLayer
            moments={moments}
            t={layerT}
            empty={
              feature("moments")?.state === "pending"
                ? `Finding the big moments, ${etaText(feature("moments")?.eta_s) || "soon"}`
                : "No moments in this game yet"
            }
            onCue={setCue}
            onJump={toMoment}
            onClose={closeLayer}
            onPlayPause={toggle}
          />
        ) : null}
        {layer === "domore" ? (
          <DoMoreLayer
            tiles={tiles}
            onClose={closeLayer}
            onPlayPause={toggle}
          />
        ) : null}
        {layer === "stats" ? (
          <StatsPanel
            game={game}
            roster={roster}
            onClose={closeLayer}
            onOpen={leave}
            onPlayPause={toggle}
          />
        ) : null}
        {layer === "phone" ? (
          <PhonePanel
            gameId={gameId}
            t={layerT}
            onClose={closeLayer}
            onPlayPause={toggle}
          />
        ) : null}
      </View>

      {tagging ? (
        <TextEntryDialog
          idPrefix="tag"
          title={`Tag player ${tagging}`}
          initial={roster.find((p) => p.id === tagging)?.name}
          presets={PRESET_NAMES.filter(
            (n) =>
              n === roster.find((p) => p.id === tagging)?.name ||
              !roster.some((p) => p.name === n),
          )}
          format={titleCase}
          dataSet={{ playerId: tagging }}
          onCancel={() => setTagging(null)}
          onSubmit={(name) => {
            const target = tagging;
            setTagging(null);
            api
              .patchPlayer(game.id, target, { name })
              .then((p) =>
                setRoster((prev) => prev.map((r) => (r.id === p.id ? p : r))),
              )
              .catch(() => {});
          }}
        />
      ) : null}

      {linking ? (
        <ProfilePicker
          gameId={game.id}
          playerId={linking}
          playerLabel={
            roster.find((p) => p.id === linking)?.name ?? `#${linking}`
          }
          onCancel={() => setLinking(null)}
          onLinked={(p) => {
            const target = linking;
            setLinking(null);
            setRoster((prev) =>
              prev.map((r) =>
                r.id === target
                  ? {
                      ...r,
                      name: p.name,
                      tagged: true,
                      profile_id: p.profile_id,
                    }
                  : r,
              ),
            );
            setToast(`Linked to ${p.name}`);
          }}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: "#000",
    alignItems: "center",
    justifyContent: "center",
  },
  top: {
    position: "absolute",
    left: safe.x,
    right: safe.x,
    top: safe.y,
    flexDirection: "row",
  },
  dim: { color: color.bleacher },
  followRow: {
    position: "absolute",
    left: safe.x,
    top: safe.y,
    flexDirection: "row",
    alignItems: "center",
  },
  followChip: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: sp(2),
    borderRadius: radius.chip,
    backgroundColor: "rgba(29, 40, 52, 0.88)",
  },
  stopHint: { marginTop: 0, marginLeft: sp(3) },
  thumb: { flex: 1, backgroundColor: color.bench },
  teamDot: {
    width: px(16),
    height: px(16),
    borderRadius: px(8),
    marginRight: sp(1.5),
  },
  indicator: {
    position: "absolute",
    right: safe.x,
    top: safe.y,
    paddingHorizontal: sp(2),
    borderRadius: radius.chip,
    backgroundColor: "rgba(18, 26, 35, 0.72)",
  },
  caption: {
    position: "absolute",
    left: px(240),
    right: px(240),
    alignItems: "center",
  },
  captionText: {
    textAlign: "center",
    paddingHorizontal: sp(3),
    paddingVertical: sp(1),
    borderRadius: radius.card,
    backgroundColor: "rgba(18, 26, 35, 0.84)",
  },
  toast: {
    position: "absolute",
    alignSelf: "center",
    top: safe.y + px(64),
    paddingHorizontal: sp(3),
    paddingVertical: sp(1),
    borderRadius: radius.card,
    backgroundColor: color.bench,
  },
});
