"""M7 stages: commentary (script + narration WAV) and embeddings fan-out per play +
search index, cache-keyed. Fake TTS / embeddings providers: no model, no GPU."""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import wave

import numpy as np
import pytest
from replay_worker import Cache, run

pytest.importorskip("replay_api")
if shutil.which("ffmpeg") is None:
    pytest.skip("needs ffmpeg", allow_module_level=True)

from replay_api import providers
from replay_worker.stages import narrate


class FakeTTS:
    def __init__(self):
        self.last: dict = {}

    def synthesize_many(self, items, *, voice=None):
        for text, path in items:
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(b"\x00\x10" * int(0.04 * 24000 * len(text.split())))


class FakeEmb:
    calls = 0

    def embed(self, images, texts):
        FakeEmb.calls += 1
        assert all(p.is_file() for p in images)
        return [[1.0, 0.0, 0.0]] * len(images), [[0.0, 1.0, 0.0]] * len(texts)


@pytest.fixture
def env(tmp_path, monkeypatch):
    gd = tmp_path / "g_toy"
    (gd / "media").mkdir(parents=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:rate=10:duration=8", "-pix_fmt", "yuv420p",
                    str(gd / "media" / "wide.mp4")], check=True)  # fmt: skip
    game = {"id": "g_toy", "sport": "basketball", "synthetic": True,
            "video": {"duration_s": 8.0},
            "players": [{"id": "p1", "name": "Avery", "team": 0},
                        {"id": "p2", "name": None, "team": 1}]}  # fmt: skip
    events = [
        {"id": "e1", "type": "pass", "t_start": 1.0, "t_key": 1.0, "t_end": 1.5,
         "player_id": "p1", "receiver_id": "p2"},
        {"id": "e2", "type": "shot", "t_start": 2.0, "t_key": 2.5, "t_end": 3.0, "made": True,
         "points": 2, "player_id": "p2", "team": 1},
        {"id": "e3", "type": "shot", "t_start": 5.0, "t_key": 5.5, "t_end": 6.0, "made": False,
         "player_id": "p1", "team": 0},
    ]  # fmt: skip
    plays = [{"id": "pl_1", "t_start": 0.8, "t_end": 3.5, "event_ids": ["e1", "e2"]},
             {"id": "pl_2", "t_start": 4.8, "t_end": 6.5, "event_ids": ["e3"]}]  # fmt: skip
    score = [{"t": 2.5, "scores": [0, 2], "event_id": "e2", "source": "auto"}]
    (gd / "game.json").write_text(json.dumps(game))
    (gd / "events.json").write_text(json.dumps({"schema": "replay.events.v1", "events": events}))
    (gd / "plays.json").write_text(json.dumps({"schema": "replay.plays.v1", "plays": plays}))
    (gd / "score.json").write_text(json.dumps({"schema": "replay.score.v1", "score": score}))
    fakes = {"tts": FakeTTS(), "embeddings": FakeEmb()}
    monkeypatch.setattr(providers, "create", lambda name, **kw: fakes[name])
    stages = {s.name: s for s in narrate.STAGES}
    reg = {
        "commentary": dataclasses.replace(stages["commentary"], after=()),
        "embeddings": dataclasses.replace(stages["embeddings"], after=()),
        "search_index": stages["search_index"],
    }
    return gd, reg, Cache(tmp_path / "cache")


def _go(env, stage, cfg=None):
    gd, reg, cache = env
    recs = run(gd, cfg or {}, registry=reg, stages=[stage], cache=cache)
    return sorted((r["stage"], r["item"] or "", r["cache"]) for r in recs)


def test_commentary_stage_writes_script_and_narration(env):
    gd = env[0]
    assert _go(env, "commentary") == [("commentary", "", "miss")]
    script = json.loads((gd / "commentary" / "script.json").read_text())
    texts = [ln["text"] for p in script["plays"] for ln in p["lines"]]
    assert texts == ["Avery finds Player 2.", "Player 2 scores two.", "That puts it at 0 to 2.",
                     "Avery shoots, no good."]  # fmt: skip
    assert script["summary"]["template_grounded"] == 2
    with wave.open(str(gd / "commentary" / "narration.wav")) as w:
        assert w.getnframes() / w.getframerate() >= 8.0
    assert (gd / "commentary" / "pl_1.wav").is_file()
    assert _go(env, "commentary") == [("commentary", "", "hit")]
    assert _go(env, "commentary", {"commentary_voice": "bf_emma"}) == [("commentary", "", "miss")]


def test_embeddings_one_model_load_for_every_play_and_index(env):
    gd = env[0]
    FakeEmb.calls = 0
    recs = _go(env, "search_index")
    assert recs == [("embeddings", "", "miss"), ("search_index", "", "off")]
    assert FakeEmb.calls == 1  # every play in one runner call (was one per play)
    vec = np.load(gd / "embeddings" / "pl_1.npy")
    assert vec.shape == (2, 3) and np.allclose(vec[0], [1, 0, 0])
    idx = json.loads((gd / "embeddings" / "index.json").read_text())
    assert [p["id"] for p in idx["plays"]] == ["pl_1", "pl_2"]
    assert idx["plays"][1]["text"] == "basketball play. Avery shoots, no good."
    assert ("embeddings", "", "hit") in _go(env, "search_index")
    assert (gd / "embeddings" / "index.json").is_file()  # rebuilt after the restore
    assert not list((gd / "embeddings").glob("_kf_*"))  # keyframes cleaned up


def test_commentary_without_a_tts_model_is_captions_only(env, monkeypatch):
    from replay_api.providers.tts import LocalTTS

    monkeypatch.delenv("REPLAY_MODEL_VENVS", raising=False)
    monkeypatch.setattr(providers, "create", lambda name, **kw: LocalTTS())
    assert _go(env, "commentary") == [("commentary", "", "miss")]
    script = json.loads((env[0] / "commentary" / "script.json").read_text())
    assert "REPLAY_MODEL_VENVS" in script["tts"]["skipped"] and script["plays"]


def test_registered_off_the_default_dag():
    from replay_worker.stages import load_registry

    reg = load_registry()
    assert {"commentary", "embeddings", "search_index"} <= set(reg)
    assert not any(reg[n].default for n in ("commentary", "embeddings", "search_index"))
    assert reg["commentary"].after == ("game",)
