"""Tier D experiment A on SYNTHETIC input, scored against the generator's ground truth.

Re-scripts the exact synthetic scene (`courtcam.synth.build_scene`, same seed/size as
the clip), then measures:

1. calibration vs the true camera (context for everything else);
2. player placement: Tier B (tracked foot point -> billboard, height from the mask top
   on that billboard plane) vs Tier D (median of the lifted MoGe player points; height =
   99th percentile z), both against the true player position / height, and the
   along-ray depth spread of the Tier D player cloud ("smear");
3. held-out views: the generator renders the same frame from cameras the pipeline never
   saw (real camera = sanity row; orbit +-30 deg about the play; high broadcast), and
   Tier B / Tier D render the same views. Scores: player silhouette IoU, floor coverage
   (share of court + 1 m the render fills), floor PSNR over covered pixels, PSNR over
   the true player region.

Writes `<out>.json` and `<out>_heldout.jpg` (GT | Tier B | Tier D per camera).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

import cv2
import numpy as np
from geom import floor_region
from replay_render.virtual import tierb as B
from replay_render.virtual.replays import read_window
from scene import TierB, TierD, caption

from courtcam import synth as S

SIZE = (1280, 720)


def gt_player_mask(scene: S.Scene, f: int) -> np.ndarray:
    """On-court players' pixels at frame f (generator painter's order, labels only)."""
    cam = scene.cam
    w, h = cam.size
    lab = np.zeros((h, w), np.uint8)
    scratch = np.zeros((h, w, 3), np.uint8)
    rigs = []
    for i, p in enumerate(scene.people):
        a = scene.aim[f, i]
        j = S.rig(scene.pos[f, i], scene.heading[f, i], p.height, scene.phase[f, i],
                  scene.amp[f, i], int(scene.pose[f, i]), float(scene.pose_w[f, i]),
                  None if np.isnan(a).any() else a)  # fmt: skip
        rigs.append((-float(cam.depth(j["pelvis"][None])[0]), i, j))
    for _, i, j in sorted(rigs, key=lambda q: q[0]):
        S._draw_person(scratch, lab, i + 1, cam, scene.people[i], j, scene.heading[f, i])
    on = [i + 1 for i, p in enumerate(scene.people) if p.oncourt]
    return np.isin(lab, on)


def billboard_height(real: B.View, foot: np.ndarray, top_px: np.ndarray) -> float:
    """z where the ray through `top_px` meets Tier B's billboard plane at `foot`."""
    c = real.centre
    n = foot - c
    n[2] = 0
    n /= np.linalg.norm(n)
    ray = real.r.T @ np.linalg.inv(real.k) @ np.r_[top_px, 1.0]
    s = float(n @ (foot - c)) / float(n @ ray)
    return float((c + s * ray)[2])


def psnr(a: np.ndarray, b: np.ndarray, sel: np.ndarray) -> float | None:
    if sel.sum() < 50:
        return None
    mse = float(np.mean((a[sel].astype(np.float64) - b[sel].astype(np.float64)) ** 2))
    return round(10 * np.log10(255.0**2 / max(mse, 1e-9)), 2)


def iou(a: np.ndarray, b: np.ndarray) -> float:
    return round(float((a & b).sum() / max(1, (a | b).sum())), 3)


def q(a, p=50) -> float | None:
    return round(float(np.percentile(a, p)), 3) if len(a) else None


def look(eye, target, f) -> S.Camera:
    r = S._look_at(np.asarray(eye, float), np.asarray(target, float))
    k = np.array([[f, 0, SIZE[0] / 2], [0, f, SIZE[1] / 2], [0, 0, 1.0]])
    return S.Camera(k, r, -r @ np.asarray(eye, float), SIZE)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("npz", type=Path)
    ap.add_argument("--sport", default="basketball")
    ap.add_argument("--variant", default="half")
    ap.add_argument("--duration", type=float, default=40.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--src-size", default="1920x1080")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    src_size = tuple(int(v) for v in a.src_size.split("x"))
    scene = S.build_scene(
        a.sport, a.variant, duration_s=a.duration, fps=30, size=src_size, seed=a.seed
    )
    d = TierD(a.npz)
    dh = TierD(a.npz, hybrid=True)
    b = TierB(Path(d.meta["game_dir"]), d.meta["play_id"])
    start = round(b.h["t_start"] * b.fps)
    out: dict = {
        "synthetic": True,
        "npz_meta": {k: d.meta[k] for k in ("model", "stride", "fov_x_deg", "plate", "timing")},
    }

    # 1. calibration vs truth
    cam = scene.cam
    out["calibration_vs_truth"] = {
        "focal_err_pct": round(100 * abs(b.real.k[0, 0] / cam.K[0, 0] - 1), 3),
        "position_err_m": round(float(np.linalg.norm(b.real.centre - (-cam.R.T @ cam.t))), 3),
    }
    sc = np.array([x["scale"] for x in d.meta["frames"]])
    out["moge_scale"] = {"plate": round(d.meta["plate"]["scale"], 3), "frames_mean": round(float(sc.mean()), 3),
                         "frames_cv": round(float(sc.std() / sc.mean()), 4)}  # fmt: skip
    out["moge_floor_after_scale"] = {
        k: q([x[k] for x in d.meta["frames"]])
        for k in ("rel_depth_err_med", "floor_abs_z_med_m", "floor_abs_z_p90_m")
    }

    # 2. player placement
    on = [i for i, p in enumerate(scene.people) if p.oncourt]
    errs = {"tierb_xy": [], "tierd_xy": [], "tierb_h": [], "tierd_h": [], "tierd_smear": []}
    for fi, f in enumerate(d.frames):
        gt = scene.pos[start + f]
        for p, pid in enumerate(b.ids):
            sel = (
                (d.when == fi) & (d.who == d.meta["pids"].index(pid))
                if pid in d.meta["pids"]
                else None
            )
            if sel is None or sel.sum() < 200 or not np.isfinite(b.court[p, f, 0]):
                continue
            tb = b.court[p, f]
            dist = np.linalg.norm(gt[on] - tb, axis=1)
            if dist.min() > 1.5:
                continue
            i = on[int(dist.argmin())]
            pts = d.pts[sel].astype(np.float64)
            errs["tierb_xy"].append(dist.min())
            errs["tierd_xy"].append(np.linalg.norm(np.median(pts[:, :2], axis=0) - gt[i]))
            errs["tierd_h"].append(np.percentile(pts[:, 2], 99) - scene.people[i].height)
            dc = d.cam_depth[sel]
            errs["tierd_smear"].append(np.percentile(dc, 90) - np.percentile(dc, 10))
            (x0, y0), m = b.masks.get(pid, f)
            ys, xs = np.nonzero(m)
            top = np.array([np.median(xs[ys == ys.min()]) + x0 + 0.5, ys.min() + y0 + 0.5])
            errs["tierb_h"].append(
                billboard_height(b.real, np.r_[tb, 0.0], top) - scene.people[i].height
            )
    out["players"] = {
        "samples": len(errs["tierb_xy"]),
        "tierb_xy_err_m": {"median": q(errs["tierb_xy"]), "p90": q(errs["tierb_xy"], 90)},
        "tierd_xy_err_m": {"median": q(errs["tierd_xy"]), "p90": q(errs["tierd_xy"], 90)},
        "tierb_height_err_m": {
            "median_abs": q(np.abs(errs["tierb_h"])),
            "median_signed": q(errs["tierb_h"]),
        },
        "tierd_height_err_m": {
            "median_abs": q(np.abs(errs["tierd_h"])),
            "median_signed": q(errs["tierd_h"]),
        },
        "tierd_depth_spread_p10_p90_m": {
            "median": q(errs["tierd_smear"]),
            "p90": q(errs["tierd_smear"], 90),
            "note": "a real body is ~0.3 m deep",
        },  # fmt: skip
    }

    # 3. held-out views
    centre = np.r_[np.nanmean(scene.pos[start : start + b.n][:, on], axis=(0, 1)), 1.0]
    eye0 = -cam.R.T @ cam.t
    f_real = cam.K[0, 0] * SIZE[0] / src_size[0]
    v = eye0 - centre

    def orbit(deg):
        c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
        return look(centre + [c * v[0] - s * v[1], s * v[0] + c * v[1], v[2]], centre, f_real)

    hv = v[:2] / np.linalg.norm(v[:2])
    cams = {
        "real (sanity)": S.Camera(
            cam.K * [[SIZE[0] / src_size[0]], [SIZE[1] / src_size[1]], [1]], cam.R, cam.t, SIZE
        ),
        "orbit +30": orbit(30),
        "orbit -30": orbit(-30),
        "orbit +60": orbit(60),
        "orbit -60": orbit(-60),
        "high 15 m back, 9 m up": look(
            np.r_[centre[:2] + 15 * hv, 9.0], centre, SIZE[0] * np.hypot(15, 9) / 26
        ),
    }
    picks = [d.frames[int(x * (len(d.frames) - 1))] for x in (0.25, 0.5, 0.75)]
    frames = {
        f: fr for f, (_, fr) in enumerate(read_window(b.video, b.h["t_start"], b.n)) if f in picks
    }
    bg = B.background(SIZE)
    held, sheet = {}, []
    for name, c2 in cams.items():
        s2 = dataclasses.replace(scene, cam=c2)
        plate2, net2 = S.render_plate(s2), S._net_layer(s2)
        view = B.View(c2.K, c2.R, c2.t)
        fl = floor_region(c2.K, c2.R, c2.t, SIZE, scene.template.polygon, 1.0)
        rows = {"tierb": [], "tierd": [], "tierd_hybrid": []}
        for f in picks:
            gt_img, _, _ = S.render_frame(s2, start + f, plate2, net2)
            gt_m = gt_player_mask(s2, start + f)
            near_player = cv2.dilate(gt_m.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
            floor = fl & ~near_player
            reg = cv2.dilate(gt_m.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
            renders = {
                "tierb": b.render(view, f, frames[f], SIZE),
                "tierd": d.render(view, f, SIZE),
                "tierd_hybrid": dh.render(view, f, SIZE, anchors=b.anchors(f)),
            }
            for k, (img, pm) in renders.items():
                void = np.all(img == bg, axis=-1)  # nothing drawn: the backdrop gradient shows
                cov = floor & ~void
                rows[k].append({
                    "player_iou": iou(pm, gt_m),
                    "floor_coverage": round(float(cov.sum() / max(1, floor.sum())), 3),
                    "floor_psnr_covered": psnr(img, gt_img, cov),
                    "player_region_psnr": psnr(img, gt_img, reg),
                })  # fmt: skip
            if f == picks[1]:
                tiles = [gt_img.copy()] + [renders[k][0].copy() for k in rows]
                labels = (
                    "GROUND TRUTH (generator)",
                    "TIER B 2.5D",
                    "TIER D (MoGe-2 raw)",
                    "TIER D HYBRID",
                )
                for t_, lab in zip(tiles, labels):
                    caption(t_, f"{lab} | held-out cam: {name}", "SYNTHETIC")
                sheet.append(
                    np.hstack(
                        [cv2.resize(t_, (640, 360), interpolation=cv2.INTER_AREA) for t_ in tiles]
                    )
                )
        held[name] = {
            k: {m: q([r_[m] for r_ in rows[k] if r_[m] is not None]) for m in rows[k][0]}
            for k in rows
        }
    out["heldout_frames"] = [int(start + f) for f in picks]
    out["heldout"] = held
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.with_suffix(".json").write_text(json.dumps(out, indent=1))
    cv2.imwrite(
        str(a.out.with_name(a.out.name + "_heldout.jpg")),
        np.vstack(sheet),
        [cv2.IMWRITE_JPEG_QUALITY, 85],
    )
    print(json.dumps(out, indent=1))  # ttsr-ignore: py/no-print (CLI)


if __name__ == "__main__":
    main()
