"""The one-parameter lens model (D-24): recoverable, invertible, and off by default.

Every assertion here is about *not* changing the undistorted path. A 1x lens must land
on `k1 = 0` and the byte-for-byte old `calibrate()` payload, or shipping the model
enabled by default would quietly move every existing calibration.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from courtcam import pipeline
from courtcam.calibrate import calibrate, project
from courtcam.court import POLYGON_STEP_M, polygon_px
from courtcam.distortion import (
    MIN_POINTS,
    distort_points,
    estimate_k1,
    reprojection_rms,
    undistort_points,
)
from courtcam.profiles import load_profile
from courtcam.synth import make_camera

SIZE = (1280, 720)
BASKETBALL = load_profile("basketball")
BADMINTON = load_profile("badminton")


def _ideal(profile, variant: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Landmark pixels from a known pinhole camera — no lens, so the truth is `k1 = 0`."""
    template = profile.template(variant)
    cam = make_camera(template, SIZE, np.zeros((0, 2)))
    names = sorted(template.landmarks)
    metres = template.landmark_array(names)
    return cam.ground(metres), metres, names


@pytest.mark.parametrize("k1", [-0.45, -0.2, 0.0, 0.15])
def test_distort_is_the_exact_inverse_of_undistort(k1: float):
    pts = np.array([[0.0, 0.0], [640.0, 360.0], [1279.0, 719.0], [40.0, 700.0], [900.0, 10.0]])
    back = distort_points(undistort_points(pts, k1, SIZE), k1, SIZE)
    assert np.allclose(back, pts, atol=1e-9)


@pytest.mark.parametrize("k1_true", [-0.45, -0.25, -0.10])
def test_a_known_k1_is_recovered_within_five_percent(k1_true: float):
    px, metres, _ = _ideal(BADMINTON, "doubles")
    bent = distort_points(px, k1_true, SIZE)
    assert len(bent) >= MIN_POINTS
    # the lens really did bend the court: a plain homography no longer sits on it
    assert reprojection_rms(bent, metres, 0.0, SIZE) > 1.5

    k1, before, after = estimate_k1(bent, metres, SIZE)
    assert abs(k1 - k1_true) <= 0.05 * abs(k1_true), f"recovered {k1} for {k1_true}"
    assert after < 0.05 * before and after < 0.5


def test_an_undistorted_lens_is_left_alone():
    px, metres, _ = _ideal(BADMINTON, "doubles")
    k1, before, after = estimate_k1(px, metres, SIZE)
    assert k1 == 0.0 and before == after


def test_too_few_landmarks_never_switch_the_model_on():
    px, metres, _ = _ideal(BADMINTON, "doubles")
    bent = distort_points(px, -0.4, SIZE)
    k1, before, after = estimate_k1(bent[: MIN_POINTS - 1], metres[: MIN_POINTS - 1], SIZE)
    assert k1 == 0.0 and before == after, "a 7-point fit would absorb k1 into the clicks"


def test_the_synthetic_basketball_fixture_keeps_the_lens_free_payload():
    """The golden fixture's clicks are pinhole and only 5 of them: `k1` must stay 0."""
    template = BASKETBALL.template("half")
    cam = make_camera(template, SIZE, np.zeros((0, 2)))
    clicks = {
        name: tuple(cam.ground(np.asarray(xy)[None, :])[0])
        for name, xy in template.landmarks.items()
    }
    plain = calibrate(clicks, BASKETBALL, "half")
    lensed = pipeline.calibrate_lens(clicks, BASKETBALL, "half", SIZE)

    assert lensed["k1"] == 0.0
    assert lensed["H"] == plain["H"] and lensed["H_inv"] == plain["H_inv"]
    assert lensed["landmarks_px"] == plain["landmarks_px"]
    assert lensed["reproj_error_px"] == plain["reproj_error_px"]
    assert lensed["rim_px"] == pytest.approx(plain["rim_px"])
    # the outline is now a polyline, but it is the same outline
    poly = np.asarray(lensed["court_polygon_px"])
    assert len(poly) > 4
    h = np.asarray(lensed["H"], dtype=np.float64)
    assert np.allclose(project(poly, h).min(axis=0), template.polygon.min(axis=0), atol=1e-6)


def test_the_polygon_bends_with_the_lens():
    template = BADMINTON.template("doubles")
    px, metres, _ = _ideal(BADMINTON, "doubles")
    h_inv, _ = cv2.findHomography(metres, px)
    straight = polygon_px(template.polygon, h_inv)
    bent = polygon_px(template.polygon, h_inv, k1=-0.4, image_size=SIZE)
    assert len(straight) == len(bent) > 4

    # the samples of the first edge only: `polygon_px` spaces them by metres, and this
    # court's edges are 6.1 m and 13.4 m long, so a quarter of the array is not an edge.
    n0 = int(np.ceil(np.linalg.norm(template.polygon[1] - template.polygon[0]) / POLYGON_STEP_M))

    def bow(poly: np.ndarray) -> float:
        """Worst distance of the first sampled edge from the chord through its ends."""
        edge = poly[: n0 + 1]
        a, b = edge[0], edge[-1]
        n = np.array([-(b - a)[1], (b - a)[0]]) / np.linalg.norm(b - a)
        return float(np.abs((edge - a) @ n).max())

    assert bow(straight) < 1e-6, "a pinhole lens keeps a straight line straight"
    assert bow(bent) > 2.0, "a fisheye lens must visibly bow the back boundary line"
