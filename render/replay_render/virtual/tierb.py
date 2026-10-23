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
BALL_MIN_M = 3.0  # the ball is not drawn nearer the camera than this
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


def draw_shadow(canvas: np.ndarray, view: View, foot: np.ndarray, strength: float = 1.0) -> None:
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
    a = (m.astype(np.float32) / 255.0 * 0.45 * strength)[..., None]
    roi = canvas[y0:y1, x0:x1]
    roi[:] = (roi * (1 - a)).astype(np.uint8)


def draw_hoops(
    canvas: np.ndarray, view: View, rims: list, baseline_ys: tuple[float, float]
) -> None:
    """Rim ring at 3.05 m with a white net under it, and a translucent backboard 0.375 m
    behind it (FIBA). No support: how a hoop is held up (wall, stanchion) is not known."""
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
        low = np.column_stack([rx + 0.13 * np.cos(ang), ry + 0.13 * np.sin(ang),
                               np.full_like(ang, RIM_HEIGHT_M - 0.42)])  # fmt: skip
        if (view.depth(np.vstack([ring, low])) > NEAR_M).all():  # the net: 12 cords
            top, bot = view.project(ring), view.project(low)
            for j in range(0, 32, 3):
                a, b = np.round(top[j]).astype(int), np.round(bot[(j + 2) % 31]).astype(int)
                cv2.line(canvas, tuple(a), tuple(b), (225, 225, 225), 1, cv2.LINE_AA)
            cv2.polylines(canvas, [np.round(bot).astype(np.int32)], False, (225, 225, 225), 1,
                          cv2.LINE_AA)  # fmt: skip
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
    """The modelled shot ball at its true size, with a short fading trail. Positions
    nearer the camera than `BALL_MIN_M` are left out (a virtual camera beside the rim
    would fill the frame with a disc), as is the whole ball once its last one is."""
    pts = np.asarray([p for p in trail if np.isfinite(p).all()]).reshape(-1, 3)
    if not len(pts) or view.depth(pts[-1:])[0] < BALL_MIN_M:
        return
    pts = pts[view.depth(pts) >= BALL_MIN_M]
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
# with a body proxy the cutout keeps its real pixels to 45° (it reads better than the
# proxy there) and hands over by 55°, where it would turn into a silhouette (the two
# bodies can stand ~0.3 m apart, so they ghost while both show: hence quickly)
PROXY_FULL, PROXY_NONE = np.radians(45), np.radians(55)
# image-based cutouts fade in from 0.5 m to 1 m from the camera: a POV's defender at
# arm's length stays solid (fading them from 3 m made people vanish whenever they came
# close; `POV_MAX_H` keeps them from filling the frame); fixed cameras do not show
# anyone that near at all (`render_angle(near_m=)`)
NEAR_IN_M, NEAR_FADE_M = 0.5, 0.5
GAP_S = 2.0  # a person lost for up to this long (or picked up by another id) is bridged
SPRINT_MS = 7.0  # ... if the gap could be crossed at a sprint (+1 m of box jitter)
FADE_S = 0.3  # a person who appears / is lost for good fades in / out over this


def near_alpha(d: float) -> float:
    return float(np.clip((d - NEAR_IN_M) / NEAR_FADE_M, 0.0, 1.0))


def bridge(court: np.ndarray, fps: float):
    """Keep people present through a window's track gaps and id hand-overs.

    `court` (P, F, 2) is NaN where a track is absent. A run of frames that ends before the
    window does is linked to a run that starts within `GAP_S` after it, near enough to be
    the same person (the same id after a short loss, or the next id the tracker gave
    them), shortest gaps first. Returns `pos` (P, F, 2) with each linked gap filled along
    a straight line (drawn as the run that ended: their last cutout, held), `alpha`
    (P, F) with a `FADE_S` fade-in where a run starts unlinked and a fade-out (held in
    place) where one ends unlinked, and `links` [(p_from, p_to)]."""
    n_p, n_f = court.shape[:2]
    ok = np.isfinite(court[..., 0])
    runs = []
    for p in range(n_p):
        d = np.diff(np.r_[0, ok[p].astype(np.int8), 0])
        runs += [(p, s, e - 1) for s, e in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1),
                                                strict=True)]  # fmt: skip
    gap = round(GAP_S * fps)
    cands = []
    for a in runs:
        for b in runs:
            g = b[1] - a[2]
            if a[2] >= n_f - 1 or b[1] == 0 or not 0 < g <= gap:
                continue
            dist = float(np.linalg.norm(court[b[0], b[1]] - court[a[0], a[2]]))
            if dist <= 1.0 + SPRINT_MS * g / fps:
                cands.append((g / fps + dist / SPRINT_MS, a, b))
    pos, alpha = court.copy(), ok.astype(np.float32)
    ended, started, links = set(), set(), []
    for _, a, b in sorted(cands, key=lambda c: c[0]):
        if a in ended or b in started:
            continue
        ended.add(a)
        started.add(b)
        links.append((a[0], b[0]))
        k = np.arange(a[2] + 1, b[1])
        free = k[~np.isfinite(pos[a[0], k, 0])]
        u = ((free - a[2]) / (b[1] - a[2]))[:, None]
        pos[a[0], free] = court[a[0], a[2]] * (1 - u) + court[b[0], b[1]] * u
        alpha[a[0], free] = 1.0
    fade = max(1, round(FADE_S * fps))
    ramp = (np.arange(fade) + 1) / (fade + 1)
    for p, s, e in runs:
        if s > 0 and (p, s, e) not in started:
            k = min(fade, e - s + 1)
            alpha[p, s : s + k] *= ramp[:k]
        if e < n_f - 1 and (p, s, e) not in ended:
            k = np.arange(e + 1, min(n_f, e + 1 + fade))
            k = k[~np.isfinite(pos[p, k, 0])]
            pos[p, k] = court[p, e]
            alpha[p, k] = ramp[::-1][: len(k)]
    return pos, alpha, links


def chain(links: list[tuple[int, int]], seeds) -> set[int]:
    """Every track index linked (either way, transitively) to one of `seeds`."""
    out, todo = set(seeds), list(seeds)
    while todo:
        q = todo.pop()
        for a, b in links:
            for x, y in ((a, b), (b, a)):
                if x == q and y not in out:
                    out.add(y)
                    todo.append(y)
    return out


# a player's view: real pixels at every angle (mirrored past 90°). Everyone faces the
# eye on their billboard; a one-colour silhouette read as a blob or a mannequin, while
# their real pixels (the side the camera saw) still read as that person
POV_SEEN = (np.pi, 2 * np.pi)
POV_MAX_H = 0.6  # nobody stands taller than 60 % of a POV frame


def seen_weight(th: float, seen=(SEEN_FULL, SEEN_NONE)) -> float:
    """How much of a cutout's real pixels to show when the virtual line of sight is `th`
    radians (horizontal) from the real camera's: all up to 35°, none past 75°."""
    full, none = seen
    return float(np.clip((none - abs(th)) / (none - full), 0.0, 1.0))


def turn(real: View, view: View, foot: np.ndarray) -> float:
    """Signed horizontal angle (rad) at `foot` from the real line of sight to the
    virtual one."""
    dr, dv = (foot - real.centre)[:2], (foot - view.centre)[:2]
    return float(np.arctan2(dr[0] * dv[1] - dr[1] * dv[0], dr @ dv))


BG_DIFF, BG_MIN_FG = 25, 0.45
CUT_EDGE = 0.3  # a mask down a crop side for this share of its rows was cut off there
SLIVER = 0.15  # a mask narrower than this x its height is a sliver (1 % of real masks)


def bad_cutout(crop: np.ndarray, mask: np.ndarray, clean, x0: int, y0: int) -> bool:
    """A SAM mask not to draw (the person's last good cutout stands in, `bridge`):
    * cut off by its crop window: it runs down the window's left or right side (the
      player left the window; up close it was a tall dark sliver);
    * a sliver: narrower than SLIVER x its height (half a player behind another);
    * mostly backdrop: under half of it differs from the empty court there (`clean`,
      the plate's source-pixel median, `courtcam.plate`), it leaked onto the wall
      (dark kits against a dark wall). Only a test: cutting the mask would punch holes
      in dark kits."""
    m = mask[: crop.shape[0], : crop.shape[1]]
    rows = max(1, int(m.any(axis=1).sum()))
    if max(m[:, 0].sum(), m[:, -1].sum()) > CUT_EDGE * rows:
        return True
    xs, ys = np.flatnonzero(m.any(axis=0)), np.flatnonzero(m.any(axis=1))
    if len(xs) and (xs[-1] - xs[0] + 1) < SLIVER * (ys[-1] - ys[0] + 1):
        return True
    bg = clean[y0 : y0 + crop.shape[0], x0 : x0 + crop.shape[1]] if clean is not None else None
    if bg is None or bg.shape != crop.shape:
        return False
    fg = np.abs(crop.astype(np.int16) - bg).max(axis=2) > BG_DIFF
    fg = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return bool(m.any()) and float(fg[m].mean()) < BG_MIN_FG


def kit_colour(crop: np.ndarray, mask: np.ndarray, fallback=None) -> tuple[int, int, int]:
    """BGR shirt colour of a cutout: the median of its own pixels over the torso (20-50 %
    down its mask), so a silhouette is never a skin tone; else `fallback` / grey."""
    m = mask[: crop.shape[0], : crop.shape[1]]
    ys = np.flatnonzero(m.any(axis=1))
    if len(ys):
        y0, y1 = ys[0], ys[-1] + 1
        band = slice(y0 + (y1 - y0) // 5, y0 + (y1 - y0) // 2 + 1)
        px = crop[band][m[band]]
        if len(px):
            return tuple(int(c) for c in np.median(px, axis=0))
    return tuple(fallback) if fallback is not None else (150, 150, 150)


def _silhouette(rgb: np.ndarray, tint, w: float) -> np.ndarray:
    """The crop blended toward a flat kit colour shaded by its own light (folds, arms and
    legs stay readable): weight `w` of the real pixels."""
    g = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY).astype(np.float32)
    # the light, not the pixel noise (magnified up close, noise reads as blocks)
    g = cv2.GaussianBlur(g, (0, 0), max(1.0, rgb.shape[0] / 60))
    shade = (0.55 + 0.45 * g / max(float(g.mean()), 1.0))[..., None]
    flat = np.clip(np.asarray(tint, np.float32) * shade, 0, 255)
    return (rgb.astype(np.float32) * w + flat * (1 - w)).astype(np.uint8)


class Billboard:
    """Player cutout -> virtual image through the plane at the foot point."""

    def __init__(self, real: View, k1: float, src_size: tuple[int, int],
                 seen=(SEEN_FULL, SEEN_NONE), max_h: float | None = None) -> None:  # fmt: skip
        """`max_h`: the tallest a cutout may stand on screen, as a share of the frame
        height; a nearer one is drawn further back along its line of sight (a POV's
        `POV_MAX_H`: someone at arm's length is not a full-frame smear)."""
        self.real, self.k1, self.src_size, self.seen = real, k1, src_size, seen
        self.max_h = max_h

    def _axis(self, cam: np.ndarray, foot: np.ndarray) -> np.ndarray:
        d = foot - cam
        a = np.cross(EZ, d)
        a[2] = 0
        return a / np.linalg.norm(a)

    def draw(self, canvas, view: View, frame, foot: np.ndarray, xy0, mask: np.ndarray,
             tint=None, fade: float = 1.0, src_foot=None, at=(0, 0)) -> None:  # fmt: skip
        """`tint`: None (the real pixels), or a BGR kit colour the cutout fades to as the
        virtual line of sight turns away from the real one (`seen_weight`): past ~45° a
        flat cutout reads wrong, so it becomes a kit-coloured, shaded silhouette of the
        same shape, mirrored once seen from behind. Never stretched garbage. With a tint
        a cutout also fades out closer than `NEAR_IN_M` + `NEAR_FADE_M` (a POV brushing
        past someone). `fade` scales its opacity (over a body proxy, `avatars.proxy`).
        A held cutout (`bridge`): `frame` is its crop, whose top-left is source pixel
        `at`, seen with the player standing at `src_foot`; it is drawn at `foot`."""
        src_foot = foot if src_foot is None else src_foot
        a_r = self._axis(self.real.centre, src_foot)
        dist = float(view.depth(foot + 0.9 * EZ)[0])
        if dist < max(NEAR_IN_M, NEAR_M):
            return
        opacity = fade * (1.0 if tint is None else near_alpha(dist))
        if opacity <= 0:
            return
        g_real = plane_homography(self.real.p, src_foot, a_r, EZ)
        ys, xs = np.nonzero(mask)
        mx0, my0, mx1, my1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        pad = 3
        mx0, my0 = max(0, mx0 - pad), max(0, my0 - pad)
        mx1, my1 = min(mask.shape[1], mx1 + pad), min(mask.shape[0], my1 + pad)
        ox, oy = xy0[0] + mx0, xy0[1] + my0
        lx, ly = ox - at[0], oy - at[1]
        rgb = frame[ly : ly + (my1 - my0), lx : lx + (mx1 - mx0)]
        m = mask[my0:my1, mx0:mx1][: rgb.shape[0], : rgb.shape[1]]
        cw, ch = rgb.shape[1], rgb.shape[0]
        if cw < 2 or ch < 2:
            return
        corners = np.array([[0, 0], [cw, 0], [cw, ch], [0, ch]], np.float64)
        src = corners + [ox, oy]
        und = distortion.undistort_points(src, self.k1, self.src_size)
        h_crop = cv2.getPerspectiveTransform(corners.astype(np.float32), und.astype(np.float32))
        to_plane = np.linalg.inv(g_real) @ h_crop

        def place(at_foot: np.ndarray):
            th = turn(self.real, view, at_foot)
            c, s = np.cos(th), np.sin(th)
            a_v = np.array([c * a_r[0] - s * a_r[1], s * a_r[0] + c * a_r[1], 0.0])
            total = plane_homography(view.p, at_foot, a_v, EZ) @ to_plane
            return th, total, cv2.perspectiveTransform(corners.reshape(-1, 1, 2),
                                                       total).reshape(-1, 2)  # fmt: skip

        th, total, dst = place(foot)
        tall = float(np.ptp(dst[:, 1])) / canvas.shape[0]
        if self.max_h and tall > self.max_h:  # too near: stand them back along the view ray
            eye = np.r_[view.centre[:2], 0.0]
            th, total, dst = place(eye + (foot - eye) * tall / self.max_h)
        lo, hi = np.floor(dst.min(0)).astype(int), np.ceil(dst.max(0)).astype(int)
        x0, y0 = max(0, lo[0]), max(0, lo[1])
        x1, y1 = min(canvas.shape[1], hi[0]), min(canvas.shape[0], hi[1])
        if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) > canvas.size:
            return
        if tint is not None:
            w = seen_weight(th, self.seen)
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
    names = {"orbit": "Orbit", "push_in": "Push-in", "broadcast_high": "Broadcast high"}
    h, w = canvas.shape[:2]
    s = w / 1280.0  # designed at 1280x720, scaled to the output
    font, small = cv2.FONT_HERSHEY_DUPLEX, cv2.FONT_HERSHEY_SIMPLEX
    # plain words, as the TV badge says it (no tier letters): synthetic stays identifiable
    head = f"VIRTUAL REPLAY  |  {names.get(angle, angle.replace('_', ' ').capitalize())}"
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
    near_m: float = 0.0,
    seen: tuple[float, float] = (SEEN_FULL, SEEN_NONE),
    max_h: float | None = None,
) -> dict[str, Any]:
    """Tier B's angle `angle`; or, given `views` (one per frame, or a function
    `views(pos, own)` of the bridged court positions (P, F, 2) and the track indices of
    the `hide` players with every id `bridge` linked to them), the image-based virtual
    views (avatars.imageview): `hide` players (a POV's own, under all their ids),
    `tints` kit colours the cutouts fade to at wide angles, `label_fn(canvas)` their
    burned-in label, `proxy` a `proxy(real, k1, src_size, masks, n)` that builds the
    posed body proxies the cutouts cross-fade to instead (`avatars.proxy`). People
    nearer the camera than `near_m` are not drawn; they fade in over the next metre.
    People stay on through short track gaps and id hand-overs (`bridge`). `seen`: the
    angles (rad) from the real camera up to which / past which a cutout shows its real
    pixels (`seen_weight`; a POV's `POV_SEEN`), `max_h` the on-screen height cap
    (`Billboard`)."""
    gd = Path(game_dir)
    started = time.time()
    h = play(gd, play_id)
    synthetic = bool(read_highlights(gd).get("synthetic"))
    calibration = json.loads((gd / "calibration.json").read_text(encoding="utf-8"))
    plate_meta = json.loads((gd / "plate" / "plate.json").read_text(encoding="utf-8"))
    floor = cv2.imread(str(gd / "plate" / plate_meta["floor"]["file"]))
    wall = cv2.imread(str(gd / "plate" / plate_meta["backdrop"]["file"]))
    clean = cv2.imread(str(gd / "plate" / "plate.jpg"))  # the empty court, source pixels
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
    pos, alpha, links = bridge(court, fps)
    own = chain(links, [i for p in hide if (i := tracks.index(p)) is not None])
    if views is None:
        views = camera_path(angle, real, src_size, centre, spread, size)
    elif callable(views):
        views = views(pos, sorted(own))
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
    billboard = Billboard(real, k1, src_size, seen, max_h)
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
    held: dict[str, tuple] = {}  # pid -> (crop, its source origin, mask, foot) last seen
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
                foot = np.array([pos[p, f, 0], pos[p, f, 1], 0.0])
                m = masks.get(pid, f) if np.isfinite(court[p, f, 0]) else None
                if m is not None:
                    (x0, y0), mk = m
                    crop = frame[y0 : y0 + mk.shape[0], x0 : x0 + mk.shape[1]]
                    if masks.held(pid, f) or bad_cutout(crop, mk, clean, x0, y0):
                        m = None  # carried, cut off, a sliver or on the wall: last good one
                    else:  # keep their cutout: it stands in while they are lost
                        held[pid] = (crop.copy(), (x0, y0), mk, foot)
                if not np.isfinite(foot[0]) or p in own or alpha[p, f] <= 0 or pid not in held:
                    continue
                d = float(view.depth(foot + 0.9 * EZ)[0])
                if d > near_m:  # (and their shadow)
                    people.append((d, foot, m is not None, pid, float(alpha[p, f])))
            for d, foot, _, _, a in people:  # (not under the eye: a dark smear)
                draw_shadow(canvas, view, foot, a * float(np.clip(d - 1.0, 0, 1)))
            if rims:
                draw_hoops(canvas, view, rims, baselines)
            # painter's order; the net goes between the far-side and near-side players
            net_d = float(view.depth(np.mean(net, axis=0, keepdims=True))[0]) if net else -1.0
            people.sort(key=lambda q: -q[0])
            for i, (d, foot, live, pid, a) in enumerate(people):
                if net and d <= net_d and (i == 0 or people[i - 1][0] > net_d):
                    draw_net(canvas, view, net)
                vis = a * (float(np.clip(d - near_m, 0, 1)) if near_m else 1.0)
                crop, at, m, src_foot = held[pid]
                tint = None if tints is None else kit_colour(crop, m, tints.get(pid))
                if live and bodies is not None:  # the cutout fades into its posed proxy
                    th = abs(turn(real, view, foot))
                    w = float(np.clip((PROXY_NONE - th) / (PROXY_NONE - PROXY_FULL), 0, 1))
                    near = near_alpha(d) * vis
                    if w < 1 and near > 0 and bodies.draw(canvas, view, f, frame, pid, masks,
                                                          near):  # fmt: skip
                        if w > 0:
                            billboard.draw(canvas, view, crop, foot, at, m, None, w * near,
                                           src_foot, at)  # fmt: skip
                        continue
                billboard.draw(canvas, view, crop, foot, at, m, tint, vis, src_foot, at)
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
