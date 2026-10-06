"""TV-17 companion: compare the web Free view's canvas shots with the CPU reference
renderer (render/replay_render/virtual/scene.py) for the same package, frame and preset.

    REPLAY_SCENE_SHOTS=<dir> pnpm exec playwright test --project=tv -g "reference shots"
    python apps/tv/e2e/scene_ref_compare.py services/api/fixtures/scene_synth <dir> [--out <dir>]

Shots are named web_f{frame:03d}_{preset}.png at the reference's size (1920x1080). Per shot:
PSNR / SSIM (Gaussian SSIM, scene.ssim_map) over the whole frame, the "scene" region
(plate texels the view sees, alpha >= 0.5, plus the reference's players) and the players
(reference billboard alpha > 0.5). With --out, writes side-by-side web | reference crops.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import cv2
import numpy as np
from replay_render.virtual.scene import Package, draw_rgba, orbit_view, psnr, render, ssim_map


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("package", type=Path)
    ap.add_argument("shots", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    pkg = Package(a.package)
    lay = pkg.layout
    presets = {p["id"]: p for p in lay["presets"]}
    shots = sorted(a.shots.glob("web_f*_*.png"))
    want = {int(re.match(r"web_f(\d+)_", s.name).group(1)) for s in shots}
    atlas = {f: im.copy() for f, im in enumerate(pkg.atlas_frames()) if f in want}
    rows = []
    for shot in shots:
        f, pid = re.match(r"web_f(\d+)_(.+)\.png", shot.name).groups()
        f = int(f)
        web = cv2.imread(str(shot), cv2.IMREAD_COLOR)
        size = (web.shape[1], web.shape[0])
        view = orbit_view(lay["envelope"], presets[pid], size)
        ref, pa = render(pkg, view, f, atlas[f], size)
        acc = np.zeros(pa.shape, np.float32)
        for entry, tex in pkg.plates:
            draw_rgba(np.zeros_like(ref), tex, view, entry["corners_m"], acc)
        players = pa > 0.5
        scene = (acc >= 0.5) | players
        sm = ssim_map(*(cv2.cvtColor(x, cv2.COLOR_BGR2GRAY).astype(np.float64) for x in (web, ref)))
        row = {"frame": f, "preset": pid}
        for name, m in (("all", np.ones_like(players)), ("scene", scene), ("players", players)):
            row[f"psnr_{name}"] = psnr(web, ref, m)
            row[f"ssim_{name}"] = round(float(sm[m].mean()), 4) if m.any() else None
        row["scene_fraction"] = round(float(scene.mean()), 3)
        rows.append(row)
        if a.out:
            a.out.mkdir(parents=True, exist_ok=True)
            ys, xs = np.nonzero(scene)
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            pair = np.hstack([web[y0:y1, x0:x1], ref[y0:y1, x0:x1]])
            scale = min(1.0, 1600 / pair.shape[1])
            pair = cv2.resize(pair, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            for txt, x in (("web (WebGL)", 10), ("reference (CPU)", pair.shape[1] // 2 + 10)):
                cv2.putText(pair, f"{txt}  f{f} {pid}  SYNTHETIC", (x, 24), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (230, 230, 230), 1, cv2.LINE_AA)  # fmt: skip
            cv2.imwrite(str(a.out / f"pair_f{f:03d}_{pid}.png"), pair)
    keys = [k for k in rows[0] if k.startswith(("psnr", "ssim"))]
    mean = {k: round(float(np.mean([r[k] for r in rows if r[k] is not None])), 3) for k in keys}
    print(json.dumps({"shots": rows, "mean": mean}, indent=1))


if __name__ == "__main__":
    main()
