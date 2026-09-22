from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from courtcam import pipeline
from courtcam.synth import generate

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "samples" / "synthetic" / "basketball_half"


@pytest.fixture(scope="session")
def synthetic_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The checked-in synthetic fixture, regenerated if it is not on disk."""
    if (SAMPLE / "clip.mp4").exists() and (SAMPLE / "ground_truth.json").exists():
        return SAMPLE
    out = tmp_path_factory.mktemp("synth")
    generate(out)
    return out


@pytest.fixture(scope="session")
def pipeline_out(synthetic_clip: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One full pipeline run over the synthetic clip, shared by every test."""
    out = tmp_path_factory.mktemp("out")
    shutil.rmtree(out, ignore_errors=True)
    pipeline.run(
        synthetic_clip / "clip.mp4",
        out,
        detector="synthetic",
        ground_truth=synthetic_clip / "ground_truth.json",
        calib=synthetic_clip / "landmarks.json",
        show_progress=False,
    )
    return out
