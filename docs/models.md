# Models on hfbox (installed and smoke-tested 2026-10-06)

Everything below was installed and run on hfbox (AMD RX 9070 XT 16 GB, gfx1201, ROCm 7.2, torch 2.14.0+rocm7.2, py3.12) under
`flock /workspace/airtools/.gpu.lock`. Numbers are measured with the throw-away scripts that live on the box in
`/workspace/wt/replay-env/models/smoke_*.py|sh` (not in the repo). Real footage used for pose/SAM/embeddings is
`samples/real` (local-only, never committed); ASR/TTS/speaker tests use synthetic Kokoro speech. Licences: `docs/licenses.md`.
Install log: `/workspace/wt/replay-env/INSTALLS.md`.

## Rules that apply to every GPU model on this box

1. **MIOpen is broken for LSTM and can hang on conv on gfx1201.** Kokoro's LSTM raises `miopenStatusUnknownError`; the first
   Whisper conv call under MIOpen sat at 0% CPU for 20+ minutes holding the GPU lock. Fix for every non-YOLO model:
   `torch.backends.cudnn.enabled = False` before the first call (it also disables MIOpen on ROCm). Cost is small (numbers
   below are with it off). Ultralytics models and SAM 2 (bf16) ran fine with the default.
2. **SAM 2 must run in bf16.** fp32 is ~10x slower on this GPU (see table).
3. Always wrap a smoke or batch job as `flock /workspace/airtools/.gpu.lock timeout <s> <cmd>` so a hang cannot wedge the lock.
4. Venvs (`/workspace/wt/replay-env/venvs/<name>`): own site-packages first, then the shared venv and `/opt/venv` (ROCm torch) via
   `zz_shared.pth`; created by `venvs/mkvenv.sh <name>`. pip run inside them sees torch as already installed, so it never
   reinstalls it. Use `<venv>/bin/python`.

## Summary

| Model | Version / licence | Venv / path | Speed (measured) | VRAM |
|---|---|---|---|---|
| YOLO11m-pose / x-pose, YOLO11m / x det | ultralytics 8.4.170, weights v8.3.0, AGPL-3.0 | shared venv; `models/yolo/*.pt` | m-pose 11.0 ms @960, 14.1 ms @1280; x-pose 19.9 ms @960, 29.6 ms @1280 (2560x960 frame, 7 persons) | 0.26 / 0.29 / 0.53 / 0.62 GB |
| SAM 2.1 video (hiera tiny/small/base+/large) | transformers 5.17 `Sam2VideoModel`, Apache-2.0 | `venvs/sam2`; weights read-only from `/workspace/.hf/hub` (`HF_HUB_CACHE`) | small bf16 39.6 ms/frame, large bf16 74.8 ms/frame (2560x960, 1 box prompt, 60 frames); fp32: 428 / 947 ms | 3.2 / 3.6 GB |
| Whisper small / large-v3-turbo | transformers pipeline, MIT | `venvs/asr`; `hf/` cache | small 0.07 s for a 1.9 s utterance (0.2-0.4 s for 7 s); turbo 0.07 s / 0.15-0.31 s | 0.89 / 1.91 GB |
| faster-whisper small (CPU int8) | 1.2.1 / CTranslate2 4.8.2, MIT | `venvs/asr` | 0.56-0.83 s per 2 s utterance, 0.68 s for 7 s (no ROCm wheel: CPU only) | none |
| Kokoro-82M TTS | kokoro 0.9.4, Apache-2.0 | `venvs/tts`; `hf/` cache | GPU RTF 0.04-0.09, CPU RTF 0.14-0.18 (24 kHz) | not measured (small) |
| LLM: Qwen3-4B-Instruct-2507 Q4_K_M | llama.cpp b11433 HIP build, Apache-2.0 model | `models/llama.cpp/llama-b11433`, `models/gguf/` | 93-131 tok/s generation, 1077-1761 tok/s prompt | not measured (GGUF 2.5 GB + KV) |
| Embeddings: open_clip ViT-B-32 (laion2b), ViT-B-16-SigLIP (webli) | open_clip_torch 3.3.0, MIT / weights MIT, Apache-2.0 | `venvs/emb`; `hf/` cache | 0.32 / 0.58 ms per image (batch 16, fp16) | 0.47 / 0.56 GB |
| Speaker verification: ECAPA-VoxCeleb | speechbrain 1.1.1, Apache-2.0 | `venvs/speaker`; `models/ecapa` | 14-18 ms per 2-4 s utterance | small |
| Wake word: openWakeWord | 0.6.0, Apache-2.0 code, CC-BY-NC-SA models | `venvs/speaker` | 1.4 ms per 80 ms frame (CPU ONNX) | none |
| Tier C lifter: MotionBERT (lite-global, full) | Walter0807/MotionBERT @705d3a9, Apache-2.0 | `venvs/lift`; code `models/src/MotionBERT`; weights `models/motionbert/` | 50 ms / 152 ms per 243-frame window | 0.48 / 0.62 GB |

Not installed (disk cap + licence): Depth-Anything-V2 (only Small is permissive), co-tracker (CC-BY-NC), insightface (weights
research-only), ollama (llama.cpp does the same job), faster-whisper on GPU (needs a ROCm CTranslate2 build that does not exist
as a wheel), rtmlib/RTMPose (permissive 2D pose alternative to AGPL ultralytics: not tried for lack of time).

## How to call

### 2D pose / detection (ultralytics)
```python
from ultralytics import YOLO
m = YOLO("/workspace/wt/replay-env/models/yolo/yolo11m-pose.pt")          # or yolo11x-pose.pt
r = m.predict(frame_bgr, imgsz=1280, device=0, verbose=False)[0]            # r.boxes.xyxy, r.keypoints.xy (N,17,2), .conf
r = m.track(frame_bgr, imgsz=1280, device=0, persist=True, tracker="botsort.yaml", verbose=False)[0]   # r.boxes.id
```
Measured `track` with x-pose @1280 including BoT-SORT: 46-56 ms/frame on the 2560x960 gym clip, 112 ms/frame on the 1920x1080 park clip. 20 frames, 7 persons found on the 2560x960 elevated-gym clip with m-pose and with x-pose alike.

### SAM 2.1 video (box prompt -> masks over a clip)
```python
import torch
from transformers import Sam2VideoModel, Sam2VideoProcessor           # env: HF_HUB_CACHE=/workspace/.hf/hub HF_HUB_OFFLINE=1
mid = "facebook/sam2.1-hiera-small"                                      # tiny | small | base-plus | large (all cached)
model = Sam2VideoModel.from_pretrained(mid, dtype=torch.bfloat16).to("cuda"); proc = Sam2VideoProcessor.from_pretrained(mid)
sess = proc.init_video_session(video=pil_frames, inference_device="cuda", dtype=torch.bfloat16)
proc.add_inputs_to_inference_session(inference_session=sess, frame_idx=0, obj_ids=1, input_boxes=[[[x1, y1, x2, y2]]])
model(inference_session=sess, frame_idx=0)
for o in model.propagate_in_video_iterator(sess):
    mask = proc.post_process_masks([o.pred_masks], original_sizes=[[sess.video_height, sess.video_width]], binarize=True)[0]
```
The official `sam2` package is also installed editable in `venvs/sam2` (`models/src/sam2`, no CUDA extension), but its `.pt`
checkpoints are not downloaded (disk); the transformers path above is the tested one. Session init (60 frames of 2560x960) 1.4-1.7 s.
Smoke note: one tracked player's mask area fell from 2443 px to 586 px when he walked into a cluster (occlusion drift), then
recovered; masks are not perfect through crowding, so cutout rendering should re-prompt on identity changes.

### ASR
```python
import torch; torch.backends.cudnn.enabled = False
from transformers import pipeline
asr = pipeline("automatic-speech-recognition", model="openai/whisper-small", device=0, dtype=torch.float16)
text = asr(wav_16k_float32, generate_kwargs=dict(language="en", task="transcribe"))["text"]
```
Both sizes transcribed "Replay, clip that." / "Replay, clip Marcus." and the 7 s commentary sentence correctly, also with white noise
at 10 dB SNR (synthetic; real crowd noise is harder): outputs came back as "Replay clip that." and "Replay Clip Marcus." (no commas,
random capitalisation), so the fuzzy matcher must normalise case and punctuation. faster-whisper (CPU) gave the same text.
`whisper-small` is the default recommendation (0.9 GB VRAM, fast enough); turbo only if accuracy on real game audio needs it
(its weights were deleted again to save disk, re-download is 1.6 GB).

### TTS
```python
import torch; torch.backends.cudnn.enabled = False                        # mandatory on gfx1201 (LSTM)
from kokoro import KPipeline
pipe = KPipeline(lang_code="a", device="cuda", repo_id="hexgrad/Kokoro-82M")
audio = np.concatenate([a.numpy() for _, _, a in pipe("Replay, clip that.", voice="af_heart")])   # 24 kHz float32
```
Voices tried: af_heart, am_michael, bf_emma. 1.9 s of speech in 0.17 s, 7.1 s in 0.28 s on the GPU (RTF 0.04); CPU RTF 0.14-0.18 is
fast enough as a fallback, which is the default for the synthetic generator if the GPU is busy. Needs the `en_core_web_sm` spaCy
model (installed in the venv) and `espeakng-loader` (GPL espeak-ng, see licenses.md).

### Local LLM with JSON-constrained output
```bash
D=/workspace/wt/replay-env/models/llama.cpp
LD_LIBRARY_PATH=$D/llama-b11433:$D/rocmlibs:/opt/venv/lib/python3.12/site-packages/torch/lib \
  $D/llama-b11433/llama-server -m /workspace/wt/replay-env/models/gguf/Qwen3-4B-Instruct-2507-Q4_K_M.gguf -ngl 99 -c 4096 --port 18081
# OpenAI-compatible: POST /v1/chat/completions with "response_format":{"type":"json_schema","json_schema":{"name":"filter","strict":true,"schema":{...}}}
```
The upstream ROCm tarball does not find the ROCm 7 runtime on this box and silently falls back to CPU (11 tok/s with the 7B model).
`models/llama.cpp/rocmlibs/` holds symlinks (`librocblas.so.5`, `librocsolver.so.0`, `libhipblas.so.3`, `libamdhip64.so.7`) to the libs
bundled in torch; with them `llama-server --list-devices` shows `ROCm0` and generation runs on the GPU. Measured: Qwen3-4B Q4_K_M
93-131 tok/s generation (32-256 tokens), Qwen2.5-7B Q4_K_M 80-107 tok/s (7B file deleted for disk). The grammar-constrained output was
always syntactically valid and honoured the enum schema, e.g. `{"player":"Marcus","sport":"basketball","event":"three_pointer","made":true}`
for "Marcus's made three pointers in basketball". Caveat: the grammar guarantees syntax, not meaning (it also set `"made": true` on
"badminton rallies longer than 10 shots", where `made` is nonsense), so keep the vision's rule: the LLM only fills a schema, a deterministic
validator rejects fields not grounded in the query. Avoid Qwen2.5-3B (Qwen Research licence).

### Embeddings
```python
import torch, open_clip; torch.backends.cudnn.enabled = False
model, _, pre = open_clip.create_model_and_transforms("ViT-B-16-SigLIP", pretrained="webli", device="cuda", precision="fp16")
tok = open_clip.get_tokenizer("ViT-B-16-SigLIP")
fi = model.encode_image(batch_of_preprocessed_images); ft = model.encode_text(tok(["a basketball game on an indoor court"]).cuda())
```
Sanity check on 8 frames each of an indoor basketball clip and a badminton clip (local real footage): the right sport was top text for
the frames inspected (first three of each). Absolute cosine values are small for SigLIP (0.07-0.11), so rank, do not threshold.

### Speaker verification and wake word
```python
from speechbrain.inference.speaker import EncoderClassifier
clf = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", savedir="/workspace/wt/replay-env/models/ecapa", run_opts={"device": "cuda"})
e = clf.encode_batch(wav_16k_tensor[None].cuda())[0, 0]; e = e / e.norm()      # cosine = e1 @ e2
```
On synthetic Kokoro voices (3 voices x 2 utterances): same voice cosine 0.66 / 0.73 / 0.80, different voices -0.02 to 0.29. This only
proves the plumbing and a clear gap; a real threshold needs real enrolment data. openWakeWord runs on CPU through ONNX
(`Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")`, `tflite-runtime` is not needed) but its bundled models are
CC-BY-NC-SA and a custom "Replay" wake word was not trained, so this stays optional/off; the default trigger is ASR + fuzzy match.

### Tier C 3D pose lifter (MotionBERT)
```python
import sys; sys.path.insert(0, "/workspace/wt/replay-env/models/src/MotionBERT")
from lib.utils.tools import get_config; from lib.utils.learning import load_backbone; from lib.utils.utils_data import crop_scale
args = get_config(".../MotionBERT/configs/pose3d/MB_ft_h36m_global_lite.yaml"); model = load_backbone(args)
# weights: hf walterzhu/MotionBERT checkpoint/pose3d/FT_MB_lite_MB_ft_h36m_global_lite/best_epoch.bin  (also FT_MB_release_MB_ft_h36m + MB_ft_h36m.yaml)
sd = torch.load(path, map_location="cpu", weights_only=False)["model_pos"]; model.load_state_dict({k.replace("module.", ""): v for k, v in sd.items()}); model.cuda().eval()
x = torch.from_numpy(crop_scale(coco17_to_h36m17(kp_T_17_3), scale_range=[1, 1]).astype("float32"))[None].cuda()   # (1, 243, 17, 3) = x, y, conf
y3d = model(x)                                                                                                      # (1, 243, 17, 3), H36M joint order
```
Input: a 243-frame window of one tracked person's YOLO COCO-17 keypoints (gaps linearly interpolated, padded), converted to
H36M-17 (pelvis = mid hips, thorax = mid shoulders, spine = mid of both, nose = neck-top, head = mid eyes) and normalised by `crop_scale`.
Output is in normalised units (not metres): scale each person by a height prior and place via calibration (see research-log, Tier C path).
Measured: 50 ms (lite, global) / 152 ms (full, root-relative) per window, i.e. 0.2-0.6 ms per frame per person. On a standing player
from the 1080p park clip the lift gave a plausible upright skeleton with bone-length coefficient of variation 4.2% (lite) / 4.8% (full)
over 243 frames. Pitfall found while testing: the largest YOLO track in the frame is often a seated spectator or a person cut by the
frame bottom, whose lower-body keypoints are hallucinated and give a nonsense skeleton: filter tracks to standing, moving, fully visible
players with confident lower-body keypoints before lifting. This is a pipeline smoke test, not an accuracy evaluation.

## Disk footprint (replay-env)

models 4.1 GB (gguf 2.4, llama.cpp 1.2, yolo 0.3, motionbert 0.2, src 0.1), venvs 1.1 GB, hf 2.7 GB, samples-cc 0.4 GB.
Deleted again: Qwen2.5-7B GGUF (4.4 GB), whisper-large-v3-turbo and faster-whisper-small caches, official SAM 2 checkpoint.
