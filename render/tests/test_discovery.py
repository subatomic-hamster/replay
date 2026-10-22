"""M11: hype meter, rally browser + condensed game, vertical export, shot chart PNG."""

from __future__ import annotations

import json
import shutil
import subprocess

import cv2
import numpy as np
import pytest
from replay_render import condensed, hype, vertical
from replay_render.gamedata import load_game
from replay_render.graphics import ACCENT
from replay_render.testing import make_toy_game

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _ev(i, kind, t0, t1=None, **kw):
    t1 = t0 if t1 is None else t1
    return {"id": f"x{i}", "type": kind, "t_start": t0, "t_key": t0, "t_end": t1,
            "confidence": 0.6, **kw}  # fmt: skip


RALLY_EVENTS = [
    _ev(1, "rally", 2.0, 6.0, contacts=None),
    _ev(2, "serve", 2.0, player_id="p1", team=0),
    *[_ev(3 + k, "contact", 2.5 + k, player_id="p1", team=0) for k in range(3)],
    _ev(6, "point", 6.0, player_id="p3", team=1),
    _ev(7, "rally", 12.0, 18.5, contacts=7),
    _ev(8, "rally", 19.0, 20.0, contacts=2),  # 0.5 s after the last: one segment
]


def test_rally_browser_counts_and_orders():
    plays = [{"id": "pl1", "grammar": "rally", "t_start": 2.0, "t_end": 6.0}]
    rallies = condensed.rally_list(RALLY_EVENTS, plays)
    assert [r["duration_s"] for r in rallies] == [4.0, 6.5, 1.0]
    r1 = rallies[0]
    assert (r1["shots"], r1["shots_source"]) == (3, "contact_events")
    assert (r1["server_id"], r1["last_hit_player_id"], r1["play_id"]) == ("p1", "p3", "pl1")
    assert (rallies[1]["shots"], rallies[1]["shots_source"]) == (7, "audio_contacts")
    doc = condensed.browser(rallies, 24.0)
    assert doc["longest"][:2] == ["r2", "r1"] and doc["most_shots"][0] == "r2"
    assert doc["rally_s"] == 11.5 and doc["dead_time_s"] == 12.5
    segs = condensed.segments(rallies, 24.0)
    assert segs == [(0.5, 7.0), (10.5, 21.0)]
    condensed.condensed_offsets(rallies, segs)
    assert [r["condensed_t"] for r in rallies] == [0.0, 6.5, 6.5 + 7.0]


def _probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    doc = json.loads(out.stdout)
    streams = {s["codec_type"]: s for s in doc["streams"]}
    return streams, float(doc["format"]["duration"])


def _with_rallies(gd):
    doc = json.loads((gd / "events.json").read_text())
    doc["events"] += RALLY_EVENTS
    (gd / "events.json").write_text(json.dumps(doc))


@needs_ffmpeg
def test_condensed_game_cuts_dead_time(tmp_path):
    gd = make_toy_game(tmp_path / "g_toy", duration=24.0)
    _with_rallies(gd)
    doc = condensed.render_condensed(gd, size=(320, 180), crf=32, label="SYNTHETIC")
    out = gd / condensed.REL
    streams, dur = _probe(out)
    assert streams["video"]["codec_name"] == "h264" and streams["audio"]["codec_name"] == "aac"
    assert (streams["video"]["width"], streams["video"]["height"]) == (320, 180)
    assert doc["condensed_s"] == pytest.approx(6.5 + 10.5, abs=0.05)
    assert dur == pytest.approx(doc["condensed_s"], abs=0.15)
    assert json.loads((gd / condensed.DOC_REL).read_text())["n"] == 3
    # the rally counter's amber second line, top right (7 + 10 px down at 180p), in rally 1
    cap = cv2.VideoCapture(str(out))
    cap.set(cv2.CAP_PROP_POS_MSEC, 2500)
    ok, f = cap.read()
    cap.release()
    assert ok
    region = f[18:23, 285:310].reshape(-1, 3)[:, ::-1].astype(float)
    assert (np.linalg.norm(region - ACCENT, axis=1) < 70).mean() > 0.3


@needs_ffmpeg
def test_condensed_basketball_cuts_to_the_plays(tmp_path):
    """No rallies: each shot / turnover from LEAD_S before it, counted PLAY n / N."""
    gd = make_toy_game(tmp_path / "g_toy", duration=24.0)
    events = load_game(gd).events
    plays = condensed.play_list(events)
    want = [e for e in events if e["type"] in condensed.PLAY_TYPES]
    assert plays and len(plays) == len(want)
    first = min(want, key=lambda e: e["t_key"])
    assert plays[0]["t_start"] == max(0.0, first["t_start"] - condensed.LEAD_S)
    doc = condensed.render_condensed(gd, size=(320, 180), crf=32)
    assert doc["unit"] == "play" and doc["n"] == len(plays)
    _, dur = _probe(gd / condensed.REL)
    assert 0 < dur <= 24.0 and dur == pytest.approx(doc["condensed_s"], abs=0.15)


def _with_user_clips(gd):
    clip = {"id": "c_0001", "trigger_id": "tr_0001", "t_start": 0.0, "t_end": 3.0,
            "attribution": {"owner_player_id": None}}  # fmt: skip
    (gd / "clips.json").write_text(json.dumps({"clips": [clip]}))
    trig = [{"id": "tr_0001", "type": "voice", "t": 7.5, "transcript": "Replay, clip that"},
            {"id": "tr_0002", "type": "gesture", "t": 23.0}]  # fmt: skip
    (gd / "triggers.json").write_text(json.dumps({"triggers": trig}))


def test_reel_plan_puts_the_users_clips_first(tmp_path):
    from itertools import combinations

    from replay_render import reel

    gd = make_toy_game(tmp_path / "g_toy", duration=24.0, video=False)
    _with_user_clips(gd)
    segs = reel.plan(load_game(gd))
    got = [(s["kind"], s["tag"], s["t_start"], s["t_end"]) for s in segs]
    assert got[0] == ("clip", "YOUR CLIP (VOICE)", 0.0, 3.0)
    # the X sign found no play: the 8 s before it; it wins over the 19 s shot it covers
    assert ("clip", "YOUR CLIP (X SIGN)", 15.0, 23.0) in got
    assert [s["t_end"] for s in segs if s["kind"] == "top"] == [11.0]  # the 9 s shot
    assert all(reel._overlap(a, b) <= 0.5 for a, b in combinations(segs, 2))
    assert [s["t_start"] for s in segs] == sorted(s["t_start"] for s in segs)


@needs_ffmpeg
def test_reel_renders_9x16_with_dips_between_segments(tmp_path):
    from replay_render import reel

    gd = make_toy_game(tmp_path / "g_toy", duration=24.0)
    _with_user_clips(gd)
    out = gd / reel.DIR / "r_test.mp4"
    doc = reel.render_reel(gd, {"id": "r_test", "aspect": "9:16"}, out)
    streams, dur = _probe(out)
    assert (streams["video"]["width"], streams["video"]["height"]) == (720, 1280)
    assert streams["audio"]["codec_name"] == "aac"
    assert dur == pytest.approx(doc["duration_s"], abs=0.15)
    plan = json.loads(out.with_suffix(".plan.json").read_text())
    assert plan["schema"] == reel.SCHEMA and plan["segments"][1]["reel_t"] > 0
    cap = cv2.VideoCapture(str(out))
    ok, first = cap.read()  # the reel opens on the dip from black
    cap.set(cv2.CAP_PROP_POS_MSEC, 2500)
    ok2, mid = cap.read()
    cap.release()
    assert ok and ok2 and first.mean() < 15 and mid.mean() > 40


@needs_ffmpeg
def test_vertical_export_follows_the_key_player(tmp_path):
    gd = make_toy_game(tmp_path / "g_toy", duration=24.0)
    game = load_game(gd)
    spec = vertical.resolve(game, event_id="e1")
    assert spec["player_id"] == "p1" and spec["caption"] == "Avery  ·  2-PT MAKE"
    assert (spec["t_start"], spec["t_end"]) == (5.0, 12.0)
    assert vertical.spec_id(spec) == vertical.spec_id(dict(spec))
    # the window stays on p1 while he runs
    p = vertical.path(game, spec["t_start"], 210, game.fps, "p1")
    i = game.tracks.index("p1")
    t = spec["t_start"] + np.arange(210) / game.fps
    box = game.tracks.at(game.tracks.box[i : i + 1], t)[0]
    cx = (box[:, 0] + box[:, 2]) / 2
    half_w = p[:, 2] / 2
    # the toy teleports 4 m at 6 s (frame 30); from 8 s on p1 never leaves the window
    assert (np.abs(p[90:, 0] - cx[90:]) < half_w[90:]).all()
    assert vertical.cam.jitter(p, 180)["rms_px"] < 1.0
    out = tmp_path / "v.mp4"
    info = vertical.export(gd, spec, out, size=(180, 320), crf=32, game=game)
    streams, dur = _probe(out)
    assert (streams["video"]["width"], streams["video"]["height"]) == (180, 320)
    assert streams["video"]["codec_name"] == "h264" and streams["audio"]["codec_name"] == "aac"
    assert dur == pytest.approx(7.0, abs=0.15) and info["render"]["frames"] == 210


def test_vertical_resolve_rejects_unknown_and_empty(tmp_path):
    game = load_game(make_toy_game(tmp_path / "g_toy", duration=24.0, video=False))
    with pytest.raises(KeyError):
        vertical.resolve(game, play_id="nope")
    with pytest.raises(ValueError):
        vertical.resolve(game, t_start=3.0, t_end=3.2)
    spec = vertical.resolve(game, t_start=1.0, t_end=4.0)
    assert spec["player_id"] is None and spec["caption"] == "HIGHLIGHT"


def test_vertical_caption_for_a_rally_play(tmp_path):
    gd = make_toy_game(tmp_path / "g_toy", duration=24.0, video=False)
    _with_rallies(gd)
    play = {"id": "pl1", "grammar": "rally", "t_start": 2.0, "t_end": 6.0,
            "event_ids": ["x2", "x3", "x4", "x5", "x6"],  # serve, contacts, point
            "participants": [{"player_id": "p1", "role": "server"}]}  # fmt: skip
    (gd / "plays.json").write_text(json.dumps({"plays": [play]}))
    spec = vertical.resolve(load_game(gd), play_id="pl1")
    assert spec["caption"] == "RALLY  ·  3 SHOTS  ·  4.0 S" and spec["player_id"] == "p1"


def _pose(arms_up: bool):
    kp = np.zeros((17, 3))
    kp[:, 2] = 0.9
    kp[[5, 6], 1] = 0.40  # shoulders
    kp[[11, 12], 1] = 0.55  # hips
    kp[[9, 10], 1] = 0.30 if arms_up else 0.60  # wrists
    return kp.round(3).tolist()


def test_hype_fuses_crowd_noise_and_arms_up(tmp_path):
    gd = make_toy_game(tmp_path / "g_toy", duration=24.0, video=False)
    db = np.full(240, -40.0)
    db[120:140] = -26.0  # a 2 s roar at 12-14 s
    (gd / "audio.json").write_text(json.dumps(
        {"schema": "replay.audio.v1", "has_audio": True, "rate_hz": 10,
         "loudness_db": db.tolist(), "onsets": [], "hype": []}))  # fmt: skip
    frames = [
        {"t": round(t, 1), "p": [{"id": pid, "c": 0.9,
                                  "kp": _pose(12.5 <= t <= 14.0 or 7.0 <= t <= 9.0)}
                                 for pid in ("p1", "p2")]}
        for t in np.arange(0, 24, 0.1)
    ]  # fmt: skip
    (gd / "poses").mkdir()
    (gd / "poses" / "00000.json").write_text(json.dumps({"t0": 0, "frames": frames}))
    doc = hype.hype_series(load_game(gd))
    assert doc["schema"] == "replay.hype.v1" and len(doc["values"]) == 48
    assert all(0.0 <= v <= 1.0 for v in doc["values"])
    assert doc["sources"] == {"audio": "audio.json", "arms_up": "poses", "speed": "tracks",
                              "plays": "events.json"}  # fmt: skip
    comps = doc["components"]
    roar = slice(2 * 12 + 1, 2 * 14)  # 12.5-13.5 s at 2 Hz
    assert min(comps["audio"][roar]) >= 0.3 and min(comps["arms_up"][roar]) >= 0.3
    assert max(doc["values"][roar]) > max(doc["values"][2 * 10 : 2 * 12])  # the cheer adds
    # the toy's two makes are the highlights, the three (19 s) first (D-90)
    top = doc["candidates"][0]
    assert 19.0 <= top["t"] <= 22.5 and "plays" in top["reasons"]
    assert any(9.0 <= c["t"] <= 14.0 for c in doc["candidates"][1:])
    quiet = doc["values"][: 2 * 5]  # nothing happens in the first 5 s
    assert max(quiet) < 0.2
    # arms up during e1's shot (6-10 s) is the shot, not a celebration
    assert max(doc["components"]["arms_up"][14:19]) == 0.0


def test_hype_without_audio_or_poses_is_motion_only(tmp_path):
    gd = make_toy_game(tmp_path / "g_toy", duration=24.0, video=False)
    (gd / "audio.json").write_text(json.dumps({"schema": "replay.audio.v1", "has_audio": False}))
    doc = hype.hype_series(load_game(gd))
    assert doc["sources"]["audio"] is None and doc["sources"]["arms_up"] is None
    assert len(doc["values"]) == 48


def test_shot_chart_png(tmp_path):
    from replay_render.review import shot_chart_png

    stats = {"confidence": 0.8, "shots": [
        {"court": [0.5, 6.0], "team": 0, "outcome": "make"},
        {"court": [-3.0, 22.0], "team": 1, "outcome": "miss"},
        {"court": [4.0, 3.0], "team": None, "outcome": "unknown"}]}  # fmt: skip
    out = shot_chart_png(stats, "basketball", "full", tmp_path / "chart.png", label="SYNTHETIC")
    img = cv2.imread(str(out))
    assert img.shape[1] > img.shape[0] > 500
