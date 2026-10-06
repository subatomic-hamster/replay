// In-memory navigation: a TV app has one screen at a time and no URL bar. The web build
// seeds the first route from its URL (`routeFromPath`) so Playwright can deep-link; the
// paths mirror apps/web's /tv routes.
import { useSyncExternalStore } from "react";

export type Route =
  | { name: "library" }
  | { name: "watch"; gameId: string; mode?: string; pid?: string; t?: number }
  | { name: "highlights"; gameId: string; q?: string }
  | { name: "review"; gameId: string }
  | { name: "pair"; gameId?: string };

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

/** `/tv`, `/tv/pair?game=`, `/tv/:id[?mode=&pid=&t=]`, `/tv/:id/highlights[?q=]`, `/tv/:id/review`. */
export function routeFromPath(path: string): Route {
  const [pathname, search = ""] = path.split("?");
  const params = new URLSearchParams(search);
  const seg = pathname.split("/").filter(Boolean);
  if (seg[0] === "tv") seg.shift();
  if (seg.length === 0) return { name: "library" };
  if (seg[0] === "pair") return { name: "pair", gameId: params.get("game") ?? undefined };
  const gameId = seg[0];
  if (seg[1] === "highlights") return { name: "highlights", gameId, q: params.get("q") ?? undefined };
  if (seg[1] === "review") return { name: "review", gameId };
  return {
    name: "watch",
    gameId,
    mode: params.get("mode") ?? undefined,
    pid: params.get("pid") ?? undefined,
    t: Number(params.get("t")) || undefined,
  };
}
