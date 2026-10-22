"""M9 stages: tierc_scene -> tierc (per play x angle) -> tierc_manifest, on the toy game
with ground-truth keypoints (analytic placement: CPU, no model)."""

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
from replay_render.avatars.skeleton import h36m_to_coco, rest_pose
from replay_worker.stages import tierc, virtual

DUR = 14.0


def _registry():
    stages = {s.name: s for s in virtual.STAGES}
    for name in ("camera", "highlights"):
        stages[name] = dataclasses.replace(stages[name], after=())
    stages["plate"] = dataclasses.replace(stages["plate"], after=("camera",))
    stages.update({s.name: s for s in tierc.STAGES})
    return stages


def _ground_truth(path):
    """Toy players as rest-pose skeletons: keypoints + boxes like the synthetic generator's."""
    frames = []
    for f in range(int(DUR * toy.FPS)):
        rows = []
        for i, (x, y) in enumerate(toy.positions(f / toy.FPS).values(), start=1):
            kp = toy.project(h36m_to_coco(rest_pose(1.85, (x, y), np.pi)))
            (fx, fy), (_, hy) = toy.project(np.asarray([[x, y, 0.0], [x, y, 1.85]]))
            bh = fy - hy
            rows.append({"id": i, "bb": [fx - 0.2 * bh, hy, 0.4 * bh, bh], "ct": [x, y],
                         "kp": [[float(u), float(v), 2] for u, v in kp]})  # fmt: skip
        frames.append({"f": f, "d": rows})
    path.write_text(json.dumps({"synthetic": True, "frames": frames}))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    gd = toy.make_toy_game(tmp_path / "g_toy", duration=DUR)
    calib = json.loads((gd / "calib.json").read_text())
    tpl = load_profile("basketball").template("full")
    names = list(tpl.landmarks)
    px = toy.project(np.column_stack([tpl.landmark_array(names), np.zeros(len(names))]))
    calib.update(image_size=[toy.W, toy.H], court_polygon_m=tpl.polygon.tolist(),
                 landmarks_px={n: p.tolist() for n, p in zip(names, px, strict=True)})  # fmt: skip
    (gd / "calib.json").write_text(json.dumps(calib))
    for pid in ("p1", "p2", "p3", "p4"):
        doc = {"schema": "replay.crops.v1", "player_id": pid, "rate_hz": 30, "t0": 0.0,
               "rects": [[0.25, 0.25, 0.5, 0.5]] * int(DUR * 30)}  # fmt: skip
        (gd / "crops" / f"{pid}.json").write_text(json.dumps(doc))
    if "plays.json" in virtual.OPTIONAL:
        (gd / "plays.json").write_text(json.dumps({"schema": "replay.plays.v1", "plays": []}))
    _ground_truth(tmp_path / "ground_truth.json")
    cfg = {"source": str(gd / "media" / "wide.mp4"), "sport": "basketball", "detector": "synthetic",
           "ground_truth": str(tmp_path / "ground_truth.json"), "segment_fake": "1",
           "highlights_n": "1", "replay_width": "320", "tierc_method": "analytic"}  # fmt: skip
    return gd, cfg, Cache(tmp_path / "cache")


def test_scene_angles_and_manifest_then_cache_hits(env):
    gd, cfg, cache = env
    recs = run(gd, cfg, registry=_registry(), stages=["tierc_manifest"], cache=cache)
    by = {r["stage"]: r for r in recs}
    assert by["tierc_scene"]["resource"] == "cpu"  # ground truth + analytic: no GPU
    items = sorted(r["item"] for r in recs if r["stage"] == "tierc")
    # a virtual POV for every player in the 3D scene, not only the key player
    povs = ("pov_p1", "pov_p2", "pov_p3", "pov_p4")
    # image-based (D-86): no baseline, it would face the toy's sideline camera head-on
    assert items == sorted(f"ev_e1/tierc_{a}" for a in ("wing", "courtside", *povs))

    doc = json.loads((gd / "scene" / "ev_e1.json").read_text())
    assert doc["schema"] == "replay.scene.v1" and doc["method"] == "analytic"
    assert len(doc["players"]) == 4 and doc["synthetic"] is True
    j = np.array([fr for fr in doc["players"][0]["joints"] if fr is not None])
    assert j.shape[1:] == (17, 3) and len(j) > 0.9 * doc["frames"]
    assert abs(doc["players"][0]["height_m"] - 1.85) < 0.1
    q = doc["quality"]
    assert q["foot_slide_cms"]["after"] <= q["foot_slide_cms"]["before"] + 1e-6
    ball = doc["ball"]
    assert ball["made"] is True and ball["target"][2] == pytest.approx(3.05)

    m = json.loads((gd / "replays" / "ev_e1" / "manifest.json").read_text())
    assert [a["tier"] for a in m["angles"]] == ["A"] * 3 + ["B"] * 3 + ["C"] * 6
    c = [a for a in m["angles"] if a["tier"] == "C"]
    assert [a["id"] for a in c] == ["3d:wing", "3d:courtside", "pov:p1", "pov:p2", "pov:p3",
                                    "pov:p4"]  # fmt: skip
    assert c[0]["label"] == "Virtual wing"
    # every angle has its own thumbnail (the TV's angle row), not one shared frame
    assert all((gd / a["poster"]).stat().st_size > 500 for a in m["angles"])
    assert len({(gd / a["poster"]).read_bytes() for a in c}) == len(c)
    ids = [a["id"] for a in m["angles"]]
    assert len(ids) == len(set(ids))  # a TV focuses and keys angles by id
    assert {a["duration_s"] for a in m["angles"]} == {m["angles"][0]["duration_s"]}  # aligned
    assert c[2]["label"] == "Virtual POV · Avery"  # the key player (shooter) first

    again = run(gd, cfg, registry=_registry(), stages=["tierc_manifest"], cache=cache)
    assert {r["cache"] for r in again if r["stage"] in ("tierc_scene", "tierc")} == {"hit"}
    m2 = json.loads((gd / "replays" / "ev_e1" / "manifest.json").read_text())
    assert m2["angles"] == m["angles"]
