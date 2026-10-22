"""Tier B: 2.5D cutout replays from virtual cameras (M8).

Everything in the scene is a plane, so no GL is needed: each plane is drawn with one
homography warp (texture -> virtual image), clipped at the virtual camera's near plane,
back to front:

* backdrop — the far wall, unprojected from the court plate (`courtcam.plate`);
* floor — the plate's top-down metric texture, with soft contact shadows;
* basketball hoops — rim ring and backboard drawn as 3D geometry from the template;
* players — SAM 2 cutouts on upright billboards standing on their tracked court
  position. A billboard is the vertical plane through the player's foot point, turned
  to the real camera; the cutout maps onto it exactly through the full calibration
  (so feet sit on the floor and height comes from K, R, t), and for the virtual camera
  the plane is turned by the same angle the line of sight turned: flat, but upright
  and facing the viewer, sorted by depth;
* the ball — only for a basketball shot event: a parabola from the shooter's release
  (shot time - 1 s, 2.3 m) to the rim (3.05 m), dropping through it on a make. It is
  a model, not a tracked ball, and before the release there is no ball at all.

Camera moves (time-aligned with the Tier A angles, eased, no jitter): `orbit` ±30°
around the play centre, `push_in` from the real camera's own pose halfway to the play,
`broadcast_high` an elevated sideline camera tracking the play. The output is labelled
"TIER B · 2.5D" (and SYNTHETIC on synthetic input).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from courtcam.calibrate import RIM_HEIGHT_M
from courtcam.render import open_encoder

from courtcam import distortion

from ..camera import ease
from ..gamedata import load_tracks
from .replays import frame_count, play, probe_video, read_highlights, read_window
from .segment import Masks

OUT_SIZE = (1280, 720)
NEAR_M = 0.3
EZ = np.array([0.0, 0.0, 1.0])
RELEASE_H_M = 2.3
BALL_R_M = 0.12
G = 9.81
BG_TOP, BG_BOTTOM = (34, 26, 22), (12, 10, 9)


@dataclass
class View:
    k: np.ndarray
    r: np.ndarray
    t: np.ndarray

    @property
    def p(self) -> np.ndarray:
        return self.k @ np.column_stack([self.r, self.t])

    @property
    def centre(self) -> np.ndarray:
        return -self.r.T @ self.t

    def depth(self, xyz: np.ndarray) -> np.ndarray:
        return np.asarray(xyz, dtype=np.float64).reshape(-1, 3) @ self.r[2] + self.t[2]

    def project(self, xyz: np.ndarray) -> np.ndarray:
        h = np.column_stack(
            [np.asarray(xyz, np.float64).reshape(-1, 3), np.ones(len(np.atleast_2d(xyz)))]
        )
        h = h @ self.p.T
        return h[:, :2] / h[:, 2:3]


def look_at(eye: np.ndarray, target: np.ndarray, f: float, size=OUT_SIZE) -> View:
    fwd = target - eye
    fwd = fwd / np.linalg.norm(fwd)
    right = np.cross(fwd, EZ)
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    r = np.vstack([right, down, fwd])
    k = np.array([[f, 0, size[0] / 2], [0, f, size[1] / 2], [0, 0, 1.0]])
    return View(k, r, -r @ eye)


# --- camera paths ------------------------------------------------------------------


def _smooth(x: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian smoothing along axis 0, edge-padded (no lag, no end droop)."""
    if sigma <= 0 or len(x) < 3:
        return x
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(x, [(r, r)] + [(0, 0)] * (x.ndim - 1), mode="edge")
    return np.stack([np.convolve(pad[:, d], k, mode="valid") for d in range(x.shape[1])], axis=1)


def play_centre(court: np.ndarray, focus: list[int], fps: float) -> np.ndarray:
    """(F, 3) smoothed centre of the focus players (all players where none is tracked)."""
    sel = court[focus] if focus else court
    c = np.nanmean(sel, axis=0)
    allc = np.nanmean(court, axis=0)
    c = np.where(np.isfinite(c), c, allc)
    ok = np.isfinite(c[:, 0])
    if not ok.any():
        raise ValueError("no tracked player in this window")
    idx = np.arange(len(c))
    c = np.column_stack([np.interp(idx, idx[ok], c[ok, d]) for d in range(2)])
    c = _smooth(c, 1.0 * fps)
    return np.column_stack([c, np.full(len(c), 1.0)])


def camera_path(
    angle: str, real: View, real_size, centre: np.ndarray, spread_m: float, size=OUT_SIZE
) -> list[View]:
    """One virtual camera per output frame of `size`, looking at `centre` (F, 3)."""
    n = len(centre)
    w_out = size[0]
    u = ease(np.linspace(0.0, 1.0, n))
    c_real = real.centre
    t0 = centre.mean(axis=0)
    v = (c_real - t0)[:2]
    d0 = float(np.linalg.norm(v))
    phi0 = float(np.arctan2(v[1], v[0]))
    elev0 = float(np.arctan2(c_real[2] - t0[2], d0))
    f_real = real.k[0, 0] * w_out / real_size[0]
    views = []
    if angle == "orbit":
        r = float(np.clip(0.6 * d0, 9.0, 22.0))
        elev = float(np.clip(elev0, np.radians(14), np.radians(40)))
        f = w_out * r / float(np.clip(spread_m + 7.0, 11.0, 22.0))
        for i in range(n):
            phi = phi0 + np.radians(30.0) * (2 * u[i] - 1)
            eye = centre[i] + r * np.array(
                [np.cos(phi) * np.cos(elev), np.sin(phi) * np.cos(elev), np.sin(elev)]
            )
            views.append(look_at(eye, centre[i], f, size))
    elif angle == "push_in":
        aim = c_real + real.r[2] * np.linalg.norm(c_real - t0)  # where the real camera looks
        end = c_real + 0.5 * (t0 - c_real)
        end[2] = max(end[2], t0[2] + 2.0)
        for i in range(n):
            eye = c_real + (end - c_real) * u[i]
            k = float(ease(min(1.0, 2.5 * i / max(1, n - 1))))
            views.append(look_at(eye, aim + (centre[i] - aim) * k, f_real, size))
    elif angle == "broadcast_high":
        r, h = 15.0, 9.0
        f = w_out * np.hypot(r, h) / float(np.clip(spread_m + 9.0, 14.0, 26.0))
        for i in range(n):
            phi = phi0 + np.radians(12.0) * (u[i] - 0.5)
            eye = np.array([t0[0] + r * np.cos(phi), t0[1] + r * np.sin(phi), h])
            eye[:2] += (centre[i][:2] - t0[:2]) * 0.5  # truck along with the play
            views.append(look_at(eye, centre[i], f, size))
    else:
        raise ValueError(f"unknown Tier B angle {angle!r}")
    return views


# --- drawing -------------------------------------------------------------------------


def _clip_poly(poly: np.ndarray, depth: np.ndarray, near: float) -> np.ndarray:
    """Sutherland-Hodgman against depth >= near; `depth` per vertex (linear on a plane)."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b, da, db = poly[i], poly[(i + 1) % n], depth[i], depth[(i + 1) % n]
        if da >= near:
            out.append(a)
        if (da >= near) != (db >= near):
            out.append(a + (b - a) * (near - da) / (db - da))
    return np.asarray(out)


def plane_homography(
    p: np.ndarray, origin: np.ndarray, ax_u: np.ndarray, ax_v: np.ndarray
) -> np.ndarray:
    """(u, v, 1) -> pixels for world point origin + u ax_u + v ax_v."""
    return p @ np.column_stack([np.r_[ax_u, 0.0], np.r_[ax_v, 0.0], np.r_[origin, 1.0]])


def draw_plane(canvas: np.ndarray, tex: np.ndarray, view: View, origin, ax_u, ax_v) -> None:
    """Draw texture `tex` (pixel (u, v) at origin + u ax_u + v ax_v) into `canvas`."""
    h_, w_ = tex.shape[:2]
    corners = np.array([[0, 0], [w_, 0], [w_, h_], [0, h_]], np.float64)
    world = origin + corners[:, :1] * ax_u + corners[:, 1:] * ax_v
    poly = _clip_poly(corners, view.depth(world), NEAR_M)
    if len(poly) < 3:
        return
    hm = plane_homography(view.p, origin, ax_u, ax_v)
    dst = cv2.perspectiveTransform(poly.reshape(-1, 1, 2), hm).reshape(-1, 2)
    size = (canvas.shape[1], canvas.shape[0])
    lo, hi = np.floor(dst.min(0)), np.ceil(dst.max(0))
    x0, y0 = int(max(0, lo[0])), int(max(0, lo[1]))
    x1, y1 = int(min(size[0], hi[0])), int(min(size[1], hi[1]))
    if x1 <= x0 or y1 <= y0:
        return
    shift = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1.0]])
    warped = cv2.warpPerspective(tex, shift @ hm, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)  # fmt: skip
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillConvexPoly(mask, np.round((dst - [x0, y0]) * 16).astype(np.int32), 255, cv2.LINE_AA, 4)
    roi = canvas[y0:y1, x0:x1]
    # one native blend (a numpy float blend of whole-frame planes was most of the time)
    w = mask.astype(np.float32) * (1 / 255.0)
    roi[:] = cv2.blendLinear(warped, np.ascontiguousarray(roi), w, 1.0 - w)


def background(size=OUT_SIZE) -> np.ndarray:
    w, h = size
    k = np.linspace(0, 1, h)[:, None, None]
    img = np.asarray(BG_TOP, np.float32) * (1 - k) + np.asarray(BG_BOTTOM, np.float32) * k
    return np.repeat(img, w, axis=1).astype(np.uint8)


def _median_colour(img: np.ndarray) -> np.ndarray:
    px = img.reshape(-1, 3)
    seen = px.max(axis=1) > 12  # unseen texels are black
    return np.median(px[seen], axis=0) if seen.any() else np.array([60.0, 60.0, 60.0])


def room_planes(floor: np.ndarray, wall: np.ndarray, plate_meta: dict) -> list:
    """Flat stand-ins for what the real camera never saw, drawn under the plate: a floor
    out to the horizon in the floor's own median colour, and a wall on every side of the
    plate's floor box shaded from the backdrop's upper to lower median colour. Plain
    colour, so nothing reads as detail that was not filmed. (tex, origin, ax_u, ax_v,
    inward normal or None) for `draw_plane`; a wall is drawn only from inside its face."""
    fx0, fy0, fx1, fy1 = plate_meta["floor"]["bounds_m"]
    hgt = float(plate_meta["backdrop"]["height_m"])
    hh = wall.shape[0]
    top, low = _median_colour(wall[: hh // 2]), _median_colour(wall[hh // 2 :])
    grad = np.repeat(np.linspace(top, low, 64)[:, None, :], 2, axis=1).astype(np.uint8)
    out = []
    ext = 60.0
    tile = np.full((2, 2, 3), _median_colour(floor), np.uint8)
    out.append((tile, np.array([fx0 - ext, fy1 + ext, 0.0]),
                np.array([(fx1 - fx0 + 2 * ext) / 2, 0, 0.0]),
                np.array([0, -(fy1 - fy0 + 2 * ext) / 2, 0.0]), None))  # fmt: skip
    ring = [(fx0, fy0), (fx1, fy0), (fx1, fy1), (fx0, fy1)]  # counter-clockwise from above
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1], strict=True):
        a, b = np.array([ax, ay, hgt]), np.array([bx, by, hgt])
        inward = np.array([-(by - ay), bx - ax]) / np.hypot(bx - ax, by - ay)
        out.append((grad, a, (b - a) / 2, -EZ * hgt / 64, (a[:2], inward)))
    return out


def fill_unseen(floor: np.ndarray, wall: np.ndarray, planes: list, seen_f, seen_b):
    """The plate's never-seen texels (`seen_*` 0, the masks the 2.5D scene package ships as
    alpha) in the stand-in colours, so a virtual camera turned past the real one's field
    of view sees plain floor / wall, not black holes."""
    floor, wall = floor.copy(), wall.copy()
    floor[seen_f[: floor.shape[0], : floor.shape[1]] < 128] = planes[0][0][0, 0]
    rows = cv2.resize(planes[1][0][:, :1], (1, wall.shape[0]), interpolation=cv2.INTER_LINEAR)
    hole = seen_b[: wall.shape[0], : wall.shape[1]] < 128
    wall[hole] = np.broadcast_to(rows, wall.shape)[hole]
    return floor, wall


def draw_room(canvas: np.ndarray, view: View, planes: list) -> None:
    eye = view.centre[:2]
    for tex, origin, ax_u, ax_v, face in planes:
        if face is None or (eye - face[0]) @ face[1] > 0:
            draw_plane(canvas, tex, view, origin, ax_u, ax_v)


def draw_shadow(canvas: np.ndarray, view: View, foot: np.ndarray) -> None:
    ang = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    ring = foot + np.column_stack([0.42 * np.cos(ang), 0.42 * np.sin(ang), np.zeros_like(ang)])
    if (view.depth(ring) < NEAR_M).any():
        return
    px = view.project(ring)
    sigma = max(1.0, float(np.ptp(px[:, 0])) / 10)
    pad = int(3 * sigma) + 2  # the blur must fade out inside the patch, not at its edge
    lo, hi = np.floor(px.min(0)).astype(int) - pad, np.ceil(px.max(0)).astype(int) + pad
    x0, y0 = max(0, lo[0]), max(0, lo[1])
    x1, y1 = min(canvas.shape[1], hi[0]), min(canvas.shape[0], hi[1])
    if x1 <= x0 or y1 <= y0:
        return
    m = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(m, [np.round(px - [x0, y0]).astype(np.int32)], 255, cv2.LINE_AA)
    k = int(sigma // 3)  # a big soft shadow (a player at a POV's feet) blurs at 1/k size:
    if k > 1:  # the full-size blur was half of a POV render's time
        small = cv2.resize(m, (max(1, m.shape[1] // k), max(1, m.shape[0] // k)),
                           interpolation=cv2.INTER_AREA)  # fmt: skip
        small = cv2.GaussianBlur(small, (0, 0), sigma / k)
        m = cv2.resize(small, (m.shape[1], m.shape[0]), interpolation=cv2.INTER_LINEAR)
    else:
        m = cv2.GaussianBlur(m, (0, 0), sigma)
    a = (m.astype(np.float32) / 255.0 * 0.45)[..., None]
    roi = canvas[y0:y1, x0:x1]
    roi[:] = (roi * (1 - a)).astype(np.uint8)


def draw_hoops(
    canvas: np.ndarray, view: View, rims: list, baseline_ys: tuple[float, float]
) -> None:
    """Rim ring at 3.05 m and a translucent backboard 0.375 m behind it (FIBA)."""
    for rx, ry in rims:
        back = -1.0 if abs(ry - baseline_ys[0]) < abs(ry - baseline_ys[1]) else 1.0
        by = ry + back * 0.375
        board = np.array(
            [[rx - 0.9, by, 2.9], [rx + 0.9, by, 2.9], [rx + 0.9, by, 3.95], [rx - 0.9, by, 3.95]]
        )
        if (view.depth(board) > NEAR_M).all():
            pts = np.round(view.project(board)).astype(np.int32)
            over = canvas.copy()
            cv2.fillConvexPoly(over, pts, (235, 235, 235), cv2.LINE_AA)
            cv2.addWeighted(over, 0.35, canvas, 0.65, 0, canvas)
            cv2.polylines(canvas, [pts], True, (250, 250, 250), 2, cv2.LINE_AA)
        ang = np.linspace(0, 2 * np.pi, 32)
        ring = np.column_stack(
            [rx + 0.225 * np.cos(ang), ry + 0.225 * np.sin(ang), np.full_like(ang, RIM_HEIGHT_M)]
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


def draw_net(canvas: np.ndarray, view: View, tops: list) -> None:
    """Net posts + a translucent net hanging from the top band (`tops`: the two post tops).
    Depth of the mesh: 1 m (volleyball), 0.76 m (badminton), to the floor (pickleball)."""
    (lx, ly, h), (rx, ry, _) = tops
    depth = 1.0 if h > 2.0 else 0.76 if h > 1.2 else h
    top = np.array([[lx, ly, h], [rx, ry, h]])
    mesh = np.array([top[0], top[1], [rx, ry, h - depth], [lx, ly, h - depth]])
    if (view.depth(mesh) > NEAR_M).all():
        pts = np.round(view.project(mesh)).astype(np.int32)
        over = canvas.copy()
        cv2.fillConvexPoly(over, pts, (40, 40, 40), cv2.LINE_AA)
        cv2.addWeighted(over, 0.3, canvas, 0.7, 0, canvas)
        cv2.line(canvas, *map(tuple, pts[:2]), (245, 245, 245), 3, cv2.LINE_AA)
    for x, y in ((lx, ly), (rx, ry)):
        post = np.array([[x, y, 0.0], [x, y, h + 0.05]])
        if (view.depth(post) > NEAR_M).all():
            a, b = np.round(view.project(post)).astype(np.int32)
            cv2.line(canvas, tuple(a), tuple(b), (60, 60, 60), 4, cv2.LINE_AA)


def ball_track(
    shot: dict, release_xy: np.ndarray, rim_xy: np.ndarray, times: np.ndarray
) -> np.ndarray:
    """(F, 3) ball position, NaN when there is no modelled ball."""
    out = np.full((len(times), 3), np.nan)
    t0, t1 = shot["t_release"], shot["t_rim"]
    dt = max(t1 - t0, 0.3)
    vz = (RIM_HEIGHT_M - RELEASE_H_M + 0.5 * G * dt * dt) / dt
    for i, t in enumerate(times):
        s = t - t0
        if 0 <= s <= dt:
            xy = release_xy + (rim_xy - release_xy) * (s / dt)
            out[i] = [*xy, RELEASE_H_M + vz * s - 0.5 * G * s * s]
        elif shot.get("made") and dt < s <= dt + 0.75:  # through the net to the floor
            q = s - dt
            out[i] = [*rim_xy, max(BALL_R_M, RIM_HEIGHT_M - 1.0 * q - 0.5 * G * q * q)]
    return out


def draw_ball(canvas: np.ndarray, view: View, trail: np.ndarray) -> None:
    pts = [p for p in trail if np.isfinite(p).all()]
    if not pts:
        return
    pts = np.asarray(pts)
    if (view.depth(pts) < NEAR_M).any():
        return
    px = view.project(pts)
    for j in range(1, len(px)):  # fading trail
        a = j / len(px)
        cv2.line(canvas, tuple(np.round(px[j - 1]).astype(int)), tuple(np.round(px[j]).astype(int)),
                 (int(60 * a), int(140 * a + 40), int(255 * a)), 2, cv2.LINE_AA)  # fmt: skip
    r = max(3, int(view.k[0, 0] * BALL_R_M / view.depth(pts[-1:])[0]))
    c = tuple(np.round(px[-1]).astype(int))
    cv2.circle(canvas, c, r, (30, 110, 235), -1, cv2.LINE_AA)
    cv2.circle(canvas, c, r, (10, 30, 60), 1, cv2.LINE_AA)


SEEN_FULL, SEEN_NONE = np.radians(35), np.radians(75)  # real pixels: full / none
# over a body proxy the cutout hands over sooner and quicker (two bodies never ghost)
PROXY_FULL, PROXY_NONE = np.radians(18), np.radians(32)
NEAR_FADE_M = 1.8  # image-based cutouts fade in from 1.2 m to 3.0 m from the camera


def seen_weight(th: float) -> float:
    """How much of a cutout's real pixels to show when the virtual line of sight is `th`
    radians (horizontal) from the real camera's: all up to 35°, none past 75°."""
    return float(np.clip((SEEN_NONE - abs(th)) / (SEEN_NONE - SEEN_FULL), 0.0, 1.0))


def turn(real: View, view: View, foot: np.ndarray) -> float:
    """Signed horizontal angle (rad) at `foot` from the real line of sight to the
    virtual one."""
    dr, dv = (foot - real.centre)[:2], (foot - view.centre)[:2]
    return float(np.arctan2(dr[0] * dv[1] - dr[1] * dv[0], dr @ dv))


def _silhouette(rgb: np.ndarray, tint, w: float) -> np.ndarray:
    """The crop blended toward a flat kit colour shaded by its own light (folds, arms and
    legs stay readable): weight `w` of the real pixels."""
    g = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY).astype(np.float32)
    shade = (0.55 + 0.45 * g / max(float(g.mean()), 1.0))[..., None]
    flat = np.clip(np.asarray(tint, np.float32) * shade, 0, 255)
    return (rgb.astype(np.float32) * w + flat * (1 - w)).astype(np.uint8)


class Billboard:
    """Player cutout -> virtual image through the plane at the foot point."""

    def __init__(self, real: View, k1: float, src_size: tuple[int, int]) -> None:
        self.real, self.k1, self.src_size = real, k1, src_size

    def _axis(self, cam: np.ndarray, foot: np.ndarray) -> np.ndarray:
        d = foot - cam
        a = np.cross(EZ, d)
        a[2] = 0
        return a / np.linalg.norm(a)

    def draw(self, canvas, view: View, frame, foot: np.ndarray, xy0, mask: np.ndarray,
             tint=None, fade: float = 1.0) -> None:  # fmt: skip
        """`tint`: None (the real pixels), or a BGR kit colour the cutout fades to as the
        virtual line of sight turns away from the real one (`seen_weight`): past ~45° a
        flat cutout reads wrong, so it becomes a kit-coloured, shaded silhouette of the
        same shape, mirrored once seen from behind. Never stretched garbage. With a tint
        a cutout also fades out closer than `NEAR_FADE_M` (a POV brushing past someone
        would fill the frame with a few dozen magnified source pixels). `fade` scales
        its opacity (over a body proxy, `avatars.proxy`)."""
        a_r = self._axis(self.real.centre, foot)
        th = turn(self.real, view, foot)
        c, s = np.cos(th), np.sin(th)
        a_v = np.array([c * a_r[0] - s * a_r[1], s * a_r[0] + c * a_r[1], 0.0])
        dist = float(view.depth(foot + 0.9 * EZ)[0])
        if dist < NEAR_M + 0.5:
            return
        opacity = fade * (1.0 if tint is None else float(np.clip((dist - 1.2) / NEAR_FADE_M, 0, 1)))
        if opacity <= 0:
            return
        g_real = plane_homography(self.real.p, foot, a_r, EZ)
        g_virt = plane_homography(view.p, foot, a_v, EZ)
        ys, xs = np.nonzero(mask)
        mx0, my0, mx1, my1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        pad = 3
        mx0, my0 = max(0, mx0 - pad), max(0, my0 - pad)
        mx1, my1 = min(mask.shape[1], mx1 + pad), min(mask.shape[0], my1 + pad)
        ox, oy = xy0[0] + mx0, xy0[1] + my0
        rgb = frame[oy : oy + (my1 - my0), ox : ox + (mx1 - mx0)]
        m = mask[my0:my1, mx0:mx1][: rgb.shape[0], : rgb.shape[1]]
        cw, ch = rgb.shape[1], rgb.shape[0]
        if cw < 2 or ch < 2:
            return
        corners = np.array([[0, 0], [cw, 0], [cw, ch], [0, ch]], np.float64)
        src = corners + [ox, oy]
        und = distortion.undistort_points(src, self.k1, self.src_size)
        h_crop = cv2.getPerspectiveTransform(corners.astype(np.float32), und.astype(np.float32))
        total = g_virt @ np.linalg.inv(g_real) @ h_crop
        dst = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), total).reshape(-1, 2)
        lo, hi = np.floor(dst.min(0)).astype(int), np.ceil(dst.max(0)).astype(int)
        x0, y0 = max(0, lo[0]), max(0, lo[1])
        x1, y1 = min(canvas.shape[1], hi[0]), min(canvas.shape[0], hi[1])
        if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) > canvas.size:
            return
        if tint is not None:
            w = seen_weight(th)
            if w < 1.0:
                rgb = _silhouette(rgb, tint, w)
            if abs(th) > np.pi / 2:  # from behind: the person's left is on our left
                rgb, m = np.ascontiguousarray(rgb[:, ::-1]), np.ascontiguousarray(m[:, ::-1])
        alpha = m.astype(np.float32)
        alpha = cv2.erode(alpha, np.ones((3, 3), np.uint8)) if min(cw, ch) > 24 else alpha
        alpha = cv2.GaussianBlur(alpha, (0, 0), max(0.7, ch / 120)) * opacity
        shift = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1.0]]) @ total
        out_wh = (x1 - x0, y1 - y0)
        col = cv2.warpPerspective(rgb, shift, out_wh, flags=cv2.INTER_LINEAR)
        a = cv2.warpPerspective(alpha, shift, out_wh, flags=cv2.INTER_LINEAR)[..., None]
        roi = canvas[y0:y1, x0:x1]
        roi[:] = (col * a + roi * (1 - a)).astype(np.uint8)


def label(canvas: np.ndarray, angle: str, synthetic: bool) -> None:
    """Burned-in honesty label, bottom right: the one corner the TV overlay leaves free
    (it puts the play title top left, the angle card bottom left, SYNTHETIC top right)."""
    names = {"orbit": "ORBIT", "push_in": "PUSH-IN", "broadcast_high": "BROADCAST HIGH"}
    h, w = canvas.shape[:2]
    s = w / 1280.0  # designed at 1280x720, scaled to the output
    font, small = cv2.FONT_HERSHEY_DUPLEX, cv2.FONT_HERSHEY_SIMPLEX
    head = f"TIER B 2.5D  |  {names.get(angle, angle.upper())}"
    note = "flat player cutouts on a reconstructed court" + ("  |  SYNTHETIC" if synthetic else "")
    (hw, _), _ = cv2.getTextSize(head, font, 0.6 * s, 1)
    (nw, _), _ = cv2.getTextSize(note, small, 0.45 * s, 1)
    x1, y1 = w - int(20 * s), h - int(20 * s)
    x0, y0 = x1 - max(hw, nw) - int(24 * s), y1 - int(54 * s)
    roi = canvas[y0:y1, x0:x1]
    roi[:] = (roi * 0.35 + 8).astype(np.uint8)
    cv2.rectangle(canvas, (x1 - int(5 * s), y0), (x1, y1), (0, 170, 255), -1)
    cv2.putText(canvas, head, (x1 - hw - int(14 * s), y0 + int(22 * s)), font, 0.6 * s,
                (0, 200, 255), 1, cv2.LINE_AA)  # fmt: skip
    cv2.putText(canvas, note, (x1 - nw - int(14 * s), y0 + int(44 * s)), small, 0.45 * s,
                (215, 215, 215), 1, cv2.LINE_AA)  # fmt: skip


# --- the render ----------------------------------------------------------------------


def _real_view(calibration: dict) -> View:
    return View(
        np.asarray(calibration["K"]), np.asarray(calibration["R"]), np.asarray(calibration["t"])
    )


def render_angle(
    game_dir: Path,
    video: Path,
    play_id: str,
    angle: str,
    out_path: Path,
    *,
    size: tuple[int, int] = OUT_SIZE,
    progress=None,
    views: list[View] | None = None,
    hide: tuple[str, ...] = (),
    tints: dict[str, tuple[int, int, int]] | None = None,
    label_fn=None,
    proxy=None,
) -> dict[str, Any]:
    """Tier B's angle `angle`; or, given `views` (one per frame), the image-based virtual
    views (avatars.imageview): `hide` players (a POV's own), `tints` kit colours the
    cutouts fade to at wide angles, `label_fn(canvas)` their burned-in label, `proxy`
    a `proxy(real, k1, src_size, masks, n)` that builds the posed body proxies the
    cutouts cross-fade to instead (`avatars.proxy`)."""
    gd = Path(game_dir)
    started = time.time()
    h = play(gd, play_id)
    synthetic = bool(read_highlights(gd).get("synthetic"))
    calibration = json.loads((gd / "calibration.json").read_text(encoding="utf-8"))
    plate_meta = json.loads((gd / "plate" / "plate.json").read_text(encoding="utf-8"))
    floor = cv2.imread(str(gd / "plate" / plate_meta["floor"]["file"]))
    wall = cv2.imread(str(gd / "plate" / plate_meta["backdrop"]["file"]))
    info = probe_video(video)
    src_size, fps = (info["width"], info["height"]), info["fps"]
    n = frame_count(h, fps)
    times = h["t_start"] + np.arange(n) / fps
    tracks = load_tracks(gd, *src_size)
    court = tracks.at(tracks.court, times)  # (P, F, 2)
    masks = Masks(gd, play_id)
    real = _real_view(calibration)
    mirrored = np.linalg.det(real.r) < 0
    k1 = float(calibration["dist"][0]) if calibration.get("dist") else 0.0
    focus = [tracks.index(p) for p in h.get("participants") or [] if tracks.index(p) is not None]
    centre = play_centre(court, focus, fps)
    # aim stays over the reconstructed floor (court + ~0.5 m), even when the focus players
    # walk off towards the camera between points: beyond it there is only backdrop/void
    fx0, fy0, fx1, fy1 = plate_meta["floor"]["bounds_m"]
    centre[:, 0] = np.clip(centre[:, 0], fx0 + 2.5, fx1 - 2.5)
    centre[:, 1] = np.clip(centre[:, 1], fy0 + 2.5, fy1 - 2.5)
    with np.errstate(all="ignore"):  # per-frame extent of the players on court, metres
        extent = np.nanmax(court, axis=0) - np.nanmin(court, axis=0)  # (F, 2)
    spread = float(np.nanmedian(extent.max(axis=1))) if np.isfinite(extent).any() else 10.0
    if views is None:
        views = camera_path(angle, real, src_size, centre, spread, size)
    fl = plate_meta["floor"]
    x0, _, _, y1 = fl["bounds_m"]
    ppm = fl["px_per_m"]
    f_origin = np.array([x0 + 0.5 / ppm, y1 - 0.5 / ppm, 0.0])
    f_u, f_v = np.array([1 / ppm, 0, 0.0]), np.array([0, -1 / ppm, 0.0])
    bd = plate_meta["backdrop"]
    bppm = bd["px_per_m"]
    along = np.asarray(bd["along"], np.float64)
    b_origin = (
        np.asarray(bd["origin_m"], np.float64)
        + along * 0.5 / bppm
        + EZ * (bd["height_m"] - 0.5 / bppm)
    )
    b_u, b_v = along / bppm, -EZ / bppm
    rims, baselines, net = [], (0.0, 0.0), None
    shot_ball = None
    try:
        from courtcam.calibrate import height_landmarks
        from courtcam.profiles import load_profile

        tpl = load_profile(calibration["sport"]).template(calibration.get("variant"))
        rims = [tuple(r) for r in (tpl.rims or ([tpl.rim] if tpl.rim else []))]
        baselines = (float(tpl.polygon[:, 1].min()), float(tpl.polygon[:, 1].max()))
        hl = height_landmarks(tpl)
        if "net_top_l" in hl and "net_top_r" in hl:
            net = [hl["net_top_l"], hl["net_top_r"]]
    except Exception:  # noqa: BLE001 - unknown sport: no hoops / net
        rims = []
    if h.get("shot") and rims:
        s = h["shot"]
        i = tracks.index(s["player_id"])
        rel = tracks.at(tracks.court, np.array([s["t_release"]]))[i, 0] if i is not None else None
        if rel is not None and np.isfinite(rel).all():
            rim = min(rims, key=lambda r: np.hypot(r[0] - rel[0], r[1] - rel[1]))
            shot_ball = ball_track(s, rel, np.asarray(rim), times)
    billboard = Billboard(real, k1, src_size)
    feet = {pid: court[i] for i, pid in enumerate(tracks.ids)}
    bodies = proxy(real, k1, src_size, masks, n, feet) if proxy is not None else None
    room = room_planes(floor, wall, plate_meta) if tints is not None else []
    if room:
        from .scene import _plates  # (scene imports this module)

        calib = json.loads((gd / "calib.json").read_text(encoding="utf-8"))
        (_, bgra_b), (_, bgra_f) = _plates(gd, calib, calibration, False)
        floor, wall = fill_unseen(floor, wall, room, bgra_f[..., 3], bgra_b[..., 3])
    proc = open_encoder(Path(out_path), size, fps)
    assert proc.stdin is not None
    drawn = 0
    try:
        for f, (_, frame) in enumerate(read_window(video, h["t_start"], n)):
            view = views[min(f, len(views) - 1)]  # (a scene doc's frame count may round 1 short)
            canvas = background(size)
            if room:  # above the stand-in walls: their top colour, dimmed (no black void)
                canvas[:] = (room[1][0][0, 0] * 0.6).astype(np.uint8)
            draw_room(canvas, view, room)
            draw_plane(canvas, wall, view, b_origin, b_u, b_v)
            draw_plane(canvas, floor, view, f_origin, f_u, f_v)
            people = []
            for p, pid in enumerate(tracks.ids):
                if not np.isfinite(court[p, f, 0]) or pid in hide:
                    continue
                m = masks.get(pid, f)
                if m is None:
                    continue
                foot = np.array([court[p, f, 0], court[p, f, 1], 0.0])
                people.append((float(view.depth(foot + 0.9 * EZ)[0]), foot, m, pid))
            for _, foot, _, _ in people:
                draw_shadow(canvas, view, foot)
            if rims:
                draw_hoops(canvas, view, rims, baselines)
            # painter's order; the net goes between the far-side and near-side players
            net_d = float(view.depth(np.mean(net, axis=0, keepdims=True))[0]) if net else -1.0
            people.sort(key=lambda q: -q[0])
            for i, (d, foot, (xy0, m), pid) in enumerate(people):
                if net and d <= net_d and (i == 0 or people[i - 1][0] > net_d):
                    draw_net(canvas, view, net)
                tint = None if tints is None else tints.get(pid, (150, 150, 150))
                if bodies is not None:  # the cutout fades into its posed, textured proxy
                    th = abs(turn(real, view, foot))
                    w = float(np.clip((PROXY_NONE - th) / (PROXY_NONE - PROXY_FULL), 0, 1))
                    near = float(np.clip((d - 1.2) / NEAR_FADE_M, 0, 1))
                    if w < 1 and near > 0 and bodies.draw(canvas, view, f, frame, pid, masks,
                                                          near):  # fmt: skip
                        if w > 0:
                            billboard.draw(canvas, view, frame, foot, xy0, m, None, w * near)
                        continue
                billboard.draw(canvas, view, frame, foot, xy0, m, tint)
            if net and (not people or people[-1][0] > net_d):
                draw_net(canvas, view, net)
            drawn += len(people)
            if shot_ball is not None:
                draw_ball(canvas, view, shot_ball[max(0, f - 8) : f + 1])
            if mirrored:  # the clicks were labelled mirror-wise: show it as the camera saw it
                canvas = cv2.flip(canvas, 1)
            if label_fn:
                label_fn(canvas)
            else:
                label(canvas, angle, synthetic)
            proc.stdin.write(np.ascontiguousarray(canvas).tobytes())
            if progress:
                progress((f + 1) / n)
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed writing {out_path}")
    return {
        "angle": angle,
        "frames": n,
        "billboards": drawn,
        "ball": shot_ball is not None,
        "wall_s": round(time.time() - started, 2),
        "ms_per_frame": round(1000 * (time.time() - started) / max(1, n), 1),
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Tier B 2.5D replay angle")
    ap.add_argument("game_dir", type=Path)
    ap.add_argument("play_id")
    ap.add_argument("angle")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    out = a.out or a.game_dir / "replays" / a.play_id / f"{a.angle}.mp4"
    print(
        json.dumps(
            render_angle(a.game_dir, a.game_dir / "media" / "wide.mp4", a.play_id, a.angle, out)
        )
    )


if __name__ == "__main__":
    main()
