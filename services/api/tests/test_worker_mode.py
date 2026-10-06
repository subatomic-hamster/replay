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
