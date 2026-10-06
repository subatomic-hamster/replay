"""2.5D scene package: one highlight as data a GPU client renders live from any camera
inside an envelope around the real one (no per-angle server renders). The format is
specified in docs/scene-format.md (`replay.scene_package.v1`).

`replays/{play_id}/scene/`:

* `floor.png`, `backdrop.png` — the Tier B court plate (`courtcam.plate`) as RGBA, alpha 0
  where the real camera never saw that texel, each with its world quad;
* `atlas.mp4` — per frame, every visible player's SAM 2.1 cutout rectified onto its
  billboard plane (metric, axis-aligned) and packed into a fixed grid of cells: colour
  in the left half, mask as luma in the right half; H.264 yuv420p, 1 s GOP, faststart;
* `layout.json` — frame -> cell map, foot points, billboard rects, static geometry, the
  modelled ball, the real camera, the camera envelope and presets.

Everything is in the *scene frame*: court metres, z up, with x negated when the
calibration is mirrored (D-53), so the real camera is a proper rotation and no client
has to flip anything.

`render()` is the CPU reference renderer (numpy/OpenCV) the web and native viewers are
compared against; `main()` builds a package and renders preset stills plus the
real-camera check against the source frames.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from courtcam.calibrate import RIM_HEIGHT_M, camera_matrix, height_landmarks
from courtcam.profiles import load_profile

from courtcam import distortion
from courtcam import plate as plate_mod

from ..gamedata import load_tracks
from .replays import frame_count, play, probe_video, read_highlights, read_window
from .segment import Masks
from .tierb import (
    EZ,
    NEAR_M,
    View,
    _clip_poly,
    background,
    ball_track,
    draw_ball,
    draw_net,
    draw_shadow,
    look_at,
    plane_homography,
)

SCHEMA = "replay.scene_package.v1"
SCENE_REL = "replays/{play_id}/scene"
LABEL = "2.5D scene · flat player cutouts on a reconstructed court"
HALF_MAX = 1024  # each atlas half <= 1024 x 1024, so the video is <= 2048 x 1024
CELLS = ((256, 512), (192, 384), (160, 320), (128, 256), (96, 192), (64, 128))  # w, h
INSET = 2  # gutter texels inside each cell (bilinear taps and 4:2:0 chroma stay inside)
MAX_UPSCALE = 2.0  # cell texels per source pixel, at most
MASK_RAMP = (0.1, 0.9)  # alpha = clamp((mask - lo) / (hi - lo), 0, 1)
CRF = 18
# Envelope limits; measured on synthetic ground truth (docs/scene-format.md, Envelope).
AZ_DEV_MAX = 30.0  # deg between real and virtual horizontal lines of sight to a player
EL_DEV_MAX = 20.0  # deg between real and virtual elevations to a player's chest
SEEN_MIN = 0.85  # fraction of the real preset's seen-plate coverage a view must keep
MAG_MAX = 2.0  # cutout magnification relative to the real camera on the same screen
MIN_EYE_Z = 1.0
METRIC_SIZE = (192, 108)
TV_SIZE = (1920, 1080)


# --- frames and geometry ---------------------------------------------------------------


def _mirror(xyz, on: bool) -> np.ndarray:
    a = np.array(xyz, dtype=np.float64)
    if on:
        a[..., 0] *= -1.0
    return a


def scene_view(calibration: dict) -> tuple[View, bool]:
    """The real camera in the scene frame and whether the court frame was mirrored."""
    r = np.asarray(calibration["R"], np.float64)
    mirrored = bool(np.linalg.det(r) < 0)
    if mirrored:
        r = r @ np.diag([-1.0, 1.0, 1.0])
    return View(
        np.asarray(calibration["K"], np.float64), r, np.asarray(calibration["t"], np.float64)
    ), mirrored


def billboard_axis(cam: np.ndarray, foot: np.ndarray) -> np.ndarray:
    """Unit horizontal axis of a billboard at `foot` facing `cam`: the viewer's right."""
    d = np.asarray(foot, np.float64) - cam
    a = np.array([d[1], -d[0], 0.0])
    return a / np.linalg.norm(a)


def orbit_view(env: dict, preset: dict, size=TV_SIZE) -> View:
    """Camera state (docs/scene-format.md) -> View: eye on a sphere around the target,
    look-at with world z up, then `roll_deg` about the optical axis."""
    az = np.radians(env["azimuth0_deg"] + preset["azimuth_deg"])
    el = np.radians(preset["elevation_deg"])
    tgt = np.asarray(env["target_m"], np.float64)
    eye = tgt + preset["distance_m"] * np.array(
        [np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)]
    )
    f = size[1] / 2 / np.tan(np.radians(preset["fov_y_deg"]) / 2)
    v = look_at(eye, tgt, f, size)
    c, s = (
        np.cos(np.radians(preset.get("roll_deg", 0.0))),
        np.sin(np.radians(preset.get("roll_deg", 0.0))),
    )
    r = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]) @ v.r
    return View(v.k, r, -r @ eye)


# --- build: plates -----------------------------------------------------------------------


def _plates(
    gd: Path, calib: dict, calibration: dict, mirrored: bool
) -> list[tuple[dict, np.ndarray]]:
    """[(layout entry, BGRA texture)] for the backdrop and the floor, alpha = seen."""
    meta = json.loads((gd / "plate" / "plate.json").read_text(encoding="utf-8"))
    src = cv2.imread(str(gd / "plate" / "plate.jpg"))
    white = np.full(src.shape[:2], 255, np.uint8)
    k1 = float(calib.get("k1") or 0.0)
    fl, bd = meta["floor"], meta["backdrop"]
    floor = cv2.imread(str(gd / "plate" / fl["file"]))
    seen_f = plate_mod.topdown(
        white, np.asarray(calib["H_inv"]), k1, tuple(fl["bounds_m"]), fl["px_per_m"]
    )
    x0, _, _, y1 = fl["bounds_m"]
    th, tw = floor.shape[:2]
    ppm = fl["px_per_m"]
    fc = [
        [x0, y1, 0],
        [x0 + tw / ppm, y1, 0],
        [x0 + tw / ppm, y1 - th / ppm, 0],
        [x0, y1 - th / ppm, 0],
    ]
    wall = cv2.imread(str(gd / "plate" / bd["file"]))
    origin, along = np.asarray(bd["origin_m"], np.float64), np.asarray(bd["along"], np.float64)
    seen_b = plate_mod.backdrop(
        white,
        camera_matrix(calibration),
        k1,
        origin,
        along,
        bd["length_m"],
        bd["height_m"],
        bd["px_per_m"],
    )
    bw = wall.shape[1]
    top = origin + EZ * bd["height_m"]
    lw = along * bw / bd["px_per_m"]
    bc = [top, top + lw, origin + lw, origin]
    out = []
    for pid, tex, seen, corners in (("backdrop", wall, seen_b, bc), ("floor", floor, seen_f, fc)):
        entry = {
            "id": pid,
            "file": f"{pid}.png",
            "size_px": [tex.shape[1], tex.shape[0]],
            "corners_m": np.round(_mirror(corners, mirrored), 4).tolist(),
        }
        out.append((entry, np.dstack([tex, seen])))
    return out


# --- build: players --------------------------------------------------------------------


def _soft_alpha(m: np.ndarray) -> np.ndarray:
    """Tier B's cutout edge: erode 1 px on big crops, then a height-scaled blur."""
    a = m.astype(np.float32)
    ys = np.nonzero(m.any(axis=1))[0]
    ch = ys[-1] - ys[0] + 1 if len(ys) else m.shape[0]
    a = cv2.erode(a, np.ones((3, 3), np.uint8)) if min(m.shape) > 24 else a
    return cv2.GaussianBlur(a, (0, 0), max(0.7, ch / 120))


def _player_items(
    real: View, mirrored: bool, k1: float, src_size, court, ids, masks
) -> list[list[dict]]:
    """Per frame, per visible player: foot, billboard rect (metres) and source texel
    density. No video is read here."""
    n = court.shape[1]
    frames: list[list[dict]] = [[] for _ in range(n)]
    for p, pid in enumerate(ids):
        for f in range(n):
            if not np.isfinite(court[p, f, 0]):
                continue
            got = masks.get(pid, f)
            if got is None:
                continue
            (x0, y0), m = got
            ys, xs = np.nonzero(m)
            pad = 3
            box = np.array(
                [[xs.min() - pad, ys.min() - pad], [xs.max() + 1 + pad, ys.min() - pad],
                 [xs.max() + 1 + pad, ys.max() + 1 + pad], [xs.min() - pad, ys.max() + 1 + pad]],
                np.float64,
            ) + [x0, y0]  # fmt: skip
            foot = _mirror([court[p, f, 0], court[p, f, 1], 0.0], mirrored)
            axis = billboard_axis(real.centre, foot)
            g = plane_homography(real.p, foot, axis, EZ)
            und = distortion.undistort_points(box, k1, src_size)
            sz = cv2.perspectiveTransform(und.reshape(-1, 1, 2), np.linalg.inv(g)).reshape(-1, 2)
            depth = float(real.depth(foot + 0.9 * EZ)[0])
            if depth < NEAR_M or not np.isfinite(sz).all():
                continue
            frames[f].append(
                {
                    "pid": pid,
                    "foot": foot,
                    "axis": axis,
                    "g": g,
                    "rect": (sz[:, 0].min(), sz[:, 1].min(), sz[:, 0].max(), sz[:, 1].max()),
                    "ppm": real.k[0, 0] / depth,
                    "depth": depth,
                }
            )
    return frames


def _grid(frames: list[list[dict]]) -> tuple[tuple[int, int], tuple[int, int]]:
    """(cell w, h), (cols, rows): the smallest cell that holds the 90th-percentile player
    at source resolution, among those whose grid fits every simultaneous player."""
    n = max([len(fr) for fr in frames] + [1])
    hs = [(it["rect"][3] - it["rect"][1]) * it["ppm"] for fr in frames for it in fr]
    need = float(np.percentile(hs, 90)) if hs else 0.0
    fits = [c for c in CELLS if (HALF_MAX // c[0]) * (HALF_MAX // c[1]) >= n]
    if not fits:
        raise ValueError(f"{n} simultaneous players do not fit a {HALF_MAX}px atlas half")
    big = [c for c in fits if c[1] - 2 * INSET >= need]
    cell = big[-1] if big else fits[0]
    cols = min(n, HALF_MAX // cell[0])
    return cell, (cols, -(-n // cols))


def _assign_cells(frames: list[list[dict]], n_cells: int) -> None:
    """A player keeps its cell while visible (temporal coherence for the encoder); a new
    one takes the cell that has been free longest."""
    cell_of: dict[str, int] = {}
    free_since = dict.fromkeys(range(n_cells), -1)
    for f, fr in enumerate(frames):
        vis = {it["pid"] for it in fr}
        for pid in [p for p in cell_of if p not in vis]:
            free_since[cell_of.pop(pid)] = f
        used = set(cell_of.values())
        for it in sorted(fr, key=lambda it: it["pid"]):
            if it["pid"] not in cell_of:
                c = min(
                    (c for c in range(n_cells) if c not in used), key=lambda c: (free_since[c], c)
                )
                cell_of[it["pid"]] = c
                used.add(c)
            it["cell"] = cell_of[it["pid"]]


def _fill_outside(col: np.ndarray, a: np.ndarray) -> np.ndarray:
    """Colour outside the mask = a normalised blur of the colour inside, so bilinear taps
    and 4:2:0 chroma at the silhouette do not pull in the court."""
    w = a.astype(np.float32)
    num = cv2.GaussianBlur(col.astype(np.float32) * w[..., None], (0, 0), 4.0)
    den = cv2.GaussianBlur(w, (0, 0), 4.0)[..., None]
    mean = (col.reshape(-1, 3) * w.reshape(-1, 1)).sum(0) / max(float(w.sum()), 1e-6)
    ext = np.where(den > 1e-3, num / np.maximum(den, 1e-6), mean)
    return np.where(w[..., None] > 0.02, col, ext).astype(np.uint8)


def _rectify(frame, xy0, alpha, it: dict, k1: float, src_size, out_wh, origin_sz, k: float):
    """Sample colour and alpha for cell texels (i, j) at plane point
    (s, z) = (s_left + (i + .5) / k, z_top - (j + .5) / k)."""
    w, h = out_wh
    i, j = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    pts = np.stack([origin_sz[0] + i / k, origin_sz[1] - j / k, np.ones_like(i)], axis=-1)
    hom = pts @ it["g"].T
    px = hom[..., :2] / hom[..., 2:3]
    if k1:
        px = distortion.distort_points(px.reshape(-1, 2), k1, src_size).reshape(px.shape)
    mx, my = px[..., 0].astype(np.float32), px[..., 1].astype(np.float32)
    col = cv2.remap(frame, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    a = cv2.remap(alpha, mx - xy0[0], my - xy0[1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return col, np.clip(a, 0.0, 1.0)


def _encoder(path: Path, size: tuple[int, int], fps: float, gop: int) -> subprocess.Popen:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH")
    return subprocess.Popen(
        [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{size[0]}x{size[1]}", "-r", f"{fps:g}", "-i", "-",
         "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", str(CRF), "-profile:v", "high",
         "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-color_range", "tv", "-movflags", "+faststart", "-an", str(path)],
        stdin=subprocess.PIPE,
    )  # fmt: skip


# --- build: static geometry, ball ------------------------------------------------------


def _static(calibration: dict, mirrored: bool) -> tuple[dict, list]:
    """Hoops (rim ring + FIBA backboard 0.375 m behind it) and the net, Tier B's geometry."""
    hoops, net, rims = [], None, []
    try:
        tpl = load_profile(calibration["sport"]).template(calibration.get("variant"))
    except Exception:  # noqa: BLE001 - unknown sport: no hoops / net
        return {"hoops": [], "net": None}, []
    rims = [tuple(r) for r in (tpl.rims or ([tpl.rim] if tpl.rim is not None else []))]
    b0, b1 = float(tpl.polygon[:, 1].min()), float(tpl.polygon[:, 1].max())
    for rx, ry in rims:
        by = ry + (-1.0 if abs(ry - b0) < abs(ry - b1) else 1.0) * 0.375
        board = [
            [rx - 0.9, by, 3.95],
            [rx + 0.9, by, 3.95],
            [rx + 0.9, by, 2.9],
            [rx - 0.9, by, 2.9],
        ]
        hoops.append(
            {
                "rim_m": np.round(_mirror([rx, ry, RIM_HEIGHT_M], mirrored), 4).tolist(),
                "rim_radius_m": 0.225,
                "backboard_m": np.round(_mirror(board, mirrored), 4).tolist(),
            }
        )
    hl = height_landmarks(tpl)
    if "net_top_l" in hl and "net_top_r" in hl:
        h = float(hl["net_top_l"][2])
        net = {
            "top_l_m": np.round(_mirror(hl["net_top_l"], mirrored), 4).tolist(),
            "top_r_m": np.round(_mirror(hl["net_top_r"], mirrored), 4).tolist(),
            "depth_m": 1.0 if h > 2.0 else 0.76 if h > 1.2 else h,  # tierb.draw_net
        }
    return {"hoops": hoops, "net": net}, rims


# --- build: envelope ---------------------------------------------------------------------


def _seen_fraction(plates, view: View, size=METRIC_SIZE) -> float:
    acc = np.zeros((size[1], size[0]), np.float32)
    canvas = np.zeros((size[1], size[0], 3), np.uint8)
    for entry, tex in plates:
        draw_rgba(canvas, tex, view, entry["corners_m"], acc)
    return float((acc >= 0.5).mean())


def view_metrics(plates, real: View, feet: np.ndarray, view: View) -> dict[str, float]:
    """What a virtual camera costs: plate coverage (`seen`), the worst billboard turn
    away from the real line of sight (`az_dev`, `el_dev`, degrees) and the worst cutout
    magnification relative to the real camera on the same screen (`mag`), over the
    players that land inside the view."""
    w, h = view.k[0, 2] * 2, view.k[1, 2] * 2  # principal point at the centre (D-53)
    s = METRIC_SIZE[0] / w
    seen = _seen_fraction(plates, View(np.diag([s, s, 1.0]) @ view.k, view.r, view.t))
    chest = feet + 0.9 * EZ
    dv = view.depth(chest)
    px = view.project(chest)
    inside = (
        (dv > NEAR_M)
        & (px[:, 0] > -0.05 * w)
        & (px[:, 0] < 1.05 * w)
        & (px[:, 1] > -0.05 * h)
        & (px[:, 1] < 1.05 * h)
    )
    if not inside.any():
        return {"seen": seen, "az_dev": 0.0, "el_dev": 0.0, "mag": 0.0, "players": 0}
    q = chest[inside]
    a, b = (q - real.centre)[:, :2], (q - view.centre)[:, :2]
    az = np.degrees(np.abs(np.arctan2(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0], (a * b).sum(1))))
    elr = np.degrees(np.arctan2(real.centre[2] - q[:, 2], np.linalg.norm(a, axis=1)))
    elv = np.degrees(np.arctan2(view.centre[2] - q[:, 2], np.linalg.norm(b, axis=1)))
    # same screen for both: lines per metre at the player, virtual over real
    mag = (view.k[1, 1] / h / dv[inside]) / (real.k[1, 1] / (2 * real.k[1, 2]) / real.depth(q))
    return {
        "seen": round(seen, 3),
        "az_dev": round(float(az.max()), 1),
        "el_dev": round(float(np.abs(elv - elr).max()), 1),
        "mag": round(float(mag.max()), 2),
        "players": int(inside.sum()),
    }


def _ok(m: dict, seen_real: float) -> bool:
    return (
        m["seen"] >= SEEN_MIN * seen_real
        and m["az_dev"] <= AZ_DEV_MAX
        and m["el_dev"] <= EL_DEV_MAX
        and m["mag"] <= MAG_MAX
    )


def envelope(plates, real: View, image_size, feet: np.ndarray) -> tuple[dict, list[dict]]:
    """Orbit envelope around the real camera and the named presets inside it.

    Target: the point of the real optical axis nearest the players' mean chest point.
    Azimuth, elevation and distance limits grow outwards from the real camera's own
    values in 2.5 deg / 5 % steps while every criterion of `_ok` holds; the four
    az/el corners are then checked and the box shrunk until they pass too."""
    c = real.centre
    fwd = real.r[2]
    mid = feet.mean(axis=0) + 0.9 * EZ if len(feet) else c + 10 * fwd
    tgt = c + fwd * max(3.0, float((mid - c) @ fwd))
    v = c - tgt
    dist = float(np.linalg.norm(v))
    az0 = float(np.degrees(np.arctan2(v[1], v[0])))
    el0 = float(np.degrees(np.arcsin(v[2] / dist)))
    fov = float(np.degrees(2 * np.arctan(image_size[1] / 2 / real.k[1, 1])))
    env = {"target_m": np.round(tgt, 4).tolist(), "azimuth0_deg": round(az0, 3)}
    base = look_at(c, tgt, 1.0)
    rr = real.r @ base.r.T
    roll = float(np.degrees(np.arctan2(rr[1, 0], rr[0, 0])))
    sample = feet[:: max(1, len(feet) // 400)]

    def cam(az=0.0, el=el0, d=dist, r=0.0):
        p = {
            "azimuth_deg": az,
            "elevation_deg": el,
            "distance_m": d,
            "roll_deg": r,
            "fov_y_deg": fov,
        }
        return orbit_view(env, p, TV_SIZE)

    def metric(**kw):
        return view_metrics(plates, real, sample, cam(**kw))

    seen_real = metric(r=roll)["seen"]

    def grow(key, start, step, lo, hi, **fixed):
        x = start
        while lo <= x + step <= hi and _ok(metric(**{key: x + step}, **fixed), seen_real):
            x += step
        return x

    el_lo = float(np.degrees(np.arcsin(np.clip((MIN_EYE_Z - tgt[2]) / dist, -1, 1))))
    az_max = grow("az", 0.0, 2.5, -90, 90)
    az_min = grow("az", 0.0, -2.5, -90, 90)
    el_max = grow("el", el0, 2.5, el_lo, 75.0)
    el_min = grow("el", el0, -2.5, el_lo, 75.0)
    d_min = grow("d", dist, -0.05 * dist, 0.3 * dist, 1.6 * dist)
    d_max = grow("d", dist, 0.05 * dist, 0.3 * dist, 1.6 * dist)
    for _ in range(10):  # corners
        bad = [(a, e) for a in (az_min, az_max) for e in (el_min, el_max)
               if not _ok(metric(az=a, el=e), seen_real)]  # fmt: skip
        if not bad:
            break
        az_min, az_max = az_min * 0.85, az_max * 0.85
        el_min, el_max = el0 + (el_min - el0) * 0.85, el0 + (el_max - el0) * 0.85
    edges = {
        "real": metric(r=roll),
        "az_min": metric(az=az_min),
        "az_max": metric(az=az_max),
        "el_min": metric(el=el_min),
        "el_max": metric(el=el_max),
        "d_min": metric(d=d_min),
        "d_max": metric(d=d_max),
    }
    env.update(
        {
            "fov_y_deg": round(fov, 3),
            "azimuth_deg": [round(az_min, 2), round(az_max, 2)],
            "elevation_deg": [round(el_min, 2), round(el_max, 2)],
            "distance_m": [round(d_min, 3), round(d_max, 3)],
            "limits": {
                "az_dev_max_deg": AZ_DEV_MAX,
                "el_dev_max_deg": EL_DEV_MAX,
                "seen_min_of_real": SEEN_MIN,
                "mag_max_rel_real": MAG_MAX,
            },
            "edge_metrics": edges,
        }
    )
    # +azimuth moves the eye towards the real camera's right or left?
    step = orbit_view(env, {"azimuth_deg": 1.0, "elevation_deg": el0, "distance_m": dist,
                            "fov_y_deg": fov}).centre - c  # fmt: skip
    right_is_pos = float(step @ real.r[0]) > 0
    left, right = (az_min, az_max) if right_is_pos else (az_max, az_min)

    def preset(pid, label, az, el, d, r=0.0):
        return {"id": pid, "label": label, "azimuth_deg": round(az, 2), "elevation_deg": round(el, 2),
                "distance_m": round(d, 3), "roll_deg": round(r, 3), "fov_y_deg": round(fov, 3)}  # fmt: skip

    presets = [
        preset("real", "Real camera", 0.0, el0, dist, roll),
        preset("broadcast_high", "Broadcast high", 0.0, el0 + 0.85 * (el_max - el0), dist),
        preset("orbit_left", "Orbit left", 0.9 * left, el0 + 0.3 * (el_max - el0), dist),
        preset("orbit_right", "Orbit right", 0.9 * right, el0 + 0.3 * (el_max - el0), dist),
        preset("push_in", "Push-in", 0.0, el0 + 0.5 * (el_min - el0), d_min + 0.1 * (dist - d_min)),
    ]
    return env, presets


# --- build -------------------------------------------------------------------------------


def build_package(
    game_dir: Path,
    video: Path,
    play_id: str,
    out_dir: Path | None = None,
    *,
    max_frames: int | None = None,
    progress=None,
) -> dict[str, Any]:
    gd = Path(game_dir)
    started = time.time()
    out = Path(out_dir) if out_dir else gd / SCENE_REL.format(play_id=play_id)
    out.mkdir(parents=True, exist_ok=True)
    h = play(gd, play_id)
    doc = read_highlights(gd)
    calibration = json.loads((gd / "calibration.json").read_text(encoding="utf-8"))
    calib = json.loads((gd / "calib.json").read_text(encoding="utf-8"))
    real, mirrored = scene_view(calibration)
    k1 = float(calibration["dist"][0]) if calibration.get("dist") else 0.0
    info = probe_video(video)
    src_size, fps = (info["width"], info["height"]), info["fps"]
    n = frame_count(h, fps) if max_frames is None else min(frame_count(h, fps), max_frames)
    times = h["t_start"] + np.arange(n) / fps
    tracks = load_tracks(gd, *src_size)
    court = tracks.at(tracks.court, times)
    masks = Masks(gd, play_id)
    game = json.loads((gd / "game.json").read_text()) if (gd / "game.json").exists() else {}
    teams = {p["id"]: p.get("team") for p in game.get("players") or []}

    plates = _plates(gd, calib, calibration, mirrored)
    for entry, tex in plates:
        cv2.imwrite(str(out / entry["file"]), tex, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    t_plates = time.time()

    frames = _player_items(real, mirrored, k1, src_size, court, tracks.ids, masks)
    (cw, ch), (cols, rows) = _grid(frames)
    _assign_cells(frames, cols * rows)
    half = cols * cw
    size = (2 * half, rows * ch)
    gop = max(1, int(np.floor(fps)))
    proc = _encoder(out / "atlas.mp4", size, fps, gop)
    assert proc.stdin is not None
    layout_frames = []
    try:
        for f, (_, frame) in enumerate(read_window(video, h["t_start"], n)):
            atlas = np.zeros((size[1], size[0], 3), np.uint8)
            row = []
            for it in frames[f]:
                s0, z0, s1, z1 = it["rect"]
                k = min(
                    (cw - 2 * INSET) / (s1 - s0),
                    (ch - 2 * INSET) / (z1 - z0),
                    MAX_UPSCALE * it["ppm"],
                )
                wc = max(1, min(cw - 2 * INSET, int(np.ceil((s1 - s0) * k))))
                hc = max(1, min(ch - 2 * INSET, int(np.ceil((z1 - z0) * k))))
                s1, z0 = s0 + wc / k, z1 - hc / k  # the rect is exactly the content texels
                (x0, y0), m = masks.get(it["pid"], f)
                col, a = _rectify(frame, (x0, y0), _soft_alpha(m), it, k1, src_size,
                                  (wc + 2 * INSET, hc + 2 * INSET),
                                  (s0 - INSET / k, z1 + INSET / k), k)  # fmt: skip
                cx, cy = (it["cell"] % cols) * cw, (it["cell"] // cols) * ch
                ox, oy = cx + (cw - wc) // 2 - INSET, cy + ch - hc - 2 * INSET  # feet at the bottom
                atlas[oy : oy + hc + 2 * INSET, ox : ox + wc + 2 * INSET] = _fill_outside(col, a)
                mk = np.round(a * 255).astype(np.uint8)
                atlas[oy : oy + hc + 2 * INSET, half + ox : half + ox + wc + 2 * INSET] = mk[
                    ..., None
                ]
                u0, v0 = (ox + INSET) / size[0], (oy + INSET) / size[1]
                row.append(
                    {
                        "pid": it["pid"],
                        "cell": it["cell"],
                        "foot": [round(float(it["foot"][0]), 3), round(float(it["foot"][1]), 3)],
                        "rect": [round(s0, 4), round(z0, 4), round(s1, 4), round(z1, 4)],
                        "uv": [
                            round(u0, 6),
                            round(v0, 6),
                            round(u0 + wc / size[0], 6),
                            round(v0 + hc / size[1], 6),
                        ],
                        "depth": round(it["depth"], 3),
                    }
                )
            layout_frames.append(row)
            proc.stdin.write(np.ascontiguousarray(atlas).tobytes())
            if progress:
                progress(0.1 + 0.8 * (f + 1) / n)
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed writing {out / 'atlas.mp4'}")
    t_atlas = time.time()

    static, rims = _static(calibration, mirrored)
    ball = None
    if h.get("shot") and rims:
        s = h["shot"]
        i = tracks.index(s["player_id"])
        rel = tracks.at(tracks.court, np.array([s["t_release"]]))[i, 0] if i is not None else None
        if rel is not None and np.isfinite(rel).all():
            rim = min(rims, key=lambda r: np.hypot(r[0] - rel[0], r[1] - rel[1]))
            xyz = _mirror(ball_track(s, rel, np.asarray(rim), times), mirrored)
            ball = {
                "source": "model",
                "note": "parabola from the shot event (release -> rim), not a tracked ball",
                "radius_m": 0.12,
                "xyz": [None if not np.isfinite(p).all() else np.round(p, 3).tolist() for p in xyz],
            }
    feet = np.array([it["foot"] for fr in frames for it in fr]).reshape(-1, 3)
    env, presets = envelope(plates, real, src_size, feet)
    layout = {
        "schema": SCHEMA,
        "play_id": play_id,
        "label": h.get("label"),
        "sport": calibration.get("sport") or doc.get("sport"),
        "synthetic": bool(doc.get("synthetic")),
        "honesty_label": LABEL + ("  |  SYNTHETIC" if doc.get("synthetic") else ""),
        "t_start": h["t_start"],
        "t_end": round(h["t_start"] + n / fps, 3),
        "fps": fps,
        "n_frames": n,
        "frame": {"units": "m", "up": "+z", "floor": "z = 0", "mirror_x": mirrored},
        "camera": {
            "image_size": list(src_size),
            "K": np.round(real.k, 4).tolist(),
            "R": np.round(real.r, 8).tolist(),
            "t": np.round(real.t, 6).tolist(),
            "position_m": np.round(real.centre, 4).tolist(),
        },
        "plates": [e for e, _ in plates],
        "atlas": {
            "file": "atlas.mp4",
            "size_px": list(size),
            "cell_px": [cw, ch],
            "grid": [cols, rows],
            "inset_px": INSET,
            "mask_offset_u": 0.5,
            "mask_ramp": list(MASK_RAMP),
            "codec": "h264 high, yuv420p, bt709 limited range",
            "gop_frames": gop,
        },
        "players": {
            pid: {"team": teams.get(pid)}
            for pid in sorted({it["pid"] for fr in frames for it in fr})
        },
        "billboard": {"facing": "real", "shadow_radius_m": 0.42},
        "frames": layout_frames,
        "static": static,
        "ball": ball,
        "envelope": env,
        "presets": presets,
    }
    (out / "layout.json").write_text(json.dumps(layout, separators=(",", ":")), encoding="utf-8")
    if progress:
        progress(1.0)
    sizes = {p.name: p.stat().st_size for p in sorted(out.iterdir())}
    return {
        "play_id": play_id,
        "frames": n,
        "atlas_px": list(size),
        "cell_px": [cw, ch],
        "players_max": cols * rows,
        "bytes": sizes,
        "wall_s": {
            "plates": round(t_plates - started, 2),
            "atlas": round(t_atlas - t_plates, 2),
            "total": round(time.time() - started, 2),
        },
        "envelope": {k: env[k] for k in ("azimuth_deg", "elevation_deg", "distance_m")},
    }


# --- reference renderer ------------------------------------------------------------------


def draw_rgba(canvas: np.ndarray, tex: np.ndarray, view: View, corners_m, acc=None) -> None:
    """Draw a BGRA texture whose edges are the world quad `corners_m` (uv (0,0), (1,0),
    (1,1), (0,1)), clipped at the near plane; `acc` accumulates coverage (over)."""
    h_, w_ = tex.shape[:2]
    c = np.asarray(corners_m, np.float64)
    ax_u, ax_v = (c[1] - c[0]) / w_, (c[3] - c[0]) / h_
    origin = c[0] + 0.5 * ax_u + 0.5 * ax_v  # texel (0, 0) centre (OpenCV pixel convention)
    poly = np.array([[-0.5, -0.5], [w_ - 0.5, -0.5], [w_ - 0.5, h_ - 0.5], [-0.5, h_ - 0.5]])
    poly = _clip_poly(poly, view.depth(c), NEAR_M)
    if len(poly) < 3:
        return
    hm = plane_homography(view.p, origin, ax_u, ax_v)
    dst = cv2.perspectiveTransform(poly.reshape(-1, 1, 2), hm).reshape(-1, 2)
    lo, hi = np.floor(dst.min(0)), np.ceil(dst.max(0))
    x0, y0 = int(max(0, lo[0])), int(max(0, lo[1]))
    x1, y1 = int(min(canvas.shape[1], hi[0])), int(min(canvas.shape[0], hi[1]))
    if x1 <= x0 or y1 <= y0:
        return
    shift = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1.0]]) @ hm
    warped = cv2.warpPerspective(tex, shift, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR)
    m = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillConvexPoly(m, np.round((dst - [x0, y0]) * 16).astype(np.int32), 255, cv2.LINE_AA, 4)
    a = (m.astype(np.float32) / 255.0) * (warped[..., 3].astype(np.float32) / 255.0)
    roi = canvas[y0:y1, x0:x1]
    roi[:] = (warped[..., :3] * a[..., None] + roi * (1 - a[..., None])).astype(np.uint8)
    if acc is not None:
        acc[y0:y1, x0:x1] = a + acc[y0:y1, x0:x1] * (1 - a)


def _draw_hoop(canvas: np.ndarray, view: View, hoop: dict) -> None:
    board = np.asarray(hoop["backboard_m"])
    if (view.depth(board) > NEAR_M).all():
        pts = np.round(view.project(board)).astype(np.int32)
        over = canvas.copy()
        cv2.fillConvexPoly(over, pts, (235, 235, 235), cv2.LINE_AA)
        cv2.addWeighted(over, 0.35, canvas, 0.65, 0, canvas)
        cv2.polylines(canvas, [pts], True, (250, 250, 250), 2, cv2.LINE_AA)
    ang = np.linspace(0, 2 * np.pi, 32)
    c, r = np.asarray(hoop["rim_m"]), hoop["rim_radius_m"]
    ring = np.column_stack(
        [c[0] + r * np.cos(ang), c[1] + r * np.sin(ang), np.full_like(ang, c[2])]
    )
    if (view.depth(ring) > NEAR_M).all():
        cv2.polylines(
            canvas,
            [np.round(view.project(ring)).astype(np.int32)],
            False,
            (0, 90, 255),
            3,
            cv2.LINE_AA,
        )


class Package:
    """Read side of a scene package directory."""

    def __init__(self, pkg_dir: Path) -> None:
        self.dir = Path(pkg_dir)
        self.layout = json.loads((self.dir / "layout.json").read_text(encoding="utf-8"))
        self.plates = [
            (p, cv2.imread(str(self.dir / p["file"]), cv2.IMREAD_UNCHANGED))
            for p in self.layout["plates"]
        ]
        self.real = View(
            *(np.asarray(self.layout["camera"][k], np.float64) for k in ("K", "R", "t"))
        )

    def atlas_frames(self):
        """Decoded atlas frames (BGR uint8), BT.709 limited range -> full-range RGB."""
        w, h = self.layout["atlas"]["size_px"]
        proc = subprocess.Popen(
            [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-i", str(self.dir / "atlas.mp4"),
             "-vf", "scale=in_color_matrix=bt709:in_range=tv:out_range=pc,format=bgr24",
             "-f", "rawvideo", "-"],
            stdout=subprocess.PIPE,
        )  # fmt: skip
        assert proc.stdout is not None
        try:
            while True:
                buf = proc.stdout.read(w * h * 3)
                if len(buf) < w * h * 3:
                    return
                yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        finally:
            proc.stdout.close()
            proc.wait()

    def view(self, preset_id: str, size=TV_SIZE) -> View:
        p = next(p for p in self.layout["presets"] if p["id"] == preset_id)
        return orbit_view(self.layout["envelope"], p, size)


def render(
    pkg: Package,
    view: View,
    f: int,
    atlas: np.ndarray,
    size,
    *,
    facing: str | None = None,
    plates: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """(BGR image, player alpha) of frame `f` from `view`. `facing`: "real" (billboards
    keep the real camera's orientation, as the package says) or "viewer" (turned to the
    viewer, Tier B's rule)."""
    lay = pkg.layout
    facing = facing or lay["billboard"]["facing"]
    canvas = background(size)
    if plates:
        for entry, tex in pkg.plates:
            draw_rgba(canvas, tex, view, entry["corners_m"])
    people = []
    for it in lay["frames"][f]:
        foot = np.array([*it["foot"], 0.0])
        people.append((float(view.depth(foot + 0.9 * EZ)[0]), foot, it))
    for _, foot, _ in people:
        draw_shadow(canvas, view, foot)
    for hoop in lay["static"]["hoops"]:
        _draw_hoop(canvas, view, hoop)
    net = lay["static"].get("net")
    net_d = float(view.depth(np.mean([net["top_l_m"], net["top_r_m"]], axis=0))[0]) if net else -1.0
    people.sort(key=lambda q: -q[0])
    pa = np.zeros((size[1], size[0]), np.float32)
    aw, ah = lay["atlas"]["size_px"]
    lo, hi = lay["atlas"]["mask_ramp"]
    net_drawn = False
    for d, foot, it in people:
        if net and not net_drawn and d <= net_d:
            draw_net(canvas, view, [net["top_l_m"], net["top_r_m"]])
            net_drawn = True
        if d < NEAR_M + 0.5:
            continue
        axis = billboard_axis(pkg.real.centre if facing == "real" else view.centre, foot)
        s0, z0, s1, z1 = it["rect"]
        world = np.array([foot + s0 * axis + z1 * EZ, foot + s1 * axis + z1 * EZ,
                          foot + s1 * axis + z0 * EZ, foot + s0 * axis + z0 * EZ])  # fmt: skip
        if (view.depth(world) < NEAR_M).any():
            continue
        dst = view.project(world).astype(np.float32)
        u0, v0, u1, v1 = it["uv"]
        x0, y0 = int(np.floor(u0 * aw)) - 1, int(np.floor(v0 * ah)) - 1
        x1, y1 = int(np.ceil(u1 * aw)) + 1, int(np.ceil(v1 * ah)) + 1
        src = (np.array([[u0 * aw, v0 * ah], [u1 * aw, v0 * ah], [u1 * aw, v1 * ah], [u0 * aw, v1 * ah]])
               - 0.5 - [x0, y0]).astype(np.float32)  # fmt: skip
        hm = cv2.getPerspectiveTransform(src, dst)
        bl, bh = np.floor(dst.min(0)).astype(int), np.ceil(dst.max(0)).astype(int)
        bx0, by0 = max(0, bl[0]), max(0, bl[1])
        bx1, by1 = min(size[0], bh[0]), min(size[1], bh[1])
        if bx1 <= bx0 or by1 <= by0:
            continue
        shift = np.array([[1, 0, -bx0], [0, 1, -by0], [0, 0, 1.0]]) @ hm
        col = cv2.warpPerspective(
            atlas[y0:y1, x0:x1], shift, (bx1 - bx0, by1 - by0), flags=cv2.INTER_LINEAR
        )
        hx = int(aw // 2)
        mk = cv2.warpPerspective(
            atlas[y0:y1, x0 + hx : x1 + hx, 1],
            shift,
            (bx1 - bx0, by1 - by0),
            flags=cv2.INTER_LINEAR,
        )
        quad = np.zeros_like(mk)
        cv2.fillConvexPoly(
            quad, np.round((dst - [bx0, by0]) * 16).astype(np.int32), 255, cv2.LINE_AA, 4
        )
        a = np.clip((mk.astype(np.float32) / 255.0 - lo) / (hi - lo), 0, 1) * (quad / 255.0)
        roi = canvas[by0:by1, bx0:bx1]
        roi[:] = (col * a[..., None] + roi * (1 - a[..., None])).astype(np.uint8)
        pa[by0:by1, bx0:bx1] = a + pa[by0:by1, bx0:bx1] * (1 - a)
    if net and not net_drawn:
        draw_net(canvas, view, [net["top_l_m"], net["top_r_m"]])
    if lay.get("ball"):
        trail = [
            np.asarray(p) if p else np.full(3, np.nan)
            for p in lay["ball"]["xyz"][max(0, f - 8) : f + 1]
        ]
        draw_ball(canvas, view, np.asarray(trail))
    return canvas, pa


# --- checks: the real camera against the source -----------------------------------------


def ssim_map(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Gaussian-window SSIM (Wang et al. 2004, sigma 1.5) of two grey float images."""
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2

    def g(x):
        return cv2.GaussianBlur(x, (11, 11), 1.5)

    ma, mb = g(a), g(b)
    va, vb, cov = g(a * a) - ma * ma, g(b * b) - mb * mb, g(a * b) - ma * mb
    return ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))


def psnr(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> float | None:
    if not m.any():
        return None
    mse = float(((a.astype(np.float64) - b.astype(np.float64))[m] ** 2).mean())
    return round(10 * np.log10(255.0**2 / max(mse, 1e-9)), 2)


def check_real(game_dir: Path, video: Path, play_id: str, pkg_dir: Path) -> dict[str, Any]:
    """Render every frame from the exact real camera and compare it with the source
    (undistorted): PSNR / SSIM over the frame, the players (the SAM masks) and the static
    plate region (seen plates, away from every player's grown mask)."""
    pkg = Package(pkg_dir)
    lay = pkg.layout
    w, h = lay["camera"]["image_size"]
    k1 = 0.0
    cal = json.loads((Path(game_dir) / "calibration.json").read_text(encoding="utf-8"))
    if cal.get("dist"):
        k1 = float(cal["dist"][0])
    if k1:
        gx, gy = np.meshgrid(np.arange(w, dtype=np.float64), np.arange(h, dtype=np.float64))
        d = distortion.distort_points(
            np.column_stack([gx.ravel(), gy.ravel()]), k1, (w, h)
        ).reshape(h, w, 2)
        maps = d[..., 0].astype(np.float32), d[..., 1].astype(np.float32)
    acc = np.zeros((h, w), np.float32)
    for entry, tex in pkg.plates:
        draw_rgba(np.zeros((h, w, 3), np.uint8), tex, pkg.real, entry["corners_m"], acc)
    seen = acc >= 0.5
    masks = Masks(game_dir, play_id)
    names = ("all", "seen", "players", "static")
    tot: dict[str, list] = {f"{m}_{n}": [] for m in ("psnr", "ssim") for n in names}
    src = read_window(video, lay["t_start"], lay["n_frames"])
    for f, ((_, frame), atlas) in enumerate(zip(src, pkg.atlas_frames(), strict=False)):
        if k1:
            frame = cv2.remap(frame, *maps, cv2.INTER_LINEAR)
        img, _ = render(pkg, pkg.real, f, atlas, (w, h))
        pm = np.zeros((h, w), bool)
        for it in lay["frames"][f]:
            got = masks.get(it["pid"], f)
            if got:
                (x0, y0), m = got
                hh, ww = m.shape
                pm[y0 : y0 + hh, x0 : x0 + ww] |= m[: h - y0, : w - x0]
        near = cv2.dilate(pm.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
        static = seen & ~near
        everything = np.ones_like(pm)
        sm = ssim_map(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float64),
                      cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float64))  # fmt: skip
        regions = (("all", everything), ("seen", seen | pm), ("players", pm), ("static", static))
        for name, m in regions:
            if m.any():
                tot[f"psnr_{name}"].append(psnr(img, frame, m))
                tot[f"ssim_{name}"].append(float(sm[m].mean()))
    return {k: round(float(np.mean(v)), 3) if v else None for k, v in tot.items()} | {
        "frames": lay["n_frames"],
        "seen_fraction": round(float(seen.mean()), 3),
    }


def stills(pkg_dir: Path, out_dir: Path, fractions=(0.3, 0.75), size=(1280, 720)) -> list[Path]:
    """One PNG per preset at each fraction of the play, labelled like the clients must."""
    pkg = Package(pkg_dir)
    lay = pkg.layout
    want = sorted({min(lay["n_frames"] - 1, int(fr * lay["n_frames"])) for fr in fractions})
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for f, atlas in enumerate(pkg.atlas_frames()):
        if f not in want:
            continue
        for p in lay["presets"]:
            img, _ = render(pkg, orbit_view(lay["envelope"], p, size), f, atlas, size)
            txt = f"{p['label']}  az {p['azimuth_deg']:+.0f}  el {p['elevation_deg']:.0f}  d {p['distance_m']:.1f} m  |  {lay['honesty_label'].replace('·', '-')}"
            cv2.putText(
                img,
                txt,
                (14, size[1] - 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 0),
                3,
                cv2.LINE_AA,
            )
            cv2.putText(
                img,
                txt,
                (14, size[1] - 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (230, 230, 230),
                1,
                cv2.LINE_AA,
            )
            path = out_dir / f"{lay['play_id']}_f{f:03d}_{p['id']}.png"
            cv2.imwrite(str(path), img)
            paths.append(path)
    return paths


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Build a 2.5D scene package, render stills, check")
    ap.add_argument("game_dir", type=Path)
    ap.add_argument("play_id")
    ap.add_argument("--video", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None, help="package dir (default in the game)")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--no-build", action="store_true", help="use the existing package")
    ap.add_argument("--stills", type=Path, default=None, help="write preset stills here")
    ap.add_argument("--check", action="store_true", help="real-camera PSNR/SSIM vs the source")
    a = ap.parse_args()
    video = a.video or a.game_dir / "media" / "wide.mp4"
    out = a.out or a.game_dir / SCENE_REL.format(play_id=a.play_id)
    res: dict[str, Any] = {}
    if not a.no_build:
        res["build"] = build_package(a.game_dir, video, a.play_id, out, max_frames=a.max_frames)
    if a.stills:
        t0 = time.time()
        res["stills"] = [str(p) for p in stills(out, a.stills)]
        res["stills_wall_s"] = round(time.time() - t0, 2)
    if a.check:
        t0 = time.time()
        res["check_real"] = check_real(a.game_dir, video, a.play_id, out)
        res["check_wall_s"] = round(time.time() - t0, 2)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
