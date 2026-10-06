"""CI drift check: regenerate every committed synthetic golden and compare within
tolerance (not byte equality — float and anti-aliasing details may differ across
machines and OpenCV builds). Regenerate on purpose with
`python samples/synthetic/generate.py --goldens`."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from courtcam.synth import CameraSpec, build_scene, golden_digest

SYNTH = Path(__file__).resolve().parents[2] / "samples" / "synthetic"
GOLDENS = sorted(SYNTH.glob("*/*/golden.json"))
BOX_TOL_PX = 1.5
KP_TOL_PX = 1.5
COURT_TOL_M = 1e-3
VIS_TOL = 0.05
TIME_TOL_S = 1e-3
KEYFRAME_MAD = 2.0  # mean |diff| on 0..255 at 640x360


def _same(a, b, tol: float, where: str = "") -> None:
    """Recursive compare: numbers within `tol`, everything else equal."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and set(a) == set(b), f"{where}: keys {set(a) ^ set(b)}"
        for k in a:
            _same(a[k], b[k], tol, f"{where}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), f"{where}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _same(x, y, tol, f"{where}[{i}]")
    elif isinstance(a, (int, float)) and not isinstance(a, bool):
        assert abs(a - b) <= tol, f"{where}: {a} != {b}"
    else:
        assert a == b, f"{where}: {a!r} != {b!r}"


def test_goldens_exist():
    assert len(GOLDENS) >= 5, "samples/synthetic/<sport>/<variant>/golden.json are committed"


@pytest.fixture(
    scope="module", params=GOLDENS, ids=lambda p: f"{p.parent.parent.name}_{p.parent.name}"
)
def regenerated(request) -> tuple[dict, dict, np.ndarray, Path]:
    golden = json.loads(request.param.read_text(encoding="utf-8"))
    cam = golden["camera"]
    scene = build_scene(
        golden["sport"],
        golden["variant"],
        duration_s=golden["duration_s"],
        fps=golden["fps"],
        size=(golden["width"], golden["height"]),
        seed=golden["seed"],
        camera=CameraSpec(k1=cam["k1"]),
    )
    doc, keyframe = golden_digest(scene, SYNTH / "voice", step=golden["step"])
    return golden, doc, keyframe, request.param.parent


def test_camera_and_script_match(regenerated):
    golden, doc, _, _ = regenerated
    _same(golden["camera"], doc["camera"], 1e-6, "camera")
    for key in ("events", "plays", "triggers", "voice"):
        _same(golden[key], doc[key], TIME_TOL_S, key)
    _same(golden["ball"], doc["ball"], COURT_TOL_M, "ball")


def test_boxes_positions_and_keypoints_match(regenerated):
    golden, doc, _, _ = regenerated
    assert golden["frames"].keys() == doc["frames"].keys()
    for f, rows in golden["frames"].items():
        got = {r["id"]: r for r in doc["frames"][f]}
        assert set(got) == {r["id"] for r in rows}, f"frame {f}: people in frame changed"
        for r in rows:
            g = got[r["id"]]
            _same(r["ct"], g["ct"], COURT_TOL_M, f"{f}/{r['id']}.ct")
            _same(r["bb"], g["bb"], BOX_TOL_PX, f"{f}/{r['id']}.bb")
            _same(r["vis"], g["vis"], VIS_TOL, f"{f}/{r['id']}.vis")
    for f, people in golden["keypoints"].items():
        for pid, kp in people.items():
            a, b = np.asarray(kp), np.asarray(doc["keypoints"][f][pid])
            both = (a[:, 2] > 0) & (b[:, 2] > 0)
            assert np.abs(a[both, :2] - b[both, :2]).max(initial=0) <= KP_TOL_PX, f"{f}/{pid}"
            assert (a[:, 2] > 0).sum() - both.sum() <= 1, f"{f}/{pid}: keypoints left the frame"


def test_audio_envelope_matches(regenerated):
    golden, doc, _, _ = regenerated
    a, b = np.asarray(golden["audio_rms"]), np.asarray(doc["audio_rms"])
    assert a.shape == b.shape
    assert np.all(np.abs(a - b) <= 0.05 * a + 2e-3)


def test_keyframe_matches(regenerated):
    _, _, keyframe, folder = regenerated
    ref = cv2.imread(str(folder / "keyframe.png"))
    assert ref is not None and ref.shape == keyframe.shape
    mad = float(np.abs(ref.astype(np.int16) - keyframe.astype(np.int16)).mean())
    assert mad <= KEYFRAME_MAD, f"keyframe drifted: mean |diff| {mad:.2f}"
