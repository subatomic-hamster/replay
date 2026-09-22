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

    @property
    def games_dir(self) -> Path:
        return self.data_dir / "games"

    @property
    def jobs_state_path(self) -> Path:
        return self.data_dir / "jobs.json"


def from_env(**overrides) -> Settings:
    env = os.environ.get
    s = Settings(
        api_key=env("REPLAY_API_KEY") or None,
        storage=env("REPLAY_STORAGE", "local"),
        jobs=env("REPLAY_JOBS", "local"),
        labeler=env("REPLAY_LABELER", "heuristic"),
        query=env("REPLAY_QUERY", "rules"),
        data_dir=Path(env("REPLAY_DATA_DIR") or REPO_ROOT / "data").expanduser(),
        cors_origins=[o.strip() for o in env("REPLAY_CORS_ORIGINS", "*").split(",") if o.strip()],
        pipeline=env("REPLAY_PIPELINE", "courtcam"),
        fake_pipeline_dir=Path(
            env("REPLAY_FAKE_PIPELINE_DIR") or PKG_ROOT / "fixtures" / "fake_game"
        ).expanduser(),
        fake_pipeline_delay_s=float(env("REPLAY_FAKE_PIPELINE_DELAY_S") or 0.0),
        detector=env("REPLAY_DETECTOR", "yolo"),
    )
    return s if not overrides else Settings(**{**s.__dict__, **overrides})
