// "On your phone" (docs/ux/redesign.md, phone handoff): the page the TV's QR opens,
// `/p/:id?job=clip|tag|review|search[&t=<s>]#k=<phone token>`. Touch, one hand, 390 px:
// the game's title on top, the four jobs as tabs at the bottom (thumb reach). The token is
// the only credential (api/phone.ts); a 401 anywhere swaps the page for "expired".
//
// Clip: the moment at/near `t` (else t ± 5 s), trim handles, 16:9 / 9:16, Save clip (the
// TV's tap route cuts it, the trim route sets the window), then a link to share.
// Names (job "tag"): the game's players; link one to a profile or name a new one.
// Review: the review queue as cards with the TV's answers.
// Search: this game's plays; a hit plays its window right here.
// Reel: the game's highlight reel (your clips, then the top plays), 16:9 or 9:16, rendered
// on the server, then a link to save or share it.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { isExpired, phoneApi, phoneToken, type PhoneApi } from "../api/phone";
import type { Game, Moment, Player } from "../api/types";
import { Avatar } from "../components/Avatar";
import { setQuery, useLocation } from "../router";
import { useAsync } from "../ui";
import { Problem } from "./QrUpload";
import {
  fmtDuration,
  highlightQueries,
  isShortTrack,
  MIN_SEEN_S,
} from "../../../../packages/tv-core/src/display";
import {
  exportPending,
  fmtClock,
  momentClip,
  nudgeTrim,
  optionTestId,
  TRIM_STEP_S,
  type BestPlay,
  type PlayClip,
  type ReelExport,
  type ReviewOption,
  type ReviewQuestion,
  type SearchHit,
  type SearchResult,
  type VerticalExport,
} from "../../../../packages/tv-core/src/discovery";
import type { Profile } from "../../../../packages/tv-core/src/profiles";

const JOBS = ["clip", "tag", "review", "search", "reel"] as const;
type Job = (typeof JOBS)[number];
const LABEL: Record<Job, string> = {
  clip: "Clip",
  tag: "Names",
  review: "Review",
  search: "Search",
  reel: "Reel",
};

const EXPIRED = "This link has expired. Scan the code on the TV again.";
const MISSING = "This link is missing its code. Scan the code on the TV again.";
/** The TV's code for this page lives on its On your phone tile (Menu opens Do more). */
const NEW_LINK = [
  "On the TV, open the game and press Menu.",
  "Choose On your phone, then what you want to do.",
  "Point your phone's camera at the code and open the link.",
];
/** No moment near `t`: clip t ± PAD_S. A moment counts as "near" within NEAR_S. */
const PAD_S = 5;
const NEAR_S = 10;
/** How far the trim handles reach past the starting window. */
const REACH_S = 10;
/** The 9:16 render takes tens of seconds; poll gently (D-87: shared Lambda concurrency). */
const POLL_MS = 3000;
/** Review's "Watch it": from 4 s before the play (as on the TV) to 3 s after. */
const WATCH_LEAD_S = 4;
const WATCH_TAIL_S = 3;

type Win = { t_start: number; t_end: number };
/** A panel's error → its message; a 401 also flips the whole page to "expired". */
type Fail = (e: unknown) => string;
interface JobProps {
  api: PhoneApi;
  game: Game;
  moments: Moment[];
  fail: Fail;
  /** Whether a TV showed this game at the last send to it (POST /tv/play answers that).
   *  Assumed at first: this page is opened from the TV's own code. */
  tv: boolean;
  sawTv: (showing: boolean) => void;
}

export function PhonePage({ gameId }: { gameId: string }) {
  const [token] = useState(() => phoneToken(gameId));
  const api = useMemo(() => phoneApi(token), [token]);
  const { params } = useLocation();
  const job = (JOBS as readonly string[]).includes(params.get("job") ?? "")
    ? (params.get("job") as Job)
    : "clip";
  const tParam = Number(params.get("t") ?? "");
  const t =
    params.get("t") && Number.isFinite(tParam) && tParam >= 0 ? tParam : null;

  const {
    data: game,
    error,
    reload,
  } = useAsync(() => api.getGame(gameId), [api, gameId]);
  const { data: moments } = useAsync(
    () => api.getMoments(gameId).catch((): Moment[] => []),
    [api, gameId],
  );
  const [expired, setExpired] = useState(false);
  const [tv, sawTv] = useState(true);
  const fail = useCallback<Fail>((e) => {
    if (isExpired(e)) setExpired(true);
    return e instanceof Error ? e.message : String(e);
  }, []);

  if (!token) return <Problem text={MISSING} steps={NEW_LINK} />;
  if (expired || (error && isExpired(error)))
    return <Problem text={EXPIRED} steps={NEW_LINK} />;
  if (error)
    return (
      <Problem
        text={`Could not reach Replay: ${error.message}`}
        onRetry={reload}
      />
    );
  if (!game || !moments) return <div className="screen phone">Loading…</div>;

  const props: JobProps = { api, game, moments, fail, tv, sawTv };
  // All the jobs stay mounted (hidden), so switching tabs keeps a search or a half-done trim.
  return (
    <div
      className="screen phone phone-jobs"
      data-testid="phone-page"
      data-job={job}
    >
      <h1 data-testid="phone-title">{game.title}</h1>
      <section
        role="tabpanel"
        aria-label="Clip"
        hidden={job !== "clip"}
        data-testid="phone-clip"
      >
        <ClipJob {...props} t={t} />
      </section>
      <section
        role="tabpanel"
        aria-label="Names"
        hidden={job !== "tag"}
        data-testid="phone-tag"
      >
        <TagJob {...props} />
      </section>
      <section
        role="tabpanel"
        aria-label="Review"
        hidden={job !== "review"}
        data-testid="phone-review"
      >
        <ReviewJob {...props} />
      </section>
      <section
        role="tabpanel"
        aria-label="Search"
        hidden={job !== "search"}
        data-testid="phone-search"
      >
        <SearchJob {...props} />
      </section>
      <section
        role="tabpanel"
        aria-label="Highlight reel"
        hidden={job !== "reel"}
        data-testid="phone-reel"
      >
        <ReelJob {...props} />
      </section>
      <nav className="phone-tabs" role="tablist" aria-label="What to do">
        {JOBS.map((j) => (
          <button
            key={j}
            type="button"
            role="tab"
            aria-selected={j === job}
            data-testid={`phone-tab-${j}`}
            onClick={() => setQuery({ job: j })}
          >
            {LABEL[j]}
          </button>
        ))}
      </nav>
    </div>
  );
}

/** The wide video, parked at `at`, playing only inside `win`. */
function WindowVideo({
  src,
  win,
  at,
  tall = false,
  autoPlay = false,
  testId,
}: {
  src: string;
  win: Win;
  at: number;
  tall?: boolean;
  autoPlay?: boolean;
  testId: string;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    v.currentTime = at;
    if (autoPlay) {
      v.scrollIntoView({ block: "nearest" });
      v.play().catch(() => {});
    }
  }, [at, autoPlay]);
  return (
    <div className={`phone-video${tall ? " tall" : ""}`}>
      <video
        ref={ref}
        src={src}
        data-testid={testId}
        data-t-start={win.t_start}
        data-t-end={win.t_end}
        controls
        playsInline
        muted
        preload="auto"
        onPlay={(e) => {
          const v = e.currentTarget;
          if (
            v.currentTime < win.t_start - 0.25 ||
            v.currentTime >= win.t_end - 0.05
          )
            v.currentTime = win.t_start;
        }}
        onTimeUpdate={(e) => {
          const v = e.currentTarget;
          if (!v.paused && v.currentTime >= win.t_end) v.pause();
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------- Clip

function nearestMoment(moments: Moment[], t: number | null): Moment | null {
  if (t === null) return moments[0] ?? null;
  const inside = moments.find((m) => m.t_start <= t && t <= m.t_end);
  if (inside) return inside;
  const best = [...moments].sort(
    (a, b) => Math.abs(a.t - t) - Math.abs(b.t - t),
  )[0];
  return best && Math.abs(best.t - t) <= NEAR_S ? best : null;
}

const r1 = (v: number) => Math.round(v * 10) / 10;
/** "p12" → "12": the TV calls an unnamed player "Player 12"; the phone matches it. */
const trackNo = (pid: string) => pid.replace(/^p/, "");

function ClipJob({
  api,
  game,
  moments,
  fail,
  t,
}: JobProps & { t: number | null }) {
  const dur = game.video.duration_s;
  const [momentId, setMomentId] = useState(
    () => nearestMoment(moments, t)?.id ?? "",
  );
  const moment = moments.find((m) => m.id === momentId) ?? null;
  const at = t ?? 0;
  const base: Win = moment
    ? momentClip(moment, dur)
    : {
        t_start: r1(Math.max(0, at - PAD_S)),
        t_end: r1(dur ? Math.min(dur, at + PAD_S) : at + PAD_S),
      };
  const [edited, setEdited] = useState<Win | null>(null);
  const win = edited ?? base;
  const [seek, setSeek] = useState(win.t_start);
  const [aspect, setAspect] = useState<"16:9" | "9:16">("16:9");
  const [clip, setClip] = useState<PlayClip | null>(null);
  const [saved, setSaved] = useState<Win | null>(null);
  const [exp, setExp] = useState<VerticalExport | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const wide = api.mediaUrl(game, game.renditions.wide);
  // The game's best play (one per game): what it is now, and "Make this the best play".
  const [best, setBest] = useState<BestPlay | null>(null);
  const [bestNote, setBestNote] = useState("");
  useEffect(() => {
    api.getBestPlay(game.id).then(setBest, () => {});
  }, [api, game.id]);
  const makeBest = async () => {
    setBusy(true);
    setBestNote("");
    try {
      const inside = moment && win.t_start <= moment.t && moment.t <= win.t_end;
      setBest(
        await api.setBestPlay(game.id, {
          t_start: win.t_start,
          t_end: win.t_end,
          t: moment && inside ? moment.t : r1((win.t_start + win.t_end) / 2),
          moment_id: moment?.id ?? null,
        }),
      );
      setBestNote(
        "This is now the best play of the game. Highlights on the TV end with it.",
      );
    } catch (e) {
      setBestNote(`Not saved: ${fail(e)}`);
    } finally {
      setBusy(false);
    }
  };

  // 9:16: poll the render until it lands.
  useEffect(() => {
    if (!exp || !exportPending(exp)) return;
    const timer = setTimeout(() => {
      api
        .getVertical(game.id, exp.id)
        .then(setExp, (e) => setNote(`Export failed: ${fail(e)}`));
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [exp, api, game.id, fail]);

  const changed = () => {
    setSaved(null);
    setExp(null);
    setNote("");
  };
  const move = (edge: "start" | "end", to: number) => {
    const next = nudgeTrim(
      win,
      edge,
      to - (edge === "start" ? win.t_start : win.t_end),
      dur,
    );
    setEdited(next);
    setSeek(
      edge === "start" ? next.t_start : Math.max(next.t_start, next.t_end - 1),
    );
    changed();
  };

  const save = async () => {
    setBusy(true);
    changed();
    try {
      const anchor = moment?.t ?? t ?? win.t_start;
      // The clip already cut around this moment, else the TV's tap route cuts one.
      let c =
        clip ??
        (await api.listClips(game.id)).find(
          (x) => x.t_start <= anchor && anchor <= x.t_end,
        ) ??
        (
          await api.tap(
            game.id,
            Math.min(dur || Infinity, moment?.t_end ?? win.t_end),
          )
        ).clip;
      if (c && (c.t_start !== win.t_start || c.t_end !== win.t_end))
        c = await api.trimClip(game.id, c.id, win.t_start, win.t_end);
      setClip(c);
      setSaved(win);
      setNote(
        c
          ? "Clip saved."
          : "No play ends here, so it is not in the game's clips. You can still share it.",
      );
      if (aspect === "9:16")
        setExp(
          await api.exportVertical(game.id, c ? { clip_id: c.id } : { ...win }),
        );
    } catch (e) {
      setNote(`Not saved: ${fail(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const failed = exp?.status === "failed" || exp?.status === "error";
  const link = !saved
    ? null
    : aspect === "16:9"
      ? `${wide}#t=${saved.t_start},${saved.t_end}`
      : exp?.status === "done"
        ? exp.url
        : null;
  const lo = Math.min(win.t_start, Math.max(0, base.t_start - REACH_S));
  const hi = Math.max(
    win.t_end,
    dur ? Math.min(dur, base.t_end + REACH_S) : base.t_end + REACH_S,
  );

  return (
    <>
      {moments.length ? (
        <label>
          Moment
          <select
            data-testid="clip-moment"
            value={momentId}
            onChange={(e) => {
              setMomentId(e.target.value);
              setEdited(null);
              setClip(null);
              const m = moments.find((x) => x.id === e.target.value);
              setSeek(m ? m.t_start : base.t_start);
              changed();
            }}
          >
            {moment ? null : <option value="">Around {fmtClock(at)}</option>}
            {moments.map((m) => (
              <option key={m.id} value={m.id}>
                {fmtClock(m.t)} · {m.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <WindowVideo
        src={wide}
        win={win}
        at={seek}
        tall={aspect === "9:16"}
        testId="clip-video"
      />

      <div className="trim-phone" data-testid="clip-trim">
        {(["start", "end"] as const).map((edge) => {
          const v = edge === "start" ? win.t_start : win.t_end;
          const name = edge === "start" ? "Start" : "End";
          return (
            <div className="trim-handle-row" key={edge}>
              <span className="trim-label">
                {name} <b data-testid={`clip-${edge}`}>{fmtClock(v)}</b>
              </span>
              <button
                type="button"
                className="secondary nudge"
                aria-label={`${name} earlier`}
                data-testid={`clip-${edge}-earlier`}
                onClick={() => move(edge, v - TRIM_STEP_S)}
              >
                −½ s
              </button>
              <input
                type="range"
                aria-label={`${name} of the clip`}
                data-testid={`clip-${edge}-range`}
                min={lo}
                max={hi}
                step={0.1}
                value={v}
                onChange={(e) => move(edge, Number(e.target.value))}
              />
              <button
                type="button"
                className="secondary nudge"
                aria-label={`${name} later`}
                data-testid={`clip-${edge}-later`}
                onClick={() => move(edge, v + TRIM_STEP_S)}
              >
                +½ s
              </button>
            </div>
          );
        })}
        <p className="dim" data-testid="clip-length">
          {(win.t_end - win.t_start).toFixed(1)} s
        </p>
      </div>

      <div className="segmented" role="radiogroup" aria-label="Shape">
        {(["16:9", "9:16"] as const).map((a) => (
          <button
            key={a}
            type="button"
            role="radio"
            aria-checked={aspect === a}
            data-testid={`clip-aspect-${a === "16:9" ? "wide" : "tall"}`}
            onClick={() => {
              setAspect(a);
              changed();
            }}
          >
            {a === "16:9" ? "16:9 wide" : "9:16 tall"}
          </button>
        ))}
      </div>

      <button
        type="button"
        className="wide-btn"
        data-testid="clip-save"
        disabled={busy}
        onClick={() => void save()}
      >
        {busy ? "Saving…" : "Save clip"}
      </button>
      {note ? (
        <p role="status" data-testid="clip-note" data-clip-id={clip?.id ?? ""}>
          {note}
        </p>
      ) : null}
      {saved && aspect === "9:16" && !link ? (
        <p
          data-testid="clip-rendering"
          className={failed ? "error" : undefined}
        >
          {failed
            ? `The 9:16 render failed${exp?.error ? `: ${exp.error}` : ""}.`
            : "Rendering the 9:16 cut…"}
        </p>
      ) : null}
      {link ? (
        <ShareLink url={link} title={game.title} tall={aspect === "9:16"} />
      ) : null}

      {best ? (
        <p
          className="dim best-play"
          data-testid="clip-best-now"
          data-source={best.source}
          data-moment-id={best.moment_id ?? ""}
        >
          ★ Best play now: {fmtDuration(best.t)}
          {best.what ? ` · ${best.what}` : ""}
          {best.source === "user"
            ? " (your pick)"
            : ` (${best.sub_label ?? "picked automatically"})`}
        </p>
      ) : null}
      <button
        type="button"
        className="secondary wide-btn"
        data-testid="clip-best"
        disabled={busy}
        onClick={() => void makeBest()}
      >
        ★ Make this the best play
      </button>
      {bestNote ? (
        <p role="status" data-testid="clip-best-note">
          {bestNote}
        </p>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------- Reel

function ReelJob({ api, game, fail }: JobProps) {
  const [aspect, setAspect] = useState<ReelExport["aspect"]>("16:9");
  const [reel, setReel] = useState<ReelExport | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  // The render takes a while: poll until it lands.
  useEffect(() => {
    if (!reel || !exportPending(reel)) return;
    const timer = setTimeout(() => {
      api
        .getGameReel(game.id, reel.id)
        .then(setReel, (e) => setNote(`Reel failed: ${fail(e)}`));
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [reel, api, game.id, fail]);

  const make = () => {
    setBusy(true);
    setNote("");
    api
      .exportGameReel(game.id, aspect)
      .then(setReel, (e) => setNote(`Not started: ${fail(e)}`))
      .finally(() => setBusy(false));
  };
  const failed = reel?.status === "failed" || reel?.status === "error";
  const done = reel?.status === "done" && reel.url ? reel : null;

  return (
    <>
      <p className="dim">
        Your clips first, then the game's top plays, in one video.
      </p>
      <div className="segmented" role="radiogroup" aria-label="Shape">
        {(["16:9", "9:16"] as const).map((a) => (
          <button
            key={a}
            type="button"
            role="radio"
            aria-checked={aspect === a}
            data-testid={`reel-aspect-${a === "16:9" ? "wide" : "tall"}`}
            onClick={() => {
              setAspect(a);
              setReel(null);
              setNote("");
            }}
          >
            {a === "16:9" ? "16:9 wide" : "9:16 tall"}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="wide-btn"
        data-testid="reel-make"
        disabled={busy || exportPending(reel)}
        onClick={make}
      >
        {busy ? "Starting…" : "Make the highlight reel"}
      </button>
      {note ? (
        <p role="status" className="error" data-testid="reel-note">
          {note}
        </p>
      ) : null}
      {reel && !done ? (
        <p
          data-testid="reel-status"
          data-state={reel.status}
          className={failed ? "error" : undefined}
        >
          {failed
            ? `The reel did not render${reel.error ? `: ${reel.error}` : ""}.`
            : "Rendering the reel…"}
        </p>
      ) : null}
      {done?.url ? (
        <ShareLink
          url={done.url}
          title={`${game.title} highlights`}
          tall={aspect === "9:16"}
          label={
            done.duration_s
              ? `Download reel (${Math.round(done.duration_s)} s)`
              : "Download reel"
          }
          testId="reel-link"
        />
      ) : null}
    </>
  );
}

function ShareLink({
  url,
  title,
  tall,
  label,
  testId = "clip-link",
}: {
  url: string;
  title: string;
  tall: boolean;
  label?: string;
  testId?: string;
}) {
  const abs = new URL(url, window.location.href).href;
  return (
    <div className="share-row">
      <a
        className="button-link"
        href={abs}
        download
        target="_blank"
        rel="noreferrer"
        data-testid={testId}
      >
        {label ?? (tall ? "Download 9:16 clip" : "Open clip")}
      </a>
      {typeof navigator.share === "function" ? (
        <button
          type="button"
          className="secondary"
          data-testid="clip-share"
          onClick={() =>
            void navigator.share({ title, url: abs }).catch(() => {})
          }
        >
          Share
        </button>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- Tag

function PlayerThumb({
  game,
  player,
  moments,
}: {
  game: Game;
  player: Player;
  moments: Moment[];
}) {
  const thumb = moments.find(
    (m) => m.player?.id === player.id && m.thumb_url,
  )?.thumb_url;
  const color =
    player.color_hex ??
    game.teams.find((x) => x.id === player.team)?.color_hex ??
    "var(--line)";
  return (
    <span
      className="player-thumb"
      style={{ borderColor: color }}
      data-thumb={thumb ? "true" : "false"}
    >
      {thumb ? <img src={thumb} alt="" /> : trackNo(player.id)}
    </span>
  );
}

function TagJob({ api, game, moments, fail }: JobProps) {
  const [players, setPlayers] = useState(game.players);
  const [pick, setPick] = useState<string | null>(null);
  const { data: profiles, error } = useAsync(() => api.listProfiles(), [api]);
  const [made, setMade] = useState<Profile[]>([]);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const list = [...(profiles ?? []), ...made];
  const label = (p: Player) => p.name ?? `Player ${trackNo(p.id)}`;
  // Tracker fragments (on screen under 5 s) wait behind one row, so the real players
  // are the list; a fragment that gets a name joins it.
  const [showShort, setShowShort] = useState(false);
  const nShort = players.filter(isShortTrack).length;
  const shown = showShort ? players : players.filter((p) => !isShortTrack(p));

  // The two sides: the game's teams, or Team 1 / Team 2 when tracking saw only one kit.
  const teams = game.teams.length >= 2 ? game.teams.map((x) => x.id) : [0, 1];
  const teamName = (id: number) => `Team ${teams.indexOf(id) + 1}`;
  const setTeam = async (p: Player, team: number) => {
    setBusy(true);
    setNote("");
    try {
      const out = await api.patchPlayer(game.id, p.id, { team });
      setPlayers((ps) => ps.map((x) => (x.id === p.id ? out : x)));
      setNote(`${label(p)} is on ${teamName(team)}.`);
    } catch (e) {
      setNote(`Not saved: ${fail(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const tag = async (pid: string, profile: Profile | null) => {
    setBusy(true);
    setNote("");
    try {
      const pr = profile ?? (await api.createProfile({ name: name.trim() }));
      if (!profile) setMade((m) => [...m, pr]);
      await api.linkProfile(pr.profile_id, game.id, pid);
      setPlayers((ps) =>
        ps.map((p) =>
          p.id === pid ? { ...p, name: pr.name, profile_id: pr.profile_id } : p,
        ),
      );
      setNote(`Named ${pr.name}.`);
      setName("");
      setPick(null);
    } catch (e) {
      setNote(`Not saved: ${fail(e)}`);
    } finally {
      setBusy(false);
    }
  };

  if (!players.length)
    return <p data-testid="tag-empty">No players found in this game yet.</p>;
  return (
    <>
      <p className="dim">Pick a player, then say who it is.</p>
      {note ? (
        <p role="status" data-testid="tag-note">
          {note}
        </p>
      ) : null}
      <ul className="phone-list">
        {shown.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              className={`row-btn${pick === p.id ? " on" : ""}`}
              aria-expanded={pick === p.id}
              data-testid="tag-player"
              data-player-id={p.id}
              data-name={p.name ?? ""}
              onClick={() => setPick(pick === p.id ? null : p.id)}
            >
              <PlayerThumb game={game} player={p} moments={moments} />
              <span className="row-text">{label(p)}</span>
              {p.profile_id ? <span className="dim">Linked</span> : null}
              {p.team_mixed ? null : (
                <span className="dim" data-testid="tag-team" data-team={p.team}>
                  {teamName(p.team)}
                </span>
              )}
            </button>
            {pick === p.id ? (
              <div className="tag-panel" data-testid="tag-panel">
                <div className="segmented" role="radiogroup" aria-label="Team">
                  {teams.map((id) => (
                    <button
                      key={id}
                      type="button"
                      role="radio"
                      aria-checked={!p.team_mixed && p.team === id}
                      data-testid="tag-team-pick"
                      data-team={id}
                      disabled={busy}
                      onClick={() => void setTeam(p, id)}
                    >
                      <span
                        className="team-dot"
                        style={{
                          background:
                            game.teams.find((x) => x.id === id)?.color_hex ??
                            "var(--line)",
                        }}
                      />
                      {teamName(id)}
                    </button>
                  ))}
                </div>
                <h2>Who is {label(p)}?</h2>
                {error ? (
                  <p className="error">
                    Could not load profiles: {error.message}
                  </p>
                ) : null}
                <ul className="phone-list">
                  {list.map((pr) => (
                    <li key={pr.profile_id}>
                      <button
                        type="button"
                        className="row-btn"
                        data-testid="tag-profile"
                        data-profile-id={pr.profile_id}
                        disabled={busy}
                        onClick={() => void tag(p.id, pr)}
                      >
                        <Avatar name={pr.name} photo={pr.photo_url} size={48} />
                        <span className="row-text">{pr.name}</span>
                      </button>
                    </li>
                  ))}
                </ul>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (name.trim()) void tag(p.id, null);
                  }}
                >
                  <label>
                    Someone new
                    <input
                      data-testid="tag-new-name"
                      value={name}
                      autoComplete="off"
                      enterKeyHint="done"
                      placeholder="Their name"
                      onChange={(e) => setName(e.target.value)}
                    />
                  </label>
                  <button
                    type="submit"
                    className="wide-btn"
                    data-testid="tag-new-save"
                    disabled={busy || !name.trim()}
                  >
                    Name as a new player
                  </button>
                </form>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      {nShort ? (
        <button
          type="button"
          className="secondary wide-btn"
          data-testid="tag-short-toggle"
          aria-expanded={showShort}
          onClick={() => setShowShort((s) => !s)}
        >
          {showShort
            ? "Hide the brief ones"
            : `${nShort} more seen only briefly (under ${MIN_SEEN_S} s)`}
        </button>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------- Review

function ReviewJob({ api, game, moments, fail, tv, sawTv }: JobProps) {
  const {
    data: queue,
    error,
    reload,
  } = useAsync(() => api.getReviewQueue(game.id), [api, game.id]);
  const [typing, setTyping] = useState<{ q: string; opt: ReviewOption } | null>(
    null,
  );
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  // "Watch it": on the TV when a TV is showing this game, else here on the card
  const [watch, setWatch] = useState<{
    q: string;
    t0: number;
    t1: number;
    onTv: boolean | null; // null: still asking
  } | null>(null);
  const name = (pid: string) =>
    game.players.find((p) => p.id === pid)?.name ?? `Player ${trackNo(pid)}`;
  const watchIt = (q: ReviewQuestion, t: number) => {
    const w = {
      q: q.id,
      t0: Math.max(0, t - WATCH_LEAD_S),
      t1: t + WATCH_TAIL_S,
    };
    setWatch({ ...w, onTv: null });
    const seen = (onTv: boolean) => {
      setWatch({ ...w, onTv });
      sawTv(onTv);
    };
    api.playOnTv(game.id, w.t0).then(
      seen,
      () => seen(false), // no TV to reach: play it here
    );
  };
  // The API's prompt names unnamed tracks by id ("Who is #p2?"): the same words as
  // everywhere else instead ("Who is Player 2?", or their name).
  const prompt = (q: ReviewQuestion) =>
    q.prompt.replace(/#(p\d+)\b/g, (_, pid: string) => name(pid));

  const answer = (opt: ReviewOption, value?: string) => {
    setBusy(true);
    setNote("");
    api
      .answerReview(opt, value)
      .then(
        () => {
          setTyping(null);
          setText("");
          setNote(`Saved: ${value ?? opt.label}.`);
          reload();
        },
        (e) => setNote(`Not saved: ${fail(e)}`),
      )
      .finally(() => setBusy(false));
  };

  if (error)
    return (
      <p className="error">Could not load the review queue: {error.message}</p>
    );
  if (!queue) return <p>Loading…</p>;
  const thumbOf = (q: ReviewQuestion) =>
    (q.event_id ? moments.find((m) => m.id === q.event_id) : undefined) ??
    (q.kind === "identity"
      ? moments.find((m) => m.player?.id === q.player_id && m.thumb_url)
      : undefined);

  return (
    <>
      {note ? (
        <p role="status" data-testid="review-note">
          {note}
        </p>
      ) : null}
      {queue.length === 0 ? (
        <p data-testid="review-empty">Nothing left to review.</p>
      ) : (
        <p className="dim">
          {queue.length} to check. Replay was not sure about these.
        </p>
      )}
      <ul className="phone-cards">
        {queue.map((q) => {
          const m = thumbOf(q);
          return (
            <li
              key={q.id}
              className="phone-card"
              data-testid="review-card"
              data-kind={q.kind}
            >
              {m?.thumb_url ? (
                <img className="card-thumb" src={m.thumb_url} alt="" />
              ) : null}
              <p className="card-prompt">{prompt(q)}</p>
              <p className="dim">
                {[
                  q.t != null ? fmtClock(q.t) : null,
                  m && q.kind !== "identity" ? m.label : null,
                  q.player_id && q.kind !== "identity" && !m
                    ? name(q.player_id)
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <div className="card-actions">
                {q.options.map((opt) => (
                  <button
                    key={opt.label}
                    type="button"
                    className="secondary"
                    data-testid={optionTestId(opt.label)}
                    disabled={busy}
                    onClick={() =>
                      opt.text_field ? setTyping({ q: q.id, opt }) : answer(opt)
                    }
                  >
                    {opt.label}
                  </button>
                ))}
                {q.t != null && q.kind !== "identity" ? (
                  <button
                    type="button"
                    className="secondary"
                    data-testid="review-watch"
                    disabled={watch?.q === q.id && watch.onTv === null}
                    onClick={() => watchIt(q, q.t as number)}
                  >
                    {tv ? "Watch on TV" : "Watch here"}
                  </button>
                ) : null}
              </div>
              {watch?.q === q.id && watch.onTv === true ? (
                <p
                  className="dim"
                  role="status"
                  data-testid="review-watch-note"
                >
                  Playing on the TV
                </p>
              ) : null}
              {watch?.q === q.id && watch.onTv === false ? (
                <>
                  <WindowVideo
                    src={api.mediaUrl(game, game.renditions.wide)}
                    win={{ t_start: watch.t0, t_end: watch.t1 }}
                    at={watch.t0}
                    autoPlay
                    testId="review-watch-video"
                  />
                  <p
                    className="dim"
                    role="status"
                    data-testid="review-watch-note"
                  >
                    No TV is showing this game, so it plays here.
                  </p>
                </>
              ) : null}
              {typing?.q === q.id ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (text.trim()) answer(typing.opt, text.trim());
                  }}
                >
                  <label>
                    Name
                    <input
                      data-testid="review-text"
                      value={text}
                      autoFocus
                      autoComplete="off"
                      enterKeyHint="done"
                      onChange={(e) => setText(e.target.value)}
                    />
                  </label>
                  <button
                    type="submit"
                    className="wide-btn"
                    data-testid="review-text-save"
                    disabled={busy || !text.trim()}
                  >
                    Save
                  </button>
                </form>
              ) : null}
            </li>
          );
        })}
      </ul>
    </>
  );
}

// ---------------------------------------------------------------- Search

function SearchJob({ api, game, fail, sawTv }: JobProps) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState("");
  const [hit, setHit] = useState<SearchHit | null>(null);
  const [tvNote, setTvNote] = useState("");
  const chips = useMemo(() => highlightQueries(game), [game]);

  const run = (raw: string) => {
    const q = raw.trim();
    if (!q || busy) return;
    setText(q);
    setBusy(true);
    setFailed("");
    setHit(null);
    api
      .search(game.id, q)
      .then(setResult, (e) => {
        setResult(null);
        setFailed(fail(e));
      })
      .finally(() => setBusy(false));
  };

  return (
    <>
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          run(text);
        }}
      >
        <label>
          Search this game
          <input
            data-testid="phone-search-input"
            value={text}
            autoComplete="off"
            enterKeyHint="search"
            placeholder="Marcus threes"
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        <button
          type="submit"
          className="wide-btn"
          data-testid="phone-search-go"
          disabled={busy || !text.trim()}
        >
          {busy ? "Searching…" : "Search"}
        </button>
      </form>
      <div className="phone-chips">
        {chips.map((c) => (
          <button
            key={c}
            type="button"
            className="secondary"
            data-testid="phone-search-chip"
            disabled={busy}
            onClick={() => run(c)}
          >
            {c}
          </button>
        ))}
      </div>
      {failed ? (
        <p className="error" role="alert" data-testid="phone-search-error">
          Search failed: {failed}
        </p>
      ) : null}
      {result ? (
        <p
          className="dim"
          data-testid="phone-search-interpretation"
          data-fallback={result.fallback ? "true" : "false"}
        >
          {result.interpretation}
          {result.fallback ? " · keyword match" : ""}
        </p>
      ) : null}
      {hit ? (
        <>
          <WindowVideo
            src={api.mediaUrl(game, game.renditions.wide)}
            win={hit}
            at={hit.t_start}
            autoPlay
            testId="phone-search-preview"
          />
          <button
            type="button"
            className="wide-btn"
            data-testid="phone-search-tv"
            disabled={tvNote === "Sending…"}
            onClick={() => {
              setTvNote("Sending…");
              api.playOnTv(game.id, hit.t_start).then(
                (onTv) => {
                  sawTv(onTv);
                  setTvNote(
                    onTv
                      ? "Playing on the TV"
                      : "No TV is showing this game, so it plays here.",
                  );
                },
                (e) => setTvNote(`Could not reach the TV: ${fail(e)}`),
              );
            }}
          >
            Play on TV
          </button>
          {tvNote ? (
            <p className="dim" role="status" data-testid="phone-search-tv-note">
              {tvNote}
            </p>
          ) : null}
        </>
      ) : null}
      {result && result.results.length === 0 ? (
        <p data-testid="phone-search-empty">Nothing in this game matches.</p>
      ) : null}
      <ul className="phone-list">
        {result?.results.map((h, i) => (
          <li key={`${h.play_id}-${i}`}>
            <button
              type="button"
              className={`row-btn${hit === h ? " on" : ""}`}
              aria-pressed={hit === h}
              data-testid="phone-search-hit"
              data-t-start={h.t_start}
              onClick={() => {
                setHit(h);
                setTvNote("");
              }}
            >
              <span className="hit-time">{fmtClock(h.t_start)}</span>
              <span className="row-text">{h.text}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
