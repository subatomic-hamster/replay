"""Model runner: the boundary between the API/worker venv and the model venvs.

The models live in their own venvs on the box (docs/models.md: `venvs/tts` Kokoro,
`venvs/emb` open_clip/SigLIP, `venvs/speaker` ECAPA), whose deps clash with the API's.
So a provider never imports a model: it runs this file with the model venv's python,
one process per batch:

    <venv>/bin/python -I _runner.py <kind>   < request.json   > response.json

This file is stdlib-only at import time (the caller side runs in the API venv); the
model imports happen inside the `_kind` functions in the child. The child sets
`torch.backends.cudnn.enabled = False` (D-39, MIOpen bugs on gfx1201). A GPU call is
wrapped as `flock <gpu lock> timeout <s> ...` (D-39), so the lock is held only while the
model runs and a hang cannot wedge it.

Config (all optional; unset → the provider raises NotConfiguredError):
  REPLAY_MODEL_VENVS   dir holding the venvs (box: /workspace/wt/replay-env/venvs)
  REPLAY_MODEL_DEVICE  cuda | cpu (default cuda)
  REPLAY_GPU_LOCK      lock file (default /workspace/airtools/.gpu.lock when it exists)
  REPLAY_HF_HOME       the child's HF_HOME (default <venvs>/../hf, the box's model cache)
  REPLAY_HF_OFFLINE    the child's HF_HUB_OFFLINE (default 1: never download, never ping)

ponytail: one process per call reloads the model (measured on the box: Kokoro load 1.1 s,
~5 s of imports + load per batch; SigLIP ~5 s; docs/evidence/M7/README.md); a long-lived
runner per venv if per-request latency starts to matter.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

VENV_OF = {"tts": "tts", "embed": "emb", "speaker": "speaker"}


def venvs_root() -> Path | None:
    root = os.environ.get("REPLAY_MODEL_VENVS")
    return Path(root) if root else None


def python_for(kind: str) -> Path | None:
    root = venvs_root()
    if root is None:
        return None
    py = root / VENV_OF[kind] / "bin" / "python"
    return py if py.exists() else None


def device() -> str:
    return os.environ.get("REPLAY_MODEL_DEVICE", "cuda")


def gpu_lock() -> str | None:
    env = os.environ.get("REPLAY_GPU_LOCK")
    if env:
        return env
    shared = "/workspace/airtools/.gpu.lock"
    return shared if os.path.exists(shared) else None


def call(kind: str, request: dict, *, timeout_s: int = 900) -> dict:
    """Run one batch in the `kind` venv and return its JSON response."""
    py = python_for(kind)
    if py is None:
        raise FileNotFoundError(f"no python for {kind!r} under REPLAY_MODEL_VENVS")
    req = {"device": device(), **request}
    cmd = [str(py), "-I", str(Path(__file__).resolve()), kind]
    lock = gpu_lock() if req["device"] != "cpu" else None
    cmd = (["flock", lock] if lock else []) + ["timeout", str(timeout_s)] + cmd
    env = dict(os.environ)
    root = venvs_root()
    if root is not None:
        # the box exports HF_HOME=/workspace/.hf (another user's cache): never inherit it
        env["HF_HOME"] = os.environ.get("REPLAY_HF_HOME") or str(root.parent / "hf")
    # weights are pre-cached; hub freshness checks from the box cost ~80 s per load (measured)
    env["HF_HUB_OFFLINE"] = os.environ.get("REPLAY_HF_OFFLINE", "1")
    res = subprocess.run(
        cmd, input=json.dumps(req), capture_output=True, text=True, env=env, check=False
    )
    if res.returncode != 0:
        raise RuntimeError(f"{kind} runner exited {res.returncode}: {res.stderr[-1500:]}")
    return json.loads(res.stdout.strip().splitlines()[-1])


# --- child side (runs inside the model venv) ---------------------------------------------


def _torch(dev: str):
    import torch

    torch.backends.cudnn.enabled = False  # D-39 / FL-9: MIOpen LSTM + conv bugs on gfx1201
    return torch


def _tts(req: dict) -> dict:
    import time

    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    _torch(req["device"])
    voice = req.get("voice") or "am_michael"
    t0 = time.time()
    pipe = KPipeline(lang_code=voice[0], device=req["device"], repo_id="hexgrad/Kokoro-82M")
    load_s = time.time() - t0
    out = []
    for item in req["items"]:
        t1 = time.time()
        audio = np.concatenate([a.numpy() for _, _, a in pipe(item["text"], voice=voice)])
        Path(item["out"]).parent.mkdir(parents=True, exist_ok=True)
        sf.write(item["out"], audio, 24000, subtype="PCM_16")
        out.append({"out": item["out"], "seconds": round(len(audio) / 24000, 3),
                    "synth_s": round(time.time() - t1, 3)})  # fmt: skip
    return {"items": out, "load_s": round(load_s, 3), "voice": voice, "sr": 24000}


def _tokenizer(open_clip, name: str):
    """open_clip's HF tokenizer from the cached snapshot dir: by hub id, transformers asks
    the hub for a config.json the repo lacks, which fails under HF_HUB_OFFLINE (measured)."""
    cfg = open_clip.get_model_config(name)["text_cfg"]
    if "hf_tokenizer_name" not in cfg:
        return open_clip.get_tokenizer(name)
    from huggingface_hub import snapshot_download

    path = snapshot_download(cfg["hf_tokenizer_name"], local_files_only=True)
    return open_clip.tokenizer.HFTokenizer(
        path, context_length=cfg.get("context_length"), **cfg.get("tokenizer_kwargs", {})
    )


def _embed(req: dict) -> dict:
    import time

    import open_clip
    from PIL import Image

    torch = _torch(req["device"])
    t0 = time.time()
    name, pre = req.get("model", "ViT-B-16-SigLIP"), req.get("pretrained", "webli")
    prec = "fp16" if req["device"] != "cpu" else "fp32"
    model, _, preprocess = open_clip.create_model_and_transforms(
        name, pretrained=pre, device=req["device"], precision=prec
    )
    model.eval()
    load_s = time.time() - t0
    t1 = time.time()
    out: dict = {"model": f"{name}/{pre}", "load_s": round(load_s, 3)}
    with torch.no_grad():
        if req.get("images"):
            x = torch.stack([preprocess(Image.open(p).convert("RGB")) for p in req["images"]])
            x = x.to(req["device"], dtype=torch.float16 if prec == "fp16" else torch.float32)
            f = model.encode_image(x).float()
            out["images"] = (f / f.norm(dim=-1, keepdim=True)).cpu().tolist()
        if req.get("texts"):
            tok = _tokenizer(open_clip, name)
            f = model.encode_text(tok(req["texts"]).to(req["device"])).float()
            out["texts"] = (f / f.norm(dim=-1, keepdim=True)).cpu().tolist()
    out["embed_s"] = round(time.time() - t1, 3)
    return out


def _speaker(req: dict) -> dict:
    import soundfile as sf
    import torchaudio
    from speechbrain.inference.speaker import EncoderClassifier

    torch = _torch(req["device"])
    clf = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=req["savedir"],
        run_opts={"device": req["device"]},
    )
    out = []
    for clip in req["clips"]:
        w, sr = sf.read(clip["path"], dtype="float32", always_2d=True)
        w = torch.from_numpy(w.mean(axis=1))
        a, b = clip.get("t_start"), clip.get("t_end")
        if a is not None and b is not None:
            w = w[int(a * sr) : int(b * sr)]
        w = torchaudio.functional.resample(w, sr, 16000)
        e = clf.encode_batch(w[None].to(req["device"]))[0, 0]
        out.append((e / e.norm()).cpu().tolist())
    return {"embeddings": out}


def main() -> int:
    import time

    t0 = time.time()
    kind = sys.argv[1]
    req = json.loads(sys.stdin.read())
    real_stdout, sys.stdout = sys.stdout, sys.stderr  # model chatter must not break the JSON
    res = {"tts": _tts, "embed": _embed, "speaker": _speaker}[kind](req)
    res["child_s"] = round(time.time() - t0, 3)  # imports + load + work, after the lock
    real_stdout.write(json.dumps(res) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
