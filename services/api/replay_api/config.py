"""Settings from environment (plan §12 rule 8). No pydantic-settings; os.environ is enough."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PKG_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    api_key: str | None = None  # REPLAY_API_KEY unset -> auth disabled
    storage: str = "local"
    jobs: str = "local"
    labeler: str = "heuristic"
    query: str = "rules"
    data_dir: Path = field(default_factory=lambda: REPO_ROOT / "data")
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    pipeline: str = "courtcam"  # "courtcam" (falls back to fake) | "fake"
    fake_pipeline_dir: Path = field(default_factory=lambda: PKG_ROOT / "fixtures" / "fake_game")
    # fake mode finishes in seconds; a delay per stage makes `running` observable (S-08)
    fake_pipeline_delay_s: float = 0.0
    detector: str = "yolo"
    # D-23: "auto" | "vlm" | "claude-cli" | "lines" | "fake". Left at "auto",
    # `pipeline="fake"` downgrades it to "fake" so tests never call a model.
    autocalib_backend: str = "auto"
    # REPLAY_WORKER_STAGES="replays,scene": opt-in worker stages (default=False in the
    # worker, D-56/D-75) run on every upload after the default ones; worker pipeline only.
    worker_stages: tuple[str, ...] = ()
    # D-80 cloud mode (REPLAY_STORAGE=s3 + REPLAY_JOBS=s3, docs/aws-migration.md). The
    # three secrets come from SSM under `ssm_prefix` when it is set, else from env.
    s3_bucket: str | None = None
    ssm_prefix: str | None = None
    public_web_base: str | None = None
    worker_key: str | None = None
    upload_token_secret: str | None = None

    @property
    def cloud(self) -> bool:
        return self.storage == "s3"

    @property
    def games_dir(self) -> Path:
        return self.data_dir / "games"

    @property
    def jobs_state_path(self) -> Path:
        return self.data_dir / "jobs.json"


def from_env(**overrides) -> Settings:
    env = os.environ.get
    storage = env("REPLAY_STORAGE", "local")
    # cloud mode's data dir is only a scratch mirror; Lambda can write nowhere but /tmp
    default_data = Path("/tmp/replay") if storage == "s3" else REPO_ROOT / "data"
    s = Settings(
        api_key=env("REPLAY_API_KEY") or None,
        storage=storage,
        jobs=env("REPLAY_JOBS", "local"),
        labeler=env("REPLAY_LABELER", "heuristic"),
        query=env("REPLAY_QUERY", "rules"),
        data_dir=Path(env("REPLAY_DATA_DIR") or default_data).expanduser(),
        cors_origins=[o.strip() for o in env("REPLAY_CORS_ORIGINS", "*").split(",") if o.strip()],
        pipeline=env("REPLAY_PIPELINE", "courtcam"),
        fake_pipeline_dir=Path(
            env("REPLAY_FAKE_PIPELINE_DIR") or PKG_ROOT / "fixtures" / "fake_game"
        ).expanduser(),
        fake_pipeline_delay_s=float(env("REPLAY_FAKE_PIPELINE_DELAY_S") or 0.0),
        detector=env("REPLAY_DETECTOR", "yolo"),
        autocalib_backend=env("REPLAY_AUTOCALIB_BACKEND", "auto"),
        worker_stages=tuple(
            s.strip() for s in env("REPLAY_WORKER_STAGES", "").split(",") if s.strip()
        ),
        s3_bucket=env("REPLAY_S3_BUCKET") or None,
        ssm_prefix=env("REPLAY_SSM_PREFIX") or None,
        public_web_base=env("REPLAY_PUBLIC_WEB_BASE") or None,
        worker_key=env("REPLAY_WORKER_KEY") or None,
        upload_token_secret=env("REPLAY_UPLOAD_TOKEN_SECRET") or None,
    )
    return s if not overrides else Settings(**{**s.__dict__, **overrides})
