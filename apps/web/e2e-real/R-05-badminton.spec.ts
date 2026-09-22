// §4.9 Tier 1 for badminton on the fisheye/ultra-wide clip — the hard lens case.
// Same walk as R-04; the calibration is the interesting difference (samples/real/RESULTS.md).
//
//   REPLAY_E2E_REAL=1 pnpm exec playwright test --project=real R-05
import { netSportSpec } from "./net-sport";

netSportSpec({
  sport: "badminton",
  variant: "doubles",
  clip: "badminton_russiaclub_smoke.mp4",
  landmarksFile: "badminton_russiaclub_240s.landmarks.json",
  title: "Russia club badminton",
});
