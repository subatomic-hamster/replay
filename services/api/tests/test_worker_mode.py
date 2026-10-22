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
    assert seen.get("stages") is None  # no opt-in: the worker's own default DAG
    assert "asr_model" not in cfg  # no voice triggers unless COURTCAM_ASR_MODEL is set


def test_worker_stages_default_makes_angles_free_view_and_pov(monkeypatch):
    """Unset, every upload gets replay angles, Free view and the Tier C angles with the
    players' virtual POVs; set to "" it gets none."""
    from replay_api.config import from_env
    from replay_worker.stages import load_registry

    monkeypatch.delenv("REPLAY_WORKER_STAGES", raising=False)
    stages = from_env().worker_stages
    assert {"replays", "scene", "tierc_manifest"} <= set(stages)
    assert set(stages) <= set(load_registry())  # names the worker knows
    monkeypatch.setenv("REPLAY_WORKER_STAGES", "")
    assert from_env().worker_stages == ()


def test_worker_stages_env_runs_opt_in_stages_after_the_defaults(tmp_path, monkeypatch):
    """Each opt-in stage runs after the default run, with `moments` (the hero follows
    hype); one that fails leaves the game ready. The ASR model joins the run config."""
    from replay_api.config import from_env

    monkeypatch.setenv("REPLAY_WORKER_STAGES", " replays, condensed, scene ,")
    monkeypatch.setenv("COURTCAM_ASR_MODEL", "openai/whisper-small")
    assert from_env().worker_stages == ("replays", "condensed", "scene")
    calls = []

    def fake_run(game_dir, cfg, **kw):
        calls.append((kw.get("stages"), cfg.get("asr_model")))
        if kw.get("stages") and kw["stages"][0] == "condensed":
            raise RuntimeError("no plays to condense")
        (game_dir / "game.json").write_text((FAKE_GAME / "game.json").read_text())
        return []

    monkeypatch.setattr(worker, "run", fake_run)
    game = {"id": "g_abc", "sport": "basketball", "court": {"landmarks_px": CALIB["landmarks_px"]}}
    keys = adapter.run(
        tmp_path / "source.mp4",
        tmp_path,
        game,
        lambda s, f: None,
        pipeline="worker",
        extra_stages=("replays", "condensed", "scene"),
    )
    assert "video" in keys
    asr = "openai/whisper-small"
    assert calls == [(None, asr), (["replays", "moments"], asr), (["condensed", "moments"], asr),
                     (["scene", "moments"], asr)]  # fmt: skip
