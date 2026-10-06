"""M8 stages: camera -> plate -> highlights -> segment -> tiera/tierb (per play x angle)
-> replays/<play>/manifest.json, cache-keyed per fan-out item."""

from __future__ import annotations

import dataclasses
import json
import shutil

import numpy as np
import pytest
from replay_worker import Cache, run

pytest.importorskip("replay_render")
if shutil.which("ffmpeg") is None:
    pytest.skip("needs ffmpeg", allow_module_level=True)

from courtcam.profiles import load_profile
from replay_render import testing as toy
from replay_worker.stages import virtual


def _registry():
    # standalone: the toy game dir already holds every courtcam output
    stages = {s.name: s for s in virtual.STAGES}
    for name in ("camera", "highlights"):
        stages[name] = dataclasses.replace(stages[name], after=())
    stages["plate"] = dataclasses.replace(stages["plate"], after=("camera",))
    return stages


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    gd = toy.make_toy_game(tmp_path / "g_toy", duration=14.0)
    calib = json.loads((gd / "calib.json").read_text())
    tpl = load_profile("basketball").template("full")
    names = list(tpl.landmarks)
    px = toy.project(np.column_stack([tpl.landmark_array(names), np.zeros(len(names))]))
    calib.update(
        image_size=[toy.W, toy.H],
        court_polygon_m=tpl.polygon.tolist(),
        landmarks_px={n: p.tolist() for n, p in zip(names, px, strict=True)},
    )
    (gd / "calib.json").write_text(json.dumps(calib))
    for pid in ("p1", "p2", "p3", "p4"):  # a fixed follow-cam window
        doc = {"schema": "replay.crops.v1", "player_id": pid, "rate_hz": 30, "t0": 0.0,
               "rects": [[0.25, 0.25, 0.5, 0.5]] * (14 * 30)}  # fmt: skip
        (gd / "crops" / f"{pid}.json").write_text(json.dumps(doc))
    if "plays.json" in virtual.OPTIONAL:
        (gd / "plays.json").write_text(json.dumps({"schema": "replay.plays.v1", "plays": []}))
    cfg = {"source": str(gd / "media" / "wide.mp4"), "sport": "basketball", "detector": "synthetic",
           "segment_fake": "1", "highlights_n": "1", "replay_width": "320"}  # fmt: skip
    return gd, cfg, Cache(tmp_path / "cache")


def _go(env):
    gd, cfg, cache = env
    return run(gd, cfg, registry=_registry(), stages=["replays"], cache=cache)


def test_fan_out_per_play_and_angle_writes_a_manifest_then_hits(env):
    gd = env[0]
    recs = _go(env)
    items = sorted(r["item"] for r in recs if r["stage"] in ("tiera", "tierb"))
    assert items == sorted(
        f"ev_e1/{a}"
        for a in ("wide", "follow_p1", "tight_p1", "broadcast_high", "orbit", "push_in")
    )
    cal = json.loads((gd / "calibration.json").read_text())
    assert cal["focal_px"] == pytest.approx(toy.K[0, 0], rel=1e-3)  # the toy's true camera
    assert (gd / "plate" / "floor.jpg").is_file()

    m = json.loads((gd / "replays" / "ev_e1" / "manifest.json").read_text())
    assert m["schema"] == "replay.replay_manifest.v1" and m["synthetic"] is True
    assert [a["id"] for a in m["angles"]] == [
        "wide", "follow:p1", "tight:p1", "broadcast_high", "orbit", "push_in"
    ]  # fmt: skip
    assert [a["tier"] for a in m["angles"]] == ["A"] * 3 + ["B"] * 3
    # time-aligned: every angle covers the same window (the TV cuts keep their place)
    durations = {a["duration_s"] for a in m["angles"]}
    assert max(durations) - min(durations) < 0.1
    assert m["t_end"] - m["t_start"] == pytest.approx(max(durations), abs=0.1)
    assert all((gd / a["url"]).stat().st_size > 1000 for a in m["angles"])
    assert next(a for a in m["angles"] if a["id"] == "orbit")["width"] == 320

    again = {(r["stage"], r["item"]): r["cache"] for r in _go(env)}
    assert all(v == "hit" for (s, _), v in again.items() if s != "replays")
    assert again[("replays", "ev_e1")] == "off"
