# What we learned

**Measure against real, hand-labelled footage early.** Synthetic clips were useful for fast tests, but the real bottlenecks showed up only on real games: referees taking player slots, kit colours that need brightness to separate, and mirrored court labels. The D-97 table of recall by pipeline stage showed us the identity stage was losing players the detector had already found, which a total accuracy number would have hidden.

**State what a result is.** Every JSON file carries a schema name, every recreated view carries a label, and a shot at the rim's edge gets "can't tell" and goes to the Review queue instead of a guess. This cost some polish and saved us from presenting recreated pixels as footage.

**Design for the real device.** The web build of the TV app let us test quickly, but the Stick found bugs the browser could not: no remote key reached JavaScript until the root view was focusable, the first request waited about 1.9 s on WebView's cookie manager, and ExoPlayer's own controller showed over the black frame while a video loaded. Each is fixed and recorded in docs/fire-tv.md. A real hold on the remote is also something `adb` cannot simulate, so hold-to-seek tiers are still not device-verified.

**Serverless fits this app, with limits.** A Lambda Function URL plus S3 plus CloudFront gave us a deployable backend with no idle cost. The limits showed quickly: no WebSockets, a 30 s timeout, an account concurrency of 10, and first requests that mirrored whole game folders from S3 (8 to 17 s) until we made each route pull only the files it reads (D-86).

**Keep expensive compute where it is cheap.** An AWS GPU would have spent our credit in days, and our quota was 0 anyway. A pull-based runner on a shared workstation with no cloud credentials was simple and safe, but it makes the project depend on a machine we do not control, so a judge cannot reproduce the full pipeline from AWS alone.

**Licences shape the architecture.** Ultralytics is AGPL-3.0, so `courtcam` keeps it behind an optional extra to stay MIT. SMPL-based body models, InsightFace and non-commercial wake-word models are not used. Research-licensed models stay optional and replay-side (docs/licenses.md).

**Shared infrastructure needs rules.** File locks for the GPU, memory and Playwright ports, and never leaking environment into a shared tmux server (FL-17), kept several agents from corrupting each other's runs.

**Tune on one video, say so.** The X-sign thresholds were tuned on the demo game. They get 5 of 5 there, and we describe them as a starting point.
