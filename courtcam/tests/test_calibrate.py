from __future__ import annotations

import numpy as np
import pytest

from courtcam.calibrate import CalibrationError, calibrate, homography, project
from courtcam.profiles import load_profile
from courtcam.synth import make_camera

PROFILE = load_profile("basketball")


def _clicks(variant: str) -> tuple[dict[str, tuple[float, float]], object]:
    """Landmark pixels from a known synthetic camera — so the true answer is known."""
    template = PROFILE.template(variant)
    cam = make_camera(template, (1280, 720), np.zeros((0, 2)))
    return {
        name: tuple(cam.ground(np.asarray(xy)[None, :])[0])
        for name, xy in template.landmarks.items()
    }, template


@pytest.mark.parametrize("variant", ["half", "full"])
def test_homography_round_trip(variant: str):
    clicks, template = _clicks(variant)
    h, err = homography(clicks, template)
    assert err < 1e-3, "exact landmarks must reproject to within a thousandth of a pixel"

    # px -> metres -> px for the whole court outline, not just the clicked points
    px = project(template.polygon, np.linalg.inv(h))
    back = project(px, h)
    assert np.allclose(back, template.polygon, atol=1e-6)  # metres


def test_reprojection_error_is_reported_and_gated():
    clicks, template = _clicks("half")
    calib = calibrate(clicks, PROFILE, "half")
    assert calib["reproj_error_px"] < 5.0
    assert calib["variant"] == "half" and calib["standard"] == "fiba"
    assert np.asarray(calib["court_polygon_px"]).shape == (4, 2)
    assert calib["rim_m"] == [0.0, 1.575]

    nudged = dict(clicks)
    nudged["corner_fr"] = (clicks["corner_fr"][0] + 60.0, clicks["corner_fr"][1] - 60.0)
    with pytest.raises(CalibrationError):
        calibrate(nudged, PROFILE, "half")


def test_needs_four_known_landmarks():
    clicks, template = _clicks("half")
    with pytest.raises(CalibrationError):
        homography({k: clicks[k] for k in list(clicks)[:3]}, template)
