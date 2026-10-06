"""Full camera calibration accuracy (M8): synthetic truth + real-clip reprojection.

    python scripts/eval_calibration.py [--seeds 20] [--real samples/real]

Synthetic: every v2 scene's true camera (courtcam.synth, labelled synthetic) is clicked
with Gaussian pixel noise, fitted through the same path the pipeline uses
(`pipeline.calibrate_lens` on the floor clicks, then `calibrate.camera_calibration` with
or without the height landmarks) and compared with the truth: focal %, rotation (deg),
camera position (m). Real: every `samples/real/*.landmarks.json` (floor clicks only, no
ground truth) reports reprojection error plus the recovered focal and camera height.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from courtcam.profiles import load_profile

from courtcam import calibrate as C
from courtcam import pipeline as P
from courtcam import synth

SCENES = [
    ("basketball", "half"),
    ("basketball", "full"),
    ("pickleball", "doubles"),
    ("badminton", "doubles"),
    ("volleyball", "indoor"),
]


def _rot_err_deg(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.degrees(np.linalg.norm(cv2.Rodrigues(a @ b.T)[0])))


def synthetic(seeds: int, noises=(0.0, 1.0, 2.0), lenses=(0.0, -0.2)) -> list[dict]:
    rows = []
    for sport, variant in SCENES:
        profile = load_profile(sport)
        for k1 in lenses:
            scene = synth.build_scene(
                sport, variant, duration_s=2.0, camera=synth.CameraSpec(k1=k1)
            )
            doc = synth.calibration_doc(scene)
            size = tuple(doc["image_size"])
            truth_c = -np.asarray(doc["R"]).T @ np.asarray(doc["t"])
            f_true = doc["K"][0][0]
            for noise in noises:
                for heights in (False, True):
                    errs = []
                    for seed in range(seeds if noise else 1):
                        rng = np.random.default_rng(seed)
                        clicks = {
                            n: tuple(np.asarray(v) + rng.normal(0, noise, 2))
                            for n, v in doc["landmarks_px"].items()
                        }
                        floor = {
                            n: v for n, v in clicks.items() if doc["landmarks_world"][n][2] == 0
                        }
                        try:
                            calib = P.calibrate_lens(floor, profile, variant, size)
                        except C.CalibrationError:
                            errs.append(None)
                            continue
                        cal = C.camera_calibration(calib, profile, clicks if heights else floor)
                        r = np.asarray(cal["R"])
                        errs.append(
                            (
                                abs(cal["focal_px"] / f_true - 1) * 100,
                                _rot_err_deg(r, np.asarray(doc["R"])),
                                float(
                                    np.linalg.norm(np.asarray(cal["camera_position_m"]) - truth_c)
                                ),
                                cal["reproj_err_px"],
                                len(cal["height_landmarks"]),
                            )
                        )
                    ok = np.asarray([e for e in errs if e is not None])
                    rows.append(
                        {
                            "scene": f"{sport}/{variant}",
                            "k1": k1,
                            "noise_px": noise,
                            "heights": int(ok[0, 4]) if heights and len(ok) else 0,
                            "n": len(ok),
                            "failed": errs.count(None),
                            "f_true": round(f_true, 1),
                            "focal_err_pct": float(np.median(ok[:, 0])),
                            "rot_err_deg": float(np.median(ok[:, 1])),
                            "pos_err_m": float(np.median(ok[:, 2])),
                            "pos_err_p90_m": float(np.percentile(ok[:, 2], 90)),
                            "reproj_px": float(np.median(ok[:, 3])),
                        }
                    )
    return rows


def real(root: Path, heights: dict | None = None) -> list[dict]:
    rows = []
    for lm_path in sorted(root.glob("*.landmarks.json")):
        name = lm_path.name.removesuffix(".landmarks.json")
        sport = name.split("_")[0]
        doc = json.loads(lm_path.read_text())
        video = root / f"{name}.mp4"
        cap = cv2.VideoCapture(str(video))
        size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        cap.release()
        profile = load_profile(sport)
        clicks = {k: tuple(v) for k, v in doc["landmarks_px"].items()}
        try:
            calib = P.calibrate_lens(clicks, profile, doc.get("variant"), size)
        except C.CalibrationError as exc:
            rows.append({"clip": name, "error": str(exc)})
            continue
        cal = C.camera_calibration(calib, profile)
        extra: dict = {}
        tops = {k: tuple(v) for k, v in (heights or {}).get(name, {}).items()}
        if tops:
            # held out: where the floor-only camera puts the clicked hoop/net tops ...
            p = C.camera_matrix(cal)
            world = C.world_landmarks(profile.template(doc.get("variant")))
            held = {}
            for k, uv in tops.items():
                q = p @ np.r_[world[k], 1.0]
                held[k] = round(float(np.linalg.norm(q[:2] / q[2] - np.asarray(uv))), 1)
            # ... and the camera refit with them (PnP over floor + height landmarks)
            both = C.camera_calibration(calib, profile, {**clicks, **tops})
            extra = {
                "height_heldout_err_px": held,
                "with_heights_reproj_px": both["reproj_err_px"],
                "with_heights_residuals_px": {k: both["residuals_px"][k] for k in tops},
                "with_heights_focal_px": round(both["focal_px"], 1),
                "with_heights_camera_xyz_m": [round(v, 2) for v in both["camera_position_m"]],
            }
        rows.append(
            {
                **extra,
                "clip": name,
                "size": f"{size[0]}x{size[1]}",
                "k1": round(calib["k1"], 3),
                "landmarks": len(cal["landmarks_px"]),
                "homography_err_px": round(calib["reproj_error_px"], 2),
                "camera_reproj_px": cal["reproj_err_px"],
                "worst_px": max(cal["residuals_px"].values()),
                "focal_px": round(cal["focal_px"], 1),
                "hfov_deg": round(
                    float(np.degrees(2 * np.arctan(size[0] / 2 / cal["focal_px"]))), 1
                ),
                "camera_xyz_m": [round(v, 2) for v in cal["camera_position_m"]],
                "mirrored": cal["mirrored"],
            }
        )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--real", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--heights", type=Path, default=None, help="{clip: {rim_top: [x, y]}}")
    a = ap.parse_args()
    tops = json.loads(a.heights.read_text()) if a.heights else None
    out = {"synthetic": synthetic(a.seeds), "real": real(a.real, tops) if a.real else []}
    print(
        "| scene | k1 | noise px | height lm | focal err % | rot err deg | pos err m (p90) | reproj px |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for r in out["synthetic"]:
        print(
            f"| {r['scene']} | {r['k1']} | {r['noise_px']:g} | {r['heights']} | "
            f"{r['focal_err_pct']:.2f} | {r['rot_err_deg']:.3f} | "
            f"{r['pos_err_m']:.3f} ({r['pos_err_p90_m']:.3f}) | {r['reproj_px']:.2f} |"
            + (f" {r['failed']} failed" if r["failed"] else "")
        )
    for r in out["real"]:
        print(json.dumps(r))
    if a.json:
        a.json.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
