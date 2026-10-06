"""REPLAY_PIPELINE=worker: the adapter hands the game to services/worker."""

from __future__ import annotations

import json

import pytest
from replay_api import pipeline_adapter as adapter

from .conftest import CALIB, FAKE_GAME

worker = pytest.importorskip("replay_worker")


def test_worker_mode_passes_the_game_and_filters_progress(tmp_path, monkeypatch):
    seen = {}

    def fake_run(game_dir, cfg, **kw):
        seen.update(game_dir=game_dir, cfg=cfg, **kw)
        kw["progress"]("detect", 0.5)
        kw["progress"]("game", 1.0)  # worker bookkeeping, not a status-page stage
        (game_dir / "game.json").write_text((FAKE_GAME / "game.json").read_text())
        return []

    monkeypatch.setattr(worker, "run", fake_run)
    game = {
        "id": "g_abc",
        "title": "Real run",
        "sport": "basketball",
        "recorded_at": "2026-09-22T19:30:00-04:00",
        "renditions": None,
        "court": {"variant": "half", "standard": "fiba", "landmarks_px": CALIB["landmarks_px"]},
    }
    stages = []
    keys = adapter.run(
        input_path=tmp_path / "source.mp4",
        out_dir=tmp_path,
        game=game,
        progress=lambda s, f: stages.append((s, f)),
        pipeline="worker",
    )
    cfg = seen["cfg"]
    assert cfg["source"] == str(tmp_path / "source.mp4") and cfg["detector"] == "yolo"
    assert (cfg["sport"], cfg["variant"], cfg["game_id"]) == ("basketball", "half", "g_abc")
    assert cfg["landmarks_px"]["rim"] == [641.1, 583.2]
    json.dumps(cfg)  # the cache key needs a JSON-able config
    assert stages == [("detect", 0.5)]
    assert set(keys) >= {"video", "players", "tracks", "croppaths", "events_url"}
    assert seen["stages"] is None  # no opt-in: the worker's own default DAG


def test_worker_stages_env_adds_opt_in_stages_to_the_defaults(tmp_path, monkeypatch):
    from replay_api.config import from_env
    from replay_worker.stages import load_registry

    monkeypatch.setenv("REPLAY_WORKER_STAGES", " replays, scene ,")
    assert from_env().worker_stages == ("replays", "scene")
    seen = {}

    def fake_run(game_dir, cfg, **kw):
        seen.update(kw)
        (game_dir / "game.json").write_text((FAKE_GAME / "game.json").read_text())
        return []

    monkeypatch.setattr(worker, "run", fake_run)
    game = {"id": "g_abc", "sport": "basketball", "court": {"landmarks_px": CALIB["landmarks_px"]}}
    adapter.run(
        tmp_path / "source.mp4",
        tmp_path,
        game,
        lambda s, f: None,
        pipeline="worker",
        extra_stages=("replays", "scene"),
    )
    defaults = [n for n, s in load_registry().items() if s.default]
    assert defaults and seen["stages"] == [*defaults, "replays", "scene"]
