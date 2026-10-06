"""M8 virtual angles: Tier B geometry and highlight selection."""

from __future__ import annotations

import numpy as np
import pytest
from replay_render import testing as toy
from replay_render.gamedata import load_game
from replay_render.virtual import replays, tierb

REAL = tierb.View(toy.K, toy.R, toy.T)
SIZE = (toy.W, toy.H)


def test_push_in_starts_on_the_real_camera():
    centre = np.tile([0.0, 14.0, 1.0], (30, 1))
    views = tierb.camera_path("push_in", REAL, SIZE, centre, 10.0, size=SIZE)
    pts = np.array([[-7.5, 0, 0], [7.5, 28, 0], [0, 14, 2.0]])
    assert np.allclose(views[0].project(pts), REAL.project(pts), atol=0.5)
    # and ends closer to the play
    assert np.linalg.norm(views[-1].centre - centre[-1]) < 0.7 * np.linalg.norm(
        REAL.centre - centre[0]
    )


@pytest.mark.parametrize("angle", ["orbit", "broadcast_high"])
def test_paths_are_smooth_and_look_at_the_play(angle):
    centre = np.column_stack([np.linspace(-2, 2, 60), np.full(60, 14.0), np.ones(60)])
    views = tierb.camera_path(angle, REAL, SIZE, centre, 8.0, size=SIZE)
    eyes = np.asarray([v.centre for v in views])
    step = np.linalg.norm(np.diff(eyes, axis=0), axis=1)
    assert step.max() < 3 * np.median(step) + 1e-6  # eased, no jumps
    for v, c in zip(views, centre, strict=True):
        assert np.allclose(v.project(c[None]), [SIZE[0] / 2, SIZE[1] / 2], atol=1e-6)
        assert eyes[:, 2].min() > 1.0  # above the floor


def test_orbit_sweeps_sixty_degrees():
    centre = np.tile([0.0, 14.0, 1.0], (50, 1))
    views = tierb.camera_path("orbit", REAL, SIZE, centre, 8.0, size=SIZE)
    a, b = ((v.centre - centre[0])[:2] for v in (views[0], views[-1]))
    cos = a @ b / np.linalg.norm(a) / np.linalg.norm(b)
    assert np.degrees(np.arccos(cos)) == pytest.approx(60.0, abs=0.5)


def test_billboard_seen_from_the_real_camera_is_the_source():
    """From the real camera the cutout lands exactly where it was cut from."""
    frame = np.zeros((toy.H, toy.W, 3), np.uint8)
    foot = np.array([1.0, 12.0, 0.0])
    (fx, fy), (_, hy) = REAL.project(np.array([foot, foot + [0, 0, 1.85]]))
    x0, y0 = int(fx - 20), int(hy)
    mask = np.zeros((int(fy - hy), 40), bool)
    mask[:, 10:30] = True
    frame[y0 : y0 + mask.shape[0], x0 : x0 + 40][mask] = (0, 255, 0)
    canvas = np.zeros_like(frame)
    tierb.Billboard(REAL, 0.0, SIZE).draw(canvas, REAL, frame, foot, (x0, y0), mask)
    inner = (slice(y0 + 4, y0 + mask.shape[0] - 4), slice(x0 + 14, x0 + 26))
    assert canvas[inner][..., 1].mean() > 200  # the green cutout, in place
    assert canvas[:, : x0 - 5].max() == 0 and canvas[:, x0 + 45 :].max() == 0


def test_floor_plane_behind_the_camera_is_clipped():
    canvas = np.zeros((toy.H, toy.W, 3), np.uint8)
    tex = np.full((400, 300, 3), 200, np.uint8)
    inside = tierb.look_at(np.array([0.0, 2.0, 1.6]), np.array([0.0, 20.0, 0.0]), 400.0, SIZE)
    # a 30 m x 40 m floor that extends behind the camera
    tierb.draw_plane(canvas, tex, inside, np.array([-15.0, 30.0, 0]), np.array([0.1, 0, 0]),
                     np.array([0, -0.1, 0]))  # fmt: skip
    horizon = int(inside.project(np.array([[0.0, 1e4, 0.0]]))[0, 1])
    assert canvas[: horizon - 2].max() == 0  # nothing above the horizon
    assert canvas[horizon + 5 :].mean() > 150  # floor everywhere below it


def test_net_band_is_drawn_at_its_height():
    tops = [(0.0, 9.5, 2.43), (0.0, 18.5, 2.43)]  # a volleyball net face-on to the toy camera
    canvas = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
    tierb.draw_net(canvas, REAL, tops)
    u, v = np.round(REAL.project(np.array([[0.0, 14.0, 2.43]]))[0]).astype(int)
    assert canvas[v - 1 : v + 2, u].max() > 200  # the white top band
    u, v = np.round(REAL.project(np.array([[0.0, 14.0, 0.5]]))[0]).astype(int)
    assert canvas[v, u].max() == 0  # under the 1 m mesh: floor, nothing drawn


def test_ball_parabola_meets_release_and_rim():
    shot = {"t_release": 1.0, "t_rim": 2.0, "made": True}
    t = np.linspace(0.0, 3.5, 351)
    b = tierb.ball_track(shot, np.array([0.0, 6.0]), np.array([0.0, 1.575]), t)
    assert np.isnan(b[t < 1.0]).all()  # no ball before the release
    assert b[100, 2] == pytest.approx(tierb.RELEASE_H_M)
    assert b[200, 2] == pytest.approx(3.05, abs=1e-6) and b[200, 1] == pytest.approx(1.575)
    assert np.nanmax(b[:, 2]) > 3.05  # an arc, not a line
    assert np.isnan(b[-1]).all()


def test_highlights_come_from_events_without_plays(tmp_path):
    gd = toy.make_toy_game(tmp_path / "g", duration=24.0, video=False)
    picked, source = replays.select(load_game(gd), n=3)
    assert source == "events" and [h["play_id"] for h in picked] == ["ev_e1", "ev_e2"]
    for h in picked:
        assert h["t_end"] - h["t_start"] <= replays.MAX_S + 1e-6
        assert h["shot"]["t_rim"] <= h["t_end"]
    assert picked[0]["label"].startswith("Shot · Avery")
