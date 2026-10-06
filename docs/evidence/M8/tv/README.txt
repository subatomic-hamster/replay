M8 multi-angle Replay view (apps/tv react-native-web build, 1920x1080), mock API fixture.
The picture is the committed synthetic test pattern apps/web/public/mock/wide.mp4, which the
mock serves for every angle (/mock/wide.mp4?angle=<id>); only the overlay differs.

replay-tierA-follow-mock.png  Tier A angle "Follow · Marcus" (2 / 4), bug still big after the cut
replay-tierB-orbit-mock.png   Tier B angle "Orbit" (4 / 4), reached with Left twice from 2 / 4 (wraps past 1 / 4)

synth_real-api_pl_0001_0N_<angle>.jpg  The same screen (apps/web /tv harness, 1920x1080) on the
  REAL worker output for SYNTHETIC basketball/half play pl_0001: services/api (REPLAY_PIPELINE=fake,
  data dir = the worker's game dir) serves /games/<id>/replays/pl_0001 and the six angle MP4s via
  /media (206 range requests); paused at t=2.50 s, then Right through all six angles. The media
  time stayed 2.508 s on every cut (wide, follow:p4, tight:p4, broadcast_high, orbit, push_in).
cc_pickleball_real-api_pl_0002_0N_<angle>.jpg  Same pass on the CC BY 3.0 pickleball clip
  (game g_cc_pb90, play pl_0002, media time 2.516 s on every cut). Derived from "2026.09.04 MD4.0
  (age 50+) John Lee + Ernest Tosch vs Brendan Fong + Anthony Chang (Gold Medal)" by
  pickleball4you, https://www.youtube.com/watch?v=4M58YJoZ4O4, CC BY 3.0
  (https://creativecommons.org/licenses/by/3.0/); cut and modified.
  Scratch driver: Playwright script outside the repo (tierb agent), not a committed spec.

Produced on hfbox:
  cd apps/tv && REPLAY_TV_EVIDENCE_DIR=<dir> pnpm exec playwright test --project=tv -g evidence
(test "TV-09 evidence screenshots" in apps/tv/e2e/TV-09-replay-angles.spec.ts)
