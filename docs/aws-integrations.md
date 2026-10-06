# AWS integrations

Status (2026-10-06): **nothing calls AWS.** Every provider has a working local
implementation (or a clear `NotConfiguredError`) and a signature-complete AWS stub that
raises `NotImplementedError`. infra/ is a CDK v2 skeleton that synthesizes without
credentials (`cd infra && npm ci && npx cdk synth`) and has never been deployed.

Selection is per provider: `REPLAY_PROVIDER_<NAME>=local|aws` (default `local`;
`services/api/replay_api/providers/__init__.py`). The API's `/healthz` reports the
selected kinds under `provider_kinds`.

## Providers

| provider | local implementation | AWS target | stub | to switch |
|---|---|---|---|---|
| storage | `storage.LocalStorage` — `data/games/{id}/` on disk, served by `/media` with Range | **S3** media bucket (`ReplayData/Media`) | `aws.S3Storage` | key layout `games/{id}/...`; presigned GET URLs in `url()`; the worker needs a local scratch mirror (download inputs, upload outputs); bucket name via env |
| index | `index.LocalIndex` — enumerates `game.json` files | **DynamoDB** `Games` table (+ `by_recorded_at` GSI) | `aws.DynamoIndex` | item schema = game summary; `list` via the GSI; table name via env |
| jobs | `jobs.LocalJobs` — one in-process thread, `data/jobs.json` | **Step Functions** `ReplayPipeline` + **SageMaker Processing** for GPU stages; job records in DynamoDB `Jobs` | `aws.StepFunctionsJobs` | worker container image in ECR; `submit` → StartExecution; stage containers report progress to `Jobs` |
| labeler | `labeler.HeuristicLabeler` | **Bedrock Nova** (video understanding) | `aws.NovaLabeler` | model access in the account/region; clip upload to S3; structured-output prompt |
| query | `query.RuleQueryEngine` (deterministic rule parser); `REPLAY_QUERY=llm` adds `LLMQueryEngine` behind the rules: only text the rules cannot parse reaches the local LLM, which may only fill a json_schema filter that `validate_filter` then checks (D-52) | **Bedrock Converse** (tool use → structured filter only) | `aws.ConverseQueryEngine` | tool schema = the rule engine's filter dict; filter still executed locally |
| tts | `tts.LocalTTS` — Kokoro-82M (Apache-2.0) in the model venv `venvs/tts`, run through the model runner (below); 24 kHz mono 16-bit WAV, default voice `am_michael`. `NotConfiguredError` naming `REPLAY_MODEL_VENVS` when that venv is absent (worker commentary then degrades to captions, D-63) | **Polly** SynthesizeSpeech (neural) | `aws.PollyTTS` | voice choice; PCM→WAV; SSML for pacing |
| llm | `llm.LocalLLM` — client for a llama.cpp `llama-server` running Qwen3-4B-Instruct-2507 Q4_K_M (D-39, D-52); `REPLAY_LLM_URL` points at it (unset → `NotConfiguredError`); temperature 0, seed 0, json_schema-constrained output. Used for commentary paraphrase, advice, card titles and the query filter; every output passes `narrate.grounding.check` or the deterministic template is used | **Bedrock Converse** with a Nova text model | `aws.BedrockLLM` | model id via env; JSON-schema-as-forced-tool; grounding check stays local |
| embeddings | `embeddings.LocalEmbeddings` — open_clip ViT-B-16-SigLIP (`webli`; Apache-2.0) in `venvs/emb` via the model runner; image and text vectors share one L2-normalised space; the worker `embeddings` stage embeds every play in one runner process and `search_index` writes the index (D-52, D-63) | **Bedrock** multimodal embeddings | `aws.BedrockEmbeddings` | model id + dimension; vectors per play under `embeddings/` |
| face | `face.LocalFace` — OpenCV YuNet + SFace, opt-in (`REPLAY_FACE_DIR`, `REPLAY_FACE_MODELS`), one mean embedding per enrolled profile | **Rekognition** face collections (opt-in enrolled profiles only) | `aws.RekognitionFace` | collection per household; consent flow; `forget` on withdrawal (M10) |
| profiles | `profiles.LocalProfiles` — SQLite `data/profiles.sqlite` (profiles + links tables) | **DynamoDB** `Profiles` + `Links` tables | `aws.DynamoProfiles` | conditional PutItem keeps one profile per game player; delete as a transaction over the profile and its links (M10) |
| speaker | `speaker.LocalSpeaker` — SpeechBrain ECAPA-VoxCeleb in `venvs/speaker` via the model runner; opt-in twice over: `NotConfiguredError` until `REPLAY_SPEAKER_DIR` (enrollment store, one mean embedding per profile) and the `speaker` venv exist; `identify` compares only enrolled profiles (cosine threshold 0.5, `REPLAY_SPEAKER_THRESHOLD`, from synthetic voices only); `REPLAY_ECAPA_DIR` overrides the weights dir | **SageMaker endpoint** hosting the local speaker model (no managed AWS speaker-ID service is used) | `aws.SageMakerSpeaker` | endpoint + model container; enrollment vectors in `Profiles` |

Speech-to-text for "Replay, clip that" (Whisper, MIT weights, `courtcam[asr]` via transformers; D-66) is not a provider: it runs inside courtcam's `triggers` stage on the game audio. There is no AWS stub for it (Amazon Transcribe is not wired anywhere).

### Local model runner and its configuration

tts, embeddings and speaker run as `<REPLAY_MODEL_VENVS>/<venv>/bin/python -I providers/_runner.py <kind>` in a subprocess, under `flock <gpu lock> timeout ...` for GPU work, so model dependencies stay out of the API venv and a model crash cannot take the API down (D-39, D-52). The model is reloaded on every call (about 5 to 6 s; ponytail ceiling noted in `_runner.py`). Environment variables (all optional; unset means the provider raises `NotConfiguredError` naming what to set):

| variable | meaning |
|---|---|
| `REPLAY_PROVIDER_<NAME>` | `local` (default) or `aws` per provider |
| `REPLAY_MODEL_VENVS` | directory holding the `tts`, `emb`, `speaker` venvs (box: `/workspace/wt/replay-env/venvs`); nothing defaults to a box path |
| `REPLAY_MODEL_DEVICE` | `cuda` (default) or `cpu` |
| `REPLAY_GPU_LOCK` | GPU lock file (default `/workspace/airtools/.gpu.lock` if it exists) |
| `REPLAY_HF_HOME`, `REPLAY_HF_OFFLINE` | the child's `HF_HOME` (default `<venvs>/../hf`) and `HF_HUB_OFFLINE` (default `1`: never download) |
| `REPLAY_LLM_URL` | llama.cpp server for the llm provider (the server holds the GPU lock while up, so TTS then runs with `REPLAY_MODEL_DEVICE=cpu`, D-52) |
| `REPLAY_QUERY` | `llm` adds the LLM layer behind the rule query engine |
| `REPLAY_SPEAKER_DIR`, `REPLAY_SPEAKER_THRESHOLD`, `REPLAY_ECAPA_DIR` | speaker store, threshold, weights |
| `REPLAY_FACE_DIR`, `REPLAY_FACE_MODELS`, `REPLAY_FACE_THRESHOLD`, `REPLAY_FACE_MIN_PX` | face store, YuNet/SFace ONNX dir, cosine threshold (0.45), minimum face width |

On AWS the same variables are replaced by per-service configuration (bucket, table, state-machine names, model ids) that no stub reads yet; the whole table above has been exercised only against the local implementations. **Nothing ran on AWS.**

All paths are under `services/api/replay_api/providers/`. Tests:
`services/api/tests/test_providers.py` (selection by env, every AWS stub mirrors its
Protocol method-for-method and raises, every local class implements its Protocol).

## Pipeline stages

The worker DAG (`python -m replay_worker dag` → `infra/dag.json`) is the single source;
`infra/lib/pipeline-stack.ts` builds the state machine from it, and CI fails if
`infra/dag.json` drifts from the worker registry.

The registry (`services/worker/replay_worker/stages/__init__.py`, `MODULES`) has 33 stages
from seven modules: courtcam, broadcast, narrate, virtual, discovery, tierc, faces. The
state machine is built only from the stages with `default: true` in `infra/dag.json` (the
14 courtcam pipeline stages below); the other 19 are opt-in locally (`worker run --stages`)
and have no state-machine state yet. A stage is `cpu`, `gpu` or `io`; a `fanout` stage runs
one task per item (per player chunk, play or play x angle). In the CDK stack a non-GPU
stage is a `Pass` placeholder and a GPU stage is a SageMaker Processing
`createProcessingJob` call (CallAwsService, `ml.g5.xlarge`, `ContainerArguments --stages
<name>`); a fan-out stage is wrapped in a `Map` state over `$.items.<stage>` (max
concurrency 1 for GPU, 4 otherwise). Nothing here has been deployed or run on AWS.

| worker stage(s) | resource | local (what runs on the box) | AWS target | to switch |
|---|---|---|---|---|
| ingest, calibrate, track, court, identity, tracks, crops, audio, events, triggers, plays (default) | cpu | courtcam stages wrapped unchanged (ffmpeg ingest, calibration, BoT-SORT tracking, court projection, identity, 16 kHz audio + onsets, event grammars, gesture/voice/tap triggers with Whisper, plays); D-34 | `Pass` placeholders; the target is a CPU Processing job or ECS task per stage | worker container image in ECR; S3 in/out |
| detect (default) | gpu | YOLO11m on ROCm under the box GPU lock | **SageMaker Processing** `createProcessingJob` | ECR image; `.sync` integration via `CustomState`; unique job names |
| pose (default, fan-out) | gpu | YOLO11m-pose on upscaled track crops per chunk; ViTPose-B is opt-in (`courtcam[vitpose]`, D-61) | SageMaker Processing inside a `Map` (concurrency 1) | same; one item per chunk |
| game (default) | io | `game.json` bookkeeping (never cached) | `Pass` placeholder | writes the game item to DynamoDB instead of / as well as S3 |
| director, broadcast | cpu | auto-director cuts and the OpenCV compositor (score bug, replays, telestrator, audio mix); D-42 to D-44 | not in the machine (opt-in) | CPU task |
| commentary | cpu | templates plus the local `llm` and `tts` providers, grounding-checked; degrades to captions when TTS is absent (D-52, D-63) | opt-in; Bedrock Converse (`llm`) + Polly (`tts`) | switch the two providers |
| embeddings, search_index | cpu | local `embeddings` provider (SigLIP) over every play; the index file is rewritten uncached | opt-in; Bedrock multimodal embeddings | switch the provider; vectors under `embeddings/` |
| camera, plate, highlights, tiera, tierb, replays | cpu / io (tiera, tierb, replays fan-out) | Tier A crops, Tier B 2.5D plate + billboards, replay manifests (D-54, D-56) | opt-in; `Map` over plays x angles | CPU task per item |
| segment | gpu, fan-out | SAM 2.1 masks per play (D-55) | opt-in; SageMaker Processing in a `Map` | same |
| tierc_scene, tierc, tierc_manifest | gpu (scene) / cpu / io, fan-out | MotionBERT lift (optional `venvs/lift`, else the analytic fallback) and the capsule-mannequin renderer (D-59) | opt-in; SageMaker Processing for the scene stage | same |
| hype, condensed, vertical | cpu (vertical fan-out) | hype meter, condensed game, 9:16 exports (M11) | opt-in | CPU task |
| face_match | cpu | the local `face` provider (YuNet + SFace), only against enrolled profiles (D-58) | opt-in; Rekognition via the `face` provider | switch the provider |

The worker's content-hash cache maps to S3 (`cache/<stage>/<key>/`), so a re-run in AWS
can skip finished stages the same way; not built yet. The edits overlay (D-63,
`<game>/edits.json`) would have to be re-applied after each restore there as well.

## IAM (infra `ReplayPipeline` stack)

- `ProcessingRole` — assumed by SageMaker; read/write the media bucket and `Jobs`.
- State machine role — `sagemaker:CreateProcessingJob` + `iam:PassRole` on
  `ProcessingRole`; `Jobs` read/write.
- `ApiProvidersPolicy` (managed policy, unattached until the API's host is chosen) —
  Bedrock InvokeModel/Converse, Polly SynthesizeSpeech, Rekognition collection calls,
  `states:StartExecution`, S3 objects, DynamoDB items. Bedrock and Rekognition
  resources are `*` with TODOs to scope them to model / collection ARNs.

## Deploying (not done; checklist)

1. AWS account + region with Bedrock model access (Nova text, multimodal embeddings).
2. `aws configure`; `cd infra && npx cdk bootstrap && npx cdk deploy --all`.
3. Build and push the worker image (services/worker + courtcam + model weights) to ECR;
   `npx cdk deploy -c workerImage=<uri>`.
4. Set `REPLAY_PROVIDER_<NAME>=aws` one provider at a time, with bucket / table /
   state-machine names in env, and implement that stub (each has a TODO).
