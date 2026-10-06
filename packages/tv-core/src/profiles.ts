// M10 player profiles on the clients (apps/web /tv + phone companion, apps/tv): the
// shapes services/api/replay_api/profiles/routes.py answers with (D-58) and the pure
// helpers both TV builds render with. Never branches on the sport: the stat rows are
// whatever keys the career stats carry.

export interface ProfileLink {
  game_id: string;
  player_id: string;
  /** GET /profiles/{id} `missing_links`: the game was deleted or the player merged away */
  missing?: "game" | "player";
}

/** One sport of `stats_by_sport`: `stats` is what to show (user values win), `auto` the
 *  pipeline's sums, `edited` the keys a user corrected. */
export interface SportStats {
  stats: Record<string, number>;
  auto: Record<string, number>;
  edited: string[];
  games?: ({ game_id: string; player_id: string } & Record<string, unknown>)[];
  label?: string;
}

export interface Profile {
  schema?: string;
  profile_id: string;
  name: string;
  photo_url: string | null;
  /** null = derived from the linked games */
  sports: string[] | null;
  positions: string[];
  user_edited_fields: string[];
  face_enrolled: boolean;
  voice_enrolled?: boolean;
  linked: ProfileLink[];
  /** GET /profiles/{id} only; the list route leaves the stats out */
  stats_by_sport?: Record<string, SportStats>;
  missing_links?: ProfileLink[];
}

export interface ProfileInput {
  name?: string;
  photo_url?: string | null;
  sports?: string[] | null;
  positions?: string[];
  /** {sport: {stat: value}}; null drops a correction (the auto value shows again) */
  stats?: Record<string, Record<string, number | null>>;
}

export type SuggestionReason =
  | { kind: "same_name" }
  | { kind: "face"; similarity: number; votes: number };

/** GET /profiles/{id}/suggestions: unlinked roster players that may be this person. */
export interface ProfileSuggestion {
  game_id: string;
  game_title?: string | null;
  player_id: string;
  reasons: SuggestionReason[];
}

export interface CardTile {
  key: string;
  label: string;
  value: number | string;
  edited: boolean;
}

/** GET/POST /profiles/{id}/reel → `items[]`: one play of the player, in game order. */
export interface ReelItem {
  game_id: string;
  player_id: string;
  play_id: string;
  sport?: string;
  t_start: number;
  t_end: number;
  t?: number;
  points?: number;
  hype?: number;
  event_ids?: string[];
  clip_ids?: string[];
  game_title?: string | null;
  /** the game's wide rendition (absolute), null when the game has none */
  url: string | null;
}

export interface CareerReel {
  schema?: string;
  profile_id: string;
  items: ReelItem[];
  duration_s: number;
}

/** `replay.card.v1` (GET / POST /profiles/{id}/card). */
export interface PlayerCard {
  schema?: string;
  profile_id: string;
  name: string;
  sport: string | null;
  sports: string[];
  positions: string[];
  games: number;
  title: string;
  title_source?: string;
  stats: CardTile[];
  user_edited: boolean;
  label: string;
  best_moment: Omit<ReelItem, "url" | "game_title"> | null;
  photo_url: string | null;
  face_enrolled: boolean;
  /** `/media/profiles/{id}/card.png`, there once `rendered` */
  png: string;
  thumb: string | null;
  rendered?: boolean;
}

const LABELS: Record<string, string> = {
  games: "Games",
  plays: "Plays",
  points: "Points",
  shots_made: "Shots made",
  shots_attempted: "Shots attempted",
  twos_made: "2-pt made",
  twos_attempted: "2-pt attempted",
  threes_made: "3-pt made",
  threes_attempted: "3-pt attempted",
  rebounds: "Rebounds",
  steals: "Steals",
  blocks: "Blocks",
  rallies: "Rallies",
  rallies_won: "Rallies won",
  contacts: "Contacts",
  serves: "Serves",
  distance_m: "Distance (m)",
};
const ORDER = Object.keys(LABELS);

export const statLabel = (key: string): string =>
  LABELS[key] ?? key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export interface StatRow {
  key: string;
  label: string;
  value: number;
  /** the pipeline's value (null for a stat only the user entered) */
  auto: number | null;
  edited: boolean;
  /** `games` counts links; it is not a stat a person corrects */
  editable: boolean;
}

/** Known stats in a fixed order, then any others alphabetically. */
export function statRows(s: SportStats | undefined): StatRow[] {
  if (!s) return [];
  const rank = (k: string) => (ORDER.includes(k) ? ORDER.indexOf(k) : ORDER.length);
  return Object.keys(s.stats)
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map((key) => ({
      key,
      label: statLabel(key),
      value: s.stats[key],
      auto: key in s.auto ? s.auto[key] : null,
      edited: s.edited.includes(key),
      editable: key !== "games",
    }));
}

/** One D-pad step of a stat: whole numbers, never below zero. */
export const stepStat = (value: number, dir: 1 | -1): number => Math.max(0, Math.round(value) + dir);

/** PATCH /profiles/{id} body for one stat; null restores the auto value. */
export const statPatch = (sport: string, key: string, value: number | null): ProfileInput => ({
  stats: { [sport]: { [key]: value } },
});

export const suggestionKey = (s: { game_id: string; player_id: string }) => `${s.game_id}/${s.player_id}`;

/** What the TV may show: face reasons only for a face-enrolled profile (the API already
 *  never sends others; this is the client's own guard), minus suggestions declined here. */
export function visibleSuggestions(
  p: Pick<Profile, "face_enrolled">,
  list: ProfileSuggestion[],
  declined: ReadonlySet<string> = new Set(),
): ProfileSuggestion[] {
  return list
    .map((s) => ({ ...s, reasons: s.reasons.filter((r) => r.kind !== "face" || p.face_enrolled) }))
    .filter((s) => s.reasons.length > 0 && !declined.has(suggestionKey(s)));
}

export function reasonText(r: SuggestionReason): string {
  return r.kind === "face"
    ? `Face match ${Math.round(r.similarity * 100)}% · ${r.votes} votes`
    : "Same name tag";
}

export const SUGGESTION_NOTE = "Suggestions only — nothing is linked until you confirm.";

export function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0].toUpperCase())
      .join("") || "?"
  );
}

export const sportsText = (p: Pick<Profile, "sports">): string =>
  (p.sports ?? []).map((s) => s[0].toUpperCase() + s.slice(1)).join(" · ") || "No games linked yet";

/** The reel items that can play (a game without a wide rendition is skipped). */
export const playableReel = (r: CareerReel | null | undefined): ReelItem[] =>
  (r?.items ?? []).filter((i) => !!i.url);

// ---------------------------------------------------------------- face enrollment (opt-in)

export const FACE_PHOTOS_MIN = 1;
export const FACE_PHOTOS_MAX = 10;

/** The consent text the phone shows before enrollment is possible (D-58). */
export const FACE_CONSENT: string[] = [
  "Your photos are turned into one face embedding (a list of numbers) for this profile, then deleted. No photo is kept.",
  "Only that one embedding is stored. It is compared only with players in your games, to suggest links you confirm. Nobody is linked automatically, and people who did not enroll are never matched.",
  "Delete it any time with “Delete my face data” on this page. Deleting the profile deletes it too.",
];

export function facePhotosError(n: number): string | null {
  if (n < FACE_PHOTOS_MIN) return "Pick at least one photo of your face.";
  if (n > FACE_PHOTOS_MAX) return `Pick at most ${FACE_PHOTOS_MAX} photos.`;
  return null;
}
