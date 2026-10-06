// Small pure helpers both TV clients render with. Profile-driven, never sport-driven
// (§4.8: read sport_ui, do not branch on the sport name).
import type { CourtTemplate, Game, GameEvent, GameSummary } from "./types";

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

/** R5: events below this confidence and unconfirmed land in the review queue. */
export const REVIEW_CONFIDENCE_THRESHOLD = 0.6;

// `source: "user"` is set by the API on any field the user changed (§4.5) — the client
// does not get to claim provenance.
export const REVIEW_ACTIONS: { label: string; patch: Partial<GameEvent> }[] = [
  { label: "Made", patch: { made: true, confirmed: true } },
  { label: "Missed", patch: { made: false, confirmed: true } },
  // D-11 "not a shot": v1 has no delete, so the event is flagged dismissed and drops
  // out of query and stats while staying in events.json.
  { label: "Not a shot", patch: { dismissed: true, confirmed: true } },
];

const ALL_PANELS = ["shot_chart", "heatmap", "box_score"];

/** The review panels the profile lists (`sport_ui.review`); all of them when it is silent. */
export function reviewPanels(game: Game | null | undefined): Set<string> {
  const listed = game?.sport_ui?.review;
  const name = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_");
  return new Set(listed?.length ? listed.map(name) : ALL_PANELS);
}
