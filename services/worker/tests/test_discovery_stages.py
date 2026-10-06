"""M11 stages: vertical exports fan out per spec and are cache-keyed; hype writes hype.json."""

from __future__ import annotations

import json
import shutil

import pytest
from replay_worker import Cache, run

pytest.importorskip("replay_render")
if shutil.which("ffmpeg") is None:
    pytest.skip("needs ffmpeg", allow_module_level=True)

from replay_render.gamedata import load_game
from replay_render.testing import make_toy_game
from replay_render.vertical import resolve, spec_id
from replay_worker.stages.discovery import VERTICAL_DIR, standalone


@pytest.fixture
def gd(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    return make_toy_game(tmp_path / "g_toy", duration=14.0)


def _spec(gd, **ref):
    spec = resolve(load_game(gd), **ref)
    vid = spec_id(spec)
    (gd / VERTICAL_DIR).mkdir(parents=True, exist_ok=True)
    (gd / VERTICAL_DIR / f"{vid}.json").write_text(json.dumps({**spec, "size": [90, 160]}))
    return vid


def test_vertical_fans_out_per_spec_and_caches(gd, tmp_path):
    cache = Cache(tmp_path / "cache")
    a = _spec(gd, event_id="e1")
    recs = run(gd, {}, registry=standalone("vertical"), stages=["vertical"], cache=cache)
    assert [(r["item"], r["cache"]) for r in recs] == [(a, "miss")]
    assert (gd / VERTICAL_DIR / f"{a}.mp4").stat().st_size > 1000
    b = _spec(gd, t_start=1.0, t_end=3.0, player_id="p2")
    recs = run(gd, {}, registry=standalone("vertical"), stages=["vertical"], cache=cache)
    assert sorted((r["item"], r["cache"]) for r in recs) == sorted([(a, "hit"), (b, "miss")])


def test_hype_stage_writes_the_series(gd, tmp_path):
    (gd / "audio.json").write_text(json.dumps({"schema": "replay.audio.v1", "has_audio": False}))
    (gd / "poses").mkdir()
    (gd / "poses" / "00000.json").write_text(json.dumps({"t0": 0, "frames": []}))
    (gd / "plays.json").write_text(json.dumps({"schema": "replay.plays.v1", "plays": []}))
    recs = run(gd, {}, registry=standalone("hype"), stages=["hype"], cache=Cache(tmp_path / "c"))
    assert recs[0]["status"] == "ok"
    doc = json.loads((gd / "hype.json").read_text())
    assert doc["schema"] == "replay.hype.v1" and len(doc["values"]) == 28
