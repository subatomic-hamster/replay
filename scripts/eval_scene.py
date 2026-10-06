"""Novel-view accuracy of a 2.5D scene package against synthetic ground truth.

A `courtcam synth` clip's choreography depends only on its seed, so the same game can be
re-rendered from any camera (`build_scene(camera=CameraSpec(...))`). For orbit offsets
around the real camera this renders the package with the reference renderer
(`replay_render.virtual.scene.render`, billboards facing the real camera and facing the
viewer) and compares it with the truth from that camera: player silhouette IoU and
player-region PSNR (on-court people only), plus the package's own `view_metrics`
(seen-plate fraction, billboard turn, magnification). docs/scene-format.md quotes it.

    python scripts/eval_scene.py <game_dir> <play_id> --synth-dir <dir with clip.mp4>
        [--seed 7 --variant full --duration 30] [--json out.json] [--stills dir]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from courtcam.synth import CameraSpec, _net_layer, build_scene, render_frame, render_plate
from replay_render.virtual import scene

OFFSETS = [(0, 0), (10, 0), (-10, 0), (20, 0), (-20, 0), (30, 0), (-30, 0), (45, 0), (-45, 0),
           (0, 10), (0, 20), (0, -5), (20, 15), (-20, 15)]  # fmt: skip


def gt_silhouette(img: np.ndarray, plate: np.ndarray, rows: list[dict]) -> np.ndarray:
    """On-court people in a synthetic frame: changed vs the empty plate, inside their
    truth boxes, minus the contact shadows (exactly 0.62 x plate)."""
    diff = cv2.absdiff(img, plate).max(axis=2) > 30
    shadow = (np.abs(img.astype(np.float32) - plate * 0.62) < 4).all(axis=2)
    box = np.zeros(diff.shape, bool)
    for r in rows:
        if r.get("oncourt"):
            x, y, w, h = (round(v) for v in r["bb"])
            box[max(0, y) : y + h + 1, max(0, x) : x + w + 1] = True
    return diff & ~shadow & box


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("game_dir", type=Path)
    ap.add_argument("play_id")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--variant", default="full")
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--stills", type=Path, default=None)
    a = ap.parse_args()
    pkg = scene.Package(a.game_dir / scene.SCENE_REL.format(play_id=a.play_id))
    lay = pkg.layout
    assert lay["synthetic"] and not lay["frame"]["mirror_x"], "synthetic, unmirrored only"
    size = tuple(lay["camera"]["image_size"])
    fps = lay["fps"]
    env = lay["envelope"]
    real = next(p for p in lay["presets"] if p["id"] == "real")
    want = set(np.linspace(0, lay["n_frames"] - 1, a.frames).round().astype(int).tolist())
    atlases = {f: at.copy() for f, at in enumerate(pkg.atlas_frames()) if f in want}
    feet = np.array([[*it["foot"], 0.0] for fr in lay["frames"] for it in fr])
    rows_out = []
    for az, del_ in OFFSETS:
        p = {
            **real,
            "azimuth_deg": az,
            "elevation_deg": real["elevation_deg"] + del_,
            "roll_deg": 0.0,
        }
        view = scene.orbit_view(env, p, size)
        sc = build_scene(
            "basketball", a.variant, duration_s=a.duration, fps=round(fps), size=size,
            seed=a.seed,
            camera=CameraSpec(eye=tuple(view.centre), target=tuple(env["target_m"]), f_px=float(view.k[0, 0])),
        )  # fmt: skip
        assert np.allclose(sc.cam.R, view.r, atol=1e-6), "synth camera != orbit view"
        plate = render_plate(sc)
        net = _net_layer(sc)
        res = {"azimuth_deg": az, "elevation_offset_deg": del_}
        res.update(scene.view_metrics(pkg.plates, pkg.real, feet, view))
        for facing in ("real", "viewer"):
            ious, psnrs = [], []
            for f in sorted(want):
                gi = round(lay["t_start"] * fps) + f
                gt, rows, _ = render_frame(sc, gi, plate, net)
                img, pa = scene.render(pkg, view, f, atlases[f], size, facing=facing)
                g, r = gt_silhouette(gt, plate, rows), pa > 0.5
                union = g | r
                if union.any():
                    ious.append((g & r).sum() / union.sum())
                    psnrs.append(scene.psnr(img, gt, union))
                if a.stills and f == sorted(want)[len(want) // 2]:
                    a.stills.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(a.stills / f"az{az:+03d}_el{del_:+03d}_{facing}.jpg"),
                                np.hstack([img, gt]), [cv2.IMWRITE_JPEG_QUALITY, 85])  # fmt: skip
            res[f"iou_{facing}"] = round(float(np.mean(ious)), 3) if ious else None
            res[f"psnr_{facing}"] = round(float(np.mean(psnrs)), 2) if psnrs else None
        print(json.dumps(res), flush=True)
        rows_out.append(res)
    if a.json:
        a.json.write_text(
            json.dumps({"play_id": a.play_id, "synthetic": True, "rows": rows_out}, indent=1)
        )


if __name__ == "__main__":
    main()
