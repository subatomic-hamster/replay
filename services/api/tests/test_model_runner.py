"""Local model providers through the runner boundary. Unit tests mock the subprocess /
HTTP server; the last test runs the real models and only on the box
(`REPLAY_MODEL_VENVS=/workspace/wt/replay-env/venvs pytest -k box`)."""

from __future__ import annotations

import json
import os
import threading
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from replay_api.providers import _runner
from replay_api.providers.embeddings import LocalEmbeddings
from replay_api.providers.llm import LocalLLM
from replay_api.providers.speaker import LocalSpeaker
from replay_api.providers.tts import LocalTTS


@pytest.fixture
def venvs(tmp_path, monkeypatch):
    for v in ("tts", "emb", "speaker"):
        py = tmp_path / "venvs" / v / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text("")
    monkeypatch.setenv("REPLAY_MODEL_VENVS", str(tmp_path / "venvs"))
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    monkeypatch.delenv("REPLAY_MODEL_DEVICE", raising=False)
    monkeypatch.delenv("REPLAY_HF_HOME", raising=False)
    monkeypatch.delenv("REPLAY_HF_OFFLINE", raising=False)
    calls: list[dict] = []

    def fake_run(cmd, input, capture_output, text, env, check):
        req = json.loads(input)
        calls.append({"cmd": cmd, "req": req, "env": env})
        kind = cmd[-1]
        if kind == "tts":
            out = {"items": [{"out": i["out"], "seconds": 1.0} for i in req["items"]], "load_s": 1}
        elif kind == "embed":
            out = {"images": [[1.0, 0.0]] * len(req["images"]), "texts": [[0.0, 1.0]] * len(req["texts"])}  # fmt: skip
        else:
            out = {"embeddings": [[0.6, 0.8]] * len(req["clips"])}
        return SimpleNamespace(returncode=0, stdout="chatter\n" + json.dumps(out), stderr="")

    monkeypatch.setattr(_runner.subprocess, "run", fake_run)
    return SimpleNamespace(root=tmp_path, calls=calls)


def test_tts_runs_in_its_venv_under_the_gpu_lock(venvs):
    out = LocalTTS().synthesize("Marcus scores!", venvs.root / "a.wav", voice="af_heart")
    assert out == venvs.root / "a.wav"
    c = venvs.calls[0]
    assert c["cmd"][:2] == ["flock", str(venvs.root / "gpu.lock")]
    assert c["cmd"][2:4] == ["timeout", "900"]
    assert c["cmd"][4].endswith("venvs/tts/bin/python") and c["cmd"][-1] == "tts"
    assert c["req"] == {"device": "cuda", "voice": "af_heart",
                        "items": [{"text": "Marcus scores!", "out": str(venvs.root / "a.wav")}]}  # fmt: skip
    assert c["env"]["HF_HOME"] == str(venvs.root / "hf")
    assert c["env"]["HF_HUB_OFFLINE"] == "1"


def test_cpu_device_takes_no_gpu_lock(venvs, monkeypatch):
    monkeypatch.setenv("REPLAY_MODEL_DEVICE", "cpu")
    LocalEmbeddings().embed_texts(["a steal"])
    assert venvs.calls[0]["cmd"][0] == "timeout"


def test_embeddings_one_load_for_images_and_texts(venvs):
    imgs, txts = LocalEmbeddings().embed([Path("a.jpg"), Path("b.jpg")], ["a steal"])
    assert len(venvs.calls) == 1 and len(imgs) == 2 and txts == [[0.0, 1.0]]


def test_runner_failure_is_loud(venvs, monkeypatch):
    def boom(*a, **k):
        return SimpleNamespace(returncode=3, stdout="", stderr="miopenStatusUnknownError")

    monkeypatch.setattr(_runner.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="miopen"):
        LocalTTS().synthesize("x", Path("x.wav"))


def test_speaker_is_opt_in(venvs, tmp_path, monkeypatch):
    sp = LocalSpeaker(store_dir=tmp_path / "voices")
    assert sp.identify(Path("game.wav"), 1.0, 3.0) == []  # nobody enrolled: model never runs
    assert venvs.calls == []
    assert sp.enroll("prof_1", [Path("a.wav"), Path("b.wav")])["voice_enrolled"]
    hits = sp.identify(Path("game.wav"), 1.0, 3.0)
    assert hits == [{"profile_id": "prof_1", "score": 1.0}]
    assert venvs.calls[-1]["req"]["clips"] == [{"path": "game.wav", "t_start": 1.0, "t_end": 3.0}]
    sp.forget("prof_1")
    assert sp.identify(Path("game.wav"), 1.0, 3.0) == []
    with pytest.raises(ValueError):
        sp.enroll("../x", [])


class _Handler(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict]] = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.seen.append({"path": self.path, "body": body})
        reply = {"choices": [{"message": {"content": '{"lines": ["ok"]}'}}],
                 "timings": {"predicted_per_second": 100.0}}  # fmt: skip
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_llm_is_deterministic_and_schema_constrained():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        llm = LocalLLM(url=f"http://127.0.0.1:{srv.server_port}")
        schema = {"type": "object"}
        assert llm.complete("hi", system="sys", json_schema=schema) == '{"lines": ["ok"]}'
    finally:
        srv.shutdown()
    seen = _Handler.seen[-1]
    assert seen["path"] == "/v1/chat/completions"
    b = seen["body"]
    assert b["temperature"] == 0 and b["seed"] == 0
    assert b["messages"][0] == {"role": "system", "content": "sys"}
    assert b["response_format"]["json_schema"]["schema"] == schema
    assert llm.last == {"predicted_per_second": 100.0}


BOX = os.environ.get("REPLAY_MODEL_VENVS")


@pytest.mark.skipif(not BOX or not Path(BOX).is_dir(), reason="box only: real model venvs")
def test_box_models_end_to_end(tmp_path):
    wav = LocalTTS().synthesize("Casey knocks down the three!", tmp_path / "line.wav")
    with wave.open(str(wav)) as w:
        seconds = w.getnframes() / w.getframerate()
    assert 0.8 < seconds < 6.0
    _, txt = LocalEmbeddings().embed([], ["a basketball game", "a badminton match"])
    assert len(txt) == 2 and abs(sum(x * x for x in txt[0]) - 1.0) < 1e-3
