"""Tier C renderer: stylized capsule avatars on a geometric court, from any angle.

No GL: a painter's-algorithm rasteriser on OpenCV (measured on the box, see README).
The floor is one textured plane (the court drawn from the sport template's lines,
`tierb.draw_plane`); players are capsules (torso, limbs) and spheres (head, hands,
shoes) shaded as cylinders (dark rim, base, light stripe toward the key light), sorted
far-to-near together with the hoop (backboard, rim, net, stanchion) or the net (net
sports: posts, mesh and tape at the template's `net_height_m`) and the ball.
Players wear their team colour (torso, shoulders, shorts); limbs and heads are a
neutral mannequin grey. Every frame is labelled "TIER C · 3D reconstruction — stylized".

Angles (all eased, no jitter; time-aligned with the Tier A/B angles of the play):
`broadcast_high` (elevated, the real camera's side), `reverse` (the opposite sideline),
`baseline` (behind the target basket; net sports: behind the focus player's baseline),
`overhead` (top-down, descending), `pov_<pid>` (from the shooter's eyes, turning to the
rim before the release; net sports: looking across the net).
"""

from __future__ import annotations

import time
import warnings
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from courtcam.calibrate import height_landmarks
from courtcam.profiles import load_profile
from courtcam.render import open_encoder

from ..camera import ease
from ..graphics import distinct_team_colors
from ..virtual.tierb import (
    NEAR_M,
    View,
    _smooth,
    background,
    draw_plane,
    draw_shadow,
    look_at,
)
from .scene import joints_array
from .skeleton import (
    ANKLES,
    HEAD,
    NOSE,
    PELVIS,
    WRISTS,
)

OUT_SIZE = (1280, 720)
ANGLES = ("broadcast_high", "baseline", "overhead", "reverse")
NAMES = {"broadcast_high": "BROADCAST HIGH", "baseline": "BASELINE", "overhead": "OVERHEAD",
         "reverse": "REVERSE", "pov": "SHOOTER'S POV"}  # fmt: skip
PX_PER_M = 50
FLOOR, APRON, PAINT, LINE = (96, 146, 196), (54, 60, 70), (70, 105, 160), (240, 240, 240)
GREY = (205, 200, 196)
SHOE = (40, 40, 44)
RIM_R = 0.225
LIGHT = np.array([-0.5, -0.8])  # screen-space direction the light comes from (up-left)

# (parent, child, radius m, part) — part: "team" jersey, "shorts", "limb" mannequin grey
CAPSULES = (
    (0, 8, 0.15, "team"), (8, 11, 0.07, "team"), (8, 14, 0.07, "team"),
    (0, 1, 0.11, "shorts"), (0, 4, 0.11, "shorts"),
    (1, 2, 0.075, "shorts"), (4, 5, 0.075, "shorts"),
    (2, 3, 0.055, "limb"), (5, 6, 0.055, "limb"),
    (11, 12, 0.05, "limb"), (14, 15, 0.05, "limb"),
    (12, 13, 0.042, "limb"), (15, 16, 0.042, "limb"),
    (8, 9, 0.05, "limb"),
)  # fmt: skip


def _tone(c, k: float) -> tuple[int, int, int]:
    return tuple(int(np.clip(v * k, 0, 255)) for v in c)


def team_colors(doc: dict) -> list[tuple[int, int, int]]:
    """BGR per player: the broadcast package's two legible, distinct team colours
    (graphics.distinct_team_colors); grey for a player without a team."""
    first = {}
    for p in doc["players"]:
        first.setdefault(p.get("team"), p.get("color") or "#888888")
    pair = distinct_team_colors([first.get(0, "#C0392B"), first.get(1, "#2E86C1")])
    out = []
    for p in doc["players"]:
        rgb = pair[p["team"]] if p.get("team") in (0, 1) else (150, 150, 150)
        out.append(tuple(int(v) for v in rgb[::-1]))
    return out


# --- the court -------------------------------------------------------------------------


def court_texture(sport: str, variant: str | None, margin: float = 2.5):
    """Top-down court image from the template, and its world origin / axes for
    `draw_plane` (pixel (u, v) at origin + u ax_u + v ax_v)."""
    tpl = load_profile(sport).template(variant)
    poly = tpl.polygon
    x0, y0 = poly.min(axis=0) - margin
    x1, y1 = poly.max(axis=0) + margin
    w, h = int((x1 - x0) * PX_PER_M), int((y1 - y0) * PX_PER_M)
    img = np.empty((h, w, 3), np.uint8)
    img[:] = APRON

    def px(pts) -> np.ndarray:
        p = np.asarray(pts, np.float64)
        return np.round(np.column_stack([(p[:, 0] - x0), (y1 - p[:, 1])]) * PX_PER_M * 16).astype(
            np.int32
        )

    cv2.fillPoly(img, [px(poly)], FLOOR, cv2.LINE_AA, 4)
    lw = max(2, round(0.05 * PX_PER_M))
    for name, pts in (tpl.features or {}).items():
        if name.startswith("paint"):
            cv2.fillPoly(img, [px(pts)], PAINT, cv2.LINE_AA, 4)
    for name, pts in (tpl.features or {}).items():
        closed = name.startswith("paint")
        cv2.polylines(img, [px(pts)], closed, LINE, lw, cv2.LINE_AA, 4)
    cv2.polylines(img, [px(poly)], True, LINE, lw, cv2.LINE_AA, 4)
    if tpl.net_y is not None:
        cv2.polylines(img, [px([[x0 + margin, tpl.net_y], [x1 - margin, tpl.net_y]])], False,
                      LINE, lw, cv2.LINE_AA, 4)  # fmt: skip
    origin = np.array([x0 + 0.5 / PX_PER_M, y1 - 0.5 / PX_PER_M, 0.0])
    return img, origin, np.array([1 / PX_PER_M, 0, 0.0]), np.array([0, -1 / PX_PER_M, 0.0]), tpl


# --- primitives ------------------------------------------------------------------------


def _capsule(canvas, view: View, a, b, r: float, color) -> None:
    pa, pb = view.project(np.array([a, b]))
    da, db = view.depth(np.array([a, b]))
    f = view.k[0, 0]
    rp = f * r * 0.5 * (1 / da + 1 / db)
    if not np.isfinite(rp) or rp > canvas.shape[0]:
        return
    s = 16
    p1, p2 = tuple(np.round(pa * s).astype(int)), tuple(np.round(pb * s).astype(int))
    t = max(1, round(2 * rp))
    cv2.line(canvas, p1, p2, _tone(color, 0.45), t + 2, cv2.LINE_AA, 4)
    cv2.line(canvas, p1, p2, color, t, cv2.LINE_AA, 4)
    if rp >= 2.0:  # cylinder highlight: a lighter stripe offset toward the light
        d = pb - pa
        nrm = np.array([-d[1], d[0]]) / max(np.linalg.norm(d), 1e-6)
        if nrm @ LIGHT < 0:
            nrm = -nrm
        off = nrm * rp * 0.35
        q1 = tuple(np.round((pa + off) * s).astype(int))
        q2 = tuple(np.round((pb + off) * s).astype(int))
        cv2.line(canvas, q1, q2, _tone(color, 1.25), max(1, round(rp * 0.6)), cv2.LINE_AA, 4)


def _sphere(canvas, view: View, c, r: float, color) -> None:
    p = view.project(np.asarray(c)[None])[0]
    rp = view.k[0, 0] * r / view.depth(np.asarray(c)[None])[0]
    if not np.isfinite(rp) or rp > canvas.shape[0]:
        return
    s = 16
    q = tuple(np.round(p * s).astype(int))
    cv2.circle(canvas, q, round((rp + 1) * s), _tone(color, 0.45), -1, cv2.LINE_AA, 4)
    cv2.circle(canvas, q, round(rp * s), color, -1, cv2.LINE_AA, 4)
    if rp >= 2.5:
        hl = tuple(np.round((p + LIGHT / np.linalg.norm(LIGHT) * rp * 0.35) * s).astype(int))
        cv2.circle(canvas, hl, round(rp * 0.35 * s), _tone(color, 1.3), -1, cv2.LINE_AA, 4)


def player_prims(j: np.ndarray, color, view: View) -> list:
    """(depth, draw) for one player's capsules and spheres at one frame."""
    out = []
    team, shorts = color, _tone(color, 0.7)
    parts = {"team": team, "shorts": shorts, "limb": GREY}
    for a, b, r, part in CAPSULES:
        pa, pb = j[a], j[b]
        if (view.depth(np.array([pa, pb])) < NEAR_M).any():
            continue
        dep = float(view.depth(((pa + pb) / 2)[None])[0])
        out.append(
            (dep, lambda c, pa=pa, pb=pb, r=r, col=parts[part]: _capsule(c, view, pa, pb, r, col))
        )
    spheres = [((j[NOSE] + j[HEAD]) / 2 + [0, 0, 0.03], 0.115, GREY)]
    spheres += [(j[w] + (j[w] - j[w - 1]) * 0.25, 0.045, GREY) for w in WRISTS]
    spheres += [(j[a] + [0, 0, -0.03], 0.06, SHOE) for a in ANKLES]
    for c, r, col in spheres:
        d = float(view.depth(c[None])[0])
        if d > NEAR_M + r:
            out.append((d, lambda cv, c=c, r=r, col=col: _sphere(cv, view, c, r, col)))
    return out


def _seg3d(canvas, view: View, a, b, color, width: int = 1) -> None:
    pts = np.array([a, b])
    if (view.depth(pts) < NEAR_M).any():
        return
    p = np.round(view.project(pts) * 16).astype(int)
    cv2.line(canvas, tuple(p[0]), tuple(p[1]), color, width, cv2.LINE_AA, 4)


def hoop_prims(rim, baseline_y: float, view: View) -> list:
    """Backboard, rim, net and stanchion of one basket as depth-sorted primitives."""
    rx, ry = rim
    back = np.sign(baseline_y - ry) or 1.0
    by = ry + back * 0.375
    z = 3.05
    board = np.array(
        [[rx - 0.9, by, 2.9], [rx + 0.9, by, 2.9], [rx + 0.9, by, 3.95], [rx - 0.9, by, 3.95]]
    )
    ang = np.linspace(0, 2 * np.pi, 33)
    ring = np.column_stack([rx + RIM_R * np.cos(ang), ry + RIM_R * np.sin(ang), np.full(33, z)])
    low = np.column_stack([rx + 0.13 * np.cos(ang), ry + 0.13 * np.sin(ang), np.full(33, z - 0.42)])

    def board_fn(c):
        if (view.depth(board) <= NEAR_M).any():
            return
        pts = np.round(view.project(board) * 16).astype(np.int32)
        over = c.copy()
        cv2.fillConvexPoly(over, pts, (235, 235, 235), cv2.LINE_AA, 4)
        cv2.addWeighted(over, 0.35, c, 0.65, 0, c)
        cv2.polylines(c, [pts], True, (250, 250, 250), 2, cv2.LINE_AA, 4)
        inner = np.array([[rx - 0.295, by, 3.0], [rx + 0.295, by, 3.0], [rx + 0.295, by, 3.45],
                          [rx - 0.295, by, 3.45]])  # fmt: skip
        cv2.polylines(c, [np.round(view.project(inner) * 16).astype(np.int32)], True,
                      (250, 250, 250), 2, cv2.LINE_AA, 4)  # fmt: skip
        # stanchion: arm from the board back over the baseline, pole down to the floor
        top = np.array([rx, by + back * 0.05, 3.2])
        foot = np.array([rx, by + back * 1.6, 3.2])
        _seg3d(c, view, top, foot, (70, 70, 80), 6)
        _seg3d(c, view, foot, foot * [1, 1, 0], (70, 70, 80), 8)

    def rim_fn(c):
        if (view.depth(ring) <= NEAR_M).any():
            return
        for k in range(0, 32, 2):  # net: lines from the rim to a smaller ring below
            _seg3d(c, view, ring[k], low[(k + 1) % 32], (235, 235, 235), 1)
            _seg3d(c, view, ring[k + 1], low[k], (235, 235, 235), 1)
        cv2.polylines(c, [np.round(view.project(ring) * 16).astype(np.int32)], False,
                      (0, 90, 255), 3, cv2.LINE_AA, 4)  # fmt: skip

    dep_b = float(view.depth(board.mean(axis=0)[None])[0])
    dep_r = float(view.depth(np.array([[rx, ry, z]]))[0])
    return [(dep_b, board_fn), (dep_r, rim_fn)]


def net_prims(left, right, view: View) -> list:
    """Net between two post tops (x, y, net height): posts, see-through mesh, white tape.
    ponytail: one sort depth (the middle) for the whole net; a player right at the net
    on the far half can be drawn in front of it. Split into segments if that shows."""
    a, b = np.asarray(left, float), np.asarray(right, float)
    h = a[2]
    quad = np.array([[*a[:2], 0.12], [*b[:2], 0.12], b, a])

    def fn(c):
        if (view.depth(quad) <= NEAR_M).any():
            return
        over = c.copy()
        cv2.fillConvexPoly(over, np.round(view.project(quad) * 16).astype(np.int32),
                           (40, 40, 40), cv2.LINE_AA, 4)  # fmt: skip
        cv2.addWeighted(over, 0.45, c, 0.55, 0, c)
        for u in np.linspace(0, 1, 25)[1:-1]:  # mesh
            p = a + (b - a) * u
            _seg3d(c, view, [*p[:2], 0.12], p, (90, 90, 90), 1)
        for p in (a, b):
            _seg3d(c, view, [*p[:2], 0.0], [*p[:2], h + 0.03], (60, 60, 70), 5)
        _seg3d(c, view, a, b, (245, 245, 245), 3)

    return [(float(view.depth(((a + b) / 2)[None])[0]), fn)]


def ball_prims(ball: np.ndarray, f: int, view: View) -> list:
    p = ball[f]
    if not np.isfinite(p).all() or view.depth(p[None])[0] < NEAR_M + 0.2:
        return []
    trail = [q for q in ball[max(0, f - 8) : f + 1] if np.isfinite(q).all()]

    def fn(c):
        tr = np.asarray(trail)
        if len(tr) > 1 and (view.depth(tr) > NEAR_M).all():
            px = view.project(tr)
            for k in range(1, len(px)):
                a = k / len(px)
                cv2.line(c, tuple(np.round(px[k - 1] * 16).astype(int)),
                         tuple(np.round(px[k] * 16).astype(int)),
                         (int(60 * a), int(140 * a + 40), int(255 * a)), 2, cv2.LINE_AA, 4)  # fmt: skip
        _sphere(c, view, p, 0.12, (30, 110, 235))

    return [(float(view.depth(p[None])[0]), fn)]


# --- cameras ---------------------------------------------------------------------------


def _fill(x: np.ndarray) -> np.ndarray:
    """Interpolate NaN rows of (F, D); all-NaN stays NaN."""
    ok = np.isfinite(x).all(axis=1)
    if not ok.any():
        return x
    idx = np.arange(len(x))
    return np.column_stack([np.interp(idx, idx[ok], x[ok, d]) for d in range(x.shape[1])])


def focus_centre(joints: list[np.ndarray], focus: list[int], fps: float) -> np.ndarray:
    """(F, 3) smoothed centre of the focus players' pelvises at 1 m."""
    sel = [joints[i][:, PELVIS, :2] for i in (focus or range(len(joints)))]
    with warnings.catch_warnings():  # frames where nobody is tracked stay NaN
        warnings.simplefilter("ignore", RuntimeWarning)
        c = np.nanmean(np.stack(sel), axis=0)
        allc = np.nanmean(np.stack([j[:, PELVIS, :2] for j in joints]), axis=0)
    c = _fill(np.where(np.isfinite(c), c, allc))
    c = _smooth(c, 1.0 * fps)
    return np.column_stack([c, np.ones(len(c))])


def pov_player(angle: str, doc: dict) -> str:
    """Whose eyes `pov_<pid>` looks through: that player, else the shooter / primary /
    first player of the scene (the highlight's player may not be on court in 3D)."""
    ids = [p["id"] for p in doc["players"]]
    want = angle.split("_", 1)[1] if "_" in angle else None
    return next((p for p in (want, doc.get("shooter"), doc.get("primary")) if p in ids), ids[0])


def _end(tpl, y: float, far: bool) -> np.ndarray:
    """Middle of the baseline on `y`'s side of the net (or the other side, `far`)."""
    poly = tpl.polygon
    lo, hi = float(poly[:, 1].min()), float(poly[:, 1].max())
    net = tpl.net_y if tpl.net_y is not None else (lo + hi) / 2
    near = lo if y < net else hi
    return np.array([float(poly[:, 0].mean()), (lo + hi - near) if far else near])


def camera_path(angle: str, doc: dict, joints: list[np.ndarray], size=OUT_SIZE) -> list[View]:
    fps, n = doc["fps"], doc["frames"]
    ids = [p["id"] for p in doc["players"]]
    focus = [ids.index(p) for p in (doc.get("shooter"), doc.get("primary")) if p in ids][:1]
    centre = focus_centre(joints, focus, fps)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        pel = np.stack([j[:, PELVIS, :2] for j in joints])
        ext = np.nanmax(pel, axis=0) - np.nanmin(pel, axis=0)
    spread = float(np.nanmedian(ext.max(axis=1))) if np.isfinite(ext).any() else 10.0
    w = size[0]
    u = ease(np.linspace(0.0, 1.0, n))
    t0 = centre.mean(axis=0)
    cam = doc["camera"]
    real_c = -np.asarray(cam["R"]).T @ np.asarray(cam["t"])
    v = (real_c - t0)[:2]
    phi0 = float(np.arctan2(v[1], v[0]))
    rims = [np.asarray(r, float) for r in doc["court"]["rims"]]
    tpl = load_profile(doc["sport"]).template(doc.get("variant"))
    # no basket (net sports): the baseline behind the play stands in for it
    rim = min(rims, key=lambda r: np.linalg.norm(r - t0[:2])) if rims else _end(tpl, t0[1], False)
    views = []
    if angle in ("broadcast_high", "reverse"):
        r, h, sweep = (15.0, 9.0, 12.0) if angle == "broadcast_high" else (14.0, 6.5, -12.0)
        phi = phi0 + (np.pi if angle == "reverse" else 0.0)
        f = w * np.hypot(r, h) / float(np.clip(spread + 9.0, 14.0, 26.0))
        for i in range(n):
            a = phi + np.radians(sweep) * (u[i] - 0.5)
            eye = np.array([t0[0] + r * np.cos(a), t0[1] + r * np.sin(a), h])
            eye[:2] += (centre[i][:2] - t0[:2]) * 0.5  # truck along with the play
            views.append(look_at(eye, centre[i], f, size))
    elif angle == "overhead":
        side = v / max(np.linalg.norm(v), 1e-6)
        f = w * 17.0 / float(np.clip(spread + 12.0, 16.0, 30.0))
        for i in range(n):
            hgt = 19.0 - 4.0 * u[i]  # slow descent
            eye = centre[i] + np.r_[side * 0.9, hgt - centre[i][2]]
            views.append(look_at(eye, centre[i], f, size))
    elif angle == "baseline":
        ref = t0[1] if rims else tpl.polygon[:, 1].mean()
        out = np.sign(rim[1] - ref) or 1.0  # away from the play, past the basket / baseline
        f = w / 2 / np.tan(np.radians(32))
        for i in range(n):
            eye = np.array([rim[0] - 1.5 + 3.0 * u[i], rim[1] + out * 3.2, 2.4])
            views.append(look_at(eye, centre[i] + [0, 0, 0.3], f, size))
    elif angle.startswith("pov"):
        j = joints[ids.index(pov_player(angle, doc))]
        head = _fill((j[:, NOSE] + j[:, HEAD]) / 2)
        head = _smooth(head, 0.25 * fps)
        f = w / 2 / np.tan(np.radians(45))  # 90° wide, like a head-mounted camera
        ball = doc.get("ball") or {}
        if not ball.get("target"):  # no shot: the basket nearest the player
            mid = np.nanmean(head[:, :2], axis=0)
            rim = min(rims, key=lambda r: np.linalg.norm(r - mid)) if rims else rim
        # aim a little under the rim: the hoop sits high in the frame, the floor shows
        rim3 = np.asarray(ball.get("target") or np.r_[rim, 3.05], float) - [0, 0, 0.9]
        t_turn = float(
            ball.get("t_release", doc["t_start"] + 0.6 * (doc["t_end"] - doc["t_start"]))
        )
        times = doc["t_start"] + np.arange(n) / fps
        k = ease(np.clip((times - (t_turn - 2.0)) / 1.5, 0.0, 1.0))
        # before the turn: look where the player is heading (toward the rim when still)
        vel = np.gradient(_smooth(_fill(j[:, PELVIS, :2]), 0.5 * fps), axis=0) * fps
        to_rim = rim3[:2] - head[:, :2]
        to_rim /= np.linalg.norm(to_rim, axis=1, keepdims=True)
        speed = np.linalg.norm(vel, axis=1, keepdims=True)
        heading = np.where(speed > 0.6, vel / np.maximum(speed, 1e-6), to_rim)
        heading = _smooth(heading, 0.7 * fps)
        heading /= np.linalg.norm(heading, axis=1, keepdims=True)
        if not rims and not ball.get("target"):  # net sport: face across the net throughout
            mid = np.nanmean(head[:, :2], axis=0)
            rim3 = np.r_[_end(tpl, mid[1], True), 1.0]
            k = np.ones(n)
        for i in range(n):
            look = np.r_[head[i, :2] + 6.0 * heading[i], 1.4]
            tgt = look + (rim3 - look) * k[i]
            views.append(look_at(head[i] + [0, 0, 0.06], tgt, f, size))
    else:
        raise ValueError(f"unknown Tier C angle {angle!r}")
    return views


# --- the render ------------------------------------------------------------------------


def label(canvas: np.ndarray, angle: str, synthetic: bool, title: str, method: str) -> None:
    h, w = canvas.shape[:2]
    s = w / 1280.0

    def at(x: float, y: float) -> tuple[int, int]:
        return round(x * s), round(y * s)

    font, small = cv2.FONT_HERSHEY_DUPLEX, cv2.FONT_HERSHEY_SIMPLEX
    cv2.rectangle(canvas, at(24, 24), at(404, 98), (20, 20, 20), -1)
    cv2.rectangle(canvas, at(24, 24), at(34, 98), (90, 200, 120), -1)
    cv2.putText(canvas, "TIER C  3D", at(46, 54), font, 0.8 * s, (120, 230, 150), 1, cv2.LINE_AA)
    name = NAMES.get(angle.split("_", 1)[0] if angle.startswith("pov") else angle, angle.upper())
    cv2.putText(canvas, name, at(46, 86), font, 0.8 * s, (245, 245, 245), 1, cv2.LINE_AA)
    cv2.putText(canvas, title[:48], (int(24 * s), h - int(28 * s)), font, 0.7 * s,
                (235, 235, 235), 1, cv2.LINE_AA)  # fmt: skip
    how = "MotionBERT lift" if method == "motionbert" else "analytic"
    note = f"3D reconstruction - stylized ({how})" + ("  |  SYNTHETIC" if synthetic else "")
    (tw, _), _ = cv2.getTextSize(note, small, 0.5 * s, 1)
    cv2.putText(canvas, note, (w - tw - int(24 * s), h - int(28 * s)), small, 0.5 * s,
                (200, 200, 200), 1, cv2.LINE_AA)  # fmt: skip


class Painter:
    """Everything that does not change per frame: court texture, hoops, colours."""

    def __init__(self, doc: dict, size=OUT_SIZE) -> None:
        self.doc, self.size = doc, size
        self.tex, self.origin, self.ax_u, self.ax_v, tpl = court_texture(
            doc["sport"], doc.get("variant")
        )
        ys = tpl.polygon[:, 1]
        self.hoops = []
        for r in doc["court"]["rims"]:
            base = float(ys.min() if abs(r[1] - ys.min()) < abs(r[1] - ys.max()) else ys.max())
            self.hoops.append((tuple(r), base))
        hl = height_landmarks(tpl)
        self.net = (hl["net_top_l"], hl["net_top_r"]) if "net_top_l" in hl else None
        self.joints = joints_array(doc)
        self.colors = team_colors(doc)
        b = doc.get("ball")
        self.ball = (
            np.array([[np.nan] * 3 if q is None else q for q in b["positions"]], float)
            if b
            else None
        )

    def frame(self, f: int, view: View, angle: str = "", pov_id: str | None = None) -> np.ndarray:
        canvas = background(self.size)
        draw_plane(canvas, self.tex, view, self.origin, self.ax_u, self.ax_v)
        prims = []
        for k, j in enumerate(self.joints):
            jf = j[f]
            if not np.isfinite(jf).all() or self.doc["players"][k]["id"] == pov_id:
                continue  # the POV player is the camera
            self._shadow(canvas, view, jf[PELVIS, :2])
            prims += player_prims(jf, self.colors[k], view)
        for rim, base in self.hoops:
            prims += hoop_prims(rim, base, view)
        if self.net:
            prims += net_prims(*self.net, view)
        if self.ball is not None:
            p = self.ball[f]
            if np.isfinite(p).all():
                self._shadow(canvas, view, p[:2])
            prims += ball_prims(self.ball, f, view)
        for _, fn in sorted(prims, key=lambda q: -q[0]):
            fn(canvas)
        return canvas

    def _shadow(self, canvas, view: View, xy) -> None:
        foot = np.r_[xy, 0.0]
        d = view.depth(foot[None])[0]
        if d > NEAR_M and view.k[0, 0] * 0.42 / d < self.size[0] / 6:  # a huge blur is slow
            draw_shadow(canvas, view, foot)


def render_angle(
    doc: dict, angle: str, out_path: Path, *, size=OUT_SIZE, progress=None
) -> dict[str, Any]:
    started = time.time()
    painter = Painter(doc, size)
    views = camera_path(angle, doc, painter.joints, size)
    pov_id = pov_player(angle, doc) if angle.startswith("pov") else None
    n = doc["frames"]
    proc = open_encoder(Path(out_path), size, doc["fps"])
    assert proc.stdin is not None
    try:
        for f in range(n):
            canvas = painter.frame(f, views[f], angle, pov_id)
            label(canvas, angle, bool(doc.get("synthetic")), doc.get("label") or "", doc["method"])
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
        "wall_s": round(time.time() - started, 2),
        "ms_per_frame": round(1000 * (time.time() - started) / max(1, n), 1),
    }


def angles_for(doc_or_highlight: dict) -> list[str]:
    """File-stem angles of a play: the four fixed ones + the shooter's POV when there is a
    shooter (else the primary player's)."""
    shot = doc_or_highlight.get("shot") or {}
    pid = (
        doc_or_highlight.get("shooter") or shot.get("player_id") or doc_or_highlight.get("primary")
    )
    return list(ANGLES) + ([f"pov_{pid}"] if pid else [])
