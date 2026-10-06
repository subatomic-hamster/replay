"""Full camera calibration (M8): K, R, t from the court homography + height landmarks."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from courtcam import calibrate as C
from courtcam import pipeline as P
from courtcam import synth
from courtcam.profiles import load_profile


def _truth(sport: str, variant: str | None, k1: float = 0.0):
    scene = synth.build_scene(sport, variant, duration_s=2.0, camera=synth.CameraSpec(k1=k1))
    return synth.calibration_doc(scene), load_profile(sport), scene.variant


def _fit(doc, profile, variant, clicks):
    floor = {n: v for n, v in clicks.items() if doc["landmarks_world"][n][2] == 0}
    calib = P.calibrate_lens(floor, profile, variant, tuple(doc["image_size"]))
    return C.camera_calibration(calib, profile, clicks)


@pytest.mark.parametrize(
    ("sport", "variant", "k1"),
    [("basketball", "full", 0.0), ("badminton", "doubles", -0.2), ("volleyball", "indoor", 0.0)],
)
def test_exact_clicks_recover_the_true_camera(sport, variant, k1):
    doc, profile, variant = _truth(sport, variant, k1)
    cal = _fit(doc, profile, variant, {n: tuple(v) for n, v in doc["landmarks_px"].items()})
    assert cal["schema"] == "replay.calibration.v1" and not cal["mirrored"]
    assert cal["focal_px"] == pytest.approx(doc["K"][0][0], rel=1e-3)
    dr = cv2.Rodrigues(np.asarray(cal["R"]) @ np.asarray(doc["R"]).T)[0]
    assert np.degrees(np.linalg.norm(dr)) < 0.05
    truth_c = -np.asarray(doc["R"]).T @ np.asarray(doc["t"])
    assert np.linalg.norm(np.asarray(cal["camera_position_m"]) - truth_c) < 0.02
    assert cal["reproj_err_px"] < 0.05
    assert cal["height_landmarks"], "rim / net-post tops are used when clicked"
    # P maps the template's world points onto the (undistorted) clicks
    p = C.camera_matrix(cal)
    w = np.asarray(cal["landmarks_world"]["corner_nl"] + [1.0])
    uv = (p @ w)[:2] / (p @ w)[2]
    assert np.allclose(
        uv,
        P.distortion.undistort_points(
            [cal["landmarks_px"]["corner_nl"]], k1, tuple(doc["image_size"])
        )[0],
        atol=0.05,
    )


def test_noisy_clicks_stay_close():
    doc, profile, variant = _truth("pickleball", "doubles")
    rng = np.random.default_rng(0)
    clicks = {
        n: tuple(np.asarray(v) + rng.normal(0, 1.0, 2)) for n, v in doc["landmarks_px"].items()
    }
    cal = _fit(doc, profile, variant, clicks)
    assert cal["focal_px"] == pytest.approx(doc["K"][0][0], rel=0.02)
    truth_c = -np.asarray(doc["R"]).T @ np.asarray(doc["t"])
    assert np.linalg.norm(np.asarray(cal["camera_position_m"]) - truth_c) < 0.15
    assert cal["reproj_err_px"] < 2.5


def test_mirrored_labels_keep_the_camera_above_the_floor():
    """l/r swapped clicks: a 2D homography takes them, a real camera cannot be below the
    floor — the mirror goes into R (det -1) and P still maps the template's points."""
    doc, profile, variant = _truth("badminton", "doubles")
    swap = {"l": "r", "r": "l"}  # every badminton name ending in l/r is a side
    clicks = {
        n[:-1] + swap.get(n[-1], n[-1]): tuple(v)
        for n, v in doc["landmarks_px"].items()
        if doc["landmarks_world"][n][2] == 0
    }
    calib = P.calibrate_lens(clicks, profile, variant, tuple(doc["image_size"]))
    cal = C.camera_calibration(calib, profile)
    assert cal["mirrored"] and np.linalg.det(np.asarray(cal["R"])) < 0
    assert cal["camera_position_m"][2] > 1.0
    assert cal["reproj_err_px"] < 0.05


def test_height_landmarks_come_from_the_template():
    bb = load_profile("basketball").template("full")
    assert C.height_landmarks(bb) == {
        "rim_top": (0.0, 1.575, 3.05),
        "rim_top_f": (0.0, 26.425, 3.05),
    }
    vb = C.height_landmarks(load_profile("volleyball").template("indoor"))
    assert vb["net_top_l"] == (-4.5, 9.0, 2.43) and vb["net_top_r"] == (4.5, 9.0, 2.43)


def test_focal_from_a_pure_homography():
    doc, _, _ = _truth("volleyball", "indoor")
    h_inv = np.linalg.inv(np.asarray(doc["H"]))
    assert C.focal_from_homography(h_inv, tuple(doc["image_size"])) == pytest.approx(
        doc["K"][0][0], rel=1e-6
    )
