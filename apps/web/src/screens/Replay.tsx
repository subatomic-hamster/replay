// M8 multi-angle replays (browser TV harness; apps/tv/src/screens/Replay.tsx is the RN
// twin). ReplayList: the game's rendered replays, reached from Watch's top nav
// ("Replays", shown when the game has any). Replay: one highlight where Left/Right cut
// between its pre-rendered angle videos like broadcast cameras. The angles are
// time-aligned, so a cut is just a src swap on PlayerSurface, which resumes at the same
// media time and play state; the highlight loops at the end. A cut shows the angle name big
// in the lower-left bug for ANGLE_BUG_MS, then it shrinks. Back: Replay → list → Watch.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { useDpad, type DpadAction } from "../platform/keys";
import { PlayerSurface, type PlayerHandle } from "../playback/PlayerSurface";
import { navigate } from "../router";
import { ApiErrorBanner, fmtDuration, useAsync } from "../ui";
import {
  ANGLE_BUG_MS,
  cutOrder,
  cycleAngle,
  nextPov,
  povOf,
  tierBadge,
} from "../../../../packages/tv-core/src/replays";
import "./Replay.css";

export function ReplayList({ gameId }: { gameId: string }) {
  const { data, error, reload } = useAsync(
    () => api.listReplays(gameId),
    [gameId],
  );
  const [focus, setFocus] = useState(0);
  const replays = useMemo(() => data ?? [], [data]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") navigate(`/tv/${gameId}`);
      else if (replays.length === 0) return;
      else if (a === "down" || a === "right")
        setFocus((i) => Math.min(replays.length - 1, i + 1));
      else if (a === "up" || a === "left") setFocus((i) => Math.max(0, i - 1));
      else if (a === "select")
        navigate(
          `/tv/${gameId}/replays/${encodeURIComponent(replays[focus].play_id)}`,
        );
    },
    [gameId, replays, focus],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!data) return <div className="screen">Loading…</div>;

  return (
    <div className="screen replay-list" data-testid="replay-list">
      <h1>Replays</h1>
      {replays.length === 0 ? (
        <p data-testid="replay-list-empty">
          No replays rendered for this game yet.
        </p>
      ) : null}
      <ol className="replay-cards">
        {replays.map((r, i) => (
          <li
            key={r.play_id}
            className={`replay-card${i === focus ? " focused" : ""}`}
            data-testid="replay-card"
            data-play-id={r.play_id}
            data-focused={i === focus ? "true" : "false"}
          >
            <span className="replay-card-title">{r.label}</span>
            <span className="replay-card-meta">
              {r.angles} angles · {fmtDuration(r.t_end - r.t_start)}
            </span>
          </li>
        ))}
      </ol>
      <p className="hint">
        <b>↑ ↓</b> move · <b>Enter</b> opens a replay · <b>Escape</b> back to
        the game
      </p>
    </div>
  );
}

export function Replay({ gameId, playId }: { gameId: string; playId: string }) {
  const {
    data: m,
    error,
    reload,
  } = useAsync(() => api.getReplay(gameId, playId), [gameId, playId]);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const [index, setIndex] = useState(0);
  const [big, setBig] = useState(true);
  const order = useMemo(() => (m ? cutOrder(m.angles, index) : []), [m, index]);

  // A replay starts playing; PlayerSurface holds the request until the media can play.
  useEffect(() => {
    if (m && handle) handle.play();
  }, [m, handle]);

  // The big label shrinks ANGLE_BUG_MS after the last cut (a new cut restarts the timer).
  useEffect(() => {
    if (!big) return;
    const timer = setTimeout(() => setBig(false), ANGLE_BUG_MS);
    return () => clearTimeout(timer);
  }, [big, index]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") navigate(`/tv/${gameId}/replays`);
      else if ((a === "left" || a === "right") && order.length > 1) {
        // the virtual POVs share one slot of the cut (the key player's); Up picks another
        const k = Math.max(0, order.indexOf(index));
        setIndex(order[cycleAngle(k, order.length, a === "right" ? 1 : -1)]);
        setBig(true);
      } else if (a === "up" && m && povOf(m.angles[index])) {
        setIndex(nextPov(m.angles, index));
        setBig(true);
      } else if (a === "select" || a === "playpause") handle?.toggle();
    },
    [gameId, order, index, m, handle],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!m) return <div className="screen">Loading…</div>;
  const angle = m.angles[index];
  if (!angle) {
    return (
      <div className="screen" data-testid="replay">
        <p>This replay has no rendered angles.</p>
        <p className="hint">
          <b>Escape</b> back to replays
        </p>
      </div>
    );
  }

  return (
    <div
      className="screen watch replay"
      data-testid="replay"
      data-angle={angle.id}
      data-tier={angle.tier}
      data-index={index}
    >
      <div className="watch-stage">
        <PlayerSurface ref={setHandle} src={angle.url} muted loop>
          <div className="replay-top">
            <span className="replay-kicker">REPLAY</span>
            <span className="replay-title" data-testid="replay-title">
              {m.label}
            </span>
            {m.synthetic ? (
              <span className="replay-synthetic" data-testid="replay-synthetic">
                SYNTHETIC
              </span>
            ) : null}
          </div>

          <div
            className={`replay-bug${big ? " prominent" : ""}`}
            data-testid="replay-bug"
            data-prominent={big ? "true" : "false"}
          >
            <div className="replay-bug-row">
              <span
                className={`replay-tier tier-${angle.tier}`}
                data-testid="replay-tier-badge"
                data-tier={angle.tier}
              >
                {tierBadge(angle.tier)}
              </span>
              <span className="replay-arrow">◀</span>
              <span className="replay-pos" data-testid="replay-angle-pos">
                {`${order.indexOf(index) + 1} / ${order.length}`}
              </span>
              <span className="replay-arrow">▶</span>
            </div>
            <div className="replay-angle" data-testid="replay-angle-label">
              {angle.label}
            </div>
          </div>

          <p className="hint replay-hint">
            <b>◀ ▶</b> cut between camera angles · <b>Enter</b> plays/pauses ·{" "}
            <b>Escape</b> back to replays
          </p>
        </PlayerSurface>
      </div>
    </div>
  );
}
