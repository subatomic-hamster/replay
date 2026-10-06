"""The M1 synthetic generator: its ground truth has to be right before anything is
measured against it."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from courtcam import synth
from courtcam.calibrate import project
from courtcam.distortion import undistort_points
from courtcam.synth import RIM_H_M, RIM_R_M, CameraSpec, build_scene

SPORTS = [
    ("basketball", "half"),
    ("basketball", "full"),
    ("pickleball", "doubles"),
    ("badminton", "doubles"),
    ("volleyball", "indoor"),
]


@pytest.fixture(scope="module", params=SPORTS, ids=lambda p: f"{p[0]}_{p[1]}")
def scene(request) -> synth.Scene:
    return build_scene(*request.param, duration_s=40.0)


def test_same_seed_same_scene_other_seed_other_scene():
    a = build_scene("pickleball", duration_s=12.0, seed=3)
    b = build_scene("pickleball", duration_s=12.0, seed=3)
    c = build_scene("pickleball", duration_s=12.0, seed=4)
    assert np.array_equal(a.pos, b.pos) and np.array_equal(a.ball, b.ball, equal_nan=True)
    assert a.events == b.events and a.triggers == b.triggers
    assert not np.allclose(a.pos, c.pos)


def test_players_move_like_people(scene):
    n = scene.profile.players.max
    speed = np.linalg.norm(np.diff(scene.pos[:, :n], axis=0), axis=2) * scene.fps
    assert np.percentile(speed, 99) < 7.5, "faster than a sprinting player"
    assert speed.max() < 11.0
    still = scene.pos[:, n:]
    assert np.allclose(still, still[:1]), "spectators are the fixed decoys"


def test_every_trigger_resolves_to_its_play(scene):
    """The product rule: a trigger at T clips the play that most recently ended before
    T, with 1-8 s of lag allowed."""
    assert scene.triggers, "every scene carries at least one trigger"
    for tr in scene.triggers:
        ended = [p for p in scene.plays if p["t_end"] < tr["t"]]
        assert ended, tr
        last = max(ended, key=lambda p: p["t_end"])
        assert last["id"] == tr["play_id"], tr
        assert 1.0 <= tr["t"] - last["t_end"] <= 8.0
        assert last["trigger"]["type"] == tr["type"]
        if tr["type"] == "gesture":
            assert tr["by_player_id"] and tr["t"] - tr["t_start"] == pytest.approx(1.0)
        if tr["type"] == "voice":
            assert tr["transcript"].startswith("Replay, clip ")


def test_all_trigger_kinds_and_a_named_voice_appear():
    kinds, named = set(), False
    for sport, variant in SPORTS:
        for tr in build_scene(sport, variant, duration_s=40.0).triggers:
            kinds.add(tr["type"])
            named |= "subject_player_id" in tr
    assert kinds == {"gesture", "voice", "tap"} and named


def test_plays_follow_their_grammar(scene):
    by_id = {e["id"]: e for e in scene.events}
    assert scene.plays
    for p in scene.plays:
        evs = [by_id[i] for i in p["event_ids"]]
        assert p["t_start"] < p["t_end"]
        if p["grammar"] == "possession":
            assert evs[0]["type"] == "possession_change"
            assert evs[0]["cause"] in {"inbound", "steal", "defensive_rebound"}
            assert evs[-1]["type"] in {"shot", "turnover"}
        else:
            assert evs[0]["type"] == "serve" and evs[-1]["type"] == "rally"
            assert evs[-2]["type"] == "point" and evs[-2]["winner_side"] in (0, 1)
            assert evs[-1]["contacts"] == 1 + sum(e["type"] == "contact" for e in evs)


def _gesture_frame(scene) -> tuple[int, dict]:
    g = next(tr for tr in scene.triggers if tr["type"] == "gesture")
    return int(round((g["t"] - 0.5) * scene.fps)), g


def test_the_x_gesture_is_in_the_rig_and_the_keypoints(scene):
    f, g = _gesture_frame(scene)
    i = int(g["by_player_id"][1:]) - 1
    p = scene.people[i]
    j = synth.rig(scene.pos[f, i], scene.heading[f, i], p.height, scene.phase[f, i],
                  scene.amp[f, i], int(scene.pose[f, i]), float(scene.pose_w[f, i]))  # fmt: skip
    kp3 = synth.keypoints_3d(j, scene.heading[f, i], p.height)
    nose, lw, rw = kp3[0], kp3[9], kp3[10]
    right = np.array([np.sin(scene.heading[f, i]), -np.cos(scene.heading[f, i]), 0.0])
    assert lw[2] > nose[2] + 0.1 and rw[2] > nose[2] + 0.1, "both wrists above the head"
    assert (lw - rw) @ right > 0, "forearms crossed: the left wrist is on the right"
    _, rows, _ = synth.render_frame(scene, f, synth.render_plate(scene), synth._net_layer(scene))
    kp = np.asarray(next(r for r in rows if r["id"] == p.id)["kp"])
    if kp[0, 2] and kp[9, 2] and kp[10, 2]:
        assert kp[9, 1] < kp[0, 1] and kp[10, 1] < kp[0, 1], "wrists above the nose in pixels"


def test_boxes_hold_their_feet_and_keypoints(scene):
    plate, net = synth.render_plate(scene), synth._net_layer(scene)
    for f in (0, len(scene.t) // 2, len(scene.t) - 1):
        _, rows, _ = synth.render_frame(scene, f, plate, net)
        for r in rows:
            x, y, w, h = r["bb"]
            fx, fy = r["px"]
            assert x - 2 <= fx <= x + w + 2 and y + 0.75 * h <= fy <= y + h + 2, r["id"]
            for kx, ky, v in r["kp"]:
                if v:
                    assert x - 3 <= kx <= x + w + 3 and y - 3 <= ky <= y + h + 3


def test_basketball_makes_drop_through_the_rim_and_misses_do_not():
    for variant in ("half", "full"):
        scene = build_scene("basketball", variant, duration_s=40.0)
        rims = np.asarray(scene.template.rims, dtype=float)
        shots = [e for e in scene.events if e["type"] == "shot"]
        assert shots
        for e in shots:
            sel = (scene.t >= e["t_key"]) & (scene.t <= e["t_end"] + 0.6)
            b = scene.ball[sel]
            b = b[np.isfinite(b).all(axis=1)]
            r = np.min(np.linalg.norm(b[:, None, :2] - rims[None], axis=2), axis=1)
            crossing = (b[:-1, 2] >= RIM_H_M) & (b[1:, 2] < RIM_H_M)
            through = bool(np.any(crossing & (r[1:] < RIM_R_M - scene.style["ball_r"] / 2)))
            assert through == e["made"], e


def test_net_sport_balls_clear_the_net():
    for sport, variant in SPORTS[2:]:
        scene = build_scene(sport, variant, duration_s=40.0)
        net_y, net_h = scene.template.net_y, scene.style["net_h"]
        into_net = [
            e["t_key"] for e in scene.events if e["type"] == "point" and e["cause"] == "net"
        ]
        b = scene.ball
        for f in range(len(b) - 1):
            if not (np.isfinite(b[f]).all() and np.isfinite(b[f + 1]).all()):
                continue
            if (b[f, 1] - net_y) * (b[f + 1, 1] - net_y) < 0:
                if any(abs(scene.t[f] - t) < 1.2 for t in into_net):
                    continue
                assert min(b[f, 2], b[f + 1, 2]) > net_h, f"{sport} t={scene.t[f]:.2f}"


def test_calibration_doc_is_the_true_camera():
    for k1 in (0.0, -0.2):
        scene = build_scene("badminton", duration_s=4.0, camera=CameraSpec(k1=k1))
        doc = synth.calibration_doc(scene)
        assert doc["synthetic"] is True and doc["dist"] == [k1]
        names = [n for n in doc["landmarks_px"] if doc["landmarks_world"][n][2] == 0.0]
        px = np.asarray([doc["landmarks_px"][n] for n in names])
        world = np.asarray([doc["landmarks_world"][n][:2] for n in names])
        straight = undistort_points(px, k1, tuple(doc["image_size"]))
        assert np.allclose(project(straight, np.asarray(doc["H"])), world, atol=1e-3)
        K, R, t = (np.asarray(doc[k]) for k in ("K", "R", "t"))
        tops = [n for n in doc["landmarks_px"] if doc["landmarks_world"][n][2] > 0]
        assert tops, "height landmarks (net tops) for a PnP calibration"
        for n in tops:
            cam = R @ np.asarray(doc["landmarks_world"][n]) + t
            uv = (K @ cam)[:2] / cam[2]
            got = undistort_points(
                np.asarray([doc["landmarks_px"][n]]), k1, tuple(doc["image_size"])
            )
            assert np.allclose(got[0], uv, atol=1e-3)


def test_voice_triggers_fall_back_to_a_labelled_tone_without_tts():
    scene = build_scene("basketball", "half", duration_s=40.0)
    audio, voices = synth.synth_audio(scene, None)
    assert voices and all(v["source"] == "tone-fallback" for v in voices)
    assert len(audio) == int(round(40.0 * synth.AUDIO_SR)) and np.abs(audio).max() <= 1.0
    for v in voices:  # the voice is audible over the crowd bed
        i, j = int(v["t_start"] * synth.AUDIO_SR), int(v["t_end"] * synth.AUDIO_SR)
        assert np.sqrt((audio[i:j] ** 2).mean()) > 3 * np.sqrt((audio[:i][-8000:] ** 2).mean())


def test_generate_writes_a_muxed_clip_and_every_contract_file(tmp_path: Path):
    paths = synth.generate(tmp_path, sport="pickleball", duration_s=3.0, size=(640, 360))
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
         str(paths["clip"])],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    assert sorted(probe) == ["audio", "video"]
    gt = json.loads(paths["ground_truth"].read_text())
    assert gt["synthetic"] is True and len(gt["frames"]) == 90
    assert {"id", "bb", "ct", "px", "vis", "kp", "oncourt"} <= set(gt["frames"][0]["d"][0])
    for name, schema in (("plays", "replay.plays.v1"), ("triggers", "replay.triggers.v1"),
                         ("calibration", "replay.calibration.v1")):  # fmt: skip
        doc = json.loads(paths[name].read_text())
        assert doc["schema"] == schema and doc["synthetic"] is True
    calib = json.loads(paths["calibration"].read_text())
    assert {"H", "K", "R", "t", "dist", "reproj_err_px", "landmarks_px", "landmarks_world"} <= set(
        calib
    )
