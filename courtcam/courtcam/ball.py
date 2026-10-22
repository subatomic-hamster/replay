"""The ball at the hoop: make/miss from the ball's own path (D-90).

The ball is ~10 px on a wide-angle phone or gym camera: a COCO detector (YOLO11x
`sports ball`) found it in 3 of 91 Nottingham frames. Around a rim it is easy, though:
the background there is a wall or the sky, so a ball-sized, ball-coloured blob that moves
against a running background is the ball. This module watches a box around every rim the
calibrated camera projects into the frame and keeps, per frame, every such blob in rim
units (`u` right, `v` down from the rim centre, 1 = one rim diameter in pixels):

* `hoops(calib, profile)` — each template rim projected 3.05 m up through the full camera
  (`calibrate.camera_calibration`), with its diameter in pixels;
* `scan(video, hoops, cfg)` — one decode pass -> `ball.json` (`courtcam.ball.v1`): the
  hoops and every ball-like blob near them;
* `arrivals(doc, cfg)` — the ball reaching each rim, one per shot, each with `made`: the
  ball passing down through the rim's middle into the net is a make; anything else
  (off the side, back out over the top, nothing seen) is not. `made` is None when too
  little of the ball was seen at the rim to tell.

No model, numpy/OpenCV only (MIT core). Thresholds are in rim units and colour, so the
scale of the picture drops out (Nottingham's rims are 17 px wide, in front of a wall).
Untested beyond that venue; the 2v2 park proxy's far rim (25 px, against sky and foliage,
heads across it) gave one visit in 120 s (D-90).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .profiles import BallCfg, Profile

SCHEMA = "courtcam.ball.v1"
RIM_DIAMETER_M = 0.45
RIM_HEIGHT_M = 3.05
# Box around a rim, in rim diameters: the ball's arc comes in from above and the side,
# a make leaves through the net below.
BOX = (-5.0, 5.0, -7.0, 3.0)  # u0, u1, v0, v1
WORK_RIM_PX = 20.0  # boxes are scaled so the rim is about this wide before differencing


@dataclass(frozen=True, slots=True)
class Hoop:
    rim_m: tuple[float, float]  # court metres of the rim centre
    px: tuple[float, float]  # rim centre in source pixels
    rim_px: float  # rim diameter in pixels


@dataclass(slots=True)
class Arrival:
    hoop: int
    t: float  # first ball sample at the rim
    t_end: float  # last ball sample at the rim
    made: bool | None
    confidence: float
    samples: int  # ball samples at the rim


def projector(calib: dict[str, Any], profile: Profile) -> Callable[[np.ndarray], Any]:
    """Court metres (x, y, z up) -> source pixel through the full camera, or None when
    no camera fits the calibration (then no hoop can be found)."""
    from . import calibrate, distortion

    try:
        p = calibrate.camera_matrix(calibrate.camera_calibration(calib, profile))
    except Exception:  # noqa: BLE001 — too few landmarks for a camera
        return lambda xyz: None
    size = tuple(calib.get("image_size") or ())
    k1 = float(calib.get("k1") or 0.0)

    def project(xyz) -> np.ndarray | None:
        x = p @ np.array([xyz[0], xyz[1], xyz[2], 1.0])
        if x[2] <= 0:
            return None
        px = x[:2] / x[2]
        return distortion.distort_points([px], k1, size)[0] if k1 and size else px

    return project


def hoops(calib: dict[str, Any], profile: Profile) -> list[Hoop]:
    """Every rim of the court template that projects inside the frame. A clip with no
    court fit (a park with no lines) can name its rims instead: `calib["hoops_px"]`,
    `[{"px": [x, y], "rim_px": width, "rim_m": [x, y]}]` (hand-clicked; `rim_m` optional)."""
    if calib.get("hoops_px"):
        return [
            Hoop(tuple(h.get("rim_m") or (0.0, 0.0)), tuple(h["px"]), float(h["rim_px"]))
            for h in calib["hoops_px"]
        ]
    try:
        tpl = profile.template(calib.get("variant"))
    except (ValueError, KeyError):
        return []
    rims = tpl.rims or ([tpl.rim] if tpl.rim else [])
    proj = projector(calib, profile)
    size = calib.get("image_size") or (0, 0)
    clicks = calib.get("landmarks_px") or {}
    out = []
    r = RIM_DIAMETER_M / 2
    # D-93: the hoop the user tapped on the calibration page (`rim_top`, `rim_top_f`, the
    # names `calibrate.height_landmarks` gives them) is where the hoop is; the camera
    # model only sizes it. A phone fit from four corners can put the projected hoop a rim
    # or more off, or have no camera at all.
    for (x, y), name in zip(rims, ("rim_top", "rim_top_f"), strict=False):
        c = proj((x, y, RIM_HEIGHT_M))
        d = None
        if c is not None:
            ends = [proj((x + dx, y + dy, RIM_HEIGHT_M))
                    for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r))]  # fmt: skip
            if all(e is not None for e in ends):
                # the rim is a horizontal circle: its widest image extent is its diameter
                d = max(abs(ends[0][0] - ends[1][0]), abs(ends[2][0] - ends[3][0]))
        if clicks.get(name):
            c = np.asarray(clicks[name], dtype=float)
            d = d if d is not None else _floor_rim_px(clicks, tpl, x, y)
        if c is None or d is None or not (0 <= c[0] < size[0] and 0 <= c[1] < size[1]):
            continue
        out.append(Hoop((float(x), float(y)), (float(c[0]), float(c[1])), float(max(d, 4.0))))
    return out


def _floor_rim_px(clicks: dict, tpl, x: float, y: float) -> float | None:
    """A rim's width in pixels from the floor homography alone: the floor under the rim
    is about as far from the camera as the rim itself. None without a homography."""
    from . import calibrate

    try:
        h, _ = calibrate.homography(clicks, tpl)
    except calibrate.CalibrationError:
        return None
    r = RIM_DIAMETER_M / 2
    a, b = calibrate.project(np.array([[x - r, y], [x + r, y]]), np.linalg.inv(h))
    return float(np.hypot(*(a - b)))


def median_frame(video: Path, n: int = 25) -> np.ndarray | None:
    """The per-pixel median of `n` frames spread over the video: the empty venue (people
    and the ball move; rims, walls and lines do not)."""
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    try:
        for i in np.linspace(0, max(0, total - 1), n).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, f = cap.read()
            if ok:
                frames.append(f)
    finally:
        cap.release()
    return np.median(np.stack(frames), axis=0).astype(np.uint8) if frames else None


def refine(h: Hoop, still: np.ndarray, cfg: BallCfg) -> Hoop:
    """Snap a projected rim onto the painted rim in the still frame: the rim-coloured
    (`cfg.rim_hue` red/orange, saturated) blob within 1.5 rim diameters that is about a
    rim wide and much flatter than tall. A 9.6 px landmark fit put Nottingham's far rim
    15 px (0.9 rim) too high; the make/miss column needs it within ~0.2. Unchanged when
    no such blob is there (a black or chain rim, or the rim out of the picture)."""
    r = h.rim_px
    x0, x1 = max(0, int(h.px[0] - 1.5 * r)), min(still.shape[1], int(h.px[0] + 1.5 * r))
    y0, y1 = max(0, int(h.px[1] - 1.5 * r)), min(still.shape[0], int(h.px[1] + 1.5 * r))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return h
    hsv = cv2.cvtColor(still[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    hue, sat = hsv[..., 0].astype(int), hsv[..., 1]
    lo, hi = cfg.rim_hue
    red = ((hue <= hi) | (hue >= lo)) if lo > hi else ((hue >= lo) & (hue <= hi))
    mask = (red & (sat >= cfg.rim_min_sat)).astype(np.uint8)
    n, _, st, cen = cv2.connectedComponentsWithStats(mask)
    best, best_d = None, np.inf
    for j in range(1, n):
        bx, by, bw, bh, a = st[j]
        if not (0.5 * r <= bw <= 1.6 * r and bh <= 0.8 * bw and a >= 0.1 * r * r):
            continue
        cx, cy = x0 + bx + bw / 2, y0 + cen[j][1]
        d = np.hypot(cx - h.px[0], cy - h.px[1])
        if d < best_d:
            best, best_d = (cx, cy), d
    if best is None:
        return h
    return Hoop(h.rim_m, (float(best[0]), float(best[1])), h.rim_px)


def _box(h: Hoop, size: tuple[int, int]) -> tuple[int, int, int, int]:
    u0, u1, v0, v1 = BOX
    x0 = max(0, int(h.px[0] + u0 * h.rim_px))
    x1 = min(size[0], int(h.px[0] + u1 * h.rim_px))
    y0 = max(0, int(h.px[1] + v0 * h.rim_px))
    y1 = min(size[1], int(h.px[1] + v1 * h.rim_px))
    return x0, y0, x1, y1


def ball_like(
    area: float, fill: float, aspect: float, hue: float, sat: float, cfg: BallCfg
) -> bool:
    """A blob the size, shape and colour of the ball (area in rim diameters squared). The
    hue range wraps through 180 when lo > hi: in shadow an orange ball reads red."""
    lo, hi = cfg.hue
    return (
        cfg.area[0] <= area <= cfg.area[1]
        and fill >= cfg.min_fill
        and aspect <= cfg.max_aspect
        and ((hue >= lo or hue <= hi) if lo > hi else lo <= hue <= hi)
        and sat >= cfg.min_sat
    )


def scan(
    video: Path,
    found: list[Hoop],
    cfg: BallCfg,
    *,
    progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """One decode pass: per frame and hoop, the ball-like blobs moving against a running
    background (`cfg.bg_s` memory). Each hoop box is first registered onto its background
    (phase correlation): a camera that shakes by a pixel turns the rim's red edge into a
    ball-coloured "moving" blob. Frames where much of the picture changes at once (a head
    in front of the lens, a camera bump) are skipped and listed in `skipped`. The hoops
    are snapped onto the painted rims first (`refine`)."""
    projected = list(found)
    still = median_frame(video) if cfg.refine else None
    if still is not None:
        found = [refine(h, still, cfg) for h in found]
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    boxes = [_box(h, size) for h in found]
    scales = [min(1.0, WORK_RIM_PX / h.rim_px) for h in found]
    alpha = 1.0 - float(np.exp(-1.0 / (fps * cfg.bg_s)))
    kernel = np.ones((3, 3), np.uint8)
    bgs: list[np.ndarray | None] = [None] * len(found)
    samples: list[list[list[float]]] = [[] for _ in found]
    quiet = [0.0] * len(found)  # per hoop: no samples before this time (after a re-aim)
    reaimed: list[float] = []
    skipped: list[float] = []
    prev = None
    i = -1
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            i += 1
            t = i / fps
            if progress and i % 300 == 0:
                progress(min(1.0, i / n_frames))
            small = cv2.cvtColor(frame[::8, ::8], cv2.COLOR_BGR2GRAY).astype(np.int16)
            whole = float(np.mean(np.abs(small - prev) > 20)) if prev is not None else 0.0
            prev = small
            if whole > cfg.max_frame_change:
                skipped.append(round(t, 3))
                bgs = [None] * len(found)  # relearn after the occlusion
                continue
            for k, (h, (x0, y0, x1, y1), s) in enumerate(zip(found, boxes, scales, strict=True)):
                if x1 - x0 < 8 or y1 - y0 < 8:
                    continue
                crop = frame[y0:y1, x0:x1]
                if s < 1.0:
                    crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                cur = crop.astype(np.float32)
                bg = bgs[k]
                if bg is None or bg.shape != cur.shape:
                    bgs[k] = cur
                    continue
                (dx, dy), _ = cv2.phaseCorrelate(bg.mean(axis=2), cur.mean(axis=2))
                if max(abs(dx), abs(dy)) > cfg.max_shift_px:
                    # the camera re-aimed (Nottingham Q1 236 s): the background is stale and
                    # every edge "moves"; start it again and stay quiet while the view
                    # settles (D-92)
                    bgs[k], quiet[k] = cur, t + 2 * cfg.bg_s
                    reaimed.append(round(t, 3))
                    continue
                if 0.25 <= max(abs(dx), abs(dy)):  # shake: register onto the background
                    m = np.float32([[1, 0, -dx], [0, 1, -dy]])
                    cur = cv2.warpAffine(cur, m, (cur.shape[1], cur.shape[0]),
                                         borderMode=cv2.BORDER_REPLICATE)  # fmt: skip
                diff = np.abs(cur - bg).max(axis=2)
                bg += alpha * (cur - bg)
                if t < quiet[k]:
                    continue
                mask = cv2.morphologyEx((diff > cfg.diff).astype(np.uint8), cv2.MORPH_OPEN, kernel)
                n, lab, st, cen = cv2.connectedComponentsWithStats(mask)
                if n <= 1:
                    continue
                hsv = None
                rim = h.rim_px * s  # rim diameter in work pixels
                for j in range(1, n):
                    bx, by, bw, bh, a = st[j]
                    area = a / rim**2
                    if not cfg.area[0] <= area <= cfg.area[1]:
                        continue
                    if hsv is None:
                        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
                    sel = lab[by : by + bh, bx : bx + bw] == j
                    patch = hsv[by : by + bh, bx : bx + bw]
                    hue, sat = (
                        float(np.median(patch[..., 0][sel])),
                        float(np.median(patch[..., 1][sel])),
                    )
                    fill, aspect = a / (bw * bh), max(bw, bh) / max(1, min(bw, bh))
                    if not ball_like(area, fill, aspect, hue, sat, cfg):
                        continue
                    u = (x0 + cen[j][0] / s - h.px[0]) / h.rim_px
                    v = (y0 + cen[j][1] / s - h.px[1]) / h.rim_px
                    samples[k].append([round(t, 3), round(u, 3), round(v, 3), round(area, 3)])
    finally:
        cap.release()
    if progress:
        progress(1.0)
    return {
        "schema": SCHEMA,
        "fps": fps,
        "image_size": list(size),
        "hoops": [
            {
                "rim_m": list(h.rim_m),
                "px": [round(h.px[0], 2), round(h.px[1], 2)],
                "px_projected": [round(p.px[0], 2), round(p.px[1], 2)],
                "rim_px": round(h.rim_px, 2),
                "samples": samples[k],
            }
            for k, (h, p) in enumerate(zip(found, projected, strict=True))
        ],
        "skipped": skipped,
        "reaimed": sorted(set(reaimed)),  # frames a hoop box jumped (any hoop)
    }


REL = "ball.json"


def run(
    video: Path,
    out_dir: Path,
    profile: Profile,
    calib: dict[str, Any],
    *,
    progress: Callable[[float], None] | None = None,
) -> dict[str, Any] | None:
    """`ball.json` for a game when the profile watches the ball and a rim is in frame;
    None otherwise, with an empty `ball.json` (no hoops) so the events stage always
    writes the same files (the worker caches them)."""
    import json

    found = hoops(calib, profile) if profile.ball.enabled else []
    doc = scan(video, found, profile.ball, progress=progress) if found else None
    empty = {"schema": SCHEMA, "hoops": [], "skipped": []}
    (Path(out_dir) / REL).write_text(json.dumps(doc or empty, separators=(",", ":")),
                                     encoding="utf-8")  # fmt: skip
    return doc


def _made(p: np.ndarray, cfg: BallCfg) -> bool | None:
    """The ball going down through the rim: two samples at most `cross_dt` apart (and a
    ball's step apart) that cross the plane just under the rim (`plane_v`) downward, at a
    point within `cross_u` of the rim's middle, then a sample within `drop_s` lower still
    (`fall_v` more) inside a cone widening down from that point — the ball leaving the
    net. A miss rolls off the rim and crosses the plane outside it; a miss that bounces
    out never crosses. Blind spot: a ball falling off the near or far side of the rim
    crosses in the middle of the picture. The crossing frames must hold at most
    `cross_max_blobs` blobs at the rim: more is a body moving through (3x3 proxy: a
    rebounder's arm and head under the rim after a rim-out, 5 blobs a frame).

    None (can't tell) when the only such drop is at the rim's edge (`cross_u` to
    `edge_u`) or has a gap up to `edge_dt`: a ball rolling in off the rim and a rim-out
    falling off its near side look the same from one camera (Nottingham Q3 156 s make,
    Q1 100.6 s and 3x3 9.8 s misses). The events stage then decides from what follows,
    and the review queue asks."""
    t, u, v = p[:, 0], p[:, 1], p[:, 2]
    near = (np.abs(u) <= 2.0) & (v >= -2.0) & (v <= 3.0)
    times, counts = np.unique(t[near], return_counts=True)
    busy = set(times[counts > cfg.cross_max_blobs].tolist())
    unsure = False
    for i in np.nonzero(v <= cfg.plane_v)[0]:
        if t[i] in busy:
            continue
        nxt = (t > t[i]) & (t <= t[i] + max(cfg.cross_dt, cfg.edge_dt)) & (v > cfg.plane_v)
        # a ball's step: 1.3 rim radii in cross_dt, more across a longer gap
        nxt &= np.hypot(u - u[i], v - v[i]) <= 1.3 * np.maximum(1.0, (t - t[i]) / cfg.cross_dt)
        for j in np.nonzero(nxt)[0]:
            if t[j] in busy:
                continue
            uc = u[i] + (u[j] - u[i]) * (cfg.plane_v - v[i]) / (v[j] - v[i])
            if abs(uc) > max(cfg.cross_u, cfg.edge_u):
                continue
            low = (t > t[j]) & (t <= t[j] + cfg.drop_s)
            low &= v >= max(v[j], cfg.plane_v + 0.4) + cfg.fall_v
            low &= np.abs(u - uc) <= 0.4 + 0.6 * (v - cfg.plane_v)
            if not low.any():
                continue
            if abs(uc) <= cfg.cross_u and t[j] - t[i] <= cfg.cross_dt:
                return True
            unsure = True
    return None if unsure else False


def arrivals(doc: dict[str, Any], cfg: BallCfg) -> list[Arrival]:
    """One arrival per visit of the ball to a rim (samples within `rim_box` of it, gaps
    under `visit_gap_s` bridged), at least `min_samples` long. `made` from `_made` over
    the visit and the `after_s` that follow; the confidence grows with the samples seen."""
    out: list[Arrival] = []
    u_max, v_lo, v_hi = cfg.rim_box
    for k, h in enumerate(doc.get("hoops") or []):
        p = np.asarray(h.get("samples") or [], dtype=np.float64).reshape(-1, 4)
        if not len(p):
            continue
        p = p[np.argsort(p[:, 0], kind="stable")]
        near = p[(np.abs(p[:, 1]) <= u_max) & (p[:, 2] >= v_lo) & (p[:, 2] <= v_hi)]
        visits: list[list[float]] = []
        for t in near[:, 0]:
            if visits and t - visits[-1][1] <= cfg.visit_gap_s:
                visits[-1][1] = t
                visits[-1][2] += 1
            else:
                visits.append([t, t, 1])
        for t0, t1, n in visits:
            if n < cfg.min_samples:
                continue
            # a shot comes down to the rim; a pass at hoop height goes across it
            first = near[near[:, 0] >= t0][0]
            before = p[(p[:, 0] >= t0 - cfg.descent_s) & (p[:, 0] < t0)]
            fell = (before[:, 2] <= first[2] - cfg.descent_v).any() if len(before) else False
            if not fell and n < cfg.settle_samples:
                continue
            # a body under the rim: many blobs at once in much of the visit (3x3 proxy
            # 11.0 s, 32% of frames; real visits up to 11%) (D-92)
            w = p[(p[:, 0] >= t0) & (p[:, 0] <= t1)]
            w = w[(np.abs(w[:, 1]) <= 2.0) & (w[:, 2] >= -2.0) & (w[:, 2] <= 3.0)]
            _, per_frame = np.unique(w[:, 0], return_counts=True)
            if np.mean(per_frame > cfg.cross_max_blobs) > cfg.visit_max_busy:
                continue
            seen = p[(p[:, 0] >= t0 - 0.2) & (p[:, 0] <= t1 + cfg.after_s)]
            made = _made(seen, cfg)
            conf = float(min(0.95, 0.35 + 0.04 * n))
            out.append(Arrival(k, round(t0, 3), round(t1, 3), made, round(conf, 3), int(n)))
    out.sort(key=lambda a: a.t)
    # one ball: visits to two rims at once are something else moving at one of them
    # (a person, a flicker); keep the better-seen one
    keep: list[Arrival] = []
    for a in out:
        clash = [
            b for b in keep if b.hoop != a.hoop and a.t <= b.t_end + 0.3 and b.t <= a.t_end + 0.3
        ]
        if not clash:
            keep.append(a)
        elif all(a.samples > b.samples for b in clash):
            keep = [b for b in keep if b not in clash] + [a]
    return keep
