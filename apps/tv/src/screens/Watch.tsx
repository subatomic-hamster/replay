// The player (route "watch"; docs/ux/redesign.md "Player"; UI pass §2). Layers stack over
// full-bleed video: Do more above (Up, or Menu in every mode), Moments below (Down). Back
// goes up one level: the layer, the seek, the picker, following, Highlights → full game,
// then Home (hiding the transport is not a step).
//
// Transport: the context chip top-left (the title, "Pick a player", "Following Player 3",
// "Highlights · 2 of 5", or a toast for 3 s; following and the reels keep it on screen), a
// key legend bottom-right, and the court-line timeline; it shows on any key and hides
// after 5 s of playback (pausing keeps it).
// Seeking (Left/Right): each tap or repeat goes to the next stop, a 10 s grid (coarser as a
// hold accelerates) plus every moment's start (playback/seek.ts nextStop); the video
// pauses while a storyboard preview (a moment's thumb and label at a moment stop) rides
// the playhead, and playback resumes at the stop after the release. Rew/FF scrub at 2/4/8/16×,
// Select or Play commits. Prev/Next jump moments (or a reel's plays).
//
// Ways to watch: Full game, Highlights (the top hype candidates, ≤13, back to back, ending
// on the game's best play under a "★ Best play of the game" banner; or a highlight
// query's clips) and Condensed (the condensed rendition, or the rallies back to
// back while it renders). Everything polls every 10 s while the game is still processing,
// so moments arrive on the line and Do more's tiles light up.
//
// Do more (UI pass §4.3, at most 6 tiles): Follow a player (pauses on the frame with a
// marker on every player: the arrows hop between them, Select follows, Back cancels; the
// camera is computed on the device, D-82; while following, the player's card and "Follow
// someone else" lead instead), Replay angles of the nearest play (AngleView replaces the
// game video until Back, which resumes the game where it was; also from a moment),
// Highlights (the ways), Stats (StatsPanel, the right third), Commentary and On your phone
// (PhonePanel's QR handoff). Bookmark lives in Moments. Where the game was is remembered (resume.ts) every second and before leaving
// (stored every 5 s, and at once on leaving), so a sub-screen's Back or Home's Resume
// comes back to the same time and play state, also after an app restart.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Animated,
  Image,
  StyleSheet,
  View,
  useWindowDimensions,
} from "react-native";
import {
  broadcastOf,
  captionAt,
  commentaryLines,
  endOnBest,
  rallyAtCondensed,
  rallyOrder,
  type Hype,
  type RallyDoc,
} from "../../../../packages/tv-core/src/discovery";
import { fmtDuration } from "../../../../packages/tv-core/src/display";
import {
  createFollowCam,
  HANDOFF_MAX_GAP_S,
  mapBB,
} from "../../../../packages/tv-core/src/follow";
import { followSource } from "../../../../packages/tv-core/src/followSource";
import {
  nextFocus,
  type Direction,
} from "../../../../packages/tv-core/src/spatial";
import {
  type ReplayManifest,
  type ReplaySummary,
} from "../../../../packages/tv-core/src/replays";
import { createTracksCache } from "../../../../packages/tv-core/src/tracksCache";
import type {
  FeatureKey,
  Game,
  Moment,
  Player,
  Storyboard,
} from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { AngleView } from "../components/AngleView";
import { DoMoreLayer, type Tile } from "../components/DoMoreLayer";
import { MomentsLayer } from "../components/MomentsLayer";
import { PhonePanel } from "../components/PhonePanel";
import { PlayerCard } from "../components/PlayerCard";
import { ProfilePicker } from "../components/ProfilePicker";
import { SelectOverlay } from "../components/SelectOverlay";
import { StatsPanel, type StatsExit } from "../components/StatsPanel";
import { TextEntryDialog } from "../components/TextEntryDialog";
import { Timeline, TIMELINE_H, type SeekView } from "../components/Timeline";
import { artFor, etaText, stageWords } from "../gameState";
import { useDpad, type DpadAction } from "../input";
import { navigate, type Way } from "../nav";
import { FOLLOWCAM_MODE } from "../platform/config";
import {
  PlayerSurface,
  useClockTime,
  usePlaying,
  type PlayerHandle,
} from "../playback/PlayerSurface";
import {
  HIDE_MS,
  holdStep,
  jumpMoment,
  LINGER_MS,
  nextScrub,
  nextStop,
  REPEAT_FLOOR_MS,
} from "../playback/seek";
import { rememberSpot, resumeAt, resumeSpot } from "../resume";
import {
  storedSession,
  useSessionMessages,
  type SessionMessage,
} from "../session";
import { color, px, radius, safe, sp, teamColorMap, type } from "../theme";
import {
  ApiErrorBanner,
  ContextChip,
  Fade,
  KeyLegend,
  Loading,
  T,
  useAsync,
  usePlayFlash,
} from "../ui";

type Mode = "wide" | "select" | "follow";
type Layer = "moments" | "domore" | "stats" | "phone" | "player" | null;
/** A play's replay angles in place of the game video: the angle to open, or Free view. */
interface Angle {
  playId: string;
  start: number | "free";
}
interface Seg {
  t_start: number;
  t_end: number;
  /** the game's best play (the Highlights reel ends on it, under its banner) */
  best?: boolean;
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
  /** the stop (or, scrubbing, the raw point) a commit lands on */
  target: number;
  /** the moment whose start `target` is */
  snapped: Moment | null;
  wasPlaying: boolean;
  /** when the current hold began (a new tap after a release starts a new hold) */
  holdStart: number;
  lastStep: number;
  step: number;
  released: boolean;
  scrub: { dir: 1 | -1; speed: number } | null;
}

const POLL_MS = 10_000;
/** How often the open Watch asks for the phone's "Play on the TV" (GET /tv/commands). */
const TV_COMMANDS_MS = 3_000;
const TV_STATE_MS = 10_000; // the API counts a TV as watching for 30 s after a beat
const EXTRAS_LATEST_MS = 3000;

/** D-87: true once the game is read and its video has a first frame (a duration), or
 *  EXTRAS_LATEST_MS after the game when the video is slow or fails: then the requests
 *  the first frame does not need (commentary, hype, rallies, replay angles) go out. */
function useExtrasReady(game: boolean, handle: PlayerHandle | null) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (ready || !game) return;
    const t0 = Date.now();
    const timer = setInterval(() => {
      if (
        (handle && handle.duration() > 0) ||
        Date.now() - t0 >= EXTRAS_LATEST_MS
      ) {
        setReady(true);
        clearInterval(timer);
      }
    }, 100);
    return () => clearInterval(timer);
  }, [ready, game, handle]);
  return ready;
}
const TOAST_MS = 3000;
/** A moment this close to a replayed play's window links to its angles. */
const ANGLES_NEAR_S = 15;
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

/** The Highlights reel: the top hype plays, merged where they overlap. The tile counts
 *  these, so "Top N plays" is what plays. */
function topReel(hype: Hype | null | undefined): Seg[] {
  return mergeSegs(
    [...(hype?.candidates ?? [])]
      .sort((a, b) => b.score - a.score)
      .slice(0, REEL_MAX)
      .map((c) => ({
        t_start: c.t_start ?? Math.max(0, c.t - 3),
        t_end: c.t_end ?? c.t + 1,
      })),
  );
}

export function Watch({
  gameId,
  initialMode,
  initialPid,
  initialT,
  initialWay,
  initialPlay,
  initialCard,
  initialPanel,
  initialBack,
  q,
}: {
  gameId: string;
  /** D-93: where Back leaves to instead of Home (Review's "Watch it") */
  initialBack?: StatsExit;
  /** reopen the player card (Back from its View profile), paused */
  initialCard?: { pid: string; resume: boolean };
  /** reopen the Stats panel (Back from Review or Tips) */
  initialPanel?: "stats";
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
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const extras = useExtrasReady(!!game, handle);
  // D-87: what the first frame does not need waits for it (`extras`): the open is the
  // game, renditions and moments, not nine requests at once on a 10-concurrency Lambda
  const { data: replays } = useAsync(
    () => (extras ? api.listReplays(gameId) : Promise.resolve(null)),
    [gameId, extras],
  );
  const { data: renditions } = useAsync(
    () => api.listRenditions(gameId),
    [gameId],
  );
  const { data: commentary } = useAsync(
    () => (extras ? api.getCommentary(gameId) : Promise.resolve(null)),
    [gameId, extras],
  );
  const { data: hype, error: hypeError } = useAsync(
    () => (extras ? api.getHype(gameId) : Promise.resolve(null)),
    [gameId, extras],
  );
  // The game's best play (the user's pick, else the game winner, else the top hype play):
  // a ★ on the line, a chip on its moment, and the Highlights reel ends on it.
  const { data: bestDoc, error: bestError } = useAsync(
    () =>
      extras
        ? api.getBestPlay(gameId).then((b) => ({ b }))
        : Promise.resolve(null),
    [gameId, extras],
  );
  const best = bestDoc?.b ?? null;
  // The game re-read while it is processing: readiness, features, the storyboard URL.
  const [live, setLive] = useState<Game | null>(null);
  const info = live ?? game;
  const [moments, setMoments] = useState<Moment[]>([]);
  const [momentsRead, setMomentsRead] = useState(false); // Moments spins until then
  const [storyboard, setStoryboard] = useState<Storyboard | null>(null);
  const [rallies, setRallies] = useState<RallyDoc | null>(null);
  const broadcast = broadcastOf(renditions);
  const lines = useMemo(() => commentaryLines(commentary), [commentary]);

  const [mode, setMode] = useState<Mode>(
    initialMode === "select" || initialMode === "follow" ? initialMode : "wide",
  );
  const [layer, setLayer] = useState<Layer>(
    initialCard ? "player" : (initialPanel ?? null),
  );
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
  /** What select mode came from (Back returns there, playback as it was). */
  const selectFrom = useRef<{ mode: Mode; playing: boolean } | null>(null);
  const [spotlight, setSpotlight] = useState(false);
  const [tagging, setTagging] = useState<string | null>(null);
  const [linking, setLinking] = useState<string | null>(null);
  /** The player card's player (layer "player"); Moments filtered to one player. */
  const [cardPid, setCardPid] = useState<string | null>(
    initialCard?.pid ?? null,
  );
  // playing when the card opened: Back resumes
  const cardPlaying = useRef(initialCard?.resume ?? false);
  const [momentsOf, setMomentsOf] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);
  const renderAsked = useRef<string | null>(null);
  const [version, bump] = useState(0);
  const [angle, setAngle] = useState<Angle | null>(
    initialPlay ? { playId: initialPlay, start: 0 } : null,
  );
  /** Where the game was when an angle opened (Back resumes it there). */
  const angleReturn = useRef<{ t: number; play: boolean } | null>(null);
  /** The "▼ Moments ▲ Do more" legend: only the first 5 s after Watch opens. */
  const [intro, setIntro] = useState(true);
  useEffect(() => {
    const timer = setTimeout(() => setIntro(false), HIDE_MS);
    return () => clearTimeout(timer);
  }, []);
  /** Seek + play once the (next) source knows its duration: deep link, a way's first
   *  play, the swap to or from the condensed rendition, the return from an angle. A plain
   *  open of the full game starts where it was left (resume.ts). */
  const pending = useRef<{ t: number | null; play: boolean } | null>(
    (() => {
      const play = initialMode !== "select" && !initialCard;
      if (initialT !== undefined) return { t: initialT, play };
      const spot =
        (initialWay ?? "full") === "full" &&
        !q &&
        !initialPlay &&
        resumeAt(gameId) !== null // the same rule as Home's "Resume" (not near either end)
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
  const playing = usePlaying(handle);
  const duration =
    handle?.duration() || (condensedSrc ? 0 : info?.video.duration_s) || 0;
  // Moments are game time: the condensed rendition has its own clock.
  const lineMoments = useMemo(
    () => (condensedSrc ? [] : moments),
    [condensedSrc, moments],
  );

  // ---------------------------------------------------------------- data
  const loadMoments = useCallback(
    () =>
      // through a promise: the mock throws synchronously for an unknown game id, and
      // that must reach the error banner, not crash the screen
      Promise.resolve()
        .then(() => api.getMoments(gameId))
        .then(setMoments, () => {})
        .finally(() => setMomentsRead(true)),
    [gameId],
  );
  useEffect(() => {
    loadMoments();
  }, [loadMoments]);
  useEffect(() => {
    if (!extras) return;
    Promise.resolve()
      .then(() => api.getRallies(gameId))
      .then(setRallies, () => setRallies(null));
  }, [gameId, extras]);

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
      (s) => {
        if (!on) return;
        setStoryboard(s);
        // A real game's first sheet is ~1 MB (3200x1800): fetched only at the first seek,
        // a 32-bit Fire TV showed an empty preview frame for seconds.
        for (const u of s.sheets) Image.prefetch(u).catch(() => {});
      },
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
  const { flash, node: flashNode } = usePlayFlash();
  const toggle = useCallback(() => {
    if (!handle) return;
    if (settle(handle)) handle.pause();
    else handle.toggle();
    flash(!handle.paused());
  }, [handle, settle, flash]);

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

  // D-82 client follow-cam: computed on the device every frame from the tracks chunks
  // already in memory (the player was picked from them), so it moves at once. One camera
  // per pick: it keeps its hand-offs across Back (the ring stays on in the wide shot).
  const rosterRef = useRef(roster);
  rosterRef.current = roster;
  const vw = game?.video.width ?? 16;
  const vh = game?.video.height ?? 9;
  const cam = useMemo(
    () =>
      tracks && pid
        ? createFollowCam(
            tracks,
            pid,
            vw / vh,
            (id) => rosterRef.current.find((p) => p.id === id)?.team,
            !!game?.tracks.people,
          )
        : null,
    [tracks, pid, vw, vh, game?.tracks.people],
  );
  /** The roster id of the player being followed now (null when not following), for
   *  anything that shows who it is (the player card). The camera may be on a later track
   *  id of the same person after a hand-off: `cam.current().id`. */
  const followedId = mode === "follow" ? pid : null;

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
      // `inOrder`: the segments are already the reel's (Highlights ends on the best play)
      const play = (name: string, segs: Seg[], inOrder = false) => {
        const list = inOrder ? segs : mergeSegs(segs);
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
        play("Highlights", endOnBest(topReel(hype), best), true);
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
    [condensedSrc, rallies, handle, goTo, gameId, q, hype, best],
  );

  // The way the route asked for, once its data is in (hype and the best play answer or
  // fail).
  const started = useRef(false);
  useEffect(() => {
    if (started.current || !game || !handle) return;
    if (way === "highlights" && !q && !hype && !hypeError) return;
    if (way === "highlights" && !q && !bestDoc && !bestError) return;
    started.current = true;
    if (way !== "full") startWay(way);
  }, [game, handle, way, q, hype, hypeError, bestDoc, bestError, startWay]);

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
      // the segment `to` is in (the best play comes last, out of time order), else the
      // next one
      const inside = reel.segs.findIndex(
        (s) => s.t_start <= to && to < s.t_end,
      );
      const i = inside >= 0 ? inside : reel.segs.findIndex((s) => to < s.t_end);
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
    setSeekV(
      s
        ? {
            target: s.target,
            delta: s.target - s.from,
            step: s.step,
            scrub: s.scrub,
            snapped: s.snapped,
            resume: s.wasPlaying || !!s.scrub,
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
      snapped: null,
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
      const { handle: h, inReel: land } = latest.current;
      seekRef.current = null;
      publish();
      if (!s || !h) return;
      h.seek(land(s.target)); // a moment stop's target is its start
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
      const live = !seekRef.current; // stepping from the playing video, not a stop
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
      const { moments: ms, duration: d } = latest.current;
      const stop = nextStop(ms, s.target, dir, s.step, d, live);
      s.target = stop.t;
      s.snapped = stop.moment;
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
      s.snapped = null;
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
  const overlay = layer === "stats" || layer === "phone" || layer === "player";
  // Paused, it stays up however the pause came (a key, the end of a reel): a still
  // frame always says "Paused".
  const shown =
    !overlay &&
    (chrome ||
      !playing ||
      layer !== null ||
      seekV !== null ||
      mode === "select");
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

  /** The player card (D-83) for `id`: the game pauses on the frame; Back resumes it if
   *  it was playing. */
  const openCard = useCallback(
    (id: string) => {
      if (seekRef.current) commit();
      if (handle) {
        cardPlaying.current = settle(handle) || !handle.paused();
        handle.pause();
      }
      setCardPid(id);
      setLayer("player");
    },
    [commit, handle, settle],
  );
  const closeCard = useCallback(
    (resume = true) => {
      setLayer(null);
      if (resume && cardPlaying.current) handle?.play();
      cardPlaying.current = false;
      lastKey.current = Date.now();
      setChrome(true);
    },
    [handle],
  );
  // Moments filtered to one player (the card's "Their moments") only while it is open.
  useEffect(() => {
    if (layer !== "moments") setMomentsOf(null);
  }, [layer]);

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

  /** Do more → Follow player: pause on the frame with a marker on every player; the
   *  arrows hop between them, Select follows, Back goes back (W3, REPLAY_PLAN §1). Focus
   *  starts on whoever the camera is on, else the leftmost player. */
  const startSelect = useCallback(() => {
    if (!handle) return;
    const playing = settle(handle) || !handle.paused();
    // picking again from Do more inside select mode keeps where it first came from
    if (mode !== "select" || !selectFrom.current)
      selectFrom.current = { mode: mode === "select" ? "wide" : mode, playing };
    handle.pause();
    setLayer(null);
    // On whoever the camera is on; lost, on the player nearest where they were last seen.
    const v = cam && pid ? cam.current() : null;
    if (v?.box) setFocusId(v.id);
    else if (v?.last) {
      const [lx, ly] = [v.last[0] + v.last[2] / 2, v.last[1] + v.last[3] / 2];
      const d = (p: { bb: number[] }) =>
        Math.hypot(p.bb[0] + p.bb[2] / 2 - lx, p.bb[1] + p.bb[3] / 2 - ly);
      const near = [...players].sort((a, b) => d(a) - d(b))[0];
      if (near) setFocusId(near.id);
    }
    setMode("select");
    poke();
  }, [handle, settle, mode, cam, pid, players, poke]);

  /** Leave select mode: following `id`, or (null) back where it came from; playback
   *  resumes if it was playing. */
  const endSelect = useCallback(
    (id: string | null) => {
      const from = selectFrom.current;
      selectFrom.current = null;
      if (id) {
        setPid(id);
        setMode("follow");
      } else setMode(from?.mode ?? "wide");
      if (from?.playing) handle?.play();
    },
    [handle],
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

  /** Bookmark `t` (Moments' "＋ Bookmark" passes the time its row shows), else now. */
  const bookmark = useCallback(
    (t?: number) => {
      if (!game || !handle) return;
      const at = t ?? handle.currentTime();
      api
        .createEvent(game.id, { type: "bookmark", t_key: at })
        .then(() => {
          setToast(`Bookmarked ${fmtDuration(at)}`);
          loadMoments();
        })
        .catch(() => setToast("Could not save the bookmark"));
    },
    [game, handle, loadMoments],
  );

  const toggleCommentary = useCallback(() => {
    // D-42: rendition time = source time, so the swap keeps the playback position; track
    // boxes describe the wide frame, so select/follow sit the broadcast out.
    setCommentaryOn(!commentaryOn);
    setToast(commentaryOn ? "Commentary off" : "Commentary on");
    if (broadcast) setMode("wide");
  }, [broadcast, commentaryOn]);

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
          // Do more in every mode (following, its first tile is the player's card)
          openLayer("domore");
          break;
        case "select":
          if (seeking) commit();
          else if (mode === "select") {
            // W4: follow at the same timestamp, playing again if it was (S-19).
            if (focusId) endSelect(focusId);
          } else if (
            mode === "follow" &&
            (cam?.current().lost ?? 0) > HANDOFF_MAX_GAP_S
          )
            startSelect(); // lost sight of them: pick again, near where they were
          else toggle();
          break;
        case "playpause":
          if (seeking) commit(true);
          else if (mode === "select" && focusId) {
            // "pick one, press play": follow them, playing
            if (selectFrom.current) selectFrom.current.playing = true;
            endSelect(focusId);
          } else toggle();
          break;
        case "prev-event":
        case "next-event":
          if (seeking) commit();
          jump(a === "next-event" ? 1 : -1);
          break;
        case "back":
          if (seeking) cancelSeek();
          else if (mode === "select") endSelect(null);
          else if (mode !== "wide") setMode("wide");
          // out of Highlights or Condensed into the full game, where the reel was
          else if (way !== "full") startWay("full");
          else leave(initialBack ?? "library");
          break;
        case "bookmark":
          bookmark();
          break;
        // the web build's dev shortcuts ('s', 't'); no on-screen hint names them
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
      endSelect,
      cam,
      startSelect,
      way,
      startWay,
      initialBack,
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
  // The phone's "Play on the TV" (a search hit, POST /games/{id}/tv/play) works without
  // pairing: poll the TV command queue (HTTP, so the cloud API serves it too) while this
  // game is open. Only this game's `play` is ours; Alexa's kinds share the queue.
  const playFromPhone = useRef<(t: number) => void>(() => {});
  useEffect(() => {
    playFromPhone.current = (t) => {
      setLayer(null);
      goTo(t);
      if (!commentaryOn) setMode("wide");
      setToast("Playing from your phone");
    };
  });
  useEffect(() => {
    let on = true;
    let busy = false; // a slow (retried) answer must not overlap the next tick's
    let cursor = "";
    const tick = () => {
      if (busy) return;
      busy = true;
      api
        .tvCommands(cursor)
        .then(
          (r) => {
            if (!on) return;
            cursor = r.cursor;
            for (const c of r.commands)
              if (c.kind === "play" && c.game_id === gameId && c.t !== null) {
                playFromPhone.current(c.t);
                api.ackTvCommand(c.id).catch(() => {});
              }
          },
          () => {}, // the next tick tries again
        )
        .finally(() => {
          busy = false;
        });
    };
    tick();
    const timer = setInterval(tick, TV_COMMANDS_MS);
    return () => {
      on = false;
      clearInterval(timer);
    };
  }, [gameId]);

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

  // The TV heartbeat (POST /tv/state): tells the phone's "Watch it" that this game is on
  // the TV, and Alexa's "clip that" where the TV is. A missed beat is harmless.
  useEffect(() => {
    if (!handle || !game) return;
    const beat = () =>
      api
        .tvState(game.id, handle.currentTime(), !handle.paused())
        .catch(() => {});
    beat();
    const timer = setInterval(beat, TV_STATE_MS);
    return () => clearInterval(timer);
  }, [handle, game]);

  // The nearest play (Do more's Replay angles). While Do more is open it stays the play
  // nearest the moment it opened: the video plays on underneath, and the tile must not
  // swap plays under the remote.
  const replayT = layer === "domore" ? layerT : t;
  const nearestReplay = [...(replays ?? [])].sort(
    (a, b) =>
      Math.abs((a.t_start + a.t_end) / 2 - replayT) -
      Math.abs((b.t_start + b.t_end) / 2 - replayT),
  )[0];
  /** The replay nearest a moment, within ANGLES_NEAR_S of its window: Moments → Down
   *  opens its angles. None near: the moment shows no angles link. */
  const replayOf = useCallback(
    (m: Moment) => {
      const gap = (r: ReplaySummary) =>
        Math.max(r.t_start - m.t, 0, m.t - r.t_end);
      const best = [...(replays ?? [])].sort((a, b) => gap(a) - gap(b))[0];
      return best && gap(best) <= ANGLES_NEAR_S ? best : undefined;
    },
    [replays],
  );
  const momentHasAngles = useCallback((m: Moment) => !!replayOf(m), [replayOf]);
  const momentAngles = useCallback(
    (m: Moment) => {
      const r = replayOf(m);
      if (r) openAngle(r.play_id, 0);
    },
    [replayOf, openAngle],
  );
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), TOAST_MS);
    return () => clearTimeout(timer);
  }, [toast]);

  // Loading and errors: the game's key art (from Home) blurred behind the spinner / words.
  if (error)
    return (
      <ApiErrorBanner error={error} onRetry={reload} art={artFor(gameId)} />
    );
  if (!game || !info) return <Loading art={artFor(gameId)} />;

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
  const closeLayer = () => {
    setLayer(null);
    poke();
  };
  const followName = roster.find((p) => p.id === pid);
  // An untagged player reads "Player 3" (track p3), as on the Moments chips.
  const targetName = (id: string) =>
    roster.find((p) => p.id === id)?.name ?? `Player ${id.replace(/^p/, "")}`;
  // The drawn team colours (in team order, so the pair keeps which side is darker), as
  // on the select markers: the ring and the Following chip's dot use them too.
  const ink = teamColorMap(
    [...roster]
      .sort((a, b) => (a.team ?? 0) - (b.team ?? 0))
      .map((r) => r.color_hex),
  );
  const followTint =
    (followName?.color_hex && ink.get(followName.color_hex)) || color.accent;
  /** A player's team colour as their card draws it (a mixed-team track: amber). */
  const tintOf = (id: string) => {
    const p = roster.find((r) => r.id === id);
    return (
      (p && !p.team_mixed && p.color_hex && ink.get(p.color_hex)) ||
      color.accent
    );
  };
  const nHype = endOnBest(topReel(hype), best).length;
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
      sub: q ? `“${q}”` : `Top ${nHype} play${nHype === 1 ? "" : "s"}`,
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
  // Follow a player: picking happens on the video (startSelect). Following (or picking,
  // on the focused marker), the player's card leads; following, "Follow someone else"
  // comes second and Commentary steps out, so the row keeps to 6.
  const followOk = roster.length > 0 && game.tracks.chunks > 0 && !commentaryOn;
  const cardTarget =
    mode === "follow" ? pid : mode === "select" ? focusId : null;
  const followTiles: Tile[] =
    followOk && cardTarget
      ? [
          {
            id: "follow-card",
            label: targetName(cardTarget),
            sub: "Player card",
            dot: tintOf(cardTarget),
            run: () => openCard(cardTarget),
          },
          ...(mode === "follow"
            ? [
                {
                  id: "follow-pick",
                  label: "Follow someone else",
                  run: startSelect,
                },
              ]
            : []),
        ]
      : tile("follow", followOk, {
          id: "action-follow",
          label: "Follow a player",
          run: startSelect,
        });
  // Replay angles: the nearest play's room, at its first cut (the room is the chooser:
  // Left/Right walk the cuts, Down is Free view). No replays: say why, not choosable.
  const anglesF = feature("angles");
  const anglesTile: Tile = nearestReplay
    ? {
        id: "nav-replays",
        label: "Replay angles",
        sub: `${nearestReplay.label} · ${fmtDuration(nearestReplay.t_start)}`,
        run: () => openAngle(nearestReplay.play_id, 0),
      }
    : {
        id: "nav-replays",
        label: "Replay angles",
        sub:
          anglesF?.state === "pending"
            ? `Getting ready, ${(etaText(anglesF.eta_s) || "soon").replace(/ /g, " ")}`
            : "Not ready for this game",
        pending: true,
      };
  const tiles: Tile[] = [
    ...followTiles,
    anglesTile,
    ...(wayTiles.length > 1
      ? [
          {
            id: "menu-watch",
            label: "Highlights",
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
        sub: "Box score, review",
        run: () => openLayer("stats"),
      },
    ),
    ...(followTiles.length > 1
      ? []
      : tile("commentary", lines.length > 0 || !!broadcast, {
          id: "action-captions",
          label: "Commentary",
          sub: commentaryOn ? "On" : "Off",
          on: commentaryOn,
          run: toggleCommentary,
        })),
    {
      id: "nav-phone",
      label: "On your phone",
      sub: "Clip, names, review, search",
      run: () => openLayer("phone"),
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
        from={[info.title]}
        onBack={closeAngle}
      />
    );
  }
  // W6 spotlight while following: the camera's last frame (box and crop), at render rate.
  const view = cam?.current();
  // Gone past a hand-off's reach (an occlusion the tracker did not bridge): say so, and
  // Select picks again near where they were, instead of a camera parked on nobody.
  const lostSight =
    mode === "follow" && !!view && view.lost > HANDOFF_MAX_GAP_S;
  const spotPlayers =
    view?.box && pid ? [{ id: pid, bb: mapBB(view.box, view.rect) }] : [];
  const onBroadcast = commentaryOn && !!broadcast && !condensedSrc;
  const src =
    condensedSrc ?? (onBroadcast && broadcast ? broadcast.url : source.src);
  // The camera runs (and the ring shows) on the wide shot only: track boxes describe it.
  const showFollowFrame =
    !!cam && !!pid && mode !== "select" && src === wideUrl;
  const stageW = Math.min(winW, (winH * 16) / 9);
  const caption = commentaryOn && !layer ? captionAt(lines, t) : null;
  const rally = condensedSrc
    ? rallyAtCondensed(rallies?.rallies ?? [], t)
    : null;
  const indicator = reel
    ? {
        text: `${reel.name} · ${reel.i + 1} of ${reel.segs.length}`,
        index: reel.i + 1,
        count: reel.segs.length,
      }
    : condensedSrc
      ? {
          text: rally
            ? `Condensed · rally ${rally.n} of ${rallies?.n ?? 0}`
            : "Condensed",
          index: rally?.n ?? 0,
          count: rallies?.n ?? 0,
        }
      : null;
  const playhead = cue ? cue.t : t;
  // The context chip (UI pass §4.1): one top-left slot for what is on screen. Following
  // and the reels are the mode, so they stay without the transport; a toast takes the
  // slot for 3 s. The ids are the old elements' (tests and the phone walk use them).
  const chip: {
    id: string;
    parts: string[];
    kind: "title" | "follow" | "pick" | "way";
    dot?: string;
    data?: Record<string, string | number>;
  } = toast
    ? { id: "toast", parts: [toast], kind: "title" }
    : mode === "select"
      ? { id: "select-hint", parts: ["Pick a player"], kind: "pick" }
      : mode === "follow" && pid
        ? {
            id: "followcam-active",
            parts: [
              `${lostSight ? "Lost sight of" : "Following"} ${targetName(pid)}${rendering ? ", getting the view ready" : ""}`,
            ],
            kind: "follow",
            dot: lostSight ? undefined : followTint,
            data: { playerId: pid },
          }
        : indicator
          ? {
              id: "way-indicator",
              parts: [indicator.text],
              kind: "way",
              data: { way, index: indicator.index, count: indicator.count },
            }
          : processing
            ? {
                // still processing: say so, and what it is doing (the title is cut
                // short so a long one cannot push the status off the chip)
                id: "watch-title",
                parts: [
                  info.title.length > 36
                    ? `${info.title.slice(0, 35).trimEnd()}…`
                    : info.title,
                  `Still processing: ${stageWords(info)}`,
                ],
                kind: "title",
                data: { processing: "true" },
              }
            : { id: "watch-title", parts: [info.title], kind: "title" };
  const sticky = chip.id !== "watch-title";
  // The key legend (§2): what the keys do here, at most 3; a layer or panel shows its own.
  const legend: { k: string; label: string }[] | null =
    layer || seekV
      ? null
      : mode === "select"
        ? [
            { k: "Select", label: "Follow" },
            { k: "Back", label: "Cancel" },
          ]
        : mode === "follow"
          ? lostSight
            ? [{ k: "Select", label: "Pick again" }]
            : shown
              ? [{ k: "Back", label: "Stop following" }]
              : null
          : shown && (intro || !playing)
            ? [
                { k: "Select", label: playing ? "Pause" : "Play" },
                { k: "▼", label: "Moments" },
                { k: "▲", label: "Do more" },
              ]
            : null;

  return (
    <View
      style={styles.screen}
      testID="watch"
      dataSet={{
        mode,
        layer: layer ?? "",
        way,
        broadcast: onBroadcast ? "true" : "false",
        followed: followedId ?? "",
      }}
    >
      <View style={{ width: stageW }}>
        {/* The broadcast rendition carries its own audio mix (game audio, stings, ducked
            narration — D-43), so it plays with sound; the raw wide shot stays muted. */}
        <PlayerSurface
          key={condensedSrc ? "condensed" : "game"}
          ref={setHandle}
          poster={artFor(gameId)}
          src={src}
          follow={
            showFollowFrame && cam && pid
              ? {
                  cam,
                  pid,
                  zoom: mode === "follow" && source.useCrop,
                  label: targetName(pid),
                  tint: followTint,
                }
              : null
          }
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
        </PlayerSurface>

        <Animated.View
          style={[StyleSheet.absoluteFill, { opacity: fade }]}
          pointerEvents="none"
          testID="transport"
          dataSet={{ hidden: shown ? "false" : "true" }}
        >
          <Fade side="top" length={px(240)} strength={0.7} />
          <Fade side="bottom" length={px(420)} strength={0.85} />
          <Timeline
            duration={duration}
            t={playhead}
            moments={lineMoments}
            seek={seekV}
            storyboard={condensedSrc ? null : storyboard}
            playing={seekV ? seekV.resume : playing}
            best={condensedSrc ? null : best}
          />
        </Animated.View>
        {flashNode}

        {legend ? <KeyLegend items={legend} /> : null}

        {best && reel?.segs[reel.i]?.best && !layer ? (
          // the Highlights reel's last play: its banner for as long as it plays
          <View style={styles.bestWrap} pointerEvents="none">
            <View
              style={styles.bestCard}
              testID="best-play-card"
              dataSet={{ source: best.source }}
            >
              <T style={[type.title, styles.bestTitle]}>★ {best.label}</T>
              {best.sub_label || best.what ? (
                <T style={[type.meta, styles.bestSub]} testID="best-play-sub">
                  {best.sub_label ?? best.what}
                </T>
              ) : null}
            </View>
          </View>
        ) : null}

        {caption ? (
          // M7 grounded commentary as captions, timed by the clock (audio_t / audio_s).
          <View
            style={[
              styles.caption,
              {
                bottom: shown
                  ? safe.y + TIMELINE_H + (legend ? px(56) : 0) + sp(4)
                  : safe.y,
              },
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

        {layer === "moments" ? (
          <MomentsLayer
            moments={
              momentsOf
                ? moments.filter((m) => m.player?.id === momentsOf)
                : moments
            }
            t={layerT}
            empty={
              feature("moments")?.state === "pending"
                ? `Finding the big moments, ${etaText(feature("moments")?.eta_s) || "soon"}`
                : "No moments in this game yet"
            }
            loading={!momentsRead}
            onCue={setCue}
            onJump={toMoment}
            onClose={closeLayer}
            onPlayPause={toggle}
            hasAngles={momentHasAngles}
            onAngles={momentAngles}
            bestId={best?.moment_id ?? null}
            title={momentsOf ? `Moments · ${targetName(momentsOf)}` : undefined}
            onBookmark={() => {
              closeLayer();
              bookmark(layerT);
            }}
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
        {layer === "player" && cardPid
          ? (() => {
              const card = roster.find((p) => p.id === cardPid) ?? {
                id: cardPid,
                name: null,
                team: 0,
              };
              const followed = mode === "follow" && pid === cardPid;
              const profileId = card.profile_id;
              return (
                <PlayerCard
                  game={game}
                  player={card}
                  tint={tintOf(cardPid)}
                  following={followed}
                  moments={
                    moments.filter((m) => m.player?.id === cardPid).length
                  }
                  onRenamed={(p) =>
                    setRoster((prev) =>
                      prev.map((r) => (r.id === p.id ? { ...r, ...p } : r)),
                    )
                  }
                  onFollow={() => {
                    if (followed) setMode("wide");
                    else if (mode === "select") endSelect(cardPid);
                    else {
                      setPid(cardPid);
                      setMode("follow");
                    }
                    closeCard();
                  }}
                  onMoments={() => {
                    closeCard();
                    setMomentsOf(cardPid);
                    openLayer("moments");
                  }}
                  onProfile={
                    profileId
                      ? () => {
                          remember(true);
                          // Back from the profile: this card again, paused here
                          const following = mode === "follow" && !!pid;
                          navigate({
                            name: "profile",
                            profileId,
                            from: gameId,
                            back: {
                              name: "watch",
                              gameId,
                              way,
                              mode: following ? "follow" : undefined,
                              pid: following ? (pid ?? undefined) : undefined,
                              t: handle?.currentTime() ?? t,
                              card: {
                                pid: cardPid,
                                resume: cardPlaying.current,
                              },
                            },
                          });
                        }
                      : undefined
                  }
                  onLink={
                    profileId
                      ? undefined
                      : () => {
                          closeCard();
                          setLinking(cardPid);
                        }
                  }
                  spotlight={spotlight}
                  onSpotlight={() => setSpotlight((s) => !s)}
                  onClose={closeCard}
                  onPlayPause={toggle}
                />
              );
            })()
          : null}

        {overlay && chip.id !== "toast" ? null : (
          // Above the layers, so a toast ("Commentary on") shows over Do more; the
          // rest of the chip hides under Do more, which would show through it.
          <Animated.View
            style={[
              StyleSheet.absoluteFill,
              {
                opacity:
                  layer === "domore" && chip.id !== "toast"
                    ? 0
                    : sticky
                      ? 1
                      : fade,
              },
            ]}
            pointerEvents="none"
            testID={chip.id}
            dataSet={chip.data}
          >
            <ContextChip parts={chip.parts} kind={chip.kind} dot={chip.dot} />
          </Animated.View>
        )}
      </View>

      {tagging ? (
        <TextEntryDialog
          idPrefix="tag"
          title={`Name ${targetName(tagging)}`}
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
            roster.find((p) => p.id === linking)?.name ?? targetName(linking)
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
  // top centre: the context chip holds the top-left corner
  bestWrap: {
    position: "absolute",
    top: safe.y,
    left: 0,
    right: 0,
    alignItems: "center",
  },
  bestCard: {
    alignItems: "center",
    paddingHorizontal: sp(4),
    paddingVertical: sp(1.5),
    borderRadius: radius.card,
    borderWidth: px(3),
    borderColor: color.scoreboard,
    backgroundColor: "rgba(18, 26, 35, 0.84)",
  },
  bestTitle: { color: color.scoreboard, marginBottom: 0 },
  bestSub: { color: color.chalk },
});
