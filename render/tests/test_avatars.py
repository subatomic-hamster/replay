"""M9 Tier C: skeleton conversion, placement, clean-up, lifter windowing, renderer."""

from __future__ import annotations

import shutil

import numpy as np
import pytest
from replay_render import testing as toy
from replay_render.avatars import lift, motion, render
from replay_render.avatars.place import Camera, place_analytic, player_height
from replay_render.avatars.scene import joints_array
from replay_render.avatars.skeleton import (
    ANKLES,
    BONES,
    PELVIS,
    bone_lengths,
    coco_to_h36m,
    h36m_to_coco,
    rest_pose,
)
from replay_render.virtual.tierb import look_at

CAM = Camera(toy.K, toy.R, toy.T, 0.0, (toy.W, toy.H))


def standing(h: float = 1.85, xy=(0.0, 14.0), face: float = np.pi) -> np.ndarray:
    return rest_pose(h, xy, face)


def test_coco_to_h36m_midpoints_and_scores():
    kp = np.zeros((17, 3))
    kp[:, 0] = np.arange(17)
    kp[:, 2] = 0.9
    kp[11, 2] = 0.3
    out = coco_to_h36m(kp)
    assert out[0, 0] == pytest.approx((11 + 12) / 2) and out[0, 2] == pytest.approx(0.3)
    assert out[8, 0] == pytest.approx((5 + 6) / 2)
    assert out[3, 0] == 16 and out[6, 0] == 15  # right ankle, left ankle
    pts = coco_to_h36m(kp, scored=False)
    assert pts[0, 2] == pytest.approx(0.6)  # z is averaged, not min'ed
    j = standing()
    assert np.allclose(coco_to_h36m(h36m_to_coco(j), scored=False)[[0, 1, 3, 10, 13]],
                       j[[0, 1, 3, 10, 13]])  # fmt: skip


def test_savgol_keeps_a_parabola_and_cuts_noise():
    t = np.linspace(0, 2, 61)
    x = (3 * t * t - t)[:, None]
    assert np.allclose(motion.savgol(x, 9), x, atol=1e-9)
    rng = np.random.default_rng(0)
    noisy = x + rng.normal(0, 0.05, x.shape)
    assert motion.jitter(motion.savgol(noisy, 9)[:, None], 30) < 0.3 * motion.jitter(
        noisy[:, None], 30
    )


def test_fix_bones_makes_lengths_constant():
    rng = np.random.default_rng(1)
    j = np.repeat(standing()[None], 40, axis=0) + rng.normal(0, 0.02, (40, 17, 3))
    out = motion.fix_bones(j)
    assert motion.bone_cv(out) < 1e-9 < motion.bone_cv(j)


def test_pinned_foot_does_not_slide_and_legs_keep_length():
    n = 60
    j = np.repeat(standing()[None], n, axis=0)
    j[:, :, 0] += np.linspace(0, 0.3, n)[:, None]  # the whole body drifts 30 cm: skating
    planted = np.zeros((n, 2), bool)
    planted[10:50] = True
    out = motion.pin_feet(j, planted)
    assert motion.foot_slide(j, planted, 30) > 10
    assert motion.foot_slide(out, planted, 30) < 0.5
    for a, b in ((1, 2), (2, 3)):
        d = np.linalg.norm(out[:, b] - out[:, a], axis=-1)
        assert np.ptp(d) < 1e-6


def test_contacts_find_the_standing_foot():
    n = 40
    j = np.repeat(standing()[None], n, axis=0)
    j[:, 3, 0] += np.linspace(0, 2.0, n)  # right ankle swings (2 m in 1.3 s)
    j[:, 3, 2] += 0.3
    c = motion.contacts(j, 30)
    assert c[:, 1].all() and not c[5:-5, 0].any()


def test_separate_pushes_overlapping_players_apart():
    a = np.repeat(standing(xy=(0.0, 14.0))[None], 20, axis=0)
    b = np.repeat(standing(xy=(0.2, 14.0))[None], 20, axis=0)
    assert motion.penetration([a, b]) == 1.0
    out = motion.separate([a, b], 30)
    assert motion.penetration(out) == 0.0
    gap = np.linalg.norm(out[1][:, PELVIS, :2] - out[0][:, PELVIS, :2], axis=-1)
    assert gap.min() > 2 * motion.TORSO_R - 0.03


def test_analytic_placement_recovers_a_seen_skeleton():
    """Project a known skeleton through the toy camera, place it back from the pixels."""
    gt = np.stack([standing(1.9, (x, 12.0)) for x in np.linspace(-1, 1, 20)])
    px = CAM.project(gt.reshape(-1, 3)).reshape(20, 17, 2)
    kp = np.concatenate([px, np.ones((20, 17, 1))], axis=-1)
    court = gt[:, ANKLES, :2].mean(axis=1)
    h = player_height(CAM, kp, court)
    assert h == pytest.approx(1.9, abs=0.08)  # the rest pose's head leans 11 cm forward
    out = place_analytic(CAM, kp, court, h)
    assert motion.mpjpe(out, gt) < 60  # mm
    assert np.allclose(CAM.project(out.reshape(-1, 3)), px.reshape(-1, 2), atol=1.5)


def test_lift_windows_cover_and_round_trip():
    rng = np.random.default_rng(2)
    for n in (90, 400):  # one stretched window; several blended ones
        seq = np.cumsum(rng.normal(0, 0.01, (n, 17, 3)), axis=0)
        w, n50 = lift.plan(seq, 30.0)
        assert w.shape[1:] == (lift.CLIP, 17, 3)
        back = lift.merge(w, n50, n)  # identity "model"
        assert np.abs(back - seq).max() < 0.02


def _toy_doc(n: int = 12) -> dict:
    j = np.stack([standing(xy=(0.0, 3.0 + 0.05 * f), face=np.pi / 2) for f in range(n)])
    k = np.stack([standing(xy=(2.0, 4.0), face=-np.pi / 2)] * n)
    ball = [[0.0, 3.0 + 0.1 * f, 2.3 + 0.05 * f] for f in range(n)]
    return {
        "schema": "replay.scene.v1", "play_id": "pl_x", "label": "Shot · #p1", "sport": "basketball",
        "variant": "full", "synthetic": True, "fps": 30.0, "t_start": 0.0, "t_end": n / 30,
        "frames": n, "method": "analytic",
        "camera": {"K": toy.K.tolist(), "R": toy.R.tolist(), "t": toy.T.tolist(),
                   "image_size": [toy.W, toy.H]},
        "court": {"rims": [[0.0, 1.575], [0.0, 26.425]], "rim_height_m": 3.05},
        "primary": "p1", "shooter": "p1",
        "players": [{"id": "p1", "team": 0, "color": "#C0392B", "joints": j.tolist()},
                    {"id": "p2", "team": 1, "color": "#2E86C1", "joints": k.tolist()}],
        "ball": {"positions": ball, "t_release": 0.2, "target": [0.0, 1.575, 3.05]},
    }  # fmt: skip


@pytest.mark.parametrize("angle", [*render.ANGLES, "pov_p1"])
def test_every_angle_frames_the_play(angle):
    doc = _toy_doc()
    painter = render.Painter(doc, (320, 180))
    views = render.camera_path(angle, doc, painter.joints, (320, 180))
    assert len(views) == doc["frames"]
    eyes = np.array([v.centre for v in views])
    assert eyes[:, 2].min() > 1.0
    img = painter.frame(5, views[5], angle, render.pov_player(angle, doc))
    team = np.all(np.abs(img.astype(int) - render.team_colors(doc)[1]) < 40, axis=-1)
    if angle.startswith("pov"):  # p1 looks at the rim; the rim (orange-red) is in view
        assert (np.abs(img.astype(int) - (0, 90, 255)) < 40).all(axis=-1).any()
    else:
        assert team.any()  # the other team's jersey is on screen


@pytest.mark.parametrize("angle", [*render.ANGLES, "pov_p1"])
def test_net_sport_angles_see_the_opponent_across_the_net(angle):
    doc = _toy_doc()
    p1 = np.stack([standing(xy=(-1.0, 3.0 + 0.02 * f), face=np.pi / 2) for f in range(12)])
    p2 = np.stack([standing(xy=(1.0, 10.0), face=-np.pi / 2)] * 12)
    doc.update(sport="pickleball", variant="doubles", court={"rims": [], "rim_height_m": 3.05},
               ball=None)  # fmt: skip
    doc["players"][0]["joints"], doc["players"][1]["joints"] = p1.tolist(), p2.tolist()
    painter = render.Painter(doc, (320, 180))
    assert painter.net is not None
    views = render.camera_path(angle, doc, painter.joints, (320, 180))
    img = painter.frame(5, views[5], angle, render.pov_player(angle, doc))
    team = np.all(np.abs(img.astype(int) - render.team_colors(doc)[1]) < 40, axis=-1)
    assert team.any()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_render_angle_writes_every_frame(tmp_path):
    doc = _toy_doc()
    out = tmp_path / "tierc_overhead.mp4"
    res = render.render_angle(doc, "overhead", out, size=(320, 180))
    assert res["frames"] == doc["frames"] and out.stat().st_size > 1000


def test_a_virtual_pov_for_every_player_in_3d_key_player_first():
    doc = {"players": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}], "shooter": "p2"}
    assert render.angles_for(doc) == [*render.ANGLES, "pov_p2", "pov_p1", "pov_p3"]
    # the key player not in 3D: no POV is labelled with someone else's eyes
    assert render.angles_for({**doc, "shooter": "p9"}) == [
        *render.ANGLES,
        "pov_p1",
        "pov_p2",
        "pov_p3",
    ]
    # a highlight (no 3D players yet): only the key player's
    assert render.angles_for({"primary": "p4"}) == [*render.ANGLES, "pov_p4"]


def test_povs_are_capped_to_the_players_nearest_the_key_player():
    doc = _toy_doc()
    base = doc["players"][1]
    doc["players"] = [doc["players"][0]] + [
        {**base, "id": f"q{k}", "joints": (np.asarray(base["joints"]) + [k, 0, 0]).tolist()}
        for k in (9, 1, 7, 3, 5, 8, 2)
    ]  # q1 is nearest p1 (the shooter), q9 farthest
    povs = [a for a in render.angles_for(doc) if a.startswith("pov_")]
    assert povs == ["pov_p1", "pov_q1", "pov_q2", "pov_q3", "pov_q5", "pov_q7"]


def test_kits_cluster_into_two_teams_and_a_referee_keeps_their_own_shirt():
    from replay_render.avatars.scene import kit_teams

    red, black, grey = (136.0, 208, 195), (20.0, 128, 128), (150.0, 128, 128)  # OpenCV Lab
    seen = {0: red, 1: np.add(red, 4), 2: black, 3: np.add(black, 3), 5: grey}
    prior = {0: 1, 1: 1, 2: 0, 3: 0, 5: 0}  # game.json: the reds are team 1
    out = kit_teams({p: np.asarray(v, float) for p, v in seen.items()}, prior)
    assert out[0][0] == out[1][0] == 1 and out[2][0] == out[3][0] == 0
    assert out[0][1] == out[1][1] and out[2][1] == out[3][1]  # one colour per team
    r, g, b = render.hex_rgb(out[2][1])
    assert max(r, g, b) < 60  # the black kit stays black, not lifted to grey
    r, g, b = render.hex_rgb(out[0][1])
    assert r > 150 and g < 80  # red
    assert out[5][0] is None  # the referee: neither team


def test_net_fades_for_a_camera_at_the_net():
    left, right = (-3.0, 7.0, 0.9), (3.0, 7.0, 0.9)

    def dark(eye) -> float:
        view = look_at(np.array(eye), np.array([0.0, 12.0, 0.9]), 320.0, (320, 180))
        c = np.full((180, 320, 3), 200, np.uint8)
        for _, fn in render.net_prims(left, right, view):
            fn(c)
        return float((c.mean(axis=-1) < 150).mean())

    assert dark([0.0, 1.0, 1.6]) > 0.05  # from 6 m: a see-through dark net
    assert dark([0.0, 5.4, 1.6]) < 0.01  # a POV 1.6 m from the net: no screen of mesh


def test_image_based_angles_stay_where_a_cutout_holds_up():
    from replay_render.avatars import imageview

    doc = _toy_doc()
    angles = imageview.angles_for(doc, (320, 180))
    # the toy camera films from the sideline: a baseline camera would face it at ~90°
    assert angles == ["wing", "courtside", "pov_p1", "pov_p2"]
    joints = joints_array(doc)
    centre = imageview._centre(doc, joints)
    real_c = imageview._real_centre(doc)
    for a, lo, hi in (("wing", 25, 45), ("courtside", 10, 18)):
        views = imageview.camera_views(a, doc, joints, (320, 180))
        assert len(views) == doc["frames"]
        off = np.degrees(imageview.off_angle(views, centre, real_c))
        assert lo - 3 < off < hi + 3
        assert min(v.centre[2] for v in views) > 1.0


def test_a_pov_stands_on_its_track_at_eye_height_and_looks_at_the_play():
    from replay_render.avatars import imageview

    doc = _toy_doc(n=60)
    doc["ball"] = None
    pos = np.full((3, 60, 2), np.nan)
    pos[0, 10:] = np.column_stack([np.zeros(50), np.linspace(10.0, 12.0, 50)])  # the POV player
    pos[1] = [4.0, 18.0]  # everyone else: ahead and to the right
    pos[2] = [6.0, 20.0]
    views = imageview.pov_views(doc, pos, [0], (320, 180), 1.7)
    eyes = np.array([v.centre for v in views])
    assert np.allclose(eyes[:, 2], 1.7)  # steady head height
    assert np.allclose(eyes[:10, :2], [0.0, 10.0], atol=0.15)  # holds before the track
    assert abs(eyes[-1, 1] - 12.0) < 0.2
    fwd = np.array([v.r[2] for v in views])
    to_play = np.array([5.0, 19.0]) - eyes[:, :2]
    cos = (
        (fwd[:, :2] * to_play).sum(1)
        / np.linalg.norm(fwd[:, :2], axis=1)
        / np.linalg.norm(to_play, axis=1)
    )
    assert (cos > np.cos(np.radians(30))).all()  # the play, not the rim behind them
    pitch = np.degrees(np.arcsin(fwd[:, 2]))
    assert np.ptp(pitch) < 1e-6 and -12 < pitch[0] < 0  # level, a little down
    assert np.degrees(np.abs(np.diff(np.unwrap(np.arctan2(fwd[:, 1], fwd[:, 0]))))).max() < 3


def test_a_pov_shot_never_looks_up_more_than_twenty_degrees():
    from replay_render.avatars import imageview

    doc = _toy_doc(n=60)
    doc["ball"] = {"positions": [], "t_release": 1.0, "t_rim": 1.5, "target": [0.0, 1.575, 3.05]}
    pos = np.full((2, 60, 2), np.nan)
    pos[0] = [0.0, 6.2]  # 4.6 m out: the rim is 24° up from a low (1 m) eye
    pos[1] = [3.0, 8.0]
    views = imageview.pov_views(doc, pos, [0], (320, 180), 1.0)
    pitch = [np.degrees(np.arcsin(v.r[2][2])) for v in views]
    assert max(pitch) == pytest.approx(20.0, abs=0.5)
    pos[0] = [0.0, 2.2]  # right under it: keeps looking at the play, not up at a wall
    views = imageview.pov_views(doc, pos, [0], (320, 180), 1.0)
    assert max(np.degrees(np.arcsin(v.r[2][2])) for v in views) < 0


def test_bones_table_covers_the_skeleton():
    assert set(bone_lengths(1.8)) == set(BONES)
