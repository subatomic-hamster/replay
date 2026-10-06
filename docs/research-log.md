# Research log

Dated running log of what was verified, installed and measured. Newest entries at the bottom. Licence detail per
component lives in `docs/licenses.md`, measured model numbers and call snippets in `docs/models.md`, footage in
`docs/test-data.md`. Every number here came from a command run on hfbox (AMD RX 9070 XT 16 GB, gfx1201, ROCm 7.2 torch 2.14).

## 2026-10-06 — Survey of the vision's research list

Method: GitHub REST API (`license`, `pushed_at`, `archived`, redirects), the repos' LICENSE/README text, Hugging Face model
cards, then installs/smoke tests on the box. "Last push" is GitHub's `pushed_at` (activity on any branch), not a release.

### Existence, licence, activity

| Item | Current URL | Code licence | Weights | Last push | Status / notes |
|---|---|---|---|---|---|
| ultralytics | github.com/ultralytics/ultralytics | AGPL-3.0 | AGPL-3.0 | 2026-10-05 | Alive. **AGPL**: courtcam currently hard-depends on it (flag in licenses.md). |
| ByteTrack | github.com/**FoundationVision**/ByteTrack (ifzhang/ByteTrack redirects here) | MIT | MIT | 2024-06-19 | Moved org, stale (no commits for 2+ years). Ultralytics ships its own ByteTrack/BoT-SORT, which is what D-5/D-31 use. |
| boxmot | github.com/mikel-brostrom/boxmot | AGPL-3.0 | ReID weights vary | 2026-09-18 | Alive, AGPL. Not needed. |
| supervision | github.com/roboflow/supervision | MIT | n/a | 2026-10-05 | Alive. |
| roboflow/sports | github.com/roboflow/sports | MIT | separate Roboflow downloads | 2026-08-28 | Alive; reference for court keypoints / team clustering. |
| mmpose (RTMPose) | github.com/open-mmlab/mmpose | Apache-2.0 | Apache-2.0 | 2025-08-04 | Maintenance slowed; needs `mmcv` (compiled ops; painful on ROCm). Use **rtmlib** (below) if a permissive 2D pose is wanted. |
| rtmlib | github.com/Tau-J/rtmlib | Apache-2.0 | Apache-2.0 | 2026-08-03 | Alive. RTMPose/RTMO/RTMW via onnxruntime, no mmcv/mmdet. |
| deep-person-reid | github.com/KaiyangZhou/deep-person-reid | MIT | model zoo, dataset terms research-only | 2026-01-09 | Low activity; not installed (D-32 identity stitching is roster/appearance based already). |
| sam2 | github.com/facebookresearch/sam2 | Apache-2.0 | Apache-2.0 | 2026-05-30 (last code commit on main 2024-12) | Alive/stable. HF-format weights also load with `transformers` (`Sam2VideoModel`). |
| co-tracker | github.com/facebookresearch/co-tracker | **CC-BY-NC-4.0** | CC-BY-NC | 2026-03-03 | Non-commercial: not installed, not used. |
| SoccerNet/sn-calibration | github.com/SoccerNet/sn-calibration | **no LICENSE file** | n/a | 2024-06-18 | Stale; not vendorable. Our calibration is OpenCV `solvePnP`. |
| Depth-Anything-V2 | github.com/DepthAnything/Depth-Anything-V2 | Apache-2.0 | **Small Apache-2.0; Base/Large/Giant CC-BY-NC-4.0** | 2026-03-24 | Use Small only. |
| 4D-Humans (HMR2.0) | github.com/shubham-goel/4D-Humans | MIT | needs SMPL (registration, research licence) | 2026-02-07 | Excluded (SMPL). |
| WHAM | github.com/yohanshin/WHAM | MIT | SMPL/SMPL-X + AMASS | 2024-04-18 | Excluded; stale. |
| GVHMR | github.com/zju3dv/GVHMR | custom non-commercial | same | 2026-09-15 | Excluded. |
| smplx | github.com/vchoutas/smplx | non-commercial research licence | SMPL/SMPL-X models: registration + research only | 2024-08-12 | Excluded from courtcam and from Tier C by design. |
| TrackNetV3 | github.com/qaz812345/TrackNetV3 | MIT (text covers checkpoints) | MIT | 2026-09-03 | Alive; badminton shuttle model, stretch goal. |
| shape-of-motion | github.com/vye16/shape-of-motion | MIT | needs third-party models | 2025-08-02 | Tier D experiment candidate. |
| monst3r | github.com/Junyi42/monst3r | CC-BY-NC-SA-4.0 | same | 2025-06-16 | Non-commercial; at most a research experiment. |
| gaussian-splatting | github.com/graphdeco-inria/gaussian-splatting | Inria non-commercial | n/a | 2025-10-17 | Non-commercial; gsplat (Apache-2.0) is the permissive route for Tier D. |
| librosa | github.com/librosa/librosa | ISC | n/a | 2026-09-29 | Alive. |
| faster-whisper | github.com/SYSTRAN/faster-whisper | MIT | MIT | 2026-10-05 | Alive; CTranslate2 wheels are CPU/CUDA only (no ROCm wheel): CPU fallback only. |
| openai/whisper | github.com/openai/whisper | MIT | MIT | 2026-08-31 | Alive; we run Whisper through `transformers` on ROCm. |
| openWakeWord | github.com/dscripka/openWakeWord | Apache-2.0 | **CC-BY-NC-SA-4.0** (all pre-trained models) | 2025-12-30 | Needs `tflite-runtime` unless ONNX mode; pre-trained models non-commercial -> opt-in only. |
| speechbrain | github.com/speechbrain/speechbrain | Apache-2.0 | ECAPA-VoxCeleb Apache-2.0 (VoxCeleb training data caveat) | 2026-08-27 | Alive. |
| ollama | github.com/ollama/ollama | MIT | n/a | 2026-10-06 | Alive (v0.35.1, ships a ROCm tarball). We used llama.cpp instead (smaller, scriptable). |
| piper | github.com/rhasspy/piper | MIT | per voice | 2025-08-26 | **Archived** (read-only). Maintained successor: **github.com/OHF-Voice/piper1-gpl**, GPL-3.0 engine, last push 2026-09-28. Voice licences vary. |
| Kokoro | github.com/hexgrad/kokoro + hf hexgrad/Kokoro-82M | Apache-2.0 | Apache-2.0 | code push 2025-08, model 2025-04 | Chosen TTS. |
| open_clip | github.com/mlfoundations/open_clip | MIT | model dependent (LAION: MIT) | 2026-09-30 | Alive. |
| insightface | github.com/deepinsight/insightface | MIT | **research-only for all downloadable models**; commercial = contact | 2026-10-04 | Opt-in face enrolment only; Rekognition is the commercial path. |
| pyrender / trimesh / PyAV | mmatl/pyrender, mikedh/trimesh, PyAV-Org/PyAV | MIT / MIT / BSD-3 | n/a | 2025-02 / 2026-10 / 2026-10 | pyrender is quiet (last push 2025-02) but fine for offscreen EGL. |
| three.js | github.com/mrdoob/three.js | MIT | n/a | 2026-10-05 | Alive. |
| react-native-tvos | github.com/react-native-tvos/react-native-tvos | MIT | n/a | 2026-10-02 | Alive. |
| react-native-video | github.com/**TheWidlarzGroup**/react-native-video (moved from react-native-community) | MIT | n/a | 2026-10-06 | Moved org, alive. |
| MotionBERT | github.com/Walter0807/MotionBERT, weights hf walterzhu/MotionBERT | Apache-2.0 | Apache-2.0 on the HF repo; trained on Human3.6M (academic-only dataset) | 2026-03-14 | Chosen Tier C lifter (see below). |

Not on the vision's list but checked: Qwen2.5-7B-Instruct (Apache-2.0), **Qwen2.5-3B-Instruct ("Qwen Research" licence: avoid)**,
SigLIP/SigLIP2 (Apache-2.0), llama.cpp (MIT, b11433 ships a ROCm tarball), yt-dlp (Unlicense).

### ROCm / AMD GPU feasibility (measured, see docs/models.md)

| Item | Result |
|---|---|
| ultralytics YOLO11 det/pose | Works. m-pose ~11 ms/frame @960 on a 2560x960 frame, x-pose ~20 ms. |
| SAM 2.1 | Works through `transformers` `Sam2VideoModel` with the cached HF weights. **Must run bf16: fp32 is ~10x slower** (428 vs 39.6 ms/frame for hiera-small). |
| Whisper (transformers) | Works with `torch.backends.cudnn.enabled=False`. With MIOpen on, the first call hung (0% CPU, 20+ min, holding the GPU lock until killed). small 0.07 s per short utterance. |
| Kokoro TTS | **`torch.nn.LSTM` fails under MIOpen on gfx1201** (`miopenStatusUnknownError`). With `torch.backends.cudnn.enabled=False` it works, RTF 0.04-0.09 on the GPU. |
| open_clip / speechbrain ECAPA | Work with MIOpen disabled (applied preventively; not tested with it on). |
| MotionBERT | Works (pure transformer, no conv). 50-152 ms per 243-frame window. |
| llama.cpp | The release tarball `llama-*-bin-ubuntu-rocm-10.0-x64` runs only after pointing it at ROCm 7.x runtime libs (symlinks to torch's bundled libs): otherwise silently falls back to CPU (11 tok/s). |
| faster-whisper/CTranslate2 | No ROCm wheel; CPU int8 only. |
| mmcv-dependent stacks (mmpose, 4D-Humans stack) | Not attempted: compiled CUDA/ROCm ops; no value given licence exclusions. |
| co-tracker, monst3r, gaussian-splatting | Licence-excluded, not attempted. |

### Tier C path that needs no body-model licence (decision proposal)

Problem: SMPL / SMPL-X (and everything built on them: HMR2.0/4D-Humans, WHAM, GVHMR, TokenHMR, Multi-HMR...) require registration
and a research-only licence, so they cannot ship in an MIT repo or a product demo path.

Chosen path, which needs neither SMPL nor a mesh at all:

1. **Stylized capsule mannequins** (cylinders/capsules per bone + a sphere head, jersey colour), the vision already allows this.
   These are driven by **3D joint positions (17 H36M joints)**, not by a body model.
2. Joints come from a 2D->3D lifter over our own 2D keypoints (YOLO11-pose COCO-17, tracked): **MotionBERT**
   (Apache-2.0 code, Apache-2.0 weights on HF, H36M 17-joint skeleton, 243-frame window, 0.2-0.6 ms/frame on the GPU, measured).
   Caveat recorded in licenses.md: the weights are trained on Human3.6M, whose dataset licence is academic-only; so MotionBERT
   lives in the replay-side `render/` optional extra (never in courtcam), and weights are never committed.
3. **Licence-clean fallback with zero learned weights** (also the scale/placement step for the MotionBERT output): analytic
   placement from the calibration. Feet/ankle rays intersected with the court plane z=0 give the 2D position in metres; limb
   segments take fixed anthropometric bone lengths (scaled to a per-player height prior, e.g. 1.80 m, refined by the rim/net
   landmarks); the lifter's relative depth ordering (or a simple "arms/legs in image plane, torso upright" pose) decides the
   rest. This is "Tier C-lite": less natural than MotionBERT but entirely ours.
4. Smoothing / foot-contact / ground-plane snapping happen after the lifter in world metres (M9 work).

Rejected alternatives and why: SMPL-family models (licence); GVHMR/WHAM (licence + SMPL); RTMW3D / RTMPose3D (Apache, but needs
mmcv/mmdet; hard on ROCm; also H3WB/H36M-trained); MeTRAbs (MIT code, not evaluated: weights were trained on a mixture of academic datasets, same caveat as MotionBERT without being lighter);
Sapiens (CC-BY-NC).

## 2026-10-06 (later) — Installs, smoke tests, findings

Full table, paths and call snippets: `docs/models.md`. What was learned that changes plans:

- **MIOpen on gfx1201 is unreliable** (LSTM error, conv hang). Every non-ultralytics model must run with
  `torch.backends.cudnn.enabled = False`. A hung job holds `/workspace/airtools/.gpu.lock` for everybody, so always add
  `timeout` inside the `flock`.
- **SAM 2 in bf16 is 10x faster than fp32** (39.6 vs 428 ms/frame, hiera-small, 2560x960). Budget for M8: a 5 s highlight at 30 fps
  with one object per player and hiera-small bf16 is roughly 6 s per player; masks are propagated per object so cost scales
  with player count (unmeasured for multi-object).
- **SAM 2.1 does not need the `sam2` package**: the HF-format weights in the shared cache load with `transformers.Sam2VideoModel`.
- **llama.cpp's ROCm release runs on the GPU only with ROCm 7 libs on `LD_LIBRARY_PATH`**; otherwise it silently uses the CPU
  (11 tok/s instead of ~100). The box has no `/opt/rocm`; torch's bundled libs work via symlinks.
- **Qwen2.5-3B is not Apache** ("Qwen Research"); use Qwen3-4B-Instruct-2507 (Apache-2.0, 93-131 tok/s) or Qwen2.5-7B (80-107 tok/s, 4.4 GB file).
- **Whisper output normalisation**: "Replay clip that." / "Replay Clip Marcus." (commas and case vary), so the trigger matcher normalises.
- **Tier C test input pitfall**: pick standing, moving, fully visible YOLO tracks, not the biggest box (usually a seated spectator or
  a player cut by the frame edge, for whom the lifter returns nonsense).
- **Disk**: /workspace dropped to 13 GB free during the session (other users); the 7B GGUF, Whisper turbo, faster-whisper and the
  official SAM 2 checkpoint were deleted to stay inside the cap. Remaining replay-env footprint for this work is about 8 GB.
- **courtcam is MIT but requires AGPL ultralytics**: a licensing flag, see `docs/licenses.md`.
- Creative-Commons footage search result (details in `docs/test-data.md`): 5 CC BY clips accepted on the box (1 basketball wide cam,
  2 pickleball, 2 badminton with stated limits), none for volleyball; Internet Archive and Wikimedia yielded nothing usable.
