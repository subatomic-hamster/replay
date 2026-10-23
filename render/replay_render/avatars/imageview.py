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
to honest shapes in the team's colour, never to stretched pixels. With `PROXY` on, past
45° the cutout hands over to a posed capsule body textured from the same video
(`proxy.py`; 45-55° cross-fade), and the silhouette is only the fallback for a player
with no pose. The eval-only `side` angle (80-95°) is carried by the proxy alone and is
not in `ANGLES`. Angles a fixed camera
cannot carry at all (more than `MAX_OFF` from the real one, e.g. a baseline camera
facing a camera behind the arc) are not rendered.

Angles: `wing` (a raised camera ~35° round from the real one), `courtside` (low, close,
just off the real line of sight), `baseline` (behind the target basket / the play's
baseline, when within `MAX_OFF`), and `pov_<pid>` (the player's eyes from the 3D scene;
their own cutout is hidden). Tier B keeps `broadcast_high`, `orbit` and `push_in`.
Every frame is labelled "VIRTUAL REPLAY" (the TV badge's words).
"""

from __future__ import annotations

import time
import warnings
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from courtcam.calibrate import RIM_HEIGHT_M as RIM_M
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
    "pov": "PLAYER'S VIEW",
}
MAX_OFF = np.radians(60)  # mean angle from the real camera's line of sight to the play
PROXY = True  # cutouts turn into posed, textured body proxies at wide angles (proxy.py)
_BODIES: dict = {}
# a fixed virtual camera does not show anyone within 3.5 m of it (fading in to 4.5 m):
# so close, a cutout or proxy is a few magnified pixels or a plain capsule. POVs keep
# their own nearer fade (tierb.NEAR_FADE_M): there, people close by are the point.
NEAR_M = 3.5


def _real_centre(doc: dict) -> np.ndarray:
    cam = doc["camera"]
    return -np.asarray(cam["R"]).T @ np.asarray(cam["t"])


def _centre(doc: dict, joints: list[np.ndarray]) -> np.ndarray:
    ids = [p["id"] for p in doc["players"]]
    focus = [ids.index(p) for p in (doc.get("shooter"), doc.get("primary")) if p in ids][:1]
    return stylized.focus_centre(joints, focus, doc["fps"])


POV_FOV = np.radians(80)  # horizontal: wide like a head, people not tiny
POV_PITCH = np.radians(-7)  # a little down: the floor and the feet of people near show
POV_MAX_PITCH = np.radians(20)  # looking up at the rim on a shot, never into the void
EYE_OF_STATURE, EYE_DEFAULT_M = 0.93, 1.65


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-6)


def pov_views(doc: dict, pos: np.ndarray, own: list[int], size, eye_m: float) -> list[View]:
    """A player's eyes, one camera per frame. `pos` (P, F, 2) are the bridged tracked foot
    points (`tierb.bridge`), `own` the POV player's track indices (all their ids).

    The eye stands on their tracked court position (not the 3D lift's head, whose root
    can sit a metre off and whose height bobs with a crouching pose) at a fixed
    `eye_m`, smoothed over 0.25 s; before their track starts / after it ends it holds
    the nearest position. They look at the play: the ball where the scene models it,
    else the middle of everyone else on court, with a pull toward the nearest basket
    (or the far baseline) so the gaze never spins when the others crowd round; the
    direction is smoothed over 0.5 s. On a modelled shot the gaze turns up to the rim
    from 1 s before the release to 0.8 s after it reaches the rim."""
    fps, n = doc["fps"], pos.shape[1]
    with warnings.catch_warnings():  # frames where nobody (else) is tracked stay NaN
        warnings.simplefilter("ignore", RuntimeWarning)
        me = np.nanmean(pos[own], axis=0) if own else np.full((n, 2), np.nan)
        rest = [p for p in range(len(pos)) if p not in own]
        others = np.nanmean(pos[rest], axis=0) if rest else np.full((n, 2), np.nan)
    if not np.isfinite(me[:, 0]).any():
        raise ValueError("the POV player is not tracked in this window")
    me = tierb._smooth(stylized._fill(me), 0.25 * fps)
    rims = [np.asarray(r, float) for r in doc["court"]["rims"]]
    mid = me.mean(axis=0)
    if rims:
        goal = np.r_[min(rims, key=lambda r: np.linalg.norm(r - mid)), RIM_M]
    else:  # net sport: across the net
        tpl = load_profile(doc["sport"]).template(doc.get("variant"))
        goal = np.r_[stylized._end(tpl, float(mid[1]), True), 1.0]
    look = 0.15 * _unit(goal[:2] - me)
    if np.isfinite(others[:, 0]).any():
        to_c = tierb._smooth(stylized._fill(others), 0.5 * fps) - me
        look += _unit(to_c) * np.clip(np.linalg.norm(to_c, axis=1, keepdims=True) / 3.0, 0, 1)
    ball = doc.get("ball") or {}
    bp = np.array([q if q else [np.nan] * 3 for q in (ball.get("positions") or [])[:n]],
                  float).reshape(-1, 3)  # fmt: skip
    if len(bp):
        ok = np.isfinite(bp[:, 0])
        look[: len(bp)][ok] += _unit(bp[ok, :2] - me[: len(bp)][ok])
    look = _unit(tierb._smooth(look, 0.5 * fps))
    k = np.zeros(n)
    if ball.get("target") and ball.get("t_release") is not None:
        times = doc["t_start"] + np.arange(n) / fps
        t_rel = float(ball["t_release"])
        t_rim = float(ball.get("t_rim") or t_rel + 1.0)
        goal = np.asarray(ball["target"], float)
        k = ease(np.clip((times - (t_rel - 1.0)) / 0.8, 0, 1)) * (
            1 - ease(np.clip((times - (t_rim + 0.8)) / 0.8, 0, 1)))  # fmt: skip
    to_g = goal[:2] - me
    # under the basket the rim is overhead: looking up at it shows a wall, not the shot
    k = k * np.clip((np.linalg.norm(to_g, axis=1) - 2.5) / 2.0, 0, 1)
    dirs = _unit(look * (1 - k[:, None]) + _unit(to_g) * k[:, None])
    up = np.arctan2(goal[2] - eye_m, np.maximum(np.linalg.norm(to_g, axis=1), 0.5))
    pitch = POV_PITCH * (1 - k) + np.minimum(up, POV_MAX_PITCH) * k
    f = size[0] / 2 / np.tan(POV_FOV / 2)
    views = []
    for i in range(n):
        eye = np.r_[me[i], eye_m]
        d = np.r_[np.cos(pitch[i]) * dirs[i], np.sin(pitch[i])]
        views.append(look_at(eye, eye + d, f, size))
    return views


def eye_height(doc: dict, pid: str) -> float:
    h = next((p.get("height_m") for p in doc["players"] if p["id"] == pid), None)
    return EYE_OF_STATURE * float(h) if h and 1.5 <= float(h) <= 2.15 else EYE_DEFAULT_M


def camera_views(angle: str, doc: dict, joints: list[np.ndarray], size) -> list[View]:
    """One fixed virtual camera per frame (court metres, like the tracks). POVs follow
    the tracks instead (`pov_views`)."""
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
    cv2.putText(
        canvas, "VIRTUAL REPLAY", at(46, 54), font, 0.8 * s, (255, 210, 130), 1, cv2.LINE_AA
    )
    name = NAMES.get("pov" if angle.startswith("pov") else angle, angle.upper())
    cv2.putText(canvas, name, at(46, 86), font, 0.8 * s, (245, 245, 245), 1, cv2.LINE_AA)
    note = "real players' pixels on a reconstructed court" + ("  |  SYNTHETIC" if synthetic else "")
    (tw, _), _ = cv2.getTextSize(note, small, 0.5 * s, 1)
    cv2.putText(canvas, note, (w - tw - int(24 * s), h - int(28 * s)), small, 0.5 * s,
                (210, 210, 210), 1, cv2.LINE_AA)  # fmt: skip


def render_angle(
    game_dir: Path, video: Path, doc: dict, angle: str, out_path: Path, *, size=(1280, 720),
    progress=None, plain: bool = False,
) -> dict[str, Any]:  # fmt: skip
    """`plain`: no burned-in label, only as input to a later pass (a diffusion refine)
    that labels its own output; everything shipped is labelled."""
    started = time.time()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        joints = joints_array(doc)
    pov = angle.startswith("pov")
    if pov:
        pid = stylized.pov_player(angle, doc)
        hide, eye_m = (pid,), eye_height(doc, pid)

        def views(pos, own):
            return pov_views(doc, pos, own, size, eye_m)
    else:
        hide, views = (), camera_views(angle, doc, joints, size)
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
        views=views, hide=hide, tints=kit,
        label_fn=(lambda c: None) if plain else (lambda c: label(c, angle, synthetic)),
        # a POV shows everyone as their cutout, facing the eye: body proxies close up
        # are blocky mannequins (their 32x16 atlases magnified)
        proxy=None if pov or not PROXY else bodies, near_m=0.0 if pov else NEAR_M,
        seen=tierb.POV_SEEN if pov else (tierb.SEEN_FULL, tierb.SEEN_NONE),
    )  # fmt: skip
    out["wall_s"] = round(time.time() - started, 2)
    return out
