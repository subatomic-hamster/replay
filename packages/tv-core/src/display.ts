// Small pure helpers both TV clients render with. Profile-driven, never sport-driven
// (§4.8: read sport_ui, do not branch on the sport name).
import type { BoxScoreRow, CourtTemplate, Game, GameEvent, GameSummary, Stats } from "./types";

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
export function courtViewBox(court: CourtTemplate | undefined, w: number, h: number) {
  const x = court?.x_range?.[0] ?? 0;
  const y = court?.y_range?.[0] ?? 0;
  return { x, y, attr: `${x} ${y} ${w} ${h}` };
}

/** Library card status: "ready", the running stage ("tracking…"), or the game status. */
export function statusText(g: GameSummary): string {
  if (g.status === "ready") return "ready";
  const running = Object.entries(g.stages ?? {}).find(([, v]) => v === "running");
  return running ? `${running[0]}ing…` : g.status;
}

export const FALLBACK_CHIPS = ["All shots", "Makes", "Top plays"];

/** H1 + H3: per-player reels first, then the profile's chips (or a generic set). */
export function highlightQueries(game: Game | null | undefined): string[] {
  const chips = game?.sport_ui?.chips?.length ? game.sport_ui.chips : FALLBACK_CHIPS;
  const perPlayer = (game?.players ?? []).filter((p) => p.name).map((p) => `${p.name} — all shots`);
  return [...perPlayer, ...chips];
}

/** W8: the next/previous event key time from `now`, or null at either end. */
export function eventJump(sorted: GameEvent[], now: number, dir: 1 | -1): number | null {
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
export function boxColumns(stats: Stats | null | undefined): { label: string; value: (r: BoxScoreRow) => string }[] {
  const rows = stats?.box_score ?? [];
  const has = new Set(stats?.available ?? []);
  const n = (v?: number) => (v === undefined ? "—" : String(v));
  return [
    { label: "Att", value: (r) => n(r.attempts) },
    { label: "Made", value: (r) => n(r.makes) },
    ...(rows.some((r) => r.points !== undefined) ? [{ label: "Pts", value: (r: BoxScoreRow) => n(r.points) }] : []),
    ...(has.has("rebounds") ? [{ label: "Reb", value: (r: BoxScoreRow) => n(r.rebounds) }] : []),
    ...(has.has("steals") ? [{ label: "Stl", value: (r: BoxScoreRow) => n(r.steals) }] : []),
    ...(has.has("blocks") ? [{ label: "Blk", value: (r: BoxScoreRow) => n(r.blocks) }] : []),
    ...(rows.some((r) => r.distance_m !== undefined)
      ? [{ label: "Dist m", value: (r: BoxScoreRow) => (r.distance_m === undefined ? "—" : r.distance_m.toFixed(0)) }]
      : []),
    { label: "Conf", value: (r) => (r.confidence === undefined ? "—" : r.confidence.toFixed(2)) },
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
