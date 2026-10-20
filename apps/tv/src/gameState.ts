// What a game can do right now, in plain words, for Home and Add game. Reads the optional
// readiness fields the API is gaining (D-80 follow-up: watchable, eta_s, features,
// stage_label, hero_url) and falls back to today's status/stages when they are absent.
import { statusText } from "../../../packages/tv-core/src/display";
import type { GameSummary } from "../../../packages/tv-core/src/types";

export interface Feature {
  state: "ready" | "pending" | "unavailable";
  eta_s?: number;
}

/** GameSummary plus the optional fields not yet declared in packages/tv-core. */
export type GameLike = GameSummary & {
  /** the best-moment frame; else thumb_url (the first frame) */
  hero_url?: string | null;
  /** playable before processing ends; else status === "ready" */
  watchable?: boolean;
  /** remaining processing seconds */
  eta_s?: number;
  features?: Record<string, Feature>;
  /** plain words for the running stage */
  stage_label?: string;
};

export const watchable = (g: GameLike) => g.watchable ?? g.status === "ready";

/** A way to watch ("highlights", "condensed") that opens now. Without `features` the
 *  answer is `fallback` for a ready game. */
export function hasFeature(
  g: GameLike,
  key: string,
  fallback: boolean,
): boolean {
  const f = g.features?.[key];
  return f ? f.state === "ready" : fallback && g.status === "ready";
}

/** 0..1 across all stages: done ones plus the running one's fraction. */
export function progressOf(g: GameLike): number {
  const stages = Object.entries(g.stages ?? {});
  if (!stages.length) return 0;
  const done = stages.filter(([, s]) => s === "done").length;
  const running = stages.find(([, s]) => s === "running")?.[0];
  const frac = running ? (g.progress?.[running] ?? 0) : 0;
  return (done + frac) / stages.length;
}

// courtcam's stage names (S-08) in words a parent understands. An unknown stage falls back
// to statusText ("tracking…" → "Tracking").
const STAGE_WORDS: Record<string, string> = {
  ingest: "Getting the video ready",
  calibrate: "Finding the court",
  detect: "Finding players",
  track: "Following players",
  court: "Mapping the court",
  identity: "Telling players apart",
  tracks: "Following players",
  crops: "Framing each player",
  events: "Finding the big moments",
};

const STATUS_WORDS: Record<string, string> = {
  created: "Waiting for the upload",
  uploading: "Uploading",
  uploaded: "Uploaded",
  calibrated: "Ready to process",
  processing: "Processing",
  error: "Processing failed",
};

const sentence = (s: string) => {
  const t = s.replace(/…$/, "");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

/** "about 6 min" / "under a minute" / "" */
export function etaText(s?: number): string {
  if (s === undefined || s === null || !Number.isFinite(s)) return "";
  return s < 60 ? "under a minute" : `about ${Math.round(s / 60)} min`;
}

/** "Finding players, about 6 min"; without an estimate, the percentage instead. */
export function stageWords(g: GameLike): string {
  const running = Object.entries(g.stages ?? {}).find(
    ([, s]) => s === "running",
  )?.[0];
  const words =
    g.stage_label ??
    (running
      ? (STAGE_WORDS[running] ?? sentence(statusText(g)))
      : (STATUS_WORDS[g.status] ?? sentence(statusText(g))));
  const eta = etaText(g.eta_s);
  if (eta) return `${words}, ${eta}`;
  return g.status === "processing"
    ? `${words}, ${Math.round(progressOf(g) * 100)}%`
    : words;
}

/** "Sep 29" */
export function shortDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** "41 min" (at least 1) */
export const minutes = (s?: number | null) =>
  s ? `${Math.max(1, Math.round(s / 60))} min` : "";
