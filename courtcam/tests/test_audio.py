"""Audio features (`courtcam.audio`) and rally fusion on a synthesized track."""

from __future__ import annotations

import numpy as np

from courtcam import audio
from courtcam.events import fuse_rallies
from courtcam.profiles import AudioCfg, RallyCfg
from courtcam.schema import Onset

SR = audio.SR
CLICKS = [2.0, 2.9, 3.7, 4.6, 12.0]
CROWD = (6.0, 8.0)
VOICE = (14.0, 15.2)


def _track() -> np.ndarray:
    rng = np.random.default_rng(0)
    x = 0.01 * rng.normal(size=20 * SR)
    tt = np.arange(int(0.08 * SR)) / SR
    # a racket hit: a broadband click plus a short ring
    ping = 0.5 * np.sin(2 * np.pi * 1000 * tt) * np.exp(-tt / 0.015)
    ping += 0.3 * rng.normal(size=len(tt)) * np.exp(-tt / 0.002)
    for t in CLICKS:
        i = int(t * SR)
        x[i : i + len(ping)] += ping
    a, b = (int(v * SR) for v in CROWD)
    x[a:b] += 0.15 * rng.normal(size=b - a)  # loud, aperiodic
    a, b = (int(v * SR) for v in VOICE)
    tv = np.arange(b - a) / SR
    x[a:b] += sum(0.08 / k * np.sin(2 * np.pi * 150 * k * tv) for k in range(1, 6))  # periodic
    return x.astype(np.float32)


def test_onsets_hype_and_speech():
    cfg = AudioCfg()
    x = _track()
    f = audio.features(x, SR)
    ons = audio.onsets(f["t"], f["flux"], cfg)
    strong = [o.t for o in ons if o.strength >= RallyCfg().contact_min_strength]
    for c in CLICKS:
        assert any(abs(o - c) < 0.05 for o in strong), (c, strong)

    hype = audio.hype_segments(f["t"], f["db"], f["voiced"], cfg)
    assert len(hype) == 1 and abs(hype[0][0] - CROWD[0]) < 0.3 and abs(hype[0][2] - CROWD[1]) < 0.3

    speech = audio.speech_segments(x, SR, cfg)
    assert len(speech) == 1 and speech[0][0] <= VOICE[0] <= speech[0][1], speech
    assert speech[0][1] >= VOICE[1]


def test_fuse_rallies_splits_on_silence_and_drops_weak_onsets():
    cfg = RallyCfg(expected_contact_hz=[1.0, 3.0])  # silences over 1.5 s split
    ons = [Onset(t=t, strength=60.0) for t in (1.0, 2.0, 3.0, 7.0, 8.0, 20.0)]
    ons.append(Onset(t=5.0, strength=5.0))  # a footstep between the two rallies
    runs = fuse_rallies(0.0, 10.0, ons, cfg)
    assert [[o.t for o in r] for r in runs] == [[1.0, 2.0, 3.0], [7.0, 8.0]]
    assert fuse_rallies(0.0, 10.0, [], cfg) == []
