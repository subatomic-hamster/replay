# Licenses of components and weights

Verified 2026-10-06 against the upstream LICENSE files / READMEs / Hugging Face model cards (sources in
`docs/research-log.md`). "Allowed in MIT courtcam?" means: may courtcam (the MIT library that gets split into its own
public repo) vendor it, or depend on it as a *required* dependency? Anything marked "extra" lives behind an optional
extra or in the replay-side packages (`render/`, `services/worker`, `services/api` providers) and is not vendored.
Code licence and weights licence are listed separately because they often differ.

Rule of thumb used below: permissive (MIT / BSD / Apache-2.0 / ISC) = yes. Copyleft (GPL / AGPL) = never vendored; may be
run as a separate process or be an opt-in extra. Non-commercial / research-only (CC-BY-NC, Inria, SMPL, InsightFace
models, Qwen-research) = no, not even as a default; at most an opt-in extra that is off by default, or not used at all.

## Table

| Component | Code licence | Weights licence | Where used | Allowed in MIT courtcam? | Optional extra? |
|---|---|---|---|---|---|
| ultralytics (YOLO11 det / pose) | AGPL-3.0 | AGPL-3.0 (Ultralytics weights; enterprise licence exists) | courtcam detect/pose/track today (D-5, D-31) | **Flag.** Currently a hard dependency of `courtcam` (pyproject). Not vendored, but anyone shipping a combined app must comply with AGPL. Recommend: make it the `courtcam[yolo]` extra and keep a permissive detector path (see "Permissive 2D pose / detection" in research-log) | Yes (should become) |
| Barlow Condensed (font) | SIL OFL 1.1 (google/fonts) | n/a | render/replay_render/assets (broadcast graphics), OFL.txt bundled | Not needed there (replay-side render/) | No (bundled asset) |
| boxmot (BoT-SORT, etc. as a package) | AGPL-3.0 | n/a (ReID weights have their own, mostly research licences) | not used (ultralytics ships BoT-SORT / ByteTrack) | No | Not planned |
| ByteTrack (FoundationVision, ex-ifzhang) | MIT | MIT (COCO/MOT weights; not used) | ultralytics' built-in ByteTrack tracker config | Yes (algorithm re-implemented in ultralytics, which is AGPL) | n/a |
| supervision (roboflow) | MIT | n/a | optional overlays / zones | Yes | n/a |
| roboflow/sports | MIT | MIT code; trained-model weights are separate Roboflow downloads: check each before use | reference only (court keypoint ideas) | Yes (code), weights not used | n/a |
| mmpose / RTMPose / RTMDet (OpenMMLab) | Apache-2.0 | Apache-2.0 | candidate permissive pose; needs mmcv (hard on ROCm) | Yes | Yes (via `rtmlib`, below) |
| rtmlib (Tau-J) | Apache-2.0 | Apache-2.0 (RTMPose / RTMO ONNX) | candidate permissive 2D pose on onnxruntime, no mmcv | Yes | Yes |
| deep-person-reid (torchreid) | MIT | model-zoo weights trained on Market1501/MSMT17/etc. (dataset terms are research-only) | candidate appearance re-ID | Code yes; weights **no** by default | Yes |
| SAM 2 / SAM 2.1 (facebookresearch) | Apache-2.0 | Apache-2.0 (`facebook/sam2.1-hiera-*`) | segmentation for cutouts (Tier B) | Yes | Yes (heavy dep, replay-side `render/`) |
| co-tracker | CC-BY-NC-4.0 (mostly) | CC-BY-NC-4.0 | not used | **No** | No |
| Depth-Anything-V2 | Apache-2.0 (code) | **Small: Apache-2.0. Base/Large/Giant: CC-BY-NC-4.0** | optional depth for court plate / Tier B | Small only | Yes (Small only) |
| SoccerNet/sn-calibration | **no LICENSE file in repo** (all rights reserved by default) | n/a | reference only (calibration-metric ideas); own OpenCV `solvePnP` code instead | No (do not vendor) | No |
| OpenCV (`solvePnP`, `calibrateCamera`) | Apache-2.0 | n/a | calibration | Yes | n/a |
| SMPL / SMPL-X / smplx | smplx repo: "non-commercial scientific research" licence | SMPL/SMPL-X body models: registration + research-only licence | **not used** (Tier C uses capsule mannequins, see research-log) | **No** | **No** (explicitly out) |
| 4D-Humans / HMR2.0 | MIT | HMR2 checkpoint needs SMPL neutral model (research licence) | not used | No (SMPL dependency) | No |
| WHAM | MIT | needs SMPL/SMPL-X, trained on AMASS (non-commercial) | not used | No | No |
| GVHMR | custom "educational, research and non-profit only", derivative works must be open and non-commercial | same | not used | **No** | No |
| MotionBERT (Walter0807) | Apache-2.0 | Apache-2.0 (LICENSE file in `walterzhu/MotionBERT` HF repo). Trained on Human3.6M, whose dataset licence is academic-use only: derived-weights status is unsettled, so treated as "research-grade weights" | Tier C 2D->3D skeleton lifter (replay-side): `render/replay_render/avatars/lift.py` runs it as a subprocess in the box's `venvs/lift`, never imported by courtcam or the worker | Code yes; weights **keep out of courtcam** | **Yes**: optional, used only when `venvs/lift` + checkpoint exist (`tierc_method=auto`); `tierc_method=analytic` (`avatars/place.py`, rays + bone lengths, no learned weights) is the licence-clean fallback |
| TrackNetV3 (qaz812345) | MIT (licence text explicitly covers "pretrained model checkpoints") | MIT | badminton/pickleball shuttle/ball tracking (stretch) | Yes | Yes |
| gaussian-splatting (Inria/MPII) | Inria non-commercial research licence | same | Tier D experiments only | **No** | Experiments only, never shipped; permissive alternative: gsplat (Apache-2.0) |
| shape-of-motion | MIT | depends on third-party models (check each) | Tier D experiment | Code yes | Experiments only |
| monst3r / dust3r | CC-BY-NC-SA-4.0 | CC-BY-NC-SA-4.0 | Tier D experiment at most | **No** | Experiments only, never shipped |
| MoGe-2 (`microsoft/MoGe`; deps utils3d_moge, pipeline) | MIT | MIT (`Ruicheng/moge-2-vitl-normal`) | Tier D experiment (`experiments/tierd-pointmaps`); candidate plate-lifting stage | Not needed there (replay-side) | Yes (shippable) |
| VGGT (facebookresearch) | Meta "VGGT License" v1 (custom, with acceptable-use policy) | **CC-BY-NC-4.0** (`facebook/VGGT-1B`); `VGGT-1B-Commercial` is gated (not downloaded) | Tier D experiment only (`experiments/tierd-vggt-static`) | **No** | Experiments only, never shipped |
| gsplat-amd (AMD-Ecosystem) | Apache-2.0 | n/a | candidate for dynamic splats; needs the ROCm HIP SDK (not on the box), not installed | Yes | Not installed |
| 4DGaussians | Apache-2.0 code, but Inria-derived non-commercial CUDA rasteriser submodules | n/a | not used | **No** | No |
| librosa | ISC | n/a | audio onsets / hype detection | Yes | n/a |
| PyAV | BSD-3-Clause | n/a (links FFmpeg LGPL build in wheels) | ingest | Yes | n/a |
| FFmpeg static build with libx264 | GPL (libx264 / `--enable-gpl` build) | n/a | rendering on the box; run as subprocess only | Do not vendor the binary; call `ffmpeg` on PATH | n/a |
| OpenAI Whisper | MIT | MIT (all sizes; `openai/whisper-*`) | ASR for "Replay, clip that" | Yes | Yes (heavy) |
| faster-whisper | MIT | MIT (CTranslate2 conversions) | CPU ASR fallback (CTranslate2 has no ROCm wheel) | Yes | Yes |
| openWakeWord | Apache-2.0 | **CC-BY-NC-SA-4.0** (all bundled pre-trained models; training data of mixed licence) | optional wake word | Code yes; models **no** | Opt-in only; default path is "ASR + fuzzy match", no wake-word model |
| speechbrain | Apache-2.0 | `speechbrain/spkrec-ecapa-voxceleb`: Apache-2.0 on the model card (trained on VoxCeleb, whose terms are research-only: flag) | opt-in speaker verification / enrolment | Code yes; weights keep replay-side | Yes (opt-in, enrolled users only) |
| Kokoro-82M + `kokoro` package | Apache-2.0 | Apache-2.0 | local TTS (commentary, synthetic "Replay, clip that") | Yes | Yes (replay-side `tts` provider) |
| misaki (Kokoro G2P) / espeak-ng (via `espeakng-loader`) | misaki Apache-2.0; **espeak-ng GPL-3.0** | n/a | out-of-vocabulary fallback inside Kokoro | No for espeak-ng | Replay-side only, as a loaded shared library; swap to a different G2P if distributing a binary |
| Piper (rhasspy/piper) | MIT, **archived 2025-08-26** | per-voice licences (many MIT / CC0 / CC-BY, some NC: check each) | superseded | n/a | n/a |
| piper1-gpl (OHF-Voice, maintained successor) | **GPL-3.0** | per-voice | optional alt TTS as a separate process | No | Optional, separate process |
| ollama | MIT | n/a | optional LLM server | Yes | Optional |
| llama.cpp | MIT | n/a | local LLM server (HIP build) | Yes | Yes |
| Qwen2.5-7B-Instruct | Apache-2.0 | Apache-2.0 | local LLM for structured filters / commentary | Yes | Yes |
| Qwen2.5-3B-Instruct | n/a | **"Qwen Research" licence (not Apache)** | not used | No | No |
| open_clip | MIT | model-dependent: LAION OpenCLIP checkpoints MIT; OpenAI CLIP MIT-style | semantic search embeddings | Yes | Yes |
| SigLIP / SigLIP2 (`google/siglip*`) | Apache-2.0 | Apache-2.0 | semantic search embeddings (transformers) | Yes | Yes |
| insightface | MIT | **non-commercial research only for all downloadable models** (buffalo_l, antelopev2, inswapper...) | **not used** (rejected for M10 face enrolment) | Code yes; weights **no** | No; commercial path = Rekognition provider |
| YuNet face detector (OpenCV Zoo `face_detection_yunet_2023mar.onnx`, libfacedetection.train) | MIT | MIT (LICENSE in the model dir; 232 KB) | opt-in face enrolment / matching (M10, `providers/face.py`), run through OpenCV's built-in `cv2.FaceDetectorYN` | Not needed (replay-side API provider) | **Yes: off by default**, weights downloaded to the box (`models/face/`), never vendored |
| SFace face recogniser (OpenCV Zoo `face_recognition_sface_2021dec.onnx`) | Apache-2.0 | **Apache-2.0** (LICENSE in the model dir; 38 MB). Caveat: the training set of this checkpoint is not documented upstream (the SFace paper trains on CASIA-WebFace / VGGFace2 / MS1MV2, all research-only datasets; open questions opencv_zoo#313, #318), so it is treated like MotionBERT: licence-clean weights with a training-data flag | opt-in face enrolment / matching (M10) via `cv2.FaceRecognizerSF` | Not in courtcam | **Yes: off by default** (needs `REPLAY_FACE_DIR` + `REPLAY_FACE_MODELS`); commercial path = Rekognition provider |
| pyrender | MIT | n/a | Tier B/C offscreen rendering (EGL) | Yes | Yes (`render/`) |
| trimesh | MIT | n/a | mesh handling | Yes | Yes |
| Blender | GPL-3.0 | n/a | optional headless renderer, separate process only | No (not linked) | Optional, separate process |
| three.js | MIT | n/a | web viewers / compositor experiments | Yes | n/a |
| react-native-tvos | MIT | n/a | TV app | n/a (apps/tv) | n/a |
| react-native-video (TheWidlarzGroup, ex-react-native-community) | MIT | n/a | TV player | n/a (apps/tv) | n/a |
| yt-dlp | Unlicense | n/a | dev tool for fetching test footage | n/a (dev only) | n/a |

## Footage and data

See `docs/test-data.md`. In short: `samples/real/*` is standard-YouTube-licence footage for local testing only (D-7),
never committed or shown in committed evidence. Creative-Commons clips (with attribution recorded in test-data.md)
may appear in committed evidence/demo assets. Synthetic data is ours.

## Actions this implies

1. `courtcam` currently lists `ultralytics` (AGPL-3.0) as a required dependency: move to an extra / make the detector
   backend pluggable before the subtree-split public release, or state the AGPL implication in the courtcam README.
2. Tier C must not import SMPL/SMPL-X; mannequins are capsules driven by 3D joints (research-log, "Tier C path").
3. Wake word and face/voice ID stay opt-in and off by default; their weights are research-only or have training-data
   caveats.
