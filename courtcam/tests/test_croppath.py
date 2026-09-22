from __future__ import annotations

import numpy as np

from courtcam.croppath import MIN_CROP_W, build_crop_path, crop_path, crop_size
from courtcam.profiles import load_profile

PROFILE = load_profile("basketball")
CFG = PROFILE.followcam
W, H = 1920, 1080


def _boxes(centres: np.ndarray, size: float = 90.0) -> np.ndarray:
    return np.column_stack(
        [
            centres[:, 0] - size / 2,
            centres[:, 1] - size / 2,
            np.full(len(centres), size),
            np.full(len(centres), size),
        ]
    )


def test_rects_stay_normalised_and_hold_a_constant_window():
    """Golden updated on purpose: `followcam.zoom` divides the COURT's pixel width, not
    the frame's (the old `frame_w / zoom` put a 60 px player in an empty 1920x720 crop
    on a 2560-px whole-court source — samples/real/RESULTS.md). The window is still
    constant over the path; it is just sized from the calibration now."""
    t = np.arange(300) / 30.0
    centres = np.column_stack([960 + 900 * np.sin(2 * t), 540 + 400 * np.cos(3 * t)])
    court_px_w = 1600.0
    rects = crop_path(_boxes(centres), W, H, CFG, court_px_w=court_px_w)
    cw, ch = crop_size(W, H, CFG.zoom, court_px_w)

    assert rects.shape == (300, 4)
    assert rects.min() >= 0.0 and rects.max() <= 1.0
    assert np.allclose(rects[:, 2], cw / W) and np.allclose(rects[:, 3], ch / H)
    assert np.all(rects[:, 0] + rects[:, 2] <= 1.0 + 1e-9)
    assert np.all(rects[:, 1] + rects[:, 3] <= 1.0 + 1e-9)


def test_crop_window_scales_with_the_court_and_stays_16_9():
    # The panoramic case this change exists for: a fraction of the COURT, 16:9, out of a
    # frame that is 8:3. Numbers are the measured Kennesaw ones (samples/real/RESULTS.md).
    cw, ch = crop_size(2560, 960, CFG.zoom, 2492.7)
    assert abs(cw / ch - 16 / 9) < 1e-6
    assert 124 / ch < 1 / 4 and 124 / ch > 1 / 6, (cw, ch)  # median player, 124 px tall
    # a tight source is barely zoomed at all, and never below the legibility floor
    assert crop_size(1280, 720, 40.0, 1071.3)[0] == MIN_CROP_W
    # no calibration -> the frame width stands in, and the crop never exceeds the frame
    assert crop_size(640, 360, 1.0)[0] == 640.0


def test_camera_is_smooth_even_when_the_target_teleports():
    """An identity switch must not snap the frame across the court."""
    centres = np.tile([300.0, 500.0], (120, 1))
    centres[60:] = [1600.0, 700.0]
    rects = crop_path(_boxes(centres), W, H, CFG, court_px_w=1600.0)
    delta = np.abs(np.diff(rects[:, :2], axis=0)).max()
    jump = abs(centres[60, 0] - centres[59, 0]) / W  # 0.68 of the frame in one frame
    assert delta < jump / 10, f"per-frame jump {delta:.4f} tracks the teleport too closely"
    # and it must take real time to get there, not two frames
    travelled = np.abs(rects[:, 0] - rects[59, 0]) / abs(rects[-1, 0] - rects[59, 0])
    assert int(np.argmax(travelled > 0.9)) - 59 > 10


def test_gaps_hold_the_last_position_then_ease_back():
    centres = np.tile([400.0, 500.0], (150, 1))
    boxes = _boxes(centres)
    boxes[50:100] = np.nan  # the player is occluded for 1.7 s
    rects = crop_path(boxes, W, H, CFG)

    assert np.isfinite(rects).all()
    parked = np.abs(np.diff(rects[60:99, :2], axis=0)).max()
    assert parked < 1e-3, "the window should sit still through a gap"


def test_build_crop_path_matches_the_contract():
    boxes = _boxes(np.tile([960.0, 540.0], (90, 1)))
    path = build_crop_path("p3", boxes, W, H, CFG)
    assert path.player_id == "p3" and path.rate_hz == 30 and path.t0 == 0.0
    assert len(path.rects) == 90 and len(path.rects[0]) == 4


def test_a_track_with_no_boxes_still_yields_finite_rects():
    rects = crop_path(np.full((30, 4), np.nan), W, H, CFG)
    assert np.isfinite(rects).all()
