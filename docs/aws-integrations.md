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
| query | `query.RuleQueryEngine` (deterministic rules) | **Bedrock Converse** (tool use → structured filter only) | `aws.ConverseQueryEngine` | tool schema = the rule engine's filter dict; filter still executed locally |
| tts | `tts.LocalTTS` → `NotConfiguredError` | **Polly** SynthesizeSpeech (neural) | `aws.PollyTTS` | voice choice; PCM→WAV; the local model is a later milestone (M7) |
| llm | `llm.LocalLLM` → `NotConfiguredError` | **Bedrock Converse** with a Nova text model | `aws.BedrockLLM` | model id via env; JSON-schema-as-forced-tool; grounding check stays local |
| embeddings | `embeddings.LocalEmbeddings` → `NotConfiguredError` | **Bedrock** multimodal embeddings | `aws.BedrockEmbeddings` | model id + dimension; vectors per play under `embeddings/` (M11) |
| face | `face.LocalFace` → `NotConfiguredError` | **Rekognition** face collections (opt-in enrolled profiles only) | `aws.RekognitionFace` | collection per household; consent flow; `forget` on withdrawal (M10) |
| speaker | `speaker.LocalSpeaker` → `NotConfiguredError` | **SageMaker endpoint** hosting the local speaker model (no managed AWS speaker-ID service is used) | `aws.SageMakerSpeaker` | endpoint + model container; enrollment vectors in `Profiles` (M5) |

All paths are under `services/api/replay_api/providers/`. Tests:
`services/api/tests/test_providers.py` (selection by env, every AWS stub mirrors its
Protocol method-for-method and raises, every local class implements its Protocol).

## Pipeline stages

The worker DAG (`python -m replay_worker dag` → `infra/dag.json`) is the single source;
`infra/lib/pipeline-stack.ts` builds the state machine from it, and CI fails if
`infra/dag.json` drifts from the worker registry.

| worker stage | resource | local | AWS target (stub in `pipeline-stack.ts`) | to switch |
|---|---|---|---|---|
| ingest | cpu | ffmpeg in the worker | Pass placeholder → CPU Processing job or ECS task | container image; S3 in/out |
| calibrate | cpu | courtcam | Pass placeholder | same |
| detect | gpu | YOLO11m on ROCm, under the box GPU lock | **SageMaker Processing** `createProcessingJob` (CallAwsService, `ml.g5.xlarge`) | ECR image; `.sync` integration via `CustomState`; unique job names |
| track, court, identity, tracks, crops, events | cpu | courtcam | Pass placeholders | container image |
| game | io | `game.json` bookkeeping (never cached) | Pass placeholder | writes the game item to DynamoDB instead of / as well as S3 |
| *fan-out stages (future)* | any | one task per item | `Map` state over `$.items.<stage>` (max concurrency 1 for GPU) | the stage's item list in the execution input |

The worker's content-hash cache maps to S3 (`cache/<stage>/<key>/`), so a re-run in AWS
can skip finished stages the same way; not built yet.

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
