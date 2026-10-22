// Small pure helpers both TV clients render with. Profile-driven, never sport-driven
// (§4.8: read sport_ui, do not branch on the sport name).
import type {
  BoxScoreRow,
  CourtTemplate,
  Game,
  GameEvent,
  GameSummary,
  Player,
  Stats,
} from "./types";

/** Ids on screen for less than this are tracker fragments: lists keep them out of the way. */
export const MIN_SEEN_S = 5;
/** A fragment, by `seen_s`; an older game without it lists everyone. Named or linked
 *  players always count, whoever they are. */
export const isShortTrack = (p: Player) =>
  p.seen_s !== undefined && p.seen_s < MIN_SEEN_S && !p.name && !p.profile_id;

export function fmtDuration(s?: number | null) {
  if (!s && s !== 0) return "—";
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

export function fmtDate(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}

/** The name label sits on the team colour, which ranges from navy to near-white, so the
 *  text colour is picked from the swatch's luminance rather than assumed. */
export function inkOn(hex: string): string {
  const h = hex.replace("#", "");
  if (h.length < 6) return "#000";
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 ? "#0b0d10" : "#ffffff";
}

/** A half court's origin is the baseline centre, so x runs -7.5..7.5: the viewBox has
 *  to start at the court's real minimum, not 0. */
export function courtViewBox(
  court: CourtTemplate | undefined,
  w: number,
  h: number,
) {
  const x = court?.x_range?.[0] ?? 0;
  const y = court?.y_range?.[0] ?? 0;
  return { x, y, attr: `${x} ${y} ${w} ${h}` };
}

/** Library card status: "ready", the running stage ("tracking…"), or the game status. */
export function statusText(g: GameSummary): string {
  if (g.status === "ready") return "ready";
  const running = Object.entries(g.stages ?? {}).find(
    ([, v]) => v === "running",
  );
  return running ? `${running[0]}ing…` : g.status;
}

export const FALLBACK_CHIPS = ["All shots", "Makes", "Top plays"];

/** H1 + H3: per-player reels first, then the profile's chips (or a generic set). */
export function highlightQueries(game: Game | null | undefined): string[] {
  const chips = game?.sport_ui?.chips?.length
    ? game.sport_ui.chips
    : FALLBACK_CHIPS;
  const perPlayer = (game?.players ?? [])
    .filter((p) => p.name)
    .map((p) => `${p.name} — all shots`);
  return [...perPlayer, ...chips];
}

/** W8: the next/previous event key time from `now`, or null at either end. */
export function eventJump(
  sorted: GameEvent[],
  now: number,
  dir: 1 | -1,
): number | null {
  const next =
    dir > 0
      ? sorted.find((e) => e.t_key > now + 0.05)
      : [...sorted].reverse().find((e) => e.t_key < now - 0.05);
  return next ? next.t_key : null;
}

/** R5: events below this confidence and unconfirmed land in the review queue (the queue
 *  itself now comes from GET /review/queue — D-48; the mock applies the same rule). */
export const REVIEW_CONFIDENCE_THRESHOLD = 0.6;

/** R3 box score columns: attempts and makes always, the rest only when the game's
 *  events support them (`Stats.available`) or the API sent them. */
export function boxColumns(
  stats: Stats | null | undefined,
): { label: string; value: (r: BoxScoreRow) => string }[] {
  const rows = stats?.box_score ?? [];
  const has = new Set(stats?.available ?? []);
  const n = (v?: number) => (v === undefined ? "—" : String(v));
  return [
    { label: "Att", value: (r) => n(r.attempts) },
    { label: "Made", value: (r) => n(r.makes) },
    ...(rows.some((r) => r.points !== undefined)
      ? [{ label: "Pts", value: (r: BoxScoreRow) => n(r.points) }]
      : []),
    ...(has.has("rebounds")
      ? [{ label: "Reb", value: (r: BoxScoreRow) => n(r.rebounds) }]
      : []),
    ...(has.has("steals")
      ? [{ label: "Stl", value: (r: BoxScoreRow) => n(r.steals) }]
      : []),
    ...(has.has("blocks")
      ? [{ label: "Blk", value: (r: BoxScoreRow) => n(r.blocks) }]
      : []),
    ...(rows.some((r) => r.distance_m !== undefined)
      ? [
          {
            label: "Dist m",
            value: (r: BoxScoreRow) =>
              r.distance_m === undefined ? "—" : r.distance_m.toFixed(0),
          },
        ]
      : []),
    {
      label: "Conf",
      value: (r) =>
        r.confidence === undefined ? "—" : r.confidence.toFixed(2),
    },
  ];
}

/** R3: every number on the review screen is labelled auto-detected (D-48), with the
 *  mean confidence of the events behind it when the API sends one. */
export function autoDetectedLabel(stats: Stats | null | undefined): string {
  const c = stats?.confidence;
  return typeof c === "number"
    ? `Auto-detected · mean confidence ${c.toFixed(2)}`
    : "All numbers below are auto-detected.";
}

const ALL_PANELS = ["shot_chart", "heatmap", "box_score"];

/** The review panels the profile lists (`sport_ui.review`); all of them when it is silent. */
export function reviewPanels(game: Game | null | undefined): Set<string> {
  const listed = game?.sport_ui?.review;
  const name = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_");
  return new Set(listed?.length ? listed.map(name) : ALL_PANELS);
}

export interface StatLine {
  cells: { label: string; value: string }[];
  /** stats this kind of game has but these events cannot tell ("assists", "digs") */
  missing: string[];
  note: string | null;
}

/**
 * The player card's line for one player in one game (D-83), counted from the game's own
 * events (events.json; dismissed ones left out, D-11). Which stats show follows the event
 * types the game has, never the sport's name (§4.8): shot events give Pts, FG, Reb, Stl,
 * Blk (Ast is never detected); rally events give Kills, Aces, Blk, Serves, Touches (Digs
 * are never detected). A stat whose events name nobody in this game goes to `missing`
 * rather than showing a 0. Pts and FG need a detected make somewhere in the game (else,
 * as on the Stats panel, the detector could not tell makes: Shots instead). Kills and
 * aces need rallies with a known winner and credited contacts: the rally's last contact
 * is this player's and their side won it; an ace when that contact was the only one (the
 * serve), a kill otherwise. A volleyball/pickleball/badminton block counts like a shot
 * block (type "block").
 */
export function statLine(events: GameEvent[], pid: string): StatLine {
  const evs = events.filter((e) => !e.dismissed);
  const of = (type: GameEvent["type"]) => evs.filter((e) => e.type === type);
  const cells: StatLine["cells"] = [];
  const missing: string[] = [];
  let note: string | null = null;
  /** a count when the game's events of this kind credit anyone, else "not detected" */
  const count = (label: string, list: GameEvent[], what: string) => {
    if (list.some((e) => e.player_id))
      cells.push({
        label,
        value: String(list.filter((e) => e.player_id === pid).length),
      });
    else missing.push(what);
  };
  const shots = of("shot");
  const rallies = of("rally");

  if (shots.length) {
    const mine = shots.filter((e) => e.player_id === pid);
    const makes = mine.filter((e) => e.made === true);
    const unknown = mine.filter((e) => e.made == null).length;
    if (shots.some((e) => e.made === true)) {
      const pts = makes.reduce((s, e) => s + (e.points ?? 2), 0); // stats.py: no value = 2
      cells.push({ label: "Pts", value: String(pts) });
      cells.push({ label: "FG", value: `${makes.length}/${mine.length}` });
      if (unknown)
        note = `${unknown} of ${mine.length} shots with the result not detected`;
    } else {
      cells.push({ label: "Shots", value: String(mine.length) });
      missing.push("points");
      if (mine.length) note = "Made or missed is not detected in this game";
    }
    count(
      "Reb",
      evs.filter((e) => e.cause === "defensive_rebound"),
      "rebounds",
    );
    missing.push("assists");
    count(
      "Stl",
      evs.filter((e) => e.type === "possession_change" && e.cause === "steal"),
      "steals",
    );
  }
  if (rallies.length) {
    const contacts = of("contact").sort((a, b) => a.t_key - b.t_key);
    const decided = rallies.filter((r) => r.winner_side != null);
    if (decided.length && contacts.some((c) => c.player_id)) {
      let kills = 0;
      let aces = 0;
      for (const r of decided) {
        const hits = contacts.filter(
          (c) => c.t_key >= r.t_start && c.t_key <= r.t_end,
        );
        const last = hits[hits.length - 1];
        if (last?.player_id !== pid || last.team !== r.winner_side) continue;
        if (hits.length === 1) aces++;
        else kills++;
      }
      cells.push({ label: "Kills", value: String(kills) });
      cells.push({ label: "Aces", value: String(aces) });
    } else missing.push("kills", "aces");
  }
  if (shots.length || rallies.length) count("Blk", of("block"), "blocks");
  if (rallies.length) {
    count("Serves", of("serve"), "serves");
    count("Touches", of("contact"), "touches");
    missing.push("digs");
  }
  return { cells, missing, note };
}
