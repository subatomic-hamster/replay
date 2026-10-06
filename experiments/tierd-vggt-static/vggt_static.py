"""Tier D experiment B: multi-frame static court reconstruction with VGGT-1B.

Question: can a feed-forward multi-view model fuse many frames of the (tripod) clip into
a court reconstruction that fills Tier B's void floor / removes its ghosts?

For N frames sampled evenly over the clip, VGGT predicts per-frame cameras and depth.
Measured: (a) how far VGGT thinks the camera moved (truth: a tripod, 0), (b) its focal
vs the calibration, (c) floor flatness after scaling each depth map onto the calibrated
floor (same metric as experiment A), (d) top-down floor coverage of court +- 3 m from
frame 0 alone vs all N frames fused, against the geometric ceiling: the share of those
cells inside the camera frustum at all. Weights facebook/VGGT-1B are CC-BY-NC-4.0:
experiment only, never shipped.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tierd-pointmaps"))
from courtcam.profiles import load_profile
from geom import align_scale, camera, floor_depth, floor_region, project

MODEL = "facebook/VGGT-1B"
W_IN = 518
CELL_M = 0.25


def read_frames(video: Path, n: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    out = []
    for i in np.linspace(0, total - 1, n).round().astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            out.append(fr)
    cap.release()
    return out


def coverage(xyz: np.ndarray, bounds, cell=CELL_M) -> np.ndarray:
    """(ny, nx) bool: top-down cells with at least one floor point (|z| < 0.3 m)."""
    x0, y0, x1, y1 = bounds
    nx, ny = int(np.ceil((x1 - x0) / cell)), int(np.ceil((y1 - y0) / cell))
    g = np.zeros((ny, nx), bool)
    p = xyz[np.abs(xyz[:, 2]) < 0.3]
    i = ((p[:, 0] - x0) / cell).astype(int)
    j = ((p[:, 1] - y0) / cell).astype(int)
    ok = (i >= 0) & (i < nx) & (j >= 0) & (j < ny)
    g[j[ok], i[ok]] = True
    return g


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("game_dir", type=Path)
    ap.add_argument("--frames", default="8,16,32")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    torch.backends.cudnn.enabled = False  # D-39
    from vggt.models.vggt import VGGT
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri

    gd = a.game_dir
    cal = json.loads((gd / "calibration.json").read_text())
    k, r, t = camera(cal)
    w, h = cal["image_size"]
    h_in = int(round(h * W_IN / w / 14) * 14)
    sx, sy = W_IN / w, h_in / h
    k_in = np.diag([sx, sy, 1.0]) @ k
    d_floor = floor_depth(k_in, r, t, (W_IN, h_in))
    tpl = load_profile(cal["sport"]).template(cal.get("variant"))
    court = floor_region(k_in, r, t, (W_IN, h_in), tpl.polygon, 1.0)
    poly = tpl.polygon
    bounds = (
        poly[:, 0].min() - 3,
        poly[:, 1].min() - 3,
        poly[:, 0].max() + 3,
        poly[:, 1].max() + 3,
    )
    # geometric ceiling: cell centres on the floor that the real camera sees at all
    gx, gy = np.meshgrid(np.arange(bounds[0], bounds[2], CELL_M) + CELL_M / 2,
                         np.arange(bounds[1], bounds[3], CELL_M) + CELL_M / 2)  # fmt: skip
    cells = np.c_[gx.ravel(), gy.ravel(), np.zeros(gx.size)]
    infront = (cells @ r.T + t)[:, 2] > 0.1
    px = project(cells, k, r, t)
    seen = infront & (px[:, 0] >= 0) & (px[:, 0] < w) & (px[:, 1] >= 0) & (px[:, 1] < h)

    t0 = time.time()
    model = VGGT.from_pretrained(MODEL).to("cuda").eval()
    load_s = time.time() - t0
    results = {"model": MODEL, "licence": "CC-BY-NC-4.0 weights (experiment only)", "load_s": round(load_s, 1),
               "input": [W_IN, h_in], "frustum_ceiling": round(float(seen.mean()), 3), "runs": []}  # fmt: skip
    for n in (int(x) for x in a.frames.split(",")):
        frames = read_frames(gd / "media" / "wide.mp4", n)
        imgs = np.stack([cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2RGB), (W_IN, h_in), interpolation=cv2.INTER_AREA)
                         for f in frames])  # fmt: skip
        x = torch.from_numpy(imgs).permute(0, 3, 1, 2).float().div(255).to("cuda")
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        try:
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
                pred = model(x)
            torch.cuda.synchronize()
        except torch.OutOfMemoryError as e:
            results["runs"].append({"frames": n, "error": f"OOM: {str(e).splitlines()[0]}"})
            break
        dt = time.time() - t0
        extri, intri = pose_encoding_to_extri_intri(pred["pose_enc"], x.shape[-2:])
        extri, intri = extri[0].float().cpu().numpy(), intri[0].float().cpu().numpy()
        depth = pred["depth"][0, ..., 0].float().cpu().numpy()
        aligns = [align_scale(depth[i], d_floor, court, k_in, r, t) for i in range(n)]
        s0 = aligns[0]["scale"]
        # camera motion relative to frame 0, metres (VGGT world = camera 0)
        centres = np.array([-e[:, :3].T @ e[:, 3] for e in extri]) * s0
        rot = [np.degrees(np.arccos(np.clip((np.trace(e[:, :3]) - 1) / 2, -1, 1))) for e in extri]
        # fuse: each frame's depth -> camera 0 via VGGT's pose -> court via the calibration
        uu, vv = np.meshgrid(np.arange(W_IN) + 0.5, np.arange(h_in) + 0.5)
        fused, fused_k, first = [], [], None
        for i in range(n):
            ki, e = intri[i], extri[i]
            dd = depth[i] * s0
            xc = np.stack(
                [(uu - ki[0, 2]) / ki[0, 0] * dd, (vv - ki[1, 2]) / ki[1, 1] * dd, dd], -1
            ).reshape(-1, 3)
            x0 = (xc - e[:, 3] * s0) @ e[:, :3]  # camera i -> camera 0 frame
            xw = (x0 - t) @ r  # camera 0 = the calibrated camera -> court metres
            fused.append(xw)
            if i == 0:
                first = xw
            # best case: VGGT depth only (own scale per frame), calibrated K, R, t for every frame
            di = depth[i] * aligns[i]["scale"]
            xk = np.stack(
                [(uu - k_in[0, 2]) / k_in[0, 0] * di, (vv - k_in[1, 2]) / k_in[1, 1] * di, di], -1
            ).reshape(-1, 3)
            fused_k.append((xk - t) @ r)
        cov0 = coverage(first, bounds).ravel()
        covn = coverage(np.vstack(fused), bounds).ravel()
        covk = coverage(np.vstack(fused_k), bounds).ravel()
        covk0 = coverage(fused_k[0], bounds).ravel()
        q = lambda v, p=50: round(float(np.percentile(v, p)), 4)
        results["runs"].append({
            "frames": n,
            "forward_s": round(dt, 2),
            "s_per_frame": round(dt / n, 3),
            "gpu_peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
            "camera_motion_m": {"median": q(np.linalg.norm(centres, axis=1)), "max": q(np.linalg.norm(centres, axis=1), 100)},
            "camera_rotation_deg": {"median": q(rot), "max": q(rot, 100)},
            "focal_err_pct": round(100 * abs(float(np.median(intri[:, 0, 0])) / sx / k[0, 0] - 1), 2),
            "depth_scale_s0": round(s0, 3),
            "depth_scale_cv": round(float(np.std([x["scale"] for x in aligns]) / np.mean([x["scale"] for x in aligns])), 4),
            "floor_rel_depth_err_med": q([x["rel_depth_err_med"] for x in aligns]),
            "floor_abs_z_med_m": q([x["floor_abs_z_med_m"] for x in aligns]),
            "floor_abs_z_p90_m": q([x["floor_abs_z_p90_m"] for x in aligns]),
            "coverage_frame0": round(float(cov0.mean()), 3),
            "coverage_fused": round(float(covn.mean()), 3),
            "coverage_fused_outside_frustum": round(float((covn & ~seen).mean()), 4),
            "coverage_calibK_frame0": round(float(covk0.mean()), 3),
            "coverage_calibK_fused": round(float(covk.mean()), 3),
            "coverage_calibK_fused_outside_frustum": round(float((covk & ~seen).mean()), 4),
        })  # fmt: skip
        if n == max(int(v) for v in a.frames.split(",")):
            top = np.zeros((*covn.reshape(gx.shape).shape, 3), np.uint8)
            top[seen.reshape(gx.shape)] = (60, 60, 60)
            top[covk.reshape(gx.shape)] = (80, 200, 255)  # grey = in frustum, not reconstructed
            top = cv2.resize(top[::-1], None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(a.out.with_name(a.out.name + "_coverage.png")), top)
        del pred
    a.out.with_suffix(".json").write_text(json.dumps(results, indent=1))
    print(json.dumps(results, indent=1))  # ttsr-ignore: py/no-print (CLI)


if __name__ == "__main__":
    main()
