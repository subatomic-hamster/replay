// D-6 / plan task 12 — which media the follow-cam plays.
//
// `client` (default): keep the wide MP4 and apply the CSS crop transform.
// `rendition`: play the pre-rendered per-player MP4 at the same currentTime instead.
//   Until that file exists we still transform the wide shot and ask the API to render
//   it once, so the next visit is a plain <video src> swap.
// Pure on purpose: `e2e/S-20-rendition-source.spec.ts` tests it without a browser.

export interface FollowSource {
  /** What PlayerSurface should load (the swap keeps currentTime). */
  src: string;
  /** Apply the client-side crop transform. */
  useCrop: boolean;
  /** Queue POST /games/{id}/players/{pid}/render — no rendition exists yet. */
  needsRender: boolean;
}

export function followSource(
  mode: "client" | "rendition",
  wideUrl: string,
  following: boolean,
  renditionUrl?: string | null,
): FollowSource {
  if (!following) return { src: wideUrl, useCrop: false, needsRender: false };
  if (mode !== "rendition") return { src: wideUrl, useCrop: true, needsRender: false };
  if (renditionUrl) return { src: renditionUrl, useCrop: false, needsRender: false };
  return { src: wideUrl, useCrop: true, needsRender: true };
}
