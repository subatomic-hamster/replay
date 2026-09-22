// §4.9 Tier 1 for badminton on the ultra-wide auditorium clip — the hard lens case.
// GoPro superview from the sideline, in the plane of the net: the back boundary lines
// run off both frame edges and the sidelines are visibly bowed, so this clip only
// calibrates with the D-24 lens model (`courtcam/courtcam/distortion.py`). The walk is
// R-04's; the calibration is the interesting difference (samples/real/RESULTS.md).
//
//   REPLAY_E2E_REAL=1 pnpm exec playwright test --project=real R-05
import { netSportSpec } from "./net-sport";

netSportSpec({
  sport: "badminton",
  variant: "doubles",
  clip: "badminton_auditorium_smoke.mp4",
  landmarksFile: "badminton_auditorium_240s.landmarks.json",
  title: "Auditorium badminton",
});
