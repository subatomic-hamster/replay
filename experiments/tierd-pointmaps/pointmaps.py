"""Tier D experiment A, GPU half: MoGe-2 metric point maps for one highlight.

For a game dir produced by the worker (`calibration.json`, `plate/plate.jpg`,
`segments/{play}.npz`, `media/wide.mp4`):

1. MoGe-2 (ViT-L, normal head; MIT code + weights) on the court plate (players removed
   by the temporal median) -> one static depth map;
2. MoGe-2 on every `--stride`-th frame of the play window -> per-frame depth;
3. every depth map is scaled onto the calibrated floor (median depth ratio over court
   floor pixels that no player covers; MoGe is given the calibrated horizontal FoV, so
   only the scale is free), and SAM-masked player pixels are lifted to court metres.

Writes one npz: plate depth (+ scale, floor residuals), per-frame scales/residuals and
the lifted player points (xyz, BGR, player, frame). Rendering is `scene.py` (CPU).
Run under `flock /workspace/airtools/.gpu.lock timeout ...` (D-39: cudnn off).
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from courtcam.profiles import load_profile
from geom import align_scale, camera, floor_depth, floor_region, to_world
from replay_render.virtual.replays import frame_count, play, probe_video, read_window
from replay_render.virtual.segment import Masks

MOGE = "Ruicheng/moge-2-vitl-normal"
PLAYER_DEPTH_BAND_M = 0.75  # drop flying pixels: farther than this from the player's median


def load_moge():
    torch.backends.cudnn.enabled = False  # D-39 (MIOpen on gfx1201)
    from moge.model.v2 import MoGeModel

    return MoGeModel.from_pretrained(MOGE).to("cuda").eval()


def infer(model, bgr: np.ndarray, fov_x: float, normals: bool = False):
    """Depth (H, W), NaN where MoGe masks the pixel; with `normals`, also (H, W, 3) camera-frame normals."""
    img = torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).to("cuda")
    img = img.permute(2, 0, 1).float() / 255.0
    with torch.no_grad():
        out = model.infer(img, fov_x=fov_x)
    torch.cuda.synchronize()
    d = out["depth"].float().cpu().numpy()
    d = np.where(np.isfinite(d), d, np.nan)
    return (d, out["normal"].float().cpu().numpy()) if normals else d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("game_dir", type=Path)
    ap.add_argument("play_id")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stride", type=int, default=2)
    a = ap.parse_args()

    gd = a.game_dir
    cal = json.loads((gd / "calibration.json").read_text())
    k, r, t = camera(cal)
    video = gd / "media" / "wide.mp4"
    info = probe_video(video)
    size = (info["width"], info["height"])
    fov_x = math.degrees(2 * math.atan(size[0] / 2 / k[0, 0]))
    tpl = load_profile(cal["sport"]).template(cal.get("variant"))
    court = floor_region(k, r, t, size, tpl.polygon, 1.0)
    d_floor = floor_depth(k, r, t, size)

    t_load = time.time()
    model = load_moge()
    t_load = time.time() - t_load
    torch.cuda.reset_peak_memory_stats()

    plate = cv2.imread(str(gd / "plate" / "plate.jpg"))
    t0 = time.time()
    d_plate, n_plate = infer(model, plate, fov_x, normals=True)
    t_plate = time.time() - t0
    plate_al = align_scale(d_plate, d_floor, court, k, r, t)

    h = play(gd, a.play_id)
    n = frame_count(h, info["fps"])
    masks = Masks(gd, a.play_id)
    pids = masks.players
    frames, per_frame, times = [], [], []
    pts, cols, who, when = [], [], [], []
    kernel = np.ones((3, 3), np.uint8)
    for f, (_, frame) in enumerate(read_window(video, h["t_start"], n)):
        if f % a.stride:
            continue
        t0 = time.time()
        d = infer(model, frame, fov_x)
        times.append(time.time() - t0)
        people = {p: masks.get(p, f) for p in pids}
        people = {p: m for p, m in people.items() if m is not None}
        busy = np.zeros(d.shape, np.uint8)
        for (x0, y0), m in people.values():
            sub = busy[y0 : y0 + m.shape[0], x0 : x0 + m.shape[1]]
            sub |= m[: sub.shape[0], : sub.shape[1]].astype(np.uint8)
        busy = cv2.dilate(busy, np.ones((31, 31), np.uint8)).astype(bool)
        al = align_scale(d, d_floor, court & ~busy, k, r, t)
        fi = len(frames)
        frames.append(f)
        per_frame.append(al)
        for p, ((x0, y0), m) in people.items():
            m = cv2.erode(m.astype(np.uint8), kernel, iterations=2).astype(bool)
            ys, xs = np.nonzero(m)
            u, v = xs + x0, ys + y0
            ok = (u < size[0]) & (v < size[1])
            u, v = u[ok], v[ok]
            dd = d[v, u] * al["scale"]
            ok = np.isfinite(dd)
            if ok.sum() < 20:
                continue
            ok &= np.abs(dd - np.median(dd[ok])) < PLAYER_DEPTH_BAND_M
            u, v, dd = u[ok], v[ok], dd[ok]
            pts.append(to_world(u, v, dd, k, r, t).astype(np.float32))
            cols.append(frame[v, u])
            who.append(np.full(len(u), pids.index(p), np.int16))
            when.append(np.full(len(u), fi, np.int16))

    meta = {
        "game_dir": str(gd),
        "play_id": a.play_id,
        "model": MOGE,
        "stride": a.stride,
        "fov_x_deg": fov_x,
        "size": size,
        "t_start": h["t_start"],
        "fps": info["fps"],
        "pids": pids,
        "plate": plate_al,
        "frames": per_frame,
        "timing": {
            "load_s": round(t_load, 2),
            "plate_s": round(t_plate, 3),
            "frame_s_median": round(float(np.median(times)), 3),
            "frame_s_max": round(float(np.max(times)), 3),
            "frames": len(times),
            "gpu_peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
        },
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        a.out,
        plate_depth=d_plate.astype(np.float16),
        plate_normal_z=(n_plate @ r[:, 2]).astype(np.float16),  # world z of the normal (floor: +-1)
        frames=np.asarray(frames, np.int32),
        pts=np.concatenate(pts),
        rgb=np.concatenate(cols),
        who=np.concatenate(who),
        when=np.concatenate(when),
        meta=json.dumps(meta),
    )
    scales = [x["scale"] for x in per_frame]
    print(json.dumps({**meta["timing"], "plate": plate_al, "scale_mean": float(np.mean(scales)),
                      "scale_cv": float(np.std(scales) / np.mean(scales))}))  # fmt: skip  # ttsr-ignore: py/no-print (CLI)


if __name__ == "__main__":
    main()
