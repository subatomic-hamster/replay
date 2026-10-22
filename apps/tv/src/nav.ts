// In-memory navigation: a TV app has one screen at a time and no URL bar. The web build
// seeds the first route from its URL (`routeFromPath`) so Playwright can deep-link; the
// paths mirror apps/web's /tv routes.
import { useSyncExternalStore } from "react";

export type Route =
  | { name: "library" }
  /** The player. `way`: a way to watch (Highlights, Condensed); `q`: a highlight query
   *  played as a reel (the paired phone's push); `play`: open that play's replay angles. */
  | {
      name: "watch";
      gameId: string;
      mode?: string;
      pid?: string;
      t?: number;
      way?: Way;
      q?: string;
      play?: string;
      /** reopen the player card on this player, paused (Back from its View profile);
       *  `resume`: the card's Back plays on, as it was when the card first opened */
      card?: { pid: string; resume: boolean };
      /** reopen the Stats panel (Back from Review or Tips, which it opened) */
      panel?: "stats";
    }
  | { name: "review"; gameId: string }
  | { name: "clips" | "search" | "advice"; gameId: string }
  | { name: "pair"; gameId?: string }
  /** M10: profiles; `from` is the game to return to on Back (when opened from Watch) */
  | { name: "players"; from?: string }
  /** `back`: where Back goes instead of Players (the player card's game, card open) */
  | { name: "profile"; profileId: string; from?: string; back?: Route }
  /** The API base (first run opens here when the build has no default) */
  | { name: "settings" }
  /** D-80: pick a sport, show the phone-upload QR, follow the game until it is ready */
  | { name: "add" };

export type Way = "full" | "highlights" | "condensed";

/** M13 screens that take only a game id: `/tv/:id/<name>`. */
const GAME_SCREENS = ["clips", "search", "advice"] as const;

let current: Route = { name: "library" };
const subs = new Set<() => void>();

export function navigate(to: Route) {
  current = to;
  subs.forEach((f) => f());
}

export function useRoute(): Route {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => current,
  );
}

/** `/tv`, `/tv/settings`, `/tv/add`, `/tv/pair?game=`, `/tv/:id[?mode=&pid=&t=&way=&q=]`,
 *  `/tv/:id/highlights[?q=]` and `/tv/:id/{rallies,condensed}` (the player in that way),
 *  `/tv/:id/review`, `/tv/:id/replays[/:playId]` (the player, on that play's angles),
 *  `/tv/:id/{clips,search,advice}`,
 *  `/tv/players[/:profileId][?from=<game>]`. */
export function routeFromPath(path: string): Route {
  const [pathname, search = ""] = path.split("?");
  const params = new URLSearchParams(search);
  const seg = pathname.split("/").filter(Boolean);
  if (seg[0] === "tv") seg.shift();
  if (seg.length === 0) return { name: "library" };
  if (seg[0] === "settings") return { name: "settings" };
  if (seg[0] === "add") return { name: "add" };
  if (seg[0] === "pair")
    return { name: "pair", gameId: params.get("game") ?? undefined };
  if (seg[0] === "players") {
    const from = params.get("from") ?? undefined;
    return seg[1]
      ? { name: "profile", profileId: decodeURIComponent(seg[1]), from }
      : { name: "players", from };
  }
  const gameId = seg[0];
  if (seg[1] === "review") return { name: "review", gameId };
  const screen = GAME_SCREENS.find((s) => s === seg[1]);
  if (screen) return { name: screen, gameId };
  // M8: a play's replay angles open inside the player (the old list is the player).
  if (seg[1] === "replays") {
    return seg[2]
      ? { name: "watch", gameId, play: decodeURIComponent(seg[2]) }
      : { name: "watch", gameId };
  }
  // The old Highlights and Rallies screens are ways to watch in the player now.
  const way =
    seg[1] === "highlights"
      ? "highlights"
      : seg[1] === "rallies" || seg[1] === "condensed"
        ? "condensed"
        : WAYS.find((w) => w === params.get("way"));
  return {
    name: "watch",
    gameId,
    mode: params.get("mode") ?? undefined,
    pid: params.get("pid") ?? undefined,
    t: Number(params.get("t")) || undefined,
    way,
    q: params.get("q") ?? undefined,
  };
}

const WAYS: Way[] = ["full", "highlights", "condensed"];
