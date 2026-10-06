"""M6 stages: director -> cuts.json -> broadcast.mp4, cache-keyed on their inputs."""

from __future__ import annotations

import dataclasses
import json
import shutil

import pytest
from replay_worker import Cache, run

pytest.importorskip("replay_render")
if shutil.which("ffmpeg") is None:
    pytest.skip("needs ffmpeg", allow_module_level=True)

from replay_render.testing import make_toy_game
from replay_worker.stages import broadcast


def _registry():
    # standalone: the toy game dir already holds every upstream output
    director, render = broadcast.STAGES
    return {"director": dataclasses.replace(director, after=()), "broadcast": render}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    gd = make_toy_game(tmp_path / "g_toy", duration=18.0)
    # what courtcam's plays stage writes, when it is registered
    if "score.json" in broadcast.OPTIONAL:
        _score(gd, [[9.0, [2, 0], "e1"]])
    if "plays.json" in broadcast.OPTIONAL:
        (gd / "plays.json").write_text(json.dumps({"schema": "replay.plays.v1", "plays": []}))
    cfg = {"source": str(gd / "media" / "wide.mp4"), "broadcast_size": "320x180",
           "broadcast_crf": 32}  # fmt: skip
    return gd, cfg, Cache(tmp_path / "cache")


def _score(gd, entries):
    rows = [{"t": t, "scores": s, "event_id": e, "source": "auto"} for t, s, e in entries]
    (gd / "score.json").write_text(json.dumps({"schema": "replay.score.v1", "score": rows}))


def _go(env, **kw):
    gd, cfg, cache = env
    recs = run(gd, cfg, registry=_registry(), stages=["broadcast"], cache=cache, **kw)
    return {r["stage"]: r["cache"] for r in recs}


def test_render_is_cached_and_keyed_on_its_inputs(env):
    gd, cfg, _ = env
    assert _go(env) == {"director": "miss", "broadcast": "miss"}
    out = gd / broadcast.RENDITION
    assert out.stat().st_size > 1000
    assert json.loads((gd / "cuts.json").read_text())["schema"] == "replay.cuts.v1"

    assert _go(env) == {"director": "hit", "broadcast": "hit"}

    # a change that does not change the cuts leaves the render a hit
    game = json.loads((gd / "game.json").read_text())
    game["status"] = "ready "
    (gd / "game.json").write_text(json.dumps(game))
    assert _go(env) == {"director": "miss", "broadcast": "hit"}

    # a user score correction reaches the graphics: both recompute
    if "score.json" in broadcast.OPTIONAL:
        _score(gd, [[9.0, [3, 0], "e1"]])
        assert _go(env) == {"director": "miss", "broadcast": "miss"}
        assert json.loads((gd / "cuts.json").read_text())["graphics"]["score"][0]["scores"] == [
            3,
            0,
        ]

    # render params are part of the key
    cfg["broadcast_size"] = "256x144"
    assert _go(env)["broadcast"] == "miss"


def test_stages_are_registered_after_the_game_stage():
    from replay_worker.stages import load_registry

    reg = load_registry()
    assert reg["director"].after == ("game",) and reg["broadcast"].after == ("director",)
    assert not reg["director"].default and not reg["broadcast"].default
