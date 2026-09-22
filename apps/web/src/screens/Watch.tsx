// W2 wide transport, W3 select mode, W4 follow mode, W5 court inset, W6 spotlight,
// W7 tagging, W8 event markers + jumps, H5 bookmarks.
//
// Mode and selected player live in the URL query (?mode=&pid=&t=) so a reload restores
// the session — this is the E-21 behaviour this implementation commits to.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { FORCE_SPOTLIGHT, MOCK_API, SEEK_STEP_S, followcam } from "../config";
import { createTracksCache } from "../data/tracksCache";
import { nextFocus, type Direction } from "../focus/spatial";
import { useDpad, type DpadAction } from "../platform/keys";
import { PlayerSurface, type PlayerHandle } from "../playback/PlayerSurface";
import { useClockTime } from "../playback/clock";
import { CourtInset } from "../components/CourtInset";
import { SeekBarEvents } from "../components/SeekBarEvents";
import { SelectOverlay } from "../components/SelectOverlay";
import { TagDialog } from "../components/TagDialog";
import { navigate, setQuery, useLocation } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import type { CropPath, GameEvent, Player } from "../api/types";

type Mode = "wide" | "select" | "follow";
const SCRUB_STEP_S = 5;

const NAV: { label: string; to: (id: string) => string }[] = [
  { label: "Library", to: () => "/tv" },
  { label: "Highlights", to: (id) => `/tv/${id}/highlights` },
  { label: "Review", to: (id) => `/tv/${id}/review` },
];

export function Watch({ gameId }: { gameId: string }) {
  const { params } = useLocation();
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
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
  const [version, bump] = useState(0);
  const restoreT = useRef<number | null>(Number(params.get("t")) || null);

  const clock = handle?.clock ?? null;
  const t = useClockTime(clock);
  const duration = handle?.duration() ?? game?.video.duration_s ?? 0;

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

  // D-6 client follow-cam: fetch the crop path for the followed player.
  useEffect(() => {
    if (mode !== "follow" || !pid || !game || followcam.mode !== "client") {
      setCrop(null);
      return;
    }
    let live = true;
    api.getCropPath(game, pid).then((c) => live && setCrop(c), () => setCrop(null));
    return () => {
      live = false;
    };
  }, [mode, pid, game]);

  // `version` is bumped when a tracks chunk lands — it is a real dependency even though
  // the cache reads it internally.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const players = useMemo(() => tracks?.playersAt(t) ?? [], [tracks, t, version]);
  const sorted = [...events].sort((a, b) => a.t_key - b.t_key);

  const jumpEvent = useCallback(
    (dir: 1 | -1) => {
      if (!handle || sorted.length === 0) return;
      const now = handle.currentTime();
      const next =
        dir > 0
          ? sorted.find((e) => e.t_key > now + 0.05)
          : [...sorted].reverse().find((e) => e.t_key < now - 0.05);
      if (next) handle.seek(next.t_key);
    },
    [handle, sorted],
  );

  const onAction = useCallback(
    (a: DpadAction) => {
      if (!handle || !game) return;
      // Top nav row: reachable with ArrowUp, so every screen is D-pad reachable (NF-03).
      if (navFocus !== null) {
        if (a === "left") setNavFocus((i) => Math.max(0, (i ?? 0) - 1));
        else if (a === "right") setNavFocus((i) => Math.min(NAV.length - 1, (i ?? 0) + 1));
        else if (a === "down" || a === "back") setNavFocus(null);
        else if (a === "select") navigate(NAV[navFocus].to(game.id));
        return;
      }

      switch (a) {
        case "playpause": {
          handle.toggle();
          // W3: pausing the wide shot is what opens select mode.
          if (mode !== "follow") setMode(handle.paused() ? "select" : "wide");
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
            setMode("wide");
            setPid(null);
            setQuery({ mode: null, pid: null });
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
    [handle, game, mode, focusId, pid, players, jumpEvent, navFocus],
  );
  useDpad(onAction, !tagging);

  // Entering select mode with nothing focused: start at the leftmost box.
  useEffect(() => {
    if (mode !== "select" || focusId || players.length === 0) return;
    setFocusId([...players].sort((a, b) => a.bb[0] - b.bb[0])[0].id);
  }, [mode, focusId, players]);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game) return <div className="screen">Loading…</div>;

  const followName = roster.find((p) => p.id === pid);
  const spotlightOn = spotlight || (mode === "follow" && FORCE_SPOTLIGHT);
  const useTransform = mode === "follow" && followcam.mode === "client" && !FORCE_SPOTLIGHT;

  return (
    <div className="screen watch" data-mode={mode}>
      <nav className="topnav">
        {NAV.map((n, i) => (
          <span
            key={n.label}
            className={`navitem${navFocus === i ? " focused" : ""}`}
            data-testid={`nav-${n.label.toLowerCase()}`}
            data-focused={navFocus === i ? "true" : "false"}
          >
            {n.label}
          </span>
        ))}
        <span className="title">{game.title}</span>
      </nav>

      <PlayerSurface
        ref={setHandle}
        src={api.mediaUrl(game, game.renditions.wide)}
        crop={useTransform ? crop : null}
        muted={MOCK_API}
      >
        {mode === "select" ? (
          <SelectOverlay players={players} roster={roster} focusId={focusId} spotlight={spotlightOn} />
        ) : null}
        {mode === "follow" ? (
          <>
            <SelectOverlay
              players={players.filter((p) => p.id === pid)}
              roster={roster}
              focusId={pid}
              spotlight={spotlightOn}
              showBoxes={false}
            />
            <div className="followcam-badge" data-testid="followcam-active" data-player-id={pid}>
              Following {followName?.name ?? pid}
            </div>
          </>
        ) : null}
      </PlayerSurface>

      <SeekBarEvents duration={duration} current={t} events={sorted} focused={mode === "wide"} />

      <div className="watch-side">
        <CourtInset
          court={game.sport_ui?.court}
          variant={game.court.variant}
          players={players}
          roster={roster}
          selectedId={mode === "follow" ? pid : focusId}
        />
        <p className="hint">
          {mode === "select"
            ? "Arrows pick a player · Enter follows · t tags · s spotlight · Escape exits"
            : mode === "follow"
              ? "Space plays · Escape returns to the wide shot"
              : "Space pauses to select · , / . ±10 s · [ / ] events · b bookmark · ↑ menu"}
        </p>
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
