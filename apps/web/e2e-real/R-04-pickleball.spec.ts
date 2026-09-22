// §4.9 Tier 1 for pickleball, proved through the product on real footage:
// select, follow-cam, tagging surface, court inset, heatmap.
//
//   REPLAY_E2E_REAL=1 pnpm exec playwright test --project=real R-04
import { netSportSpec } from "./net-sport";

netSportSpec({
  sport: "pickleball",
  variant: "doubles",
  clip: "pickleball_legacypark_smoke.mp4",
  landmarksFile: "pickleball_legacypark_240s.landmarks.json",
  title: "Legacy Park pickleball",
});
