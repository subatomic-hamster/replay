"""Compositor + audio smoke tests on the toy synthetic game (needs ffmpeg on PATH)."""

from __future__ import annotations

import json
import shutil
import subprocess

import cv2
import numpy as np
import pytest
from replay_render import audio
from replay_render.camera import Feel, jitter, smooth
from replay_render.compositor import render
from replay_render.director import direct
from replay_render.gamedata import load_game
from replay_render.graphics import ACCENT, LIVE_RED
from replay_render.testing import make_toy_game

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return {s["codec_type"]: s for s in json.loads(out.stdout)["streams"]}


def _frame(path, t):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, f = cap.read()
    cap.release()
    assert ok
    return f


def test_broadcast_rendition_smoke(tmp_path):
    gd = make_toy_game(tmp_path / "g_toy")
    (gd / "cuts.json").write_text(json.dumps(direct(load_game(gd))))
    out = tmp_path / "broadcast.mp4"
    # the commentary hook: a narration WAV on the source clock, game audio ducks under it
    t = np.arange(audio.SR * 20) / audio.SR
    voice = np.where((t > 6) & (t < 8), 0.3 * np.sin(2 * np.pi * 300 * t), 0.0)
    narration = audio.write_wav(tmp_path / "narration.wav", np.column_stack([voice, voice]))
    info = render(gd, out, size=(640, 360), t0=5.0, t1=17.0, crf=23, narration=narration)
    assert info["frames"] == 360 and info["replays"] == 1
    s = _probe(out)
    assert s["video"]["codec_name"] == "h264"
    assert (s["video"]["width"], s["video"]["height"]) == (640, 360)
    assert s["audio"]["codec_name"] == "aac"
    assert not list(tmp_path.glob("*.video.mp4")) and not list(tmp_path.glob("*.mix.wav"))

    def bug_color(t):  # the top-right bug's top padding: red LIVE vs amber REPLAY pill
        f = _frame(out, t - 5.0)
        px = f[14:16, 602:618].reshape(-1, 3).astype(float).mean(axis=0)[::-1]
        return min((LIVE_RED, ACCENT), key=lambda c: np.linalg.norm(np.subtract(px, c)))

    assert bug_color(7.0) == LIVE_RED
    assert bug_color(13.5) == ACCENT  # replay 11-16

    # game audio continues under the replay, ducked ~9 dB; the sting sits on the edges
    mix = audio.mix(gd / "media" / "wide.mp4", 5.0, 17.0, [(11.0, 16.0)])
    sr = audio.SR

    def rms(a, b):
        return float(np.sqrt(np.mean(mix[int((a - 5) * sr) : int((b - 5) * sr)] ** 2)))

    assert rms(13, 15) == pytest.approx(rms(7, 9) * 10 ** (-9 / 20), rel=0.1)
    assert rms(10.8, 11.4) > rms(13, 15) * 1.2


def test_sting_is_deterministic_and_not_noise():
    a, b = audio.sting("in"), audio.sting("in")
    assert np.array_equal(a, b) and a.shape[1] == 2
    assert 0.1 < np.abs(a).max() <= 0.5
    # tonal: the spectrum is peaky, unlike a noise whoosh
    spec = np.abs(np.fft.rfft(a[:, 0]))
    assert spec.max() / np.median(spec) > 100


def test_narration_ducks_game_audio():
    sr = audio.SR
    t = np.arange(sr * 2) / sr
    game = np.column_stack([np.sin(2 * np.pi * 200 * t)] * 2).astype(np.float32) * 0.5
    voice = np.zeros_like(game)
    voice[sr : sr + sr // 2] = 0.3 * np.sin(2 * np.pi * 300 * t[: sr // 2])[:, None]
    out = audio.duck_under(game, voice)
    before = np.abs(out[sr // 4 : sr // 2]).max()
    during = np.abs(out[sr + sr // 8 : sr + sr // 2]).max()
    assert before == pytest.approx(0.5, abs=0.01)
    assert during < 0.5 * 10 ** (-9 / 20)  # at least ~9 dB down while the voice speaks


def test_spring_smoothing_cuts_jitter():
    rng = np.random.default_rng(0)
    n = 600
    raw = np.column_stack(
        [960 + 300 * np.sin(np.arange(n) / 90) + rng.normal(0, 25, n),
         np.full(n, 540.0), np.full(n, 960.0)]
    )  # fmt: skip
    out = smooth(raw, Feel(), 30.0, 1920, 1080, 480.0)
    assert jitter(out)["rms_px"] < 0.05 * jitter(raw)["rms_px"]
    assert np.abs(out[:, 0] - raw[:, 0]).mean() < 120  # still follows the action
