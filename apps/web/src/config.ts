export const API_BASE = (
  import.meta.env.VITE_REPLAY_API_BASE ?? "http://localhost:8000"
).replace(/\/$/, "");

/** §4.6: shared demo key, only sent when configured. */
export const API_KEY: string = import.meta.env.VITE_REPLAY_API_KEY ?? "";

export const MOCK_API = import.meta.env.VITE_MOCK_API === "1";

/** D-6: client-side CSS transform follow-cam is the Phase 1 default. `rendition` swaps
 *  the video src for a pre-rendered per-player MP4 (plan task 12) when one exists. */
export const followcam: { mode: "client" | "rendition" } = {
  mode: import.meta.env.VITE_FOLLOWCAM_MODE === "rendition" ? "rendition" : "client",
};

/** W6 fallback: force spotlight instead of a transform (S-23 flips this). */
export const FORCE_SPOTLIGHT = import.meta.env.VITE_FORCE_SPOTLIGHT === "1";

/** R5: events below this confidence and unconfirmed land in the review queue. */
export { REVIEW_CONFIDENCE_THRESHOLD } from "../../../packages/tv-core/src/display";

export const SEEK_STEP_S = 10;
