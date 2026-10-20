"""The worker's courtcam stages write exactly what `courtcam.pipeline.run` writes."""

from __future__ import annotations

import filecmp
from pathlib import Path

import pytest
from replay_worker import Cache, run

pipeline = pytest.importorskip("courtcam.pipeline")

SAMPLE = Path(__file__).resolve().parents[3] / "samples" / "synthetic" / "basketball_half"
IDS = {"game_id": "g_synth", "title": "synthetic", "recorded_at": "2026-10-06T00:00:00+00:00"}
PREVIEW = ("storyboard/", "moments", "media/hero.jpg")


def _files(root: Path) -> set[str]:
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != "worker.jsonl"
    }


@pytest.mark.skipif(not (SAMPLE / "clip.mp4").exists(), reason="synthetic sample missing")
def test_worker_matches_pipeline_run_and_second_run_is_all_hits(tmp_path):
    from courtcam.pipeline import load_landmarks

    direct = tmp_path / "direct"
    pipeline.run(
        SAMPLE / "clip.mp4",
        direct,
        detector="synthetic",
        ground_truth=SAMPLE / "ground_truth.json",
        calib=SAMPLE / "landmarks.json",
        show_progress=False,
        **IDS,
    )
    marks, variant = load_landmarks(SAMPLE / "landmarks.json")
    cfg = {
        "source": str(SAMPLE / "clip.mp4"),
        "sport": "basketball",
        "variant": variant,
        "landmarks_px": {k: list(v) for k, v in marks.items()},
        "detector": "synthetic",
        "ground_truth": str(SAMPLE / "ground_truth.json"),
        **IDS,
    }
    cache = Cache(tmp_path / "cache")
    seen: list[str] = []
    first = run(tmp_path / "worker", cfg, cache=cache, progress=lambda s, f: seen.append(s))
    assert {r["cache"] for r in first if r["stage"] != "game"} == {"miss"}
    assert set(pipeline.STAGES) <= set(seen)

    # the worker's own default stages (storyboard, moments) add files courtcam never writes
    a, b = _files(direct), _files(tmp_path / "worker")
    extra = {f for f in b - a if f.startswith(PREVIEW)}
    assert {"storyboard/manifest.json", "moments.json", "media/hero.jpg"} <= extra
    assert a == b - extra
    differ = [f for f in sorted(a) if not filecmp.cmp(direct / f, tmp_path / "worker" / f, False)]
    assert differ == []

    again = run(tmp_path / "worker2", cfg, cache=cache)
    assert {r["stage"]: r["cache"] for r in again} == {
        **dict.fromkeys(pipeline.STAGES, "hit"),
        "game": "off",
        "storyboard": "hit",
        "moments": "hit",
    }
    assert _files(tmp_path / "worker2") == b
