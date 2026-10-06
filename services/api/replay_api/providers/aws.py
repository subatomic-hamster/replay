"""AWS implementations — signature-complete stubs, nothing calls AWS yet.

Each class mirrors its Protocol method for method and raises NotImplementedError naming
the target service. Selected with `REPLAY_PROVIDER_<NAME>=aws`. Config will come from env
vars (bucket/table/state-machine names, region) — never from the repo. The CDK skeleton
that creates the resources is infra/; the switch-over checklist is
docs/aws-integrations.md.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def _todo(service: str, what: str) -> NotImplementedError:
    return NotImplementedError(f"{service}: {what} is a stub (TODO, docs/aws-integrations.md)")


class S3Storage:
    """Target: Amazon S3 (media bucket from infra `ReplayData`).

    TODO: `game_dir`/`path` become key prefixes (`games/{id}/...`) with a local scratch
    mirror for the worker; `read_json`/`write_json` → GetObject/PutObject; `url` →
    presigned GET (or CloudFront) instead of the API's `/media` route.
    """

    def game_dir(self, game_id: str) -> Path:
        raise _todo("S3", "game_dir")

    def path(self, game_id: str, rel: str) -> Path:
        raise _todo("S3", "path")

    def read_json(self, game_id: str, rel: str) -> dict:
        raise _todo("S3", "read_json")

    def write_json(self, game_id: str, rel: str, data: dict) -> None:
        raise _todo("S3", "write_json")

    def url(self, game_id: str, rel: str, base: str) -> str:
        raise _todo("S3", "url")


class DynamoIndex:
    """Target: Amazon DynamoDB `games` table (partition key `id`).

    TODO: one item per game holding the `game.json` summary fields; `list` → Query on a
    `recorded_at` GSI rather than Scan; `save` → PutItem with a version attribute.
    """

    def new_id(self) -> str:
        raise _todo("DynamoDB", "new_id")

    def create(self, title: str, sport: str) -> dict:
        raise _todo("DynamoDB", "create")

    def load(self, game_id: str) -> dict | None:
        raise _todo("DynamoDB", "load")

    def save(self, game: dict) -> None:
        raise _todo("DynamoDB", "save")

    def list(self) -> list[dict]:
        raise _todo("DynamoDB", "list")


class StepFunctionsJobs:
    """Target: AWS Step Functions (state machine `ReplayPipeline`, mirroring the worker
    DAG) with GPU stages as SageMaker Processing jobs; job records in the DynamoDB `jobs`
    table.

    TODO: `submit` → StartExecution with `{game_id, kind}` (the in-process `fn` is not
    shipped: the state machine runs the worker's stages); `get`/`for_game` → the `jobs`
    table (GSI on `game_id`); `progress` → UpdateItem from the stage containers.
    """

    def submit(self, kind: str, game_id: str, fn: Callable[[str], None]) -> dict:
        raise _todo("Step Functions", "submit")

    def get(self, job_id: str) -> dict | None:
        raise _todo("Step Functions", "get")

    def for_game(self, game_id: str) -> list[dict]:
        raise _todo("Step Functions", "for_game")

    def progress(self, job_id: str, stage: str, fraction: float) -> None:
        raise _todo("Step Functions", "progress")


class NovaLabeler:
    """Target: Amazon Bedrock, Nova (video understanding) via InvokeModel/Converse.

    TODO: send the shot clip (S3 URI) + the detector's hint, accept only the structured
    `{is_shot, made, shooter_player_id, confidence}` answer; low confidence → review queue.
    """

    def label_shot(self, clip_path: Path, hint: dict) -> dict:
        raise _todo("Bedrock Nova", "label_shot")


class ConverseQueryEngine:
    """Target: Amazon Bedrock Converse (tool use) turning free text into the rule
    engine's structured filter only — never timestamps (vision §22).

    TODO: tool schema = the filter dict `RuleQueryEngine` understands; execute the filter
    locally against `events`.
    """

    def query(self, text: str, game: dict, events: list[dict]) -> dict:
        raise _todo("Bedrock Converse", "query")


class PollyTTS:
    """Target: Amazon Polly (SynthesizeSpeech, neural voices) for commentary audio.

    TODO: PCM 16 kHz → WAV at `out_path`; SSML for pacing; voice from `voice` or env.
    """

    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None) -> Path:
        raise _todo("Polly", "synthesize")


class BedrockLLM:
    """Target: Amazon Bedrock Converse with a Nova text model.

    TODO: `json_schema` → a single forced tool whose input schema it is; return the tool
    input as JSON text. Grounding check stays on our side.
    """

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: dict | None = None,
        max_tokens: int = 512,
    ) -> str:
        raise _todo("Bedrock Converse", "complete")


class BedrockEmbeddings:
    """Target: Amazon Bedrock multimodal embeddings (text + image in one space).

    TODO: batch InvokeModel calls; persist vectors per play next to `embeddings/`.
    """

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise _todo("Bedrock embeddings", "embed_texts")

    def embed_images(self, paths: list[Path]) -> list[list[float]]:
        raise _todo("Bedrock embeddings", "embed_images")


class RekognitionFace:
    """Target: Amazon Rekognition face collections — opt-in enrolled profiles only.

    TODO: `enroll` → IndexFaces into a per-household collection with ExternalImageId =
    profile_id; `identify` → SearchFacesByImage over that collection only; `forget` →
    DeleteFaces (consent withdrawal).
    """

    def enroll(self, profile_id: str, images: list[Path]) -> dict:
        raise _todo("Rekognition", "enroll")

    def identify(self, image: Path, *, min_similarity: float = 0.8) -> list[dict]:
        raise _todo("Rekognition", "identify")

    def forget(self, profile_id: str) -> None:
        raise _todo("Rekognition", "forget")


class SageMakerSpeaker:
    """Target: a SageMaker endpoint hosting the local speaker-embedding model (no managed
    AWS speaker-identification service is used; Amazon Transcribe diarization only labels
    speakers, it does not identify them).

    TODO: enrollment vectors in the DynamoDB `profiles` table; cosine match server-side.
    """

    def enroll(self, profile_id: str, clips: list[Path]) -> dict:
        raise _todo("SageMaker endpoint", "enroll")

    def identify(self, audio: Path, t_start: float, t_end: float) -> list[dict]:
        raise _todo("SageMaker endpoint", "identify")

    def forget(self, profile_id: str) -> None:
        raise _todo("SageMaker endpoint", "forget")
