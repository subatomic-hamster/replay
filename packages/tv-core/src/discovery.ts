// M13 integration wave: the API contracts of the M5/M6/M7/M11 routes the TV clients now
// use, plus the pure helpers both clients render with (apps/web /tv and apps/tv). Shapes
// follow services/api (plays_routes, discovery_routes, narrate/routes, stats.py) and the
// contracts in docs/decisions.md D-45..D-52. Never branches on the sport.

// ---------------------------------------------------------------- renditions (M6)

/** GET /games/{id}/renditions → `renditions[]`. */
export interface Rendition {
  id: string;
  kind: "wide" | "follow" | "broadcast";
  url: string;
  player_id?: string;
  cuts_url?: string | null;
}

/** The directed broadcast rendition, or null (no rendition → Watch stays on wide). */
export const broadcastOf = (
  rs: Rendition[] | null | undefined,
): Rendition | null => rs?.find((r) => r.kind === "broadcast") ?? null;

// ---------------------------------------------------------------- commentary (M7)

export interface CommentaryLine {
  /** Game time of the event the line describes. */
  t: number;
  text: string;
  event_ids?: string[];
  /** When the narration actually speaks it (worker stage) and for how long. */
  audio_t?: number;
  audio_s?: number;
}

export interface Commentary {
  schema?: string;
  plays: { play_id: string; source?: string; lines: CommentaryLine[] }[];
  /** game-clock narration WAV, when the worker's `commentary` stage ran */
  narration_url?: string | null;
  stored?: boolean;
}

/** A caption without measured audio stays up this long. */
export const CAPTION_S = 3;

/** Every line of the game, in time order. */
export const commentaryLines = (
  c: Commentary | null | undefined,
): CommentaryLine[] =>
  (c?.plays ?? []).flatMap((p) => p.lines).sort((a, b) => a.t - b.t);

/** The line being spoken at media time `t` (latest start wins), or null. */
export function captionAt(
  lines: CommentaryLine[],
  t: number,
): CommentaryLine | null {
  let hit: CommentaryLine | null = null;
  for (const ln of lines) {
    const t0 = ln.audio_t ?? ln.t;
    if (t0 > t) break;
    if (t < t0 + (ln.audio_s ?? CAPTION_S)) hit = ln;
  }
  return hit;
}

// ---------------------------------------------------------------- "Replay, clip that" (M5)

export type TriggerType = "gesture" | "voice" | "tap";

export interface Trigger {
  id: string;
  type: TriggerType;
  t: number;
  by_player_id?: string | null;
  subject_player_id?: string | null;
  transcript?: string | null;
  confidence: number;
  source: "auto" | "user";
  play_id?: string | null;
  clip_id?: string | null;
}

/** `replay.clips.v1` — named PlayClip: `Clip` is the older query-reel item. */
export interface PlayClip {
  id: string;
  play_id: string;
  trigger_id: string;
  t_start: number;
  t_end: number;
  attribution: {
    owner_player_id?: string | null;
    by_player_id?: string | null;
    subject_player_id?: string | null;
  };
  participants: string[];
  source: "auto" | "user";
  /** Newer APIs: a person changed the window. Older ones only had `source`. */
  edited?: boolean;
}

/** Whether a person trimmed this clip: the API's `edited` (absent on older clips = false).
 *  `source` cannot tell it: a phone-tap clip is user-sourced from birth. */
export const clipEdited = (c: PlayClip): boolean => c.edited === true;

/** POST /games/{id}/triggers → the tap and the clip it cut (null: no play just ended). */
export interface TapResult {
  trigger: Trigger;
  clip: PlayClip | null;
}

/** How a clip was marked, in plain words (the same as apps/tv's Clips screen). */
const TRIGGER_LABEL: Record<TriggerType, string> = {
  gesture: "Marked with a gesture",
  voice: "Marked by voice",
  tap: "Marked on your phone",
};
export const triggerLabel = (t: TriggerType | undefined): string =>
  (t && TRIGGER_LABEL[t]) ?? "Clip";

/** "by Marcus · about Jordan", from the clip's attribution and the current roster. */
export function attributionText(
  clip: PlayClip,
  name: (pid: string) => string,
): string {
  const a = clip.attribution ?? {};
  const parts: string[] = [];
  if (a.by_player_id) parts.push(`by ${name(a.by_player_id)}`);
  if (a.subject_player_id && a.subject_player_id !== a.by_player_id) {
    parts.push(`of ${name(a.subject_player_id)}`);
  }
  return parts.join(" · ") || "unattributed";
}

/** First index of a `size`-row window that keeps `index` visible (a 1080p list scrolls
 *  by moving this window, not by native scrolling — focus is app state). */
export const listWindow = (
  index: number,
  count: number,
  size: number,
): number => Math.max(0, Math.min(index - Math.floor(size / 2), count - size));

/** m:ss.s — trim handles move in half seconds, so whole seconds are not enough. */
export function fmtClock(s: number): string {
  const v = Math.round(Math.max(0, s) * 10) / 10; // round first: 59.96 is 1:00.0
  const m = Math.floor(v / 60);
  return `${m}:${(v - m * 60).toFixed(1).padStart(4, "0")}`;
}

/** D-pad trim step and the shortest clip the trim UI allows. */
export const TRIM_STEP_S = 0.5;
export const MIN_CLIP_S = 1;

/** Nudge one edge of a [t_start, t_end] window, clamped to [0, duration] and MIN_CLIP_S. */
export function nudgeTrim(
  win: { t_start: number; t_end: number },
  edge: "start" | "end",
  delta: number,
  duration: number,
): { t_start: number; t_end: number } {
  const r = (v: number) => Math.round(v * 1000) / 1000;
  const end = duration > 0 ? duration : Number.MAX_SAFE_INTEGER;
  if (edge === "start") {
    return {
      t_start: r(
        Math.min(Math.max(0, win.t_start + delta), win.t_end - MIN_CLIP_S),
      ),
      t_end: win.t_end,
    };
  }
  return {
    t_start: win.t_start,
    t_end: r(
      Math.max(Math.min(end, win.t_end + delta), win.t_start + MIN_CLIP_S),
    ),
  };
}

/** A moment's window shorter than this is too short to share as a clip (a steal or a
 *  rebound is 0.5 s): it starts CLIP_LEAD_S before the key time and ends CLIP_TAIL_S after. */
export const SHORT_MOMENT_S = 3;
export const CLIP_LEAD_S = 5;
export const CLIP_TAIL_S = 2;

/** The clip a moment starts as: its own window, or the build-up and the finish around its
 *  key time when that window is too short; within [0, duration]. */
export function momentClip(
  m: { t: number; t_start: number; t_end: number },
  duration: number,
): { t_start: number; t_end: number } {
  if (m.t_end - m.t_start >= SHORT_MOMENT_S)
    return { t_start: m.t_start, t_end: m.t_end };
  const r = (v: number) => Math.round(v * 10) / 10;
  return {
    t_start: r(Math.max(0, Math.min(m.t_start, m.t - CLIP_LEAD_S))),
    t_end: r(
      Math.min(duration || Infinity, Math.max(m.t_end, m.t + CLIP_TAIL_S)),
    ),
  };
}

// ---------------------------------------------------------------- hype (D-45)

export interface HypeCandidate {
  t: number;
  score: number;
  t_start?: number;
  t_end?: number;
  play_id?: string | null;
  reasons?: string[];
}

/** GET /games/{id}/hype (`replay.hype.v1`): 2 Hz series + highlight candidates. */
export interface Hype {
  schema?: string;
  rate_hz: number;
  duration_s?: number;
  values: number[];
  candidates: HypeCandidate[];
}

// ---------------------------------------------------------------- best play

/** GET /games/{id}/best-play: the game's one best play. `source` says who chose it: the
 *  user ("Make this the best play" on the phone), the last make in the final 30 s (the
 *  game winner), or the top hype play. `what` is its moment's own label when it is one. */
export interface BestPlay {
  t: number;
  t_start: number;
  t_end: number;
  source: "user" | "auto:last_make" | "auto:hype";
  label: string;
  sub_label: string | null;
  moment_id: string | null;
  what: string | null;
}

export interface BestPlayPick {
  t_start: number;
  t_end: number;
  t: number;
  moment_id?: string | null;
}

/** The Highlights reel ends on the best play: `segs` (in time order) as they are, except
 *  that a play overlapping the best one joins it (no second plays twice), and the best
 *  play comes last. */
export function endOnBest(
  segs: { t_start: number; t_end: number }[],
  best: BestPlay | null | undefined,
): { t_start: number; t_end: number; best?: true }[] {
  if (!best) return segs;
  const over = (s: { t_start: number; t_end: number }) =>
    s.t_end > best.t_start && s.t_start < best.t_end;
  const joined = segs.filter(over);
  return [
    ...segs.filter((s) => !over(s)),
    {
      t_start: Math.min(best.t_start, ...joined.map((s) => s.t_start)),
      t_end: Math.max(best.t_end, ...joined.map((s) => s.t_end)),
      best: true,
    },
  ];
}

/** Max-pool the series into `n` bars for the scrubber (a peak must never vanish). */
export function hypeBars(values: number[], n: number): number[] {
  if (!values.length || n <= 0) return [];
  return Array.from({ length: n }, (_, i) => {
    const a = Math.floor((i * values.length) / n);
    const b = Math.max(a + 1, Math.floor(((i + 1) * values.length) / n));
    return Math.max(...values.slice(a, b));
  });
}

/** Jumping to a peak lands this long before it, so the build-up is on screen. */
export const PEAK_LEAD_S = 3;

/** Where "Hype peak" seeks from `now`: the next candidate's lead-in, wrapping to the
 *  first; null when the game has no candidates. */
export function nextPeak(cands: HypeCandidate[], now: number): number | null {
  const targets = cands
    .map((c) => Math.max(0, c.t - PEAK_LEAD_S))
    .sort((a, b) => a - b);
  if (!targets.length) return null;
  // the 0.25 s margin: pressing again right after a jump moves on to the next peak
  return targets.find((t) => t > now + 0.25) ?? targets[0];
}

// ---------------------------------------------------------------- rallies (D-46)

export interface Rally {
  id: string;
  n: number;
  event_id: string;
  play_id?: string | null;
  t_start: number;
  t_end: number;
  duration_s: number;
  /** 0 = unknown */
  shots: number;
  confidence?: number;
  /** offset of this rally's segment in the condensed video, once rendered */
  condensed_t?: number | null;
}

export interface JobStatus {
  /** "missing": it was done but the file is gone; the UI offers to render again, as "none" */
  status:
    "none" | "missing" | "queued" | "running" | "done" | "failed" | "error";
  url: string | null;
  job_id?: string | null;
  error?: string | null;
}

/** GET /games/{id}/rallies (`replay.rallies.v1` + the condensed rendition's status). */
export interface RallyDoc {
  n: number;
  game_s?: number;
  rally_s?: number;
  longest: string[];
  most_shots?: string[];
  rallies: Rally[];
  condensed: JobStatus;
}

/** Rallies in game order, or longest first (the doc's own ranking, then the rest). */
export function rallyOrder(doc: RallyDoc, by: "time" | "longest"): Rally[] {
  const byTime = [...doc.rallies].sort((a, b) => a.t_start - b.t_start);
  if (by === "time") return byTime;
  const rank = new Map(doc.longest.map((id, i) => [id, i]));
  return [...byTime].sort(
    (a, b) =>
      (rank.get(a.id) ?? 1e9) - (rank.get(b.id) ?? 1e9) ||
      b.duration_s - a.duration_s,
  );
}

/** The rally on screen at condensed-video time `t` (for the "RALLY n / N" counter). */
export function rallyAtCondensed(rallies: Rally[], t: number): Rally | null {
  let hit: Rally | null = null;
  for (const r of rallies) {
    if (
      r.condensed_t != null &&
      r.condensed_t <= t + 0.05 &&
      (!hit || r.condensed_t >= (hit.condensed_t ?? 0))
    ) {
      hit = r;
    }
  }
  return hit;
}

// ---------------------------------------------------------------- vertical export (D-47)

export interface VerticalRequest {
  clip_id?: string;
  play_id?: string;
  event_id?: string;
  t_start?: number;
  t_end?: number;
  player_id?: string;
}

export interface VerticalExport extends JobStatus {
  id: string;
  t_start: number;
  t_end: number;
  player_id?: string | null;
  caption?: string;
  size?: [number, number];
}

/** POST/GET /games/{id}/exports/reel: the game's highlight reel (the user's clips, then
 *  the top plays, ≤ 90 s) as one MP4. The id hashes the aspect and the plan's inputs. */
export interface ReelExport extends JobStatus {
  id: string;
  aspect: "16:9" | "9:16";
  duration_s?: number | null;
}

/** Still rendering: poll again. */
export const exportPending = (
  e: { status: string } | null | undefined,
): boolean => !!e && (e.status === "queued" || e.status === "running");

// ---------------------------------------------------------------- review queue (D-48)

export interface ReviewOption {
  label: string;
  method: string;
  path: string;
  body: Record<string, unknown>;
  /** The client fills body[text_field] from the on-screen keyboard. */
  text_field?: string;
}

/** GET /games/{id}/review/queue → `questions[]`. */
export interface ReviewQuestion {
  id: string;
  kind: "shot_outcome" | "low_confidence" | "identity";
  prompt: string;
  t?: number | null;
  event_id?: string;
  player_id?: string | null;
  confidence?: number;
  options: ReviewOption[];
}

export const optionTestId = (label: string) =>
  `review-action-${label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")}`;

// ---------------------------------------------------------------- search + advice (M7)

export interface SearchHit {
  play_id: string;
  t_start: number;
  t_end: number;
  text: string;
  filter_match?: boolean;
  score?: number;
}

/** POST /games/{id}/search; `fallback` is set by the client when it had to use the
 *  keyword route instead (no embeddings yet). */
export interface SearchResult {
  query: string;
  interpretation: string;
  filter_source?: string;
  results: SearchHit[];
  fallback?: boolean;
}

/** GET /games/{id}/players/{pid}/advice (`replay.advice.v1`). */
export interface Advice {
  player_id: string;
  name?: string | null;
  lines: string[];
  source: string;
  auto_detected?: boolean;
}
