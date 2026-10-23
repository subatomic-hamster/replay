# Accomplishments we are proud of

**It runs on a real Fire TV Stick against a real AWS deployment.** On 2026-10-21 the app first ran on an AFTSS Stick (Fire OS 7.7.1.6, 32-bit, about 900 MB RAM) against the deployed API. Measured on the device (docs/fire-tv.md): cold start to first frame about 1.0 s, cold start to Home with live games about 5 s, a Home focus move drawn within 0.13 s, opening a game to first video frame about 3.2 s, and a follow-cam over 8 s with 393 frames and 0.76% janky. Memory during playback was a total PSS of 165 to 177 MB.

**The follow-cam interaction works as imagined.** You pick a person on the video with the arrows and the camera follows them, driven on the client from the tracks.

**A serverless cloud with almost no idle cost.** One Lambda, two S3 buckets and CloudFront, no database, no VPC. The estimate in docs/aws-deploy.md is about $0.50 to $1 per month at demo usage (an estimate, not a bill).

**Tracking measured against hand-labelled truth.** On a labelled CC BY basketball game: player recall 0.73 to 0.88 and team accuracy 0.70 to 0.98 (D-97). For few-player games, the K-person roster labelling raised right-person accuracy on a 2v2 proxy from 52% to 83%.

**The demo game, scored against a hand list of moments (D-98).**

- 5 of 5 X signs found, none false.
- 25 of 25 shot precision (two shooters still wrong).
- Pickup score 11 to 0, the right winner, with one dead-ball shot counted.
- Replays cover 6 of 9 moments; the highlight reel covers 9 of 9.

**Honest by construction.** Synthetic media is labelled synthetic. Real footage never goes into git. The app says "can't tell" when the ball is at the rim's edge, and the last basket is called "Last basket", not "Game winner".

**A permissive core.** `courtcam` is MIT with permissive-only required dependencies. Research-licensed models are optional extras with the licences listed in docs/licenses.md.

**Discipline.** 143 commits in a month, a numbered decision log through D-98, and a test gate (133 TV and 125 web end-to-end tests plus the Python suites at the last full run) that every commit had to pass.

TODO(team): add any submission-specific items, such as the demo video link and open-source repository link, once published.
