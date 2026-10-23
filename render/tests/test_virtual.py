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


def test_ball_true_size_and_never_beside_the_camera():
    view = tierb.look_at(np.zeros(3), np.array([0.0, 1, 0]), 1000.0, (1280, 720))
    canvas = np.zeros((720, 1280, 3), np.uint8)
    tierb.draw_ball(canvas, view, np.array([[0.0, 1.0, 0.0]]))  # 1 m away: not drawn
    assert canvas.max() == 0
    tierb.draw_ball(canvas, view, np.array([[0.0, 6.0, 0.0]]))  # 0.24 m at 6 m: r 20 px
    width = (canvas[360].sum(1) > 0).sum()
    assert 38 <= width <= 44


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


def _cutout(frame, foot):
    (fx, fy), (_, hy) = REAL.project(np.array([foot, foot + [0, 0, 1.85]]))
    x0, y0 = int(fx - 20), int(hy)
    mask = np.zeros((int(fy - hy), 40), bool)
    mask[:, 10:30] = True
    frame[y0 : y0 + mask.shape[0], x0 : x0 + 40][mask] = (0, 255, 0)
    return (x0, y0), mask


def test_a_cutout_seen_from_the_side_becomes_its_kit_colour():
    """Image-based views: real pixels near the real line of sight, the kit-coloured
    silhouette (not stretched pixels) once the view has turned ~90° round the player."""
    frame = np.zeros((toy.H, toy.W, 3), np.uint8)
    foot = np.array([1.0, 12.0, 0.0])
    xy0, mask = _cutout(frame, foot)
    bb = tierb.Billboard(REAL, 0.0, SIZE)
    side = REAL.centre - foot
    side = foot + np.array([-side[1], side[0], 0.0]) * 0.8  # 90° round, a bit closer
    side[2] = REAL.centre[2]
    view = tierb.look_at(side, foot + [0, 0, 1.0], 500.0, SIZE)
    canvas = np.zeros_like(frame)
    bb.draw(canvas, view, frame, foot, xy0, mask, tint=(200, 40, 40))
    drawn = canvas.max(axis=-1) > 60
    assert drawn.sum() > 50
    px = canvas[drawn].astype(int)
    assert (px[:, 0] > px[:, 1]).mean() > 0.9  # blue kit, not the green source pixels
    assert tierb.seen_weight(np.radians(20)) == 1.0 and tierb.seen_weight(np.radians(80)) == 0.0


def test_a_cutout_right_at_the_camera_fades_out_but_one_at_arms_length_stays():
    frame = np.full((toy.H, toy.W, 3), 200, np.uint8)
    foot = np.array([1.0, 12.0, 0.0])
    xy0, mask = _cutout(frame, foot)

    def at(m: float) -> np.ndarray:
        d = (REAL.centre - foot)[:2] / np.linalg.norm((REAL.centre - foot)[:2])
        eye = np.r_[foot[:2] + m * d, 1.6]
        view = tierb.look_at(eye, np.r_[foot[:2], 1.6], 300.0, SIZE)  # level, at them
        canvas = np.zeros_like(frame)
        tierb.Billboard(REAL, 0.0, SIZE).draw(canvas, view, frame, foot, xy0, mask,
                                              tint=(0, 0, 255))  # fmt: skip
        return canvas

    assert at(0.85).max() < 40  # brushing past: (almost) nothing, not a wall of pixels
    assert at(1.6).max() > 150  # a defender at arm's length is there, solid (POV, D-88)


def test_bridge_keeps_a_person_through_a_gap_and_an_id_hand_over():
    fps, n = 10.0, 60
    court = np.full((3, n, 2), np.nan)
    x = np.linspace(0, 6, n)
    court[0, :20] = np.column_stack([x[:20], np.zeros(20)])  # p0, lost after frame 19 ...
    court[1, 30:] = np.column_stack([x[30:], np.zeros(30)])  # ... picked up as p1 at 30
    court[2, :40] = [[8.0, 8.0]] * 40  # far away, lost for good at 39
    pos, alpha, links = tierb.bridge(court, fps)
    assert links == [(0, 1)]
    assert np.isfinite(pos[0, 20:30, 0]).all() and (alpha[0, 20:30] == 1).all()
    assert np.allclose(pos[0, 25], [x[25], 0.0], atol=0.05)  # along the line between
    assert alpha[1, 30] == 1.0  # a hand-over does not fade in
    fade = round(tierb.FADE_S * fps)
    assert (
        np.allclose(pos[2, 40 : 40 + fade], 8.0) and (np.diff(alpha[2, 39 : 40 + fade]) < 0).all()
    )
    assert np.isnan(pos[2, 40 + fade :]).all()
    assert tierb.chain(links, [1]) == {0, 1}


def test_a_held_cutout_is_drawn_where_the_person_is_now():
    frame = np.zeros((toy.H, toy.W, 3), np.uint8)
    foot = np.array([1.0, 12.0, 0.0])
    xy0, mask = _cutout(frame, foot)
    crop = frame[xy0[1] : xy0[1] + mask.shape[0], xy0[0] : xy0[0] + mask.shape[1]].copy()
    now = foot + [1.5, 0, 0]
    canvas = np.zeros_like(frame)
    tierb.Billboard(REAL, 0.0, SIZE).draw(canvas, REAL, crop, now, xy0, mask, None, 1.0,
                                          foot, xy0)  # fmt: skip
    u = np.flatnonzero(canvas.max(axis=(0, 2)) > 100)
    want = REAL.project(now[None])[0, 0]
    assert len(u) and abs((u.min() + u.max()) / 2 - want) < 6


def test_unseen_walls_fill_the_view_from_inside_and_vanish_from_outside():
    floor = np.full((40, 30, 3), (60, 120, 180), np.uint8)
    wall = np.full((40, 60, 3), 90, np.uint8)
    meta = {"floor": {"bounds_m": [-7.5, -3.0, 7.5, 17.0]}, "backdrop": {"height_m": 8.0}}
    planes = tierb.room_planes(floor, wall, meta)
    inside = tierb.look_at(np.array([0.0, 14.0, 1.7]), np.array([0.0, -3.0, 1.7]), 600.0, SIZE)
    canvas = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
    tierb.draw_room(canvas, inside, planes)
    assert (canvas.max(axis=-1) == 0).mean() < 0.01  # walls and floor everywhere
    outside = tierb.look_at(np.array([0.0, 30.0, 6.0]), np.array([0.0, 7.0, 1.0]), 300.0, SIZE)
    canvas[:] = 0
    tierb.draw_room(canvas, outside, planes)
    # the near wall (between the camera and the court) is culled: the court shows
    u, v = np.round(outside.project(np.array([[0.0, 7.0, 0.0]]))[0]).astype(int)
    assert tuple(canvas[v, u]) == (60, 120, 180)


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


def test_plays_with_angles_scale_with_the_game_and_spread_over_it():
    assert [replays.auto_n(s) for s in (60, 241, 3600)] == [3, 4, 10]

    def w(t: float) -> dict:
        return {"play_id": f"at{t:g}", "t_start": t, "t_end": t + 6}

    ranked = [w(200), w(203), w(210), w(10), w(100)]  # the best plays bunch at the end
    got = replays._spread(ranked, 3, 240.0)
    assert [h["play_id"] for h in got] == ["at10", "at100", "at200"]
    # fewer stretches with a play: the rest come from the ranking, never overlapping
    assert [h["play_id"] for h in replays._spread(ranked[:3], 3, 240.0)] == ["at200", "at210"]


def test_highlights_come_from_events_without_plays(tmp_path):
    gd = toy.make_toy_game(tmp_path / "g", duration=24.0, video=False)
    picked, source = replays.select(load_game(gd), n=3)
    assert source == "events" and [h["play_id"] for h in picked] == ["ev_e1", "ev_e2"]
    for h in picked:
        assert h["t_end"] - h["t_start"] <= replays.MAX_S + 1e-6
        assert h["shot"]["t_rim"] <= h["t_end"]
    # the replay angles' best play reaches back a whole stretch (its player's views)
    got, _ = replays.select(load_game(gd), n=3, long_first=True)
    dur = sorted(h["t_end"] - h["t_start"] for h in got)
    assert dur[-1] > replays.MAX_S and dur[-1] <= replays.LONG_S + 1e-6
    assert all(d <= replays.MAX_S + 1e-6 for d in dur[:-1])
    assert replays._window(30.0, 34.0, 33.0, 240.0, long=True) == (20.5, 34.5)
    assert replays._window(30.0, 34.0, 33.0, 240.0) == (30.0, 34.5)
    assert picked[0]["label"].startswith("Shot · Avery")
