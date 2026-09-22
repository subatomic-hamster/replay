// ponytail: ~40 lines of history API instead of react-router. Eight static routes and
// one dynamic segment do not need a router dependency. Swap it in if nesting or loaders
// ever show up.
import { useEffect, useState } from "react";

function current() {
  return window.location.pathname + window.location.search;
}

const subs = new Set<() => void>();
function emit() {
  subs.forEach((f) => f());
}

export function navigate(to: string, replace = false) {
  if (to === current()) return;
  window.history[replace ? "replaceState" : "pushState"]({}, "", to);
  emit();
}

/** Merge query params into the current URL without a history entry (W4 state restore). */
export function setQuery(patch: Record<string, string | null>) {
  const url = new URL(window.location.href);
  for (const [k, v] of Object.entries(patch)) {
    if (v === null) url.searchParams.delete(k);
    else url.searchParams.set(k, v);
  }
  const next = url.pathname + (url.search === "?" ? "" : url.search);
  if (next === current()) return;
  window.history.replaceState({}, "", next);
  emit();
}

export function useLocation() {
  const [loc, setLoc] = useState(current);
  useEffect(() => {
    const onChange = () => setLoc(current());
    subs.add(onChange);
    window.addEventListener("popstate", onChange);
    return () => {
      subs.delete(onChange);
      window.removeEventListener("popstate", onChange);
    };
  }, []);
  const [pathname, search = ""] = loc.split("?");
  return { pathname, params: new URLSearchParams(search) };
}
