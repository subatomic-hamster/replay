# How we built it

**Fire TV app (`apps/tv`).** React Native for TV (react-native-tvos 0.87.1-1) with react-native-video 6.19.3. Shared logic (API client, spatial focus, media clock, follow-cam math, request retry) lives in `packages/tv-core`, so the same screens also build as a react-native-web app that Playwright can drive with keyboard keys standing in for the D-pad. We patched react-native-video so its TextureView mode builds a real TextureView, which the follow-cam needs to zoom and pan the picture. The APK runs on a Fire TV Stick (AFTSS, Fire OS 7).

**Phone side (`apps/web`).** One Vite and React 19 app: the upload page at `/u/{id}`, and a phone page at `/p/{id}` for Clip, Tag, Review and Search. The TV's QR code carries a per-game capability token in the URL fragment, so it never reaches server logs.

**API on AWS (`services/api`, `infra/`).** FastAPI behind Mangum on one arm64 Lambda with a Function URL. State lives in a private S3 bucket: games, job records (claimed with conditional writes), and the profiles database mirrored write-through. Uploads are multipart through presigned URLs. Both web builds sit behind CloudFront with origin access control, and a runtime `config.json` carries the API address so builds bake in neither the address nor a key. Secrets are SSM Parameter Store SecureStrings created outside the template. The stack is AWS CDK (TypeScript). We chose this shape to have no idle cost: no VPC, NAT, API Gateway or database.

**Pipeline (`courtcam/`, `services/worker`, `render/`).** `courtcam` is an MIT Python library: ingest, court calibration (template fit plus tapped landmarks, with a lens model), YOLO11 person detection with BoT-SORT tracking, identity stitching, pose, events, sport play grammars, and crop paths. The worker runs these as named, versioned stages cached by content hash. The render package makes the director, highlights, hype meter, and the real-video, 2.5D and virtual replay angles. Optional model stages: SAM 2.1 masks, Whisper for voice clips, Kokoro TTS, SigLIP search embeddings, a small local LLM for paraphrase and query parsing behind a grounding check.

**Where the GPU runs.** Our AWS account has no GPU quota, so a shared AMD GPU workstation (ROCm, PyTorch) runs a pull-based runner. It claims jobs from the API over HTTPS with a worker key, runs the same worker code, and uploads outputs. It holds no AWS credentials.

**Process.** We worked with Claude Code as an orchestrator that handed stages to coding and research agents, with a decision log (`docs/decisions.md`, D-1 to D-98), a friction log, and a Playwright check after each feature. The commit gate ran ruff, pytest suites and the TV and web end-to-end tests (133 and 125 at the last full gate, per HANDOFF.md). We accepted features on real game footage, not only synthetic clips.

TODO(team): add team member roles and bios. The repo does not record them.
