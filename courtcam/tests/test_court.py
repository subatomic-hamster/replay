from __future__ import annotations

import numpy as np

from courtcam.court import inside, moving_average, on_court
from courtcam.profiles import load_profile
from courtcam.track import Tracklet

PROFILE = load_profile("basketball")
TEMPLATE = PROFILE.template("half")
IDENTITY = np.eye(3)  # keep the test in court metres: "pixels" are already metres


def _tracklet(
    tid: int, x: float, y: float, *, duration_s: float = 3.0, fps: int = 15, sway_m: float = 0.0
) -> Tracklet:
    n = int(duration_s * fps)
    times = np.arange(n) / fps
    # foot point (bottom-centre of the box) must land on (x, y), swaying +-sway_m in x
    xs = x - 0.25 + sway_m * np.sin(times)
    boxes = np.column_stack([xs, np.full(n, y - 1.8), np.full(n, 0.5), np.full(n, 1.8)])
    return Tracklet(
        track_id=tid, frames=np.arange(n) * 2, times=times, boxes=boxes, confs=np.full(n, 0.9)
    )


def test_inside_respects_the_profile_margin():
    poly = TEMPLATE.polygon
    pts = np.array([[0.0, 7.0], [8.0, 7.0], [9.0, 7.0]])  # on court, 0.5 m out, 1.5 m out
    assert list(inside(pts, poly, 1.0)) == [True, True, False]


def test_on_court_drops_spectators_but_does_not_cap_at_max_players():
    """The `players.max` cap lives in `identity` now — capping here would throw away
    tracklet fragments that merging is about to join into a real player."""
    on = [_tracklet(i, x=-6 + 1.2 * i, y=3.0 + 0.5 * i) for i in range(12)]
    spectators = [_tracklet(100 + j, x=9.6 + j, y=4.0 + 3 * j) for j in range(3)]
    kept = on_court(on + spectators, IDENTITY, PROFILE, TEMPLATE.polygon)

    assert len(kept) == 12 > PROFILE.players.max
    assert all(t.track_id < 100 for t in kept), "spectators must not survive the filter"
    assert all(t.inside_fraction >= PROFILE.tracking.oncourt_min_fraction for t in kept)


def test_short_lived_tracklets_are_dropped():
    blip = _tracklet(1, 0.0, 5.0, duration_s=0.4)
    assert on_court([blip], IDENTITY, PROFILE, TEMPLATE.polygon) == []


def test_moving_average_smooths_without_shifting_or_shrinking():
    pts = np.column_stack([np.arange(20.0), np.zeros(20)])
    out = moving_average(pts, 5)
    assert out.shape == pts.shape
    assert np.allclose(out[5:-5], pts[5:-5])  # a straight line survives a centred average


def test_a_seated_official_is_not_a_player():
    """The scorer's table sits inside the Kennesaw court polygon and never moves;
    samples/real/RESULTS.md. A player who stands still for a few seconds survives."""
    official = _tracklet(1, 7.0, 3.0, duration_s=40.0, sway_m=0.1)
    player = _tracklet(2, 0.0, 5.0, duration_s=40.0, sway_m=2.0)
    free_throw = _tracklet(3, 0.0, 5.0, duration_s=10.0)
    kept = on_court([official, player, free_throw], IDENTITY, PROFILE, TEMPLATE.polygon)
    assert [t.track_id for t in kept] == [2, 3]


def test_the_bench_inside_the_margin_is_a_bystander():
    """The Kennesaw bench sits on the baseline, inside `margin_m`: it passes the on-court
    test but a player is inside the painted lines most of the time."""
    from courtcam.court import bystander

    bench = _tracklet(1, 8.0, 5.0, duration_s=10.0, sway_m=0.3)  # sideline is x = 7.5
    player = _tracklet(2, 6.5, 5.0, duration_s=10.0, sway_m=1.5)  # steps out and back
    kept = on_court([bench, player], IDENTITY, PROFILE, TEMPLATE.polygon)
    assert sorted(t.track_id for t in kept) == [1, 2]
    verdict = {t.track_id: bystander(t, TEMPLATE.polygon, PROFILE.tracking) for t in kept}
    assert verdict == {1: True, 2: False}


def _camera_people(k: np.ndarray, r: np.ndarray, t: np.ndarray):
    """Six 1.75 m people walking on the half court, boxed as this camera sees them."""
    out = []
    for i in range(6):
        times = np.arange(45) / 15
        ground = np.c_[-5 + 2 * i + np.sin(times), 3 + i + times]
        foot, head = ((k @ (r @ np.c_[ground, np.full(45, z)].T + t[:, None])).T for z in (0, 1.75))
        foot, head = foot[:, :2] / foot[:, 2:], head[:, :2] / head[:, 2:]
        hgt = foot[:, 1] - head[:, 1]
        boxes = np.c_[foot[:, 0] - hgt / 6, head[:, 1], hgt / 3, hgt]
        out.append(Tracklet(i, np.arange(45) * 2, times, boxes, np.full(45, 0.9)))
    return out


def test_a_court_fit_the_people_disagree_with_filters_nobody():
    """D-94. A camera 3 m up behind the baseline: the true floor homography keeps the
    people; one that puts the court 30 m away (the people all off it), or one that
    squeezes the floor 3x (the people on it but a third of their height), is not
    trusted, and then `on_court` drops nobody for where they stand."""
    from courtcam.court import fit_check

    size = (1920, 1080)
    k = np.array([[1000.0, 0, 960], [0, 1000.0, 540], [0, 0, 1]])
    eye, at = np.array([0.0, -6.0, 3.0]), np.array([0.0, 7.0, 0.0])
    fwd = (at - eye) / np.linalg.norm(at - eye)
    right = np.cross(fwd, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    r = np.stack([right, np.cross(fwd, right), fwd])  # rows: camera x (right), y (down), z
    t = -r @ eye
    h_inv = k @ np.c_[r[:, :2], t]
    people = _camera_people(k, r, t)
    good = np.linalg.inv(h_inv)
    assert fit_check(people, good, PROFILE, TEMPLATE.polygon, image_size=size)["trusted"]

    away = np.array([[1.0, 0, 30.0], [0, 1, 0], [0, 0, 1]]) @ good
    squeezed = np.diag([1 / 3, 1 / 3, 1.0]) @ good
    for bad in (away, squeezed):
        fit = fit_check(people, bad, PROFILE, TEMPLATE.polygon, image_size=size)
        assert not fit["trusted"], fit
    assert on_court(people, away, PROFILE, TEMPLATE.polygon) == []
    kept = on_court(people, away, PROFILE, TEMPLATE.polygon, trusted=False)
    assert len(kept) == len(people)
