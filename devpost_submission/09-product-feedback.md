# Product feedback

One section per tool, API or SDK we used. Each says what we used it for, what worked, what needs work, how onboarding felt, and whether we would build with it again. Everything comes from our docs (docs/friction-log.md, docs/fire-tv.md, docs/decisions.md, docs/models.md, docs/aws-deploy.md, docs/licenses.md) or the repo. Where we did not use a thing the track mentions, we say so.

Sections: [Fire TV and Android](#fire-tv-and-android) · [AWS services](#aws-services) · [Web, test and build tooling](#web-test-and-build-tooling) · [Python and ML stack](#python-and-ml-stack) · [Compute and dev environment](#compute-and-dev-environment)

---

## Fire TV and Android

### Fire TV Stick (AFTSS, Fire OS 7.7.1.6, Android 9)

- **Used for:** the only target device. We side-loaded a release APK over USB adb and tested headless (HDMI unplugged).
- **Worked well:** adb over USB is reliable once the device is awake. After `KEYCODE_WAKEUP`, `am start`, key events, `screencap` and real video playback all work, so we could verify UI changes on the device without a TV. The hardware AVC decoder handled our MP4 playback, and a follow-cam over 8 s measured 0.76% janky frames.
- **Needs work:** it sleeps with HDMI unplugged and you must wake it before every session. Joining Wi-Fi from adb needs root or the Settings UI (Fire OS 7 has no `cmd wifi`). `input keyevent --longpress` acts as a tap, so key-hold behaviour cannot be tested without a physical remote. Each `adb shell input` call takes about 1 s on this stick. Our app did not appear in Your Apps & Channels or the App Library even though `LEANBACK_LAUNCHER` resolves with a banner; cause unknown.
- **Onboarding:** quick to side-load, slow to get on a usable network. See the friction log.
- **Build again:** yes. It is a good target for this product, and device testing found real bugs.

### react-native-tvos (0.87.1-1) and Metro

- **Used for:** the TV app. Screens never branch on sport; platform code sits behind `PlayerSurface` and `platform/`.
- **Worked well:** one codebase for the TV app and a react-native-web build that Playwright drives. Hermes and Fabric started on the Stick without JavaScript or native errors, and no low-memory kills in logcat.
- **Needs work:** no remote key reached JavaScript until the app root was `focusable` with `hasTVPreferredFocus`; that is not the first thing the docs lead you to. Metro could not bundle shared TypeScript outside the project root without `resolver.nodeModulesPaths`, and the error named `@babel/runtime`, a module our source never imports (FL-8). React Native's cookie jar waited about 1.9 s on WebView's `CookieManager` at the first request; we installed an OkHttp client factory with a no-op cookie jar.
- **Onboarding:** moderate. The debug path is easy; the release bundle and shared-package setup took time.
- **Build again:** yes, with the focus and Metro notes above kept in a README.

### react-native-video (6.19.3)

- **Used for:** playback, including a TextureView so the follow-cam can transform the picture.
- **Worked well:** Media3 playback on the Stick's hardware AVC decoder; tap seeks showed their preview within 0.3 s.
- **Needs work:** we carry two patches (D-65 and the controller fix). `viewType` TEXTURE did not build a real TextureView on Android, and the patched `PlayerView` showed ExoPlayer's own controller over the black picture until init.
- **Onboarding:** easy to start, hard to customise. **Build again:** yes, with the patch in `patches/`.

### Android toolchain (Gradle, adb, signing)

- **Used for:** building `armeabi-v7a` release APKs (about 18.5 MB, about a minute of Gradle time) and installing them.
- **Worked well:** `buildConfigField` for the API base and key made a one-command build per environment; release signing reads keys from outside the repo.
- **Needs work:** a key baked into an APK means the APK is a secret (see friction log). The fallback chain for the key is BuildConfig, then config.json, then a Settings override.
- **Build again:** yes.

### Vega SDK

- **Not used.** Our Phase 1 notes listed a Vega port as later work; the repo never started it (the decision log, D-37, records react-native-tvos with a react-native-web build for tests instead). We have no hands-on feedback on Vega. TODO(team): add a line on why Vega was not chosen if the team remembers.

### Alexa Skills Kit (custom skill, HTTPS endpoint)

- **Used for:** a backend for "Alexa, ask replay court to clip that" and "export a highlight reel": request verification (certificate chain, signature, timestamp, skill id), TV pairing codes, and a command queue the TV polls.
- **Worked well:** pointing the endpoint at a Lambda Function URL with the wildcard-certificate option kept the skill on our own API.
- **Needs work:** the invocation name cannot be the single word "replay", so users must say "ask replay court". Whether a Fire TV Stick forwards a development skill's phrase is untested by us (docs/alexa-research.md). The TV app does not yet use the queue, so the feature is not in the demo.
- **Onboarding:** the console steps are manual (docs/alexa.md). TODO(team): confirm whether the skill was created in the console and tested on an Echo.
- **Build again:** yes, for a clip-that voice path, if the Stick path can be confirmed.

---

## AWS services

Deployed in the `ReplayCloud` CDK stack (`infra/lib/cloud-stack.ts`), us-east-1, tagged `project=replay`. The `ReplayData` and `ReplayPipeline` stacks (DynamoDB, Step Functions) exist in the CDK app behind a flag and are not deployed, so we do not give feedback on services we did not run.

### AWS CDK (TypeScript) and CloudFormation

- **How we used it:** one stack with the media and web buckets, the Lambda and Function URL, CloudFront and its Function, an IAM policy limited to our bucket and `/replay/*` parameters, and BucketDeployment for the web builds. Unit tests check the synthesized template, and CI synthesizes with `stubBuilds=true`.
- **Worked well:** least-privilege IAM was easy to express. Synthesizing without builds (stub mode) made CI independent of AWS.
- **Needs work:** CDK cannot read an `aws login` session, so the account owner exported credentials with `aws configure export-credentials` to deploy from a pre-synthesized `cdk.out`. The CLI profile has no default region, so `AWS_REGION` must be set every time.
- **Onboarding:** reasonable. **Build again:** yes.

### AWS Lambda (Function URL, Python 3.12, arm64)

- **How we used it:** the whole FastAPI app through Mangum, 1024 MB, 30 s timeout, auth type NONE because the app checks its own key, upload tokens and a worker key.
- **Worked well:** no API Gateway, no idle cost, and a stable URL. Mangum let us run the FastAPI app behind the URL. Packaging fit the limits (about 170 MiB unzipped, 60 MiB zipped).
- **Needs work:** a new account's concurrency limit was 10, and one Watch screen made about nine parallel requests, giving 429s. We reduced client concurrency (D-87) and requested a higher limit. Function URLs have no WebSockets, so we dropped the companion WebSocket pairing in cloud mode. A cold instance that mirrored a whole game from S3 took 8 to 17 s per request until D-86. Lambda's own 429 is answered before our code runs, so we could not add CORS headers to it.
- **Onboarding:** easy. **Build again:** yes, with a higher concurrency limit.

### Amazon S3

- **How we used it:** the only data store. Games, job records (claimed by conditional writes), a mirrored profiles database, and presigned multipart uploads direct from the phone. A lifecycle rule aborts incomplete multipart uploads after one day. The media bucket is retained on stack delete.
- **Worked well:** presigned multipart uploads and Range reads for video were solid. Conditional writes gave us a job queue without a database.
- **Needs work:** with no database, our runner polls a job prefix (about 86k LISTs a month in our cost estimate), and mirroring a whole game is one LIST plus one GET per object, which was slow on a fresh Lambda instance. CORS for multipart needs ETag exposed, which is easy to miss.
- **Onboarding:** easy. **Build again:** yes.

### Amazon CloudFront (and CloudFront Functions)

- **How we used it:** one distribution, origin access control, serving the phone web app at `/` and the TV web build at `/tvapp/`. A small CloudFront Function rewrites extension-less paths to the right `index.html` for each app.
- **Worked well:** OAC with a private bucket; the Function made two single-page apps share one distribution.
- **Needs work:** BucketDeployment invalidations and the two-app prefix layout needed care so one deploy does not prune the other. Presigned video GETs go straight from S3, not through CloudFront, to stay within free egress.
- **Onboarding:** moderate. **Build again:** yes.

### AWS Systems Manager Parameter Store (SecureString)

- **How we used it:** three secrets (API key, worker key, upload-token secret) under the AWS-managed key, created by hand from a pipe so the values never touch shell history. The Lambda reads `/replay/*` only. A plain String parameter holds the Alexa skill id.
- **Worked well:** free at standard tier and simple IAM scoping.
- **Needs work:** secrets must be created outside the stack, so a fresh deploy has a manual step.
- **Build again:** yes.

### AWS KMS (aws/ssm managed key)

- **How we used it:** only through SSM. The Lambda role allows `kms:Decrypt` conditioned on the SSM service and our parameter ARN.
- **Worked well:** the encryption-context condition lets the role decrypt only through SSM, for our parameters only. **Needs work:** nothing found. **Build again:** yes.

### AWS IAM, CloudWatch Logs

- **How we used it:** one function role with no wildcard resources beyond the parameter and key patterns above. A log group with one-week retention.
- **Worked well:** straightforward. **Build again:** yes.

### AWS Budgets, Service Quotas, free-plan credits

- **How we used it:** a $10 monthly budget with alerts; credit activities (Budgets, Lambda, EC2) to unlock credits, with placeholder resources torn down afterwards; Service Quotas to find our limits.
- **Worked well:** the budget alerts (50, 80 and 100% actual, 100% forecast) are in place.
- **Needs work:** Service Quotas showed EC2 G and P instance quotas at 0 (on-demand and spot) and a Lambda concurrency limit of 10 on a new account. Increases are requests we had to file by hand; the repo does not record the outcome of the Lambda one. Some credit activities needed the console rather than the CLI.
- **Build again:** yes.

### AWS services we designed for but did not run

DynamoDB, Step Functions, SageMaker Processing, Bedrock, Polly and Rekognition appear as provider stubs and a CDK skeleton (docs/aws-integrations.md). Nothing in the deployed system calls them. We give no feedback on them.

---

## Web, test and build tooling

### Playwright (1.60)

- **Used for:** end-to-end tests of the TV web build and the phone pages; 133 TV and 125 web end-to-end tests at the last full gate, plus recorded runs.
- **Worked well:** several `webServer` entries in one config; keyboard-only driving suits a D-pad app.
- **Needs work:** fixed ports force a lock on a shared box. **Onboarding:** easy. **Build again:** yes.

### Vite 7, React 19, react-native-web

- **Used for:** the phone app and the TV web build.
- **Worked well:** fast dev server and clean `tsc` and ESLint.
- **Needs work:** `import.meta.env` is fixed at server start, so per-test API bases need separate servers (FL-6); we fetch a runtime `config.json` in the deployed builds.
- **Build again:** yes.

### pnpm 11

- **Used for:** installs for both apps. **Worked well:** speed, lockfiles. **Needs work:** build scripts are blocked until approved interactively, which breaks CI; we committed `allowBuilds` (FL-4). **Build again:** yes.

### uv

- **Used for:** the Python workspace with four members and a pinned 3.12 interpreter.
- **Needs work:** a workspace root with no dependencies silently drops members on `uv sync` (FL-3). **Build again:** yes.

### FastAPI, Mangum, boto3, moto

- **Used for:** the API, its Lambda adapter, S3 and SSM access, and S3 tests without AWS.
- **Worked well:** Starlette's Range support served MP4 with no custom code; moto let us test the cloud mode locally (including a test that no route pulls a whole game).
- **Build again:** yes.

### ffmpeg

- **Needs work:** Fedora's ffmpeg has no `libx264`, so we probe `-encoders` at run time (FL-1). A static build segfaulted on https inputs (FL-12). **Build again:** yes.

---

## Python and ML stack

### Ultralytics YOLO11 and BoT-SORT

- **Used for:** person detection (yolo11m) and tracking, plus pose.
- **Worked well:** accuracy and speed: about 10.7 ms per frame for the model alone on the AMD GPU, and the detect stage at about 4.7 times realtime with tracking. Single-frame yolo11m found 94.7% of labelled players at 960 px, so the detector was not our bottleneck (D-97).
- **Needs work:** AGPL-3.0 licensing forces an optional extra to keep `courtcam` MIT. No Python 3.14 wheels at the time (FL-2). It writes a user-level settings file on import (FL-14).
- **Build again:** yes for the quality, with the licence in mind.

### SAM 2.1 (transformers `Sam2VideoModel`)

- **Used for:** per-player masks for cutout angles. **Worked well:** accurate masks from a box prompt; 39.6 ms per frame in bf16 on the AMD GPU.
- **Needs work:** fp32 was 428 ms per frame, about ten times slower (FL-11). **Build again:** yes.

### Whisper (transformers)

- **Used for:** the spoken "Replay, clip that" trigger on the game's own audio track. **Worked well:** small model, MIT weights. **Needs work:** a first call hung under MIOpen on this GPU (FL-9); voice triggers were measured on synthetic speech first. **Build again:** yes.

### Kokoro-82M TTS

- **Used for:** optional commentary narration. **Worked well:** Apache-2.0, real-time factor 0.04 to 0.09 on GPU. **Needs work:** its LSTM fails under MIOpen on gfx1201; we disable cuDNN/MIOpen for it. espeak-ng (GPL-3.0) is a dependency to watch. **Build again:** yes.

### SigLIP (open_clip), llama.cpp with Qwen3-4B, ViTPose, MotionBERT, YuNet and SFace, SpeechBrain ECAPA

- **Used for:** play search embeddings; paraphrase and query parsing behind a grounding check; optional pose; optional lifting for 3D mannequins; enrolled-only face matching; enrolled-only voice matching.
- **Notes:** the llama.cpp ROCm release silently ran on CPU until we linked the ROCm libraries (FL-10); we kept the LLM output behind a grounding check. MotionBERT's weights are Apache-2.0 but were trained on an academic-only dataset, so it is an optional replay-side extra. **Build again:** yes for SigLIP, llama.cpp and YuNet/SFace; the others stay optional.

### Other models we tried and kept out

MoGe-2, VGGT and Gaussian-splat experiments live in `experiments/` and are not used by the product (docs/tier-d.md). SMPL, InsightFace and non-commercial wake-word models are not used because of their licences.

### OpenCV

- **Used for:** calibration, homography, lens model, ingest. **Worked well:** `solvePnP` and our template fit. **Build again:** yes.

---

## Compute and dev environment

### AMD ROCm and PyTorch on a Radeon RX 9070 XT (shared workstation)

- **Used for:** all GPU work: detection, tracking, SAM, ASR, TTS, embeddings, LLM.
- **Worked well:** torch 2.14 with ROCm 7.2 ran YOLO and SAM in bf16 quickly, and `torch.cuda` just worked.
- **Needs work:** MIOpen errors or hangs for LSTM and some conv calls on gfx1201 (FL-9); there is no `rocm-smi` or `/opt/rocm` in the container; memory is limited by the container, not by what `free` shows.
- **Onboarding:** hard on a new GPU generation without the box owner's notes. **Build again:** yes, with flags noted in docs/models.md.

### Tailscale (Funnel) for access to the workstation

- **Used for:** SSH to the shared workstation through a Funnel relay owned by the workstation's owner.
- **Needs work:** when the backend host is down the failure reads "SSL routines::unexpected eof" with TCP open, which does not say the relay has no backend. A foreground ssh build died with the link (FL-18). **Build again:** yes for access, but with detached jobs.

### tmux, flock

- **Used for:** long jobs and box-wide locks (GPU, memory, CPU, Playwright ports). A first tmux session leaked its environment into later sessions (FL-17).

### Claude Code

- **Used for:** orchestrating coding and research agents across the stages, with a decision log and a commit gate. It built much of the repo.
- **Worked well:** staged, parallel work with disjoint file areas; agent notes carried the box rules between sessions.
- **Needs work:** auto-mode blocked `cdk bootstrap/deploy`, quota requests and `rds create-db-instance`, so the account owner did those. The `aws login` session was not readable by CDK. Shared-box rules had to be restated in every brief.
- **Build again:** yes.

### yt-dlp

- **Used for:** fetching licensed test clips. Needs `-4` when IPv6 is blackholed (FL-7). **Build again:** yes.
