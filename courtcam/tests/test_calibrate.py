from __future__ import annotations

import numpy as np
import pytest

from courtcam.calibrate import (
    MAX_RANSAC_PX,
    CalibrationError,
    calibrate,
    fit_error_px,
    homography,
    project,
)
from courtcam.profiles import load_profile
from courtcam.synth import make_camera

PROFILE = load_profile("basketball")
PICKLEBALL = load_profile("pickleball")


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
    h, residuals = homography(clicks, template)
    assert set(residuals) == set(clicks)
    assert max(residuals.values()) < 1e-3, (
        "exact landmarks must reproject to within a thousandth of a pixel"
    )

    # px -> metres -> px for the whole court outline, not just the clicked points
    px = project(template.polygon, np.linalg.inv(h))
    back = project(px, h)
    assert np.allclose(back, template.polygon, atol=1e-6)  # metres


def test_reprojection_error_is_reported_and_gated():
    clicks, template = _clicks("half")
    calib = calibrate(clicks, PROFILE, "half")
    assert calib["reproj_error_px"] < 5.0
    assert set(calib["residuals_px"]) == set(clicks)
    assert calib["variant"] == "half" and calib["standard"] == "fiba"
    assert np.asarray(calib["court_polygon_px"]).shape == (4, 2)
    assert calib["rim_m"] == [0.0, 1.575]

    # All 9 template landmarks is >= RANSAC_MIN_POINTS, so one bad click is voted out of
    # the fit and reported as its own residual rather than poisoning the gate (bug 3).
    nudged = dict(clicks)
    nudged["corner_fr"] = (clicks["corner_fr"][0] + 60.0, clicks["corner_fr"][1] - 60.0)
    out = calibrate(nudged, PROFILE, "half")
    assert out["residuals_px"]["corner_fr"] > 50.0
    assert out["reproj_error_px"] < 5.0


def test_needs_four_known_landmarks():
    clicks, template = _clicks("half")
    with pytest.raises(CalibrationError):
        homography({k: clicks[k] for k in list(clicks)[:3]}, template)


def _pickleball_clicks() -> dict[str, tuple[float, float]]:
    template = PICKLEBALL.template("doubles")
    cam = make_camera(template, (1920, 1080), np.zeros((0, 2)))
    return {
        name: tuple(cam.ground(np.asarray(xy)[None, :])[0])
        for name, xy in list(template.landmarks.items())[:10]
    }


def test_ransac_votes_out_one_badly_placed_click():
    """Bug 3: the old gate ran RANSAC with a 3.0 threshold against points in *metres*,
    so a click 200 px off was folded into the fit instead of rejected."""
    clicks = _pickleball_clicks()
    assert len(clicks) == 10
    bad = "kitchen_nl"
    good = {k: v for k, v in clicks.items() if k != bad}
    nudged = dict(clicks)
    nudged[bad] = (clicks[bad][0] + 200.0, clicks[bad][1] + 60.0)

    calib = calibrate(nudged, PICKLEBALL, "doubles")
    residuals = calib["residuals_px"]

    # the outlier is visible...
    assert residuals[bad] > 100.0
    assert max(residuals, key=residuals.get) == bad
    # ...and did not drag the other nine off their marks, nor the reported fit error
    assert max(residuals[k] for k in good) < 3.0
    assert calib["reproj_error_px"] < MAX_RANSAC_PX


def test_with_five_points_a_bad_click_still_fails_the_gate():
    """Under RANSAC_MIN_POINTS there is no consensus to vote with, so the whole fit is
    reported as bad rather than silently absorbing the outlier."""
    clicks, _ = _clicks("half")
    five = {k: clicks[k] for k in ("corner_nl", "corner_nr", "corner_fl", "corner_fr", "rim")}
    five["rim"] = (five["rim"][0] + 120.0, five["rim"][1] + 120.0)
    with pytest.raises(CalibrationError):
        calibrate(five, PROFILE, "half")


# The twelve clicks from samples/real/badminton_auditorium_240s.landmarks.json, copied in
# as literals because samples/real/ is gitignored (D-7). GoPro superview, camera beside
# the court in the plane of the net: the pinhole model cannot hold all twelve at once.
BADMINTON_AUDITORIUM = {
    "net_post_l": (929.0, 982.7),
    "net_post_r": (931.0, 517.1),
    "short_nl": (416.6, 920.7),
    "short_nr": (747.0, 513.2),
    "short_fl": (1442.8, 927.1),
    "short_fr": (1126.0, 517.0),
    "centre_sn": (650.4, 630.8),
    "centre_sf": (1218.6, 635.4),
    "singles_nl": (467.7, 856.4),
    "singles_nr": (736.5, 526.0),
    "singles_fl": (1396.0, 861.9),
    "singles_fr": (1136.1, 530.1),
}


def test_barrelled_frame_reports_its_worst_landmark_not_a_five_point_consensus():
    """RANSAC used to keep a 5-of-12 consensus here and report 1.5 px for a fit whose
    worst landmark is 167 px out — a lens problem hiding from its own quality gate
    (D-25). Over two points voted out, the fit is redone by least squares over every
    landmark and the error reported is that fit's worst."""
    template = load_profile("badminton").template("doubles")
    _, residuals = homography(BADMINTON_AUDITORIUM, template)
    assert set(residuals) == set(BADMINTON_AUDITORIUM)
    assert max(residuals.values()) >= 40.0
    assert fit_error_px(residuals) >= 40.0


def test_the_barrelled_fit_is_deterministic():
    """cv2.theRNG() is process-global, so the same clicks used to calibrate differently
    run to run (measured: 52/90 px one run, 45/33/26 px the next)."""
    template = load_profile("badminton").template("doubles")
    runs = [homography(BADMINTON_AUDITORIUM, template)[1] for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


def _camera_height(calib: dict) -> float:
    """Height of the camera the fit implies (negative: below the floor, a mirror)."""
    from courtcam.calibrate import focal_from_homography, pose_from_homography

    h_inv = np.asarray(calib["H_inv"])
    f = focal_from_homography(h_inv, (1280, 720)) or 1280.0
    k = np.array([[f, 0, 640.0], [0, f, 360.0], [0, 0, 1.0]])
    r, t = pose_from_homography(h_inv, k)
    return float((-r.T @ t)[2])


@pytest.mark.parametrize("variant", ["half", "full"])
def test_left_right_labelled_as_a_mirror_are_swapped_back(variant: str):
    """A user naming left/right as they see it labels the court's mirror image: it fits
    exactly as well (every template is symmetric about its long axis) but puts the camera
    under the floor, and the people check then distrusts the court (265 ids on the
    owner's 2v2 game). calibrate swaps the labels back and keeps the user's names for
    the residuals the uploader shows."""
    from courtcam.calibrate import mirrored, swap_lr

    clicks, template = _clicks(variant)
    clicks["rim_top"] = (600.0, 200.0)
    as_seen = {swap_lr(k): v for k, v in clicks.items()}
    assert not mirrored(clicks, template) and mirrored(as_seen, template)

    right, mirror = calibrate(clicks, PROFILE, variant), calibrate(as_seen, PROFILE, variant)
    assert right["labels_swapped"] is False and mirror["labels_swapped"] is True
    assert mirror["landmarks_px"] == right["landmarks_px"]  # the court's own names
    assert np.allclose(mirror["H"], right["H"], atol=1e-6)
    assert set(mirror["residuals_px"]) == set(as_seen) - {"rim_top"}  # the user's names
    assert _camera_height(mirror) > 1.0


def test_court_standard_is_picked_by_the_lane_and_kept_when_corners_cannot_tell():
    """A 12 ft lane clicked on a US court: FIBA's 4.9 m lane is metres out, so the fit
    switches; the four corners alone cannot tell the standards apart, so FIBA stands; a
    standard the user picked is used as is."""
    assert PROFILE.standards("half") == ["fiba", "nba", "ncaa", "nfhs"]
    us = PROFILE.template("half", "nfhs")
    assert us.landmarks["key_nr"][0] == pytest.approx(1.8288)  # 6 ft
    assert us.landmarks["corner_fr"][1] == pytest.approx(12.8016)  # 42 ft
    cam = make_camera(us, (1280, 720), np.zeros((0, 2)))
    clicks = {n: tuple(cam.ground(np.asarray(xy)[None, :])[0]) for n, xy in us.landmarks.items()}

    auto = calibrate(clicks, PROFILE, "half")
    assert auto["standard"] == "nfhs" and auto["standard_source"] == "fit"
    # FIBA alone fails the reprojection gate on these clicks (before standards: rejected)
    assert "fiba" not in auto["standard_fit_px"] and auto["standard_fit_px"]["nfhs"] < 0.01
    with pytest.raises(CalibrationError):
        calibrate(clicks, PROFILE, "half", standard="fiba")
    assert auto["rim_m"] == pytest.approx([0.0, 1.6002])

    corners = {n: clicks[n] for n in ("corner_nl", "corner_nr", "corner_fl", "corner_fr")}
    assert calibrate(corners, PROFILE, "half")["standard"] == "fiba"
    picked = calibrate(corners, PROFILE, "half", standard="nfhs")
    assert picked["standard"] == "nfhs" and picked["standard_source"] == "user"
    # an old game.json without a standard, or "fiba", is the default template
    assert PROFILE.template("half", None).name == PROFILE.template("half", "fiba").name
