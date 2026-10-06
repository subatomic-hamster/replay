"""MotionBERT 3D pose lifter adapter (the optional, H36M-trained extra; D-40).

MotionBERT (Walter0807/MotionBERT, Apache-2.0 code + weights, trained on Human3.6M)
lives on the box outside the repo; nothing here imports it. `lift()` resamples each
2D sequence to the model's 50 fps, cuts 243-frame windows (stride 121, blended with
triangular weights; a shorter sequence is stretched to one window), and runs the model
in a subprocess with the `lift` venv's python — the caller holds the GPU lock (the
worker's GPU stage does; on the command line wrap it in `flock`). Inputs and outputs
are in MotionBERT's normalised units: (x, y, score) in, root-relative (x, y, z) out,
camera axes (x right, y down, z forward).

Configure with REPLAY_MOTIONBERT_DIR (code checkout), REPLAY_MOTIONBERT_CKPT,
REPLAY_LIFT_PYTHON; `available()` says whether all three exist.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ENV = Path("/workspace/wt/replay-env")
MODEL_FPS = 50.0
CLIP = 243
STRIDE = 121
TIMEOUT_S = 600


def _paths() -> tuple[Path, Path, Path]:
    code = Path(os.environ.get("REPLAY_MOTIONBERT_DIR", ENV / "models/src/MotionBERT"))
    ckpt = Path(
        os.environ.get(
            "REPLAY_MOTIONBERT_CKPT",
            ENV / "models/motionbert/checkpoint/pose3d/FT_MB_release_MB_ft_h36m/best_epoch.bin",
        )
    )
    py = Path(os.environ.get("REPLAY_LIFT_PYTHON", ENV / "venvs/lift/bin/python"))
    return code, ckpt, py


def available() -> bool:
    return all(p.exists() for p in _paths())


def _resample(x: np.ndarray, n: int) -> np.ndarray:
    """(F, ...) -> (n, ...) by linear interpolation over the index."""
    src = np.linspace(0.0, 1.0, len(x))
    dst = np.linspace(0.0, 1.0, n)
    flat = x.reshape(len(x), -1)
    out = np.stack([np.interp(dst, src, flat[:, d]) for d in range(flat.shape[1])], axis=1)
    return out.reshape((n, *x.shape[1:]))


def windows(n: int) -> list[int]:
    """Start frames of the 243-frame windows covering n >= 243 frames."""
    starts = list(range(0, n - CLIP + 1, STRIDE))
    if starts[-1] != n - CLIP:
        starts.append(n - CLIP)
    return starts


def plan(seq: np.ndarray, fps: float) -> tuple[np.ndarray, int]:
    """One (F, 17, 3) sequence -> (W, 243, 17, 3) model windows and the 50 fps length."""
    n = max(2, round((len(seq) - 1) * MODEL_FPS / fps) + 1)
    s = _resample(seq, n)
    if n <= CLIP:
        return _resample(s, CLIP)[None], n
    return np.stack([s[a : a + CLIP] for a in windows(n)]), n


def merge(out: np.ndarray, n: int, length: int) -> np.ndarray:
    """Model windows back to one (length, 17, 3) sequence at the caller's fps."""
    if n <= CLIP:
        s = _resample(out[0], n)
    else:
        acc = np.zeros((n, *out.shape[2:]))
        wsum = np.zeros(n)
        tri = 1.0 - np.abs(np.linspace(-1, 1, CLIP)) + 1e-3
        for w, a in zip(out, windows(n), strict=True):
            acc[a : a + CLIP] += w * tri[:, None, None]
            wsum[a : a + CLIP] += tri
        s = acc / wsum[:, None, None]
    return _resample(s, length)


def lift(seqs: list[np.ndarray], fps: float) -> list[np.ndarray]:
    """2D (F, 17, 3) sequences (normalised x, y, score; H36M order) -> 3D (F, 17, 3)."""
    if not seqs:
        return []
    code, ckpt, py = _paths()
    plans = [plan(s, fps) for s in seqs]
    batch = np.concatenate([w for w, _ in plans]).astype(np.float32)
    with tempfile.TemporaryDirectory(prefix="tierc_lift_") as tmp:
        src, dst = Path(tmp) / "in.npy", Path(tmp) / "out.npy"
        np.save(src, batch)
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
        subprocess.run(
            [str(py), "-m", "replay_render.avatars.lift", str(code), str(ckpt), str(src), str(dst)],
            check=True,
            timeout=TIMEOUT_S,
            env=env,
        )
        res = np.load(dst)
    out, i = [], 0
    for (w, n), s in zip(plans, seqs, strict=True):
        out.append(merge(res[i : i + len(w)], n, len(s)))
        i += len(w)
    return out


def _run(code: Path, ckpt: Path, src: Path, dst: Path) -> None:  # pragma: no cover - box only
    import torch

    torch.backends.cudnn.enabled = False  # D-39: MIOpen on gfx1201
    sys.path.insert(0, str(code))
    from lib.utils.learning import load_backbone
    from lib.utils.tools import get_config
    from lib.utils.utils_data import flip_data

    args = get_config(str(code / "configs/pose3d/MB_ft_h36m.yaml"))
    model = load_backbone(args)
    sd = torch.load(ckpt, map_location="cpu", weights_only=False)["model_pos"]
    model.load_state_dict({k.replace("module.", ""): v for k, v in sd.items()}, strict=True)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(dev).eval()
    x = torch.from_numpy(np.load(src))
    outs = []
    with torch.no_grad():
        for b in torch.split(x, 8):
            b = b.to(dev)
            y = (model(b) + flip_data(model(flip_data(b)))) / 2  # flip test-time augmentation
            y[:, :, 0, :] = 0  # root-relative
            outs.append(y.cpu().numpy())
    np.save(dst, np.concatenate(outs))


if __name__ == "__main__":
    _run(*(Path(a) for a in sys.argv[1:5]))
