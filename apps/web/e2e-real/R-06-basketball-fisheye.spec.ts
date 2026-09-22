// §4.9 on the extreme-fisheye ceiling clip — the case the D-24 lens model does NOT fix.
// The camera sits above and behind the near backboard, so the near baseline and both
// near corners are behind the glass barrier and the backboard rigging: four of the five
// landmarks `basketball` requires are unclickable, and the eight that ARE visible all
// sit inside r < 0.54 of the half-diagonal, where k1 is not separable from click noise
// (measured: reprojection 18.3 px, best k1 = 0, samples/real/RESULTS.md).
//
// So there is deliberately no `basketball_ceilingcam_240s.landmarks.json` in the repo
// and this spec skips with that reason rather than asserting on a fit we do not believe.
// It is kept, not deleted, because it is the standing check for the next ceiling clip:
// drop a landmarks file next to the clip and the whole Tier 1 walk runs.
//
//   REPLAY_E2E_REAL=1 pnpm exec playwright test --project=real R-06
import { netSportSpec } from "./net-sport";

netSportSpec({
  sport: "basketball",
  variant: "full",
  clip: "basketball_ceilingcam_smoke.mp4",
  landmarksFile: "basketball_ceilingcam_240s.landmarks.json",
  title: "Ceiling-cam basketball",
});
