"""Tier C virtual views, image-based (D-86): the real players' pixels, not avatars.

Every tracked person stands on the court plane at their tracked foot point (the tracks'
court positions, `tracks.court`), and is drawn from the real video: their SAM 2.1 cutout
(`segments/`) on an upright billboard through the foot point (`tierb.Billboard`), over
the reconstructed court plate (floor + backdrop) with the template's hoops / net as
real geometry. The 3D scene (`avatars.scene`, `scene/<play>.json`) only steers the
cameras: the play centre, the key player, and every POV's eyes and heading.

A cutout is a photo of one side of a person, so it holds up only near the real line of
sight. Each billboard therefore fades, per player and per frame, from its real pixels
(up to 35° from the real camera's view of that player) to a kit-coloured silhouette
shaded by its own light (past 75°, mirrored when seen from behind): the view degrades
to honest shapes in the team's colour, never to stretched pixels. Angles a fixed camera
cannot carry at all (more than `MAX_OFF` from the real one, e.g. a baseline camera
facing a camera behind the arc) are not rendered.

Angles: `wing` (a raised camera ~35° round from the real one), `courtside` (low, close,
just off the real line of sight), `baseline` (behind the target basket / the play's
baseline, when within `MAX_OFF`), and `pov_<pid>` (the player's eyes from the 3D scene;
their own cutout is hidden). Tier B keeps `broadcast_high`, `orbit` and `push_in`.
Every frame is labelled "VIRTUAL VIEW".
"""

from __future__ import annotations

import time
import warnings
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from courtcam.profiles import load_profile

from ..camera import ease
from ..virtual import tierb
from ..virtual.replays import play
from ..virtual.tierb import View, look_at
from . import proxy
from . import render as stylized
from .scene import joints_array

ANGLES = ("wing", "courtside", "baseline")
NAMES = {
    "wing": "WING",
    "courtside": "COURTSIDE",
    "side": "SIDE",
    "baseline": "BASELINE",
    "pov": "PLAYER POV",
}
MAX_OFF = np.radians(60)  # mean angle from the real camera's line of sight to the play
PROXY = True  # cutouts turn into posed, textured body proxies at wide angles (proxy.py)
_BODIES: dict = {}


def _real_centre(doc: dict) -> np.ndarray:
    cam = doc["camera"]
    return -np.asarray(cam["R"]).T @ np.asarray(cam["t"])


def _centre(doc: dict, joints: list[np.ndarray]) -> np.ndarray:
    ids = [p["id"] for p in doc["players"]]
    focus = [ids.index(p) for p in (doc.get("shooter"), doc.get("primary")) if p in ids][:1]
    return stylized.focus_centre(joints, focus, doc["fps"])


def camera_views(angle: str, doc: dict, joints: list[np.ndarray], size) -> list[View]:
    """One virtual camera per frame (court metres, like the tracks)."""
    if angle.startswith("pov"):
        return _level(stylized.camera_path(angle, doc, joints, size), size)
    if angle not in ("wing", "courtside", "side"):
        return stylized.camera_path(angle, doc, joints, size)
    n, w = doc["frames"], size[0]
    centre = _centre(doc, joints)
    t0 = centre.mean(axis=0)
    real_c = _real_centre(doc)
    v = (real_c - t0)[:2]
    d0, phi0 = float(np.linalg.norm(v)), float(np.arctan2(v[1], v[0]))
    u = ease(np.linspace(0.0, 1.0, n))
    if angle == "wing":
        r, h, a0, a1, fov = float(np.clip(0.7 * d0, 9.0, 16.0)), 3.2, 25.0, 45.0, 30.0
    elif angle == "side":  # square to the real camera: only a body proxy carries it
        r, h, a0, a1, fov = 10.0, 2.6, 80.0, 95.0, 32.0
    else:
        r, h, a0, a1, fov = 7.5, 1.7, 10.0, 18.0, 34.0
    f = w / 2 / np.tan(np.radians(fov))
    # turn toward the middle of the court (round the other way the camera would stand
    # off the end of the reconstructed floor, looking at the edge of the plate)
    mid = load_profile(doc["sport"]).template(doc.get("variant")).polygon.mean(axis=0)

    def eye(sign: float, k: float) -> np.ndarray:
        a = phi0 + sign * np.radians(a0 + (a1 - a0) * k)
        return np.array([t0[0] + r * np.cos(a), t0[1] + r * np.sin(a), h])

    sign = min((1.0, -1.0), key=lambda s: np.linalg.norm(eye(s, 1.0)[:2] - mid))
    views = []
    for i in range(n):
        e = eye(sign, u[i])
        e[:2] += (centre[i][:2] - t0[:2]) * 0.5  # truck along with the play
        views.append(look_at(e, centre[i] + [0, 0, 0.2], f, size))
    return views


def _level(views: list[View], size, max_pitch: float = np.radians(20)) -> list[View]:
    """A POV under the basket aims at the rim almost straight up, into the void over the
    reconstructed walls: cap how far it looks up (continuous, so no jump at the cap)."""
    out, hor = [], np.array([1.0, 0.0])
    for v in views:
        fwd = v.r[2]
        h = np.linalg.norm(fwd[:2])
        hor = fwd[:2] / h if h > 1e-3 else hor
        p = min(float(np.arcsin(np.clip(fwd[2], -1, 1))), max_pitch)
        d = np.r_[np.cos(p) * hor, np.sin(p)]
        out.append(look_at(v.centre, v.centre + d, float(v.k[0, 0]), size))
    return out


def off_angle(views: list[View], centre: np.ndarray, real_c: np.ndarray) -> float:
    """Mean horizontal angle at the play centre between the virtual and real cameras."""
    out = []
    for vw, c in zip(views, centre, strict=False):
        a, b = (vw.centre - c)[:2], (real_c - c)[:2]
        out.append(abs(np.arctan2(a[0] * b[1] - a[1] * b[0], a @ b)))
    return float(np.mean(out)) if out else 0.0


def angles_for(doc_or_highlight: dict, size=(1280, 720)) -> list[str]:
    """File-stem angles of a play: the fixed angles a cutout can carry (within `MAX_OFF`
    of the real camera) + a virtual POV per reconstructed player (`stylized.MAX_POV`)."""
    shot = doc_or_highlight.get("shot") or {}
    key = (
        doc_or_highlight.get("shooter") or shot.get("player_id") or doc_or_highlight.get("primary")
    )
    if "players" not in doc_or_highlight:  # no 3D scene yet: the key player's POV
        return ["wing", "courtside"] + ([f"pov_{key}"] if key else [])
    doc = doc_or_highlight
    if not any(p.get("joints") for p in doc["players"]):
        return []
    joints = joints_array(doc)
    centre, real_c = _centre(doc, joints), _real_centre(doc)
    fixed = [a for a in ANGLES if off_angle(camera_views(a, doc, joints, size), centre, real_c)
             <= MAX_OFF]  # fmt: skip
    return fixed + [f"pov_{p}" for p in stylized._pov_players(doc, key)]


def tints(doc: dict) -> dict[str, tuple[int, int, int]]:
    """BGR kit colour per player id (the silhouette a cutout fades to)."""
    return {p["id"]: c for p, c in zip(doc["players"], stylized.team_colors(doc), strict=True)}


def label(canvas: np.ndarray, angle: str, synthetic: bool) -> None:
    """Burned-in honesty label, top left (the TV moves its title right for Tier C)."""
    h, w = canvas.shape[:2]
    s = w / 1280.0

    def at(x: float, y: float) -> tuple[int, int]:
        return round(x * s), round(y * s)

    font, small = cv2.FONT_HERSHEY_DUPLEX, cv2.FONT_HERSHEY_SIMPLEX
    roi = canvas[at(0, 24)[1] : at(0, 98)[1], at(24, 0)[0] : at(404, 0)[0]]
    roi[:] = (roi * 0.3 + 10).astype(np.uint8)
    cv2.rectangle(canvas, at(24, 24), at(34, 98), (255, 190, 90), -1)
    cv2.putText(canvas, "VIRTUAL VIEW", at(46, 54), font, 0.8 * s, (255, 210, 130), 1, cv2.LINE_AA)
    name = NAMES.get("pov" if angle.startswith("pov") else angle, angle.upper())
    cv2.putText(canvas, name, at(46, 86), font, 0.8 * s, (245, 245, 245), 1, cv2.LINE_AA)
    note = "real players' pixels on a reconstructed court" + ("  |  SYNTHETIC" if synthetic else "")
    (tw, _), _ = cv2.getTextSize(note, small, 0.5 * s, 1)
    cv2.putText(canvas, note, (w - tw - int(24 * s), h - int(28 * s)), small, 0.5 * s,
                (210, 210, 210), 1, cv2.LINE_AA)  # fmt: skip


def render_angle(
    game_dir: Path, video: Path, doc: dict, angle: str, out_path: Path, *, size=(1280, 720),
    progress=None,
) -> dict[str, Any]:  # fmt: skip
    started = time.time()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        joints = joints_array(doc)
    views = camera_views(angle, doc, joints, size)
    hide = (stylized.pov_player(angle, doc),) if angle.startswith("pov") else ()
    synthetic = bool(doc.get("synthetic"))
    kit = tints(doc)

    def bodies(real, k1, src_size, masks, n, feet):
        key = (str(game_dir), doc["play_id"], n, [p["id"] for p in doc["players"]])
        if _BODIES.get("key") != key:  # one play's atlases serve all its angles
            h = play(Path(game_dir), doc["play_id"])
            _BODIES.update(key=key, proxy=proxy.build(doc, joints, real, k1, src_size, kit,
                                                      video, h, masks, n, feet))  # fmt: skip
        return _BODIES["proxy"]

    out = tierb.render_angle(
        game_dir, video, doc["play_id"], angle, out_path, size=size, progress=progress,
        views=views, hide=hide, tints=kit, label_fn=lambda c: label(c, angle, synthetic),
        proxy=bodies if PROXY else None,
    )  # fmt: skip
    out["wall_s"] = round(time.time() - started, 2)
    return out
