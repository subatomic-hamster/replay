"""Synthetic clips with full ground truth (plan §7.4, M1).

A sport profile's court template is drawn through a configurable pinhole camera (K, R,
t, optional one-parameter lens `k1` — the same division model as `distortion.py`), with
articulated 3D mannequins playing scripted plays on it:

* basketball (a template with a `rim`): possessions that start on an inbound, a steal
  or a defensive rebound and end on a shot (makes drop through the rim at 3.05 m, misses
  clang off its front edge) or a turnover;
* net sports (a template with a `net_y`): serve -> contacts -> point, with up to
  `touches_per_side` same-side touches (volleyball's pass, set, attack).

On top of the plays sit the "Replay, clip that" triggers: an arms-crossed-overhead X
gesture held ~1 s (drawn on the rig *and* exported as COCO-17 keypoints), a voice line
mixed into the audio, and a phone tap — each placed 1-8 s after a play ends, so it
resolves to that play.

Everything is seeded and written as ground truth labelled `"synthetic": true`:
`ground_truth.json` (per-frame boxes, court metres, foot pixels, keypoints in pixels
and in court metres (`kp3`), visibility, ball), `events.json`, `plays.json`,
`triggers.json`, `calibration.json` and the pipeline's `landmarks.json`.
`--detector synthetic` replays the boxes, so tracking tests do not depend on YOLO.

Nothing in here branches on the sport id: the choreography is picked by the template's
geometry and tuned by the profile's `synth:` block.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .distortion import distort_points
from .profiles import CourtTemplate, Profile, load_profile
from .render import open_encoder

GT_SCHEMA = "courtcam.synth.v2"
RIM_H_M = 3.05
RIM_R_M = 0.225
PLAYER_H_M = 1.82
MAX_SPEED_MPS = 8.5  # a sprinting amateur
AUDIO_SR = 16000
NAMES = (
    "Alex", "Sam", "Jordan", "Riley", "Casey", "Morgan",
    "Taylor", "Jamie", "Avery", "Quinn", "Drew", "Blake",
)  # fmt: skip
COCO_KEYPOINTS = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)  # fmt: skip
POSE_NONE, POSE_X, POSE_SHOOT, POSE_HIT, POSE_CLAP, POSE_HOLD = range(6)
DEFAULT_TEAM_COLORS = ("#1F4FA0", "#E8E8E8")
SKIN = ((150, 180, 225), (95, 130, 175), (60, 85, 125), (120, 160, 205))  # BGR
HAIR = ((30, 30, 35), (40, 60, 90), (25, 25, 25), (70, 110, 150))


def _bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def _shade(bgr, k: float) -> tuple[int, int, int]:
    return tuple(int(min(255, max(0, c * k))) for c in bgr)


# --- camera -------------------------------------------------------------------


@dataclass(frozen=True)
class Camera:
    """Pinhole camera (+ optional division-model lens) over the court; z = 0 is the floor.

    `project` returns *frame* pixels (lens applied); `H_court_to_px` is the pinhole
    homography of the floor, i.e. undistorted pixels — the convention of `calib.json`.
    """

    K: np.ndarray
    R: np.ndarray  # world -> camera
    t: np.ndarray
    size: tuple[int, int]
    k1: float = 0.0

    @property
    def P(self) -> np.ndarray:
        return self.K @ np.column_stack([self.R, self.t])

    def depth(self, pts_xyz: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts_xyz, dtype=np.float64).reshape(-1, 3)
        return pts @ self.R[2] + self.t[2]

    def project(self, pts_xyz: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts_xyz, dtype=np.float64).reshape(-1, 3)
        hom = np.column_stack([pts, np.ones(len(pts))]) @ self.P.T
        z = hom[:, 2:3]
        px = np.where(z > 0.05, hom[:, :2] / np.where(z > 0.05, z, 1.0), np.nan)
        return distort_points(px, self.k1, self.size) if self.k1 else px

    def ground(self, pts_xy: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts_xy, dtype=np.float64).reshape(-1, 2)
        return self.project(np.column_stack([pts, np.zeros(len(pts))]))

    @property
    def H_court_to_px(self) -> np.ndarray:
        h = self.P[:, [0, 1, 3]]
        return h / h[2, 2]

    def as_dict(self) -> dict[str, Any]:
        return {
            "K": self.K.tolist(),
            "R": self.R.tolist(),
            "t": self.t.tolist(),
            "k1": self.k1,
            "size": list(self.size),
        }


def _look_at(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    forward = target - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, np.array([0.0, 0.0, 1.0]))
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    return np.vstack([right, down, forward])  # world → camera


def make_camera(
    template: CourtTemplate, size: tuple[int, int], extra_xy: np.ndarray, margin_px: int = 48
) -> Camera:
    """Elevated sideline camera, auto-framed so the court and `extra_xy` all fit.

    The original fixture camera: its principal point is shifted to centre the content,
    which the calibration tests and the frozen `basketball_half` fixture rely on.
    """
    w_m, l_m = template.size
    eye = np.array([w_m * 0.85, l_m * 0.5, 6.0])
    target = np.array([0.0, l_m * 0.5, 0.9])
    r = _look_at(eye, target)
    t = -r @ eye

    keep = np.vstack([template.polygon, np.asarray(extra_xy).reshape(-1, 2)])
    corners = np.column_stack([keep, np.zeros(len(keep))])
    tops = np.column_stack([keep, np.full(len(keep), PLAYER_H_M)])
    cam = np.vstack([corners, tops]) @ r.T + t
    norm = cam[:, :2] / cam[:, 2:3]

    lo, hi = norm.min(axis=0), norm.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)
    f = float(np.min((np.asarray(size) - 2 * margin_px) / span))
    centre = (lo + hi) / 2.0
    c = np.asarray(size) / 2.0 - f * centre
    k = np.array([[f, 0.0, c[0]], [0.0, f, c[1]], [0.0, 0.0, 1.0]])
    return Camera(k, r, t, tuple(size))


@dataclass(frozen=True)
class CameraSpec:
    """Where the synthetic camera stands. Any field left None comes from the profile's
    `synth.view` preset (`sideline` or `baseline`), auto-framed onto the court."""

    eye: tuple[float, float, float] | None = None
    target: tuple[float, float, float] | None = None
    f_px: float | None = None
    k1: float = 0.0


def scene_camera(
    template: CourtTemplate,
    size: tuple[int, int],
    view: str,
    keep_xyz: np.ndarray,
    spec: CameraSpec | None = None,
    margin_px: int = 40,
) -> Camera:
    """A physical camera (principal point at the image centre, no skew) aimed at the
    middle of `keep_xyz` with the focal length that just fits it, unless `spec` pins it."""
    spec = spec or CameraSpec()
    w_m, l_m = template.size
    if view == "baseline":
        eye = (0.8, -max(4.0, 0.4 * l_m), 3.0 + 0.15 * l_m)
        target = (0.0, 0.55 * l_m, 0.6)
    else:
        eye = (w_m * 0.85, l_m * 0.5, 6.0)
        target = (0.0, l_m * 0.5, 0.9)
    eye = np.asarray(spec.eye or eye, dtype=np.float64)
    target = np.asarray(spec.target or target, dtype=np.float64)
    size_a = np.asarray(size, dtype=np.float64)
    for _ in range(3 if spec.target is None else 1):
        r = _look_at(eye, target)
        cam = (keep_xyz - eye) @ r.T
        norm = cam[:, :2] / cam[:, 2:3]
        mid = (norm.min(axis=0) + norm.max(axis=0)) / 2.0
        if spec.target is not None:
            break
        target = eye + r.T @ np.array([mid[0], mid[1], 1.0])
    r = _look_at(eye, target)
    cam = (keep_xyz - eye) @ r.T
    norm = cam[:, :2] / cam[:, 2:3]
    f = spec.f_px or float(np.min((size_a / 2 - margin_px) / np.abs(norm).max(axis=0)))
    k = np.array([[f, 0.0, size_a[0] / 2], [0.0, f, size_a[1] / 2], [0.0, 0.0, 1.0]])
    return Camera(k, r, -r @ eye, (int(size[0]), int(size[1])), float(spec.k1))


# --- the rig ------------------------------------------------------------------


def rig(
    xy, heading: float, h: float, phase: float, amp: float, pose: int, pw: float, aim=None
) -> dict[str, np.ndarray]:
    """3D joints of one mannequin standing at court point `xy` facing `heading` (rad).

    `phase`/`amp` drive the gait (amp 0 = standing, 1 = running); `pose` blends the arms
    toward a scripted pose with weight `pw`. Lowest foot always touches the floor, so the
    box bottom is the floor contact the pipeline's foot point assumes.
    """
    f = np.array([math.cos(heading), math.sin(heading), 0.0])
    r = np.array([math.sin(heading), -math.cos(heading), 0.0])
    z = np.array([0.0, 0.0, 1.0])
    base = np.array([xy[0], xy[1], 0.0])
    pelvis = base + z * 0.52 * h
    swing = 0.55 * amp * math.sin(phase)
    lean = 0.12 * amp
    up = z * math.cos(lean) + f * math.sin(lean)

    j: dict[str, np.ndarray] = {"pelvis": pelvis}
    for side, sgn, a, ph in (("l", -1, swing, phase), ("r", 1, -swing, phase + math.pi)):
        hip = pelvis + r * sgn * 0.09 * h
        flex = 0.9 * amp * max(0.0, math.sin(ph + math.pi / 2)) + 0.08
        knee = hip + 0.245 * h * (math.sin(a) * f - math.cos(a) * z)
        b = a - flex
        ankle = knee + 0.245 * h * (math.sin(b) * f - math.cos(b) * z)
        j[f"hip_{side}"], j[f"knee_{side}"], j[f"ankle_{side}"] = hip, knee, ankle
        j[f"toe_{side}"] = ankle + 0.075 * h * f - 0.015 * h * z
    floor = min(j["toe_l"][2], j["toe_r"][2], j["ankle_l"][2], j["ankle_r"][2])
    drop = z * (floor - 0.028 * h)  # the shoe capsule's radius: its sole is on the floor
    for k in list(j):
        j[k] = j[k] - drop
    pelvis = j["pelvis"]
    sh_c = pelvis + 0.30 * h * up
    j["neck"] = sh_c + 0.04 * h * up
    j["head"] = j["neck"] + 0.085 * h * up
    for side, sgn in (("l", -1), ("r", 1)):
        sh = sh_c + r * sgn * 0.13 * h
        c = -sgn * 0.6 * amp * math.sin(phase)
        out = r * sgn * 0.12
        arm = math.sin(c) * f - math.cos(c) * z + out
        elbow = sh + 0.17 * h * arm / np.linalg.norm(arm)
        e = c + 0.3 + 0.9 * amp
        fore = math.sin(e) * f - math.cos(e) * z + out * 0.5
        wrist = elbow + 0.15 * h * fore / np.linalg.norm(fore)
        if pose != POSE_NONE and pw > 0:
            pe, pwr = _pose_arm(pose, side, sgn, sh, j["head"], f, r, z, h, aim)
            elbow = (1 - pw) * elbow + pw * pe
            wrist = (1 - pw) * wrist + pw * pwr
        j[f"shoulder_{side}"], j[f"elbow_{side}"], j[f"wrist_{side}"] = sh, elbow, wrist
        d = wrist - elbow
        j[f"hand_{side}"] = wrist + 0.035 * h * d / max(np.linalg.norm(d), 1e-6)
    return j


def _pose_arm(pose, side, sgn, sh, head, f, r, z, h, aim):
    if pose == POSE_X:
        # forearms cross above the head: each wrist ends up on the *other* side
        elbow = sh + h * (-sgn * 0.03 * r + 0.15 * z + 0.06 * f)
        wrist = head + h * (-sgn * 0.035 * r + (0.15 if sgn < 0 else 0.16) * z + 0.05 * f)
        return elbow, wrist
    if pose == POSE_SHOOT:
        return sh + h * (0.10 * f + 0.12 * z), head + h * (0.10 * f + 0.17 * z + sgn * 0.03 * r)
    if pose == POSE_HIT and side == "r":
        d = (np.asarray(aim) - sh) if aim is not None else (0.4 * f + z)
        d = d / max(np.linalg.norm(d), 1e-6)
        return sh + 0.17 * h * d, sh + 0.32 * h * d
    if pose == POSE_CLAP:
        chest = sh - sgn * 0.13 * h * r - 0.08 * h * z
        return sh + h * (0.08 * f - 0.12 * z), chest + h * (0.2 * f + sgn * 0.03 * r)
    # POSE_HOLD, and the free arm of POSE_HIT: hands forward at the chest
    chest = sh - sgn * 0.13 * h * r - 0.10 * h * z
    return sh + h * (0.10 * f - 0.13 * z), chest + h * (0.22 * f + sgn * 0.08 * r)


def keypoints_3d(j: dict[str, np.ndarray], heading: float, h: float) -> np.ndarray:
    """COCO-17 keypoints (person's left/right) as (17, 3) world points."""
    f = np.array([math.cos(heading), math.sin(heading), 0.0])
    r = np.array([math.sin(heading), -math.cos(heading), 0.0])
    z = np.array([0.0, 0.0, 1.0])
    hd = j["head"]
    face = [
        hd + 0.06 * h * f - 0.005 * h * z,
        hd + 0.05 * h * f - 0.03 * h * r + 0.015 * h * z,
        hd + 0.05 * h * f + 0.03 * h * r + 0.015 * h * z,
        hd - 0.06 * h * r,
        hd + 0.06 * h * r,
    ]
    body = [
        j[f"{p}_{s}"]
        for p in ("shoulder", "elbow", "wrist", "hip", "knee", "ankle")
        for s in ("l", "r")
    ]
    return np.vstack(face + body)


# --- scene: who is where, when ---------------------------------------------------


@dataclass
class Person:
    id: int
    team: int  # -1 = spectator
    name: str | None
    height: float
    jersey: tuple[int, int, int]
    shorts: tuple[int, int, int]
    skin: tuple[int, int, int]
    hair: tuple[int, int, int]
    oncourt: bool = True

    @property
    def pid(self) -> str:
        return f"p{self.id}"


@dataclass
class Scene:
    profile: Profile
    variant: str
    template: CourtTemplate
    cam: Camera
    fps: int
    t: np.ndarray
    seed: int
    people: list[Person]
    pos: np.ndarray  # (T, N, 2) court metres
    heading: np.ndarray  # (T, N)
    phase: np.ndarray
    amp: np.ndarray
    pose: np.ndarray  # (T, N) int
    pose_w: np.ndarray
    aim: np.ndarray  # (T, N, 3)
    ball: np.ndarray  # (T, 3), NaN = no ball in play
    events: list[dict]
    plays: list[dict]
    triggers: list[dict]
    sounds: list[dict]
    style: dict[str, Any]
    spectators_m: np.ndarray

    @property
    def duration_s(self) -> float:
        return len(self.t) / self.fps


class _Keys:
    """Per-person position keyframes; strong keys (contacts, shots) evict weak ones."""

    def __init__(self, n: int):
        self.k: list[dict[float, tuple[np.ndarray, bool]]] = [{} for _ in range(n)]

    def set(self, i: int, t: float, xy, strong: bool = True, gap: float = 0.5) -> None:
        d = self.k[i]
        near = [u for u in d if abs(u - t) < gap]
        if not strong and near:
            return
        for u in near:
            if not d[u][1] or abs(u - t) < 0.05:
                del d[u]
        d[round(t, 4)] = (np.asarray(xy, dtype=np.float64).copy(), strong)

    def last(self, i: int, t: float) -> np.ndarray:
        before = [u for u in self.k[i] if u <= t + 1e-9]
        return self.k[i][max(before) if before else min(self.k[i])][0]

    def sample(self, t: np.ndarray) -> np.ndarray:
        """Cubic Hermite through the keys (finite-difference tangents): velocity is
        continuous, so a player runs *through* a waypoint instead of stopping at it."""
        out = np.empty((len(t), len(self.k), 2))
        for i, d in enumerate(self.k):
            times = np.array(sorted(d))
            pts = np.array([d[u][0] for u in times])
            m = np.zeros_like(pts)
            if len(times) > 2:
                m[1:-1] = (pts[2:] - pts[:-2]) / (times[2:] - times[:-2])[:, None]
            seg = np.clip(np.searchsorted(times, t, side="right") - 1, 0, max(len(times) - 2, 0))
            if len(times) == 1:
                out[:, i] = pts[0]
                continue
            t0, t1 = times[seg], times[seg + 1]
            dt = (t1 - t0)[:, None]
            u = np.clip((t[:, None] - t0[:, None]) / dt, 0.0, 1.0)
            h00, h10 = 2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u
            h01, h11 = -2 * u**3 + 3 * u**2, u**3 - u**2
            out[:, i] = (
                h00 * pts[seg] + h10 * dt * m[seg] + h01 * pts[seg + 1] + h11 * dt * m[seg + 1]
            )
        return out


@dataclass
class _Script:
    """Everything a choreography writes; turned into arrays by `build_scene`."""

    keys: _Keys
    poses: list[tuple[int, float, float, int, Any]] = field(default_factory=list)
    ball: list[tuple] = field(default_factory=list)  # ("hold"|"arc"|"drop"|"hide", ...)
    events: list[dict] = field(default_factory=list)
    plays: list[dict] = field(default_factory=list)
    sounds: list[dict] = field(default_factory=list)
    busy: dict[int, list[tuple[float, float]]] = field(default_factory=dict)

    def event(self, kind: str, t0: float, tk: float, t1: float, **kw) -> dict:
        e = {"type": kind, "t_start": round(t0, 3), "t_key": round(tk, 3), "t_end": round(t1, 3)}
        e.update({k: v for k, v in kw.items() if v is not None})
        self.events.append(e)
        return e

    def sound(self, t: float, kind: str, gain: float = 1.0) -> None:
        self.sounds.append({"t": round(t, 4), "kind": kind, "gain": round(gain, 3)})

    def pose(self, i: int, t0: float, t1: float, kind: int, aim=None) -> None:
        self.poses.append((i, t0, t1, kind, aim))
        self.mark(i, t0, t1)

    def mark(self, i: int, t0: float, t1: float) -> None:
        self.busy.setdefault(i, []).append((t0, t1))

    def is_free(self, i: int, t0: float, t1: float) -> bool:
        return all(b < t0 or a > t1 for a, b in self.busy.get(i, []))


def _cfg(profile: Profile) -> dict[str, Any]:
    return dict((profile.model_extra or {}).get("synth") or {})


def _clip_court(xy, template: CourtTemplate, inset: float = 0.4) -> np.ndarray:
    w, length = template.size
    return np.array(
        [np.clip(xy[0], -w / 2 + inset, w / 2 - inset), np.clip(xy[1], inset, length - inset)]
    )


def _possessions(sc: _Script, people: list[Person], template: CourtTemplate, dur: float, rng):
    """Basketball-shaped choreography: possession start (inbound / steal / defensive
    rebound) -> passes -> shot (make or miss) or turnover."""
    w, length = template.size
    rims = [np.asarray(r, dtype=float) for r in (template.rims or [template.rim])]
    team_of = {p.id - 1: p.team for p in people if p.oncourt}
    members = {k: [i for i, tm in team_of.items() if tm == k] for k in (0, 1)}

    def rim_of(team: int) -> np.ndarray:
        return rims[team % len(rims)]

    def inward(rim: np.ndarray) -> np.ndarray:
        return np.array([0.0, 1.0 if rim[1] < length / 2 else -1.0])

    def spots(rim: np.ndarray) -> list[np.ndarray]:
        e = inward(rim)
        return [
            _clip_court(
                rim + 6.0 * (math.sin(a) * np.array([1.0, 0.0]) + math.cos(a) * e), template, 0.8
            )
            for a in (-1.15, -0.55, 0.0, 0.55, 1.15)
        ]

    def guard(o: np.ndarray, rim: np.ndarray) -> np.ndarray:
        d = rim - o
        return o + 1.3 * d / max(np.linalg.norm(d), 1e-6)

    # tip-off layout: team 0 attacks first
    offense, cause, handler = 0, "inbound", None
    sp = spots(rim_of(0))
    for k, i in enumerate(members[0]):
        sc.keys.set(i, 0.0, sp[k])
    for k, i in enumerate(members[1]):
        sc.keys.set(i, 0.0, guard(sp[k], rim_of(0)))
    t = 0.6
    n_play = 0
    inbounder = None
    while t < dur - 7.0:
        att, dfn = list(members[offense]), list(members[1 - offense])
        rim = rim_of(offense)
        sp = spots(rim)
        order = list(rng.permutation(len(att)))
        att = [att[k] for k in order]
        play = {"grammar": "possession", "team": offense, "participants": [], "events": []}

        if cause == "inbound":
            inb = inbounder if inbounder is not None else att[0]
            recv = next(i for i in att if i != inb)
            out_pt = np.array([rim[0] + 1.2, rim[1] - inward(rim)[1] * 2.3])  # behind baseline
            walk = max(1.0, float(np.linalg.norm(sc.keys.last(inb, t) - out_pt)) / 4.5)
            sc.keys.set(inb, t + walk, out_pt)
            t_pass = t + walk + 1.0
            sc.keys.set(inb, t_pass, out_pt)
            sc.ball.append(("hold", inb, t + walk, t_pass, "hold"))
            sc.pose(inb, t + walk, t_pass, POSE_HOLD)
            sc.ball.append(("arc", t_pass, t_pass + 0.6, ("hand", inb), ("hand", recv)))
            sc.sound(t_pass + 0.6, "catch")
            e = sc.event(
                "possession_change", t_pass, t_pass, t_pass + 0.6,
                cause="inbound", player_id=people[recv].pid, team=offense,
            )  # fmt: skip
            play["participants"] += [(inb, "inbounder"), (recv, "receiver")]
            handler, t_cur = recv, t_pass + 0.6
            sc.mark(inb, t, t_pass)
            inbounder = None
        else:
            e = sc.events[-1]  # the steal / rebound that ended the last play starts this one
            t_cur = t
            play["participants"].append((handler, "stealer" if cause == "steal" else "rebounder"))
        play["events"].append(e)
        play["t_start"] = e["t_key"]
        # bring the ball up if this end is far away (full court)
        here = sc.keys.last(handler, t_cur)
        transit = max(0.0, (abs(here[1] - sp[0][1]) - 6.0) / 5.0)
        t_set = t_cur + transit
        for k, i in enumerate(att):
            if i not in (handler,) or transit > 0:
                # the inbounder jogs in from out of bounds: give them the time to
                run = float(np.linalg.norm(sc.keys.last(i, t_cur) - sp[k])) / 5.5
                sc.keys.set(i, max(t_set + 0.3, t_cur + run), sp[k], strong=False)
        for k, i in enumerate(dfn):
            sc.keys.set(i, t_set + 0.3, guard(sp[k], rim), strong=False)

        t_shot = min(t_set + rng.uniform(4.0, 6.5), dur - 3.0)
        passes, tp = [], t_cur
        while (t_next := tp + rng.uniform(1.4, 2.2)) <= t_shot - 1.4:
            passes.append(t_next)
            tp = t_next + 0.55
        steal_at = (
            int(rng.integers(len(passes))) if passes and n_play > 0 and rng.random() < 0.2 else -1
        )
        t_stop = passes[steal_at] + 0.35 if steal_at >= 0 else t_shot
        # drift around the spots every ~1.4 s, defence shadowing
        tk = t_set + 1.4
        while tk < t_stop - 0.6:
            for k, i in enumerate(att):
                p = _clip_court(sp[k] + rng.normal(0, 0.9, 2), template, 0.8)
                sc.keys.set(i, tk, p, strong=False)
                sc.keys.set(dfn[k], tk + 0.3, guard(p, rim), strong=False)
            tk += rng.uniform(1.2, 1.7)

        # passes
        tp = t_cur
        turnover = False
        for n_pass, t_next in enumerate(passes):
            turnover = n_pass == steal_at
            sc.ball.append(("hold", handler, tp, t_next, "dribble"))
            sc.mark(handler, tp, t_next)
            recv = att[int(rng.integers(len(att)))]
            if recv == handler:
                recv = att[(att.index(recv) + 1) % len(att)]
            if turnover:
                stealer = dfn[att.index(recv)]
                t_int = t_next + 0.35
                a = sc.keys.last(handler, t_next)
                b = sc.keys.last(recv, t_next)
                spot = a + 0.6 * (b - a)
                sc.keys.set(stealer, t_int, spot)
                sc.ball.append(("arc", t_next, t_int, ("hand", handler), ("hand", stealer)))
                sc.sound(t_int, "catch")
                to = sc.event(
                    "turnover", t_next, t_int, t_int,
                    cause="steal", player_id=people[handler].pid, team=offense,
                )  # fmt: skip
                # the next play's start event (picked up as sc.events[-1])
                sc.event(
                    "possession_change", t_int, t_int, t_int,
                    cause="steal", player_id=people[stealer].pid, team=1 - offense,
                )  # fmt: skip
                play["events"] += [to]
                play["participants"] += [(handler, "turnover"), (stealer, "stealer")]
                play["t_end"] = round(t_int, 3)
                sc.plays.append(play)
                sc.mark(stealer, t_int - 0.5, t_int + 1.0)
                handler, cause, offense, t = stealer, "steal", 1 - offense, t_int
                break
            sc.ball.append(("arc", t_next, t_next + 0.55, ("hand", handler), ("hand", recv)))
            sc.sound(t_next + 0.55, "catch")
            ev = sc.event(
                "pass", t_next, t_next, t_next + 0.55,
                player_id=people[handler].pid, receiver_id=people[recv].pid, team=offense,
            )  # fmt: skip
            play["events"].append(ev)
            play["participants"].append((handler, "passer"))
            sc.mark(recv, t_next, t_next + 0.8)
            handler, tp = recv, t_next + 0.55
        if turnover:
            n_play += 1
            continue

        # the shot
        shooter = handler
        spot = _clip_court(sc.keys.last(shooter, t_shot - 0.6), template, 0.8)
        sc.keys.set(shooter, t_shot - 0.6, spot)
        sc.keys.set(shooter, t_shot + 0.4, spot)
        sc.ball.append(("hold", shooter, tp, t_shot - 0.45, "dribble"))
        sc.ball.append(("hold", shooter, t_shot - 0.45, t_shot, "overhead"))
        sc.pose(shooter, t_shot - 0.5, t_shot + 0.3, POSE_SHOOT)
        sc.mark(shooter, tp, t_shot + 0.3)
        dist = float(np.linalg.norm(spot - rim))
        flight = 0.85 + 0.035 * dist
        t_rim = t_shot + flight
        made = bool(rng.random() < 0.55)
        rim3 = np.array([rim[0], rim[1], RIM_H_M])
        if made:
            sc.ball.append(("arc", t_shot, t_rim, ("hand", shooter), rim3 + [0, 0, 0.12]))
            sc.ball.append(
                ("drop", t_rim, t_rim + 2.6, rim3 + [0, 0, 0.12], np.array([0.0, 0.0, -1.5]))
            )
            sc.sound(t_rim, "swish")
            sc.sound(t_rim + 0.25, "cheer", 1.0)
        else:
            toward = (spot - rim) / max(dist, 1e-6)
            front = rim3 + np.r_[toward * RIM_R_M, 0.05]
            sc.ball.append(("arc", t_shot, t_rim, ("hand", shooter), front))
            sc.sound(t_rim, "rim")
        shot = sc.event(
            "shot", t_shot - 0.6, t_shot, t_rim, made=made, player_id=people[shooter].pid,
            team=offense, court=[round(float(spot[0]), 3), round(float(spot[1]), 3)],
        )  # fmt: skip
        play["events"].append(shot)
        play["participants"].append((shooter, "shooter"))
        if made:
            play["t_end"] = round(t_rim + 1.0, 3)
            sc.plays.append(play)
            # the other team picks the ball up under the rim and inbounds it
            t = t_rim + 1.0
            cause, offense = "inbound", 1 - offense
            inbounder = min(
                members[offense], key=lambda i: np.linalg.norm(sc.keys.last(i, t) - rim)
            )
            sc.keys.set(inbounder, t_rim + 1.4, rim + inward(rim) * 0.6)
            sc.ball.append(("hold", inbounder, t_rim + 1.5, t + 1.0, "hold"))
        else:
            ang = rng.uniform(-0.7, 0.7)
            e_in = inward(rim)
            rot = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
            reb = _clip_court(rim + 2.6 * (rot @ e_in), template, 0.6)
            rebounder = min(dfn, key=lambda i: np.linalg.norm(sc.keys.last(i, t_rim) - reb))
            t_reb = t_rim + 0.9
            sc.keys.set(rebounder, t_reb, reb)
            sc.ball.append(("arc", t_rim, t_reb, front, ("hand", rebounder)))
            sc.sound(t_reb, "catch")
            sc.pose(rebounder, t_reb - 0.3, t_reb + 0.3, POSE_HOLD)
            play["t_end"] = round(t_rim + 0.5, 3)
            sc.plays.append(play)
            sc.event(
                "possession_change", t_reb, t_reb, t_reb, cause="defensive_rebound",
                player_id=people[rebounder].pid, team=1 - offense,
            )  # fmt: skip
            handler, cause, offense, t = rebounder, "defensive_rebound", 1 - offense, t_reb
        n_play += 1


def _rallies(
    sc: _Script, people: list[Person], template: CourtTemplate, cfg: dict, dur: float, rng
):
    """Net-sport choreography: serve -> contacts (with same-side touches) -> point."""
    w, length = template.size
    net = float(template.net_y if template.net_y is not None else length / 2)
    net_h = float((template.model_extra or {}).get("net_height_m", 1.0))
    side = {p.id - 1: p.team for p in people if p.oncourt}
    members = {s: [i for i, v in side.items() if v == s] for s in (0, 1)}
    flight_lo, flight_hi = cfg.get("flight_s", [0.8, 1.3])
    touches_lo, touches_hi = cfg.get("touches_per_side", [1, 1])
    shots_lo, shots_hi = cfg.get("shots_per_rally", [3, 8])
    serve_h = float(cfg.get("serve_height_m", 1.0))
    heights = cfg.get("touch_heights_m")
    ch_lo, ch_hi = cfg.get("contact_height_m", [0.6, 1.4])

    def sgn(s: int) -> float:
        return -1.0 if s == 0 else 1.0  # near side has y < net

    def formation(s: int) -> list[np.ndarray]:
        m = len(members[s])
        cols = min(m, 3)
        rows = math.ceil(m / cols)
        half = net if s == 0 else length - net
        depths = [0.55] if rows == 1 else [0.25, 0.7]
        out = []
        for k in range(m):
            row, col = divmod(k, cols)
            x = -w / 2 + w * (col + 0.5) / cols
            out.append(np.array([x, net + sgn(s) * depths[row] * half]))
        return out

    def region(s: int, deep: float = 0.85) -> np.ndarray:
        half = net if s == 0 else length - net
        return np.array(
            [rng.uniform(-w / 2 + 0.6, w / 2 - 0.6), net + sgn(s) * rng.uniform(1.0, deep * half)]
        )

    def ballistic_ok(p0, p1, T) -> bool:
        if (p0[1] - net) * (p1[1] - net) >= 0:
            return True
        g = np.array([0.0, 0.0, -9.81])
        v = (p1 - p0 - 0.5 * g * T * T) / T
        u = (net - p0[1]) / (p1[1] - p0[1])
        tc = u * T
        return p0[2] + v[2] * tc + 0.5 * g[2] * tc * tc > net_h + 0.15

    def contact_h(k: int, n: int) -> float:
        if heights:
            seq = list(heights[: n - 1]) + [heights[-1]] if n > 1 else [heights[0]]
            return float(seq[min(k, len(seq) - 1)])
        return float(rng.uniform(ch_lo, ch_hi))

    for s in (0, 1):
        for k, i in enumerate(members[s]):
            sc.keys.set(i, 0.0, formation(s)[k])
    serving, rotation = 0, {0: 0, 1: 0}
    t = 0.5
    while t + 6.5 < dur:
        server = members[serving][rotation[serving] % len(members[serving])]
        form = {s: formation(s) for s in (0, 1)}
        serve_xy = np.array(
            [form[serving][members[serving].index(server)][0] * 0.6,
             -0.6 if serving == 0 else length + 0.6]
        )  # fmt: skip
        t_s = t + 2.2
        for s in (0, 1):
            for k, i in enumerate(members[s]):
                sc.keys.set(i, t_s - 0.4, serve_xy if i == server else form[s][k])
                sc.keys.set(i, t_s, serve_xy if i == server else form[s][k])
        sc.ball.append(("hold", server, t + 0.6, t_s - 0.15, "hold"))
        sc.pose(server, t_s - 0.15, t_s + 0.25, POSE_HIT, np.r_[serve_xy, serve_h + 0.3])
        p_prev = np.r_[serve_xy + np.array([0.0, -sgn(serving) * 0.3]), serve_h]
        hitter, h_side, t_prev = server, serving, t_s
        serve = sc.event("serve", t_s, t_s, t_s, player_id=people[server].pid, team=serving)
        play = {"grammar": "rally", "team": serving, "events": [serve], "t_start": round(t_s, 3),
                "participants": [(server, "server")]}  # fmt: skip
        h0 = round(float(p_prev[2]), 2)
        contacts = [
            sc.event(
                "contact", t_s, t_s, t_s, player_id=people[server].pid, team=serving, touch=1,
                height_m=h0,
            )
        ]  # fmt: skip
        sc.sound(t_s, "contact")
        n_shots = int(rng.integers(shots_lo, shots_hi + 1))
        for shot in range(1, n_shots + 1):
            r_side = 1 - h_side
            if shot == n_shots or t_prev > dur - 4.0:  # end the rally inside the clip
                outcome = rng.choice(["winner", "out", "net"], p=[0.5, 0.3, 0.2])
                T = float(rng.uniform(flight_lo, flight_hi))
                if outcome == "net":
                    land = np.r_[rng.uniform(-w / 2 + 0.6, w / 2 - 0.6), net, net_h * 0.7]
                elif outcome == "out":
                    half = net if r_side == 0 else length - net
                    land = np.r_[
                        region(r_side)[0], net + sgn(r_side) * (half + rng.uniform(0.4, 1.2)), 0.05
                    ]
                else:
                    opts = [region(r_side) for _ in range(8)]
                    far = [
                        min(np.linalg.norm(o - sc.keys.last(i, t_prev)) for i in members[r_side])
                        for o in opts
                    ]
                    land = np.r_[opts[int(np.argmax(far))], 0.05]
                while outcome != "net" and not ballistic_ok(p_prev, land, T) and T < 2.5:
                    T += 0.1
                t_land = t_prev + T
                sc.ball.append(("arc", t_prev, t_land, p_prev, land))
                win = h_side if outcome == "winner" else r_side
                if outcome == "net":
                    sc.ball.append(
                        (
                            "drop",
                            t_land,
                            t_land + 1.0,
                            land,
                            np.array([0.0, -sgn(h_side) * 0.5, 0.0]),
                        )
                    )
                else:
                    sc.ball.append(
                        (
                            "drop",
                            t_land,
                            t_land + 1.0,
                            land,
                            np.array([0.0, sgn(r_side) * 2.0, 2.0]),
                        )
                    )
                    sc.sound(t_land, "bounce", 0.7)
                pt = sc.event(
                    "point", t_land, t_land, t_land, winner_side=int(win), cause=str(outcome),
                    player_id=people[hitter].pid, team=int(h_side),
                )  # fmt: skip
                sc.sound(t_land + 0.3, "cheer", 1.0 if outcome == "winner" else 0.6)
                rally = sc.event(
                    "rally", t_s, t_s, t_land, contacts=len(contacts), winner_side=int(win)
                )
                play["events"] += contacts[1:] + [pt, rally]
                play["participants"].append((hitter, "last_hitter"))
                play["t_end"] = round(t_land + 0.3, 3)
                play["winner_side"] = int(win)
                sc.plays.append(play)
                serving = int(win)
                rotation[serving] += 1
                t = t_land + rng.uniform(2.6, 3.6)
                break
            # cross the net to the receiving side
            n_t = int(rng.integers(touches_lo, touches_hi + 1))
            target = region(r_side)
            recv = min(
                members[r_side], key=lambda i: np.linalg.norm(sc.keys.last(i, t_prev) - target)
            )
            for touch in range(n_t):
                T = float(rng.uniform(flight_lo, flight_hi)) if touch == 0 else 1.0
                start = sc.keys.last(recv, t_prev)
                reach = min(3.0, 4.0 * T - 0.3)
                d = target - start
                d = d * min(1.0, reach / max(np.linalg.norm(d), 1e-6))
                c_xy = _clip_court(start + d, template, 0.3)
                if touch == 0:
                    c_xy[1] = net + sgn(r_side) * max(abs(c_xy[1] - net), 1.0)
                p_c = np.r_[c_xy + np.array([0.0, -sgn(r_side) * 0.25]), contact_h(touch, n_t)]
                while touch == 0 and not ballistic_ok(p_prev, p_c, T) and T < 2.5:
                    T += 0.1
                t_c = t_prev + T
                sc.keys.set(recv, t_prev, start, strong=False, gap=0.3)
                sc.keys.set(recv, t_c, c_xy)
                sc.ball.append(("arc", t_prev, t_c, p_prev, p_c))
                sc.pose(recv, t_c - 0.3, t_c + 0.2, POSE_HIT, p_c)
                sc.sound(t_c, "contact")
                ev = sc.event(
                    "contact", t_c, t_c, t_c, player_id=people[recv].pid, team=r_side,
                    touch=touch + 1, height_m=round(float(p_c[2]), 2),
                )  # fmt: skip
                contacts.append(ev)
                play["participants"].append((recv, "hitter"))
                # everyone else shades toward the ball
                for s in (0, 1):
                    for k, i in enumerate(members[s]):
                        if i != recv:
                            p = form[s][k] + np.array([0.35 * c_xy[0], 0.0]) + rng.normal(0, 0.3, 2)
                            sc.keys.set(i, t_c, _clip_court(p, template, 0.3), strong=False)
                hitter, p_prev, t_prev = recv, p_c, t_c
                if touch < n_t - 1:  # next touch stays on this side, a teammate takes it
                    mates = [i for i in members[r_side] if i != recv]
                    recv = mates[int(rng.integers(len(mates)))] if mates else recv
                    target = sc.keys.last(recv, t_c) + rng.normal(0, 0.6, 2)
                    target[1] = net + sgn(r_side) * float(np.clip(abs(target[1] - net), 1.0, 4.0))
            h_side = r_side


def _triggers(sc: _Script, people: list[Person], dur: float, rng) -> list[dict]:
    """One trigger per play, cycling gesture / voice "clip that" / voice "clip <name>" /
    tap, each 1.5-3 s after the play ends — inside the 1-8 s window that resolves it."""
    kinds = ("gesture", "voice", "voice_name", "tap")
    out: list[dict] = []
    ends = sorted(p["t_end"] for p in sc.plays)
    for play in sc.plays:
        kind = kinds[len(out) % len(kinds)]
        lag = float(rng.uniform(1.5, 3.0))
        t0 = play["t_end"] + lag
        nxt = [e for e in ends if e > play["t_end"]]
        if t0 + 1.6 > dur or (nxt and nxt[0] <= t0 + 1.2):
            continue
        key = [
            i for i, role in play["participants"] if role in ("shooter", "last_hitter", "stealer")
        ]
        main = key[-1] if key else play["participants"][-1][0]
        trig: dict[str, Any] = {"type": "gesture" if kind == "gesture" else kind.split("_")[0]}
        if kind == "gesture":
            cands = (
                [main]
                + [i for i, _ in play["participants"]]
                + [p.id - 1 for p in people if p.oncourt]
            )
            by = next((i for i in cands if sc.is_free(i, t0 - 0.3, t0 + 1.3)), None)
            if by is None:
                continue
            sc.pose(by, t0, t0 + 1.0, POSE_X)
            trig.update(t_start=round(t0, 3), t=round(t0 + 1.0, 3), by_player_id=people[by].pid)
        elif kind == "voice":  # t = speech onset; synth_audio adds t_end
            trig.update(t=round(t0, 3), transcript="Replay, clip that")
        elif kind == "voice_name":
            trig.update(t=round(t0, 3), transcript=f"Replay, clip {people[main].name}",
                        subject_player_id=people[main].pid)  # fmt: skip
        else:
            trig.update(t=round(t0, 3))
        trig["play_ref"] = play
        out.append(trig)
    return out


def _people(profile: Profile, cfg: dict, spectators: np.ndarray, rng) -> list[Person]:
    n = profile.players.max
    colors = cfg.get("team_colors") or profile.teams.colors or list(DEFAULT_TEAM_COLORS)
    out = []
    for i in range(n):
        team = i % 2
        out.append(
            Person(
                id=i + 1,
                team=team,
                name=NAMES[i % len(NAMES)],
                height=float(rng.uniform(1.70, 1.95)),
                jersey=_bgr(colors[team]),
                shorts=(40, 40, 48) if team == 0 else (70, 70, 80),
                skin=SKIN[int(rng.integers(len(SKIN)))],
                hair=HAIR[int(rng.integers(len(HAIR)))],
            )  # fmt: skip
        )
    for j in range(len(spectators)):
        out.append(
            Person(
                id=n + 1 + j,
                team=-1,
                name=None,
                height=float(rng.uniform(1.65, 1.85)),
                jersey=(95, 95, 110),  # neutral grey: no team uses it
                shorts=(50, 50, 60),
                skin=SKIN[j % len(SKIN)],
                hair=HAIR[j % len(HAIR)],
                oncourt=False,
            )  # fmt: skip
        )
    return out


def build_scene(
    sport: str | Profile = "basketball",
    variant: str | None = None,
    *,
    duration_s: float = 40.0,
    fps: int = 30,
    size: tuple[int, int] = (1280, 720),
    seed: int = 7,
    camera: CameraSpec | None = None,
) -> Scene:
    """Script the whole clip: positions, poses, ball, events, plays, triggers, sounds."""
    profile = sport if isinstance(sport, Profile) else load_profile(sport)
    variant = variant or profile.default_variant()
    template = profile.template(variant)
    cfg = _cfg(profile)
    rng = np.random.default_rng(seed)
    w_m, l_m = template.size
    off = profile.court.margin_m
    # Off court by the profile's own `margin_m` plus a body length, or the on-court
    # filter keeps them (pickleball's margin once was 2.5 m).
    spectators = np.array([[-w_m / 2 - off - 0.8, l_m * 0.25], [-w_m / 2 - off - 1.4, l_m * 0.7]])
    people = _people(profile, cfg, spectators, rng)
    n_play = profile.players.max

    t = np.arange(int(round(duration_s * fps))) / fps
    sc = _Script(_Keys(len(people)))
    if template.rim is not None:
        _possessions(sc, people, template, duration_s, rng)
    else:
        _rallies(sc, people, template, cfg, duration_s, rng)
    for j, s in enumerate(spectators):
        sc.keys.set(n_play + j, 0.0, s)
    trig = _triggers(sc, people, duration_s, rng)
    for p in people:  # every player needs at least one key
        if not sc.keys.k[p.id - 1]:
            sc.keys.set(p.id - 1, 0.0, np.zeros(2))

    pos = sc.keys.sample(t)
    # ponytail: speed cap as a safety net for keys the script placed too close in time
    # (a player lags behind instead of teleporting); exact keys stay exact when feasible.
    step = MAX_SPEED_MPS / fps
    for f in range(1, len(t)):
        d = pos[f] - pos[f - 1]
        n = np.linalg.norm(d, axis=1, keepdims=True)
        pos[f] = pos[f - 1] + d * np.minimum(1.0, step / np.maximum(n, 1e-9))
    # idle sway so nobody is a statue; spectators stay put (they are the decoys)
    ph = rng.uniform(0, 2 * np.pi, (len(people), 2))
    sway = 0.06 * np.sin(2 * np.pi * 0.25 * t[:, None, None] + ph[None])
    sway[:, n_play:] = 0.0
    pos = pos + sway

    vel = np.gradient(pos, 1.0 / fps, axis=0) if len(t) > 1 else np.zeros_like(pos)
    speed = np.linalg.norm(vel, axis=2)
    stride = 1.3 + 0.25 * speed
    phase = np.cumsum(2 * np.pi * speed / fps / stride, axis=0) + rng.uniform(0, 6.28, len(people))
    amp = np.clip(speed / 3.5, 0.0, 1.0)

    pose = np.zeros((len(t), len(people)), dtype=np.int8)
    pose_w = np.zeros((len(t), len(people)))
    aim = np.full((len(t), len(people), 3), np.nan)
    for i, t0, t1, kind, target in sorted(sc.poses, key=lambda p: p[1]):
        ramp = 0.15
        sel = (t >= t0 - ramp) & (t <= t1 + ramp)
        w = np.clip(np.minimum(t[sel] - (t0 - ramp), (t1 + ramp) - t[sel]) / ramp, 0.0, 1.0)
        pose[sel, i] = kind
        pose_w[sel, i] = w
        if target is not None:
            aim[sel, i] = target
    # spectators clap after cheers
    for snd in sc.sounds:
        if snd["kind"] == "cheer":
            sel = (t >= snd["t"]) & (t <= snd["t"] + 1.5)
            pose[sel, n_play:] = POSE_CLAP
            pose_w[sel, n_play:] = 1.0

    style = {
        "floor": _bgr(cfg.get("floor", "#CDA06E")),
        "apron": _bgr(cfg.get("apron", "#7A4A2A")),
        "ball": _bgr(cfg.get("ball", {}).get("color", "#E0702A")),
        "ball_r": float(cfg.get("ball", {}).get("radius_m", 0.12)),
        "contact_hz": float(cfg.get("contact_sound_hz", 900)),
        "net_h": float((template.model_extra or {}).get("net_height_m", 1.0)),
    }
    args = (sc, people, t, pos, pose, pose_w, aim, phase, amp, style["ball_r"])
    ball = _resolve_ball(*args, np.zeros(pos.shape[:2]))
    heading = _headings(pos, vel, ball, template, fps)
    # the ball follows hands, and hands follow the heading: one more pass with real headings
    ball = _resolve_ball(*args, heading)

    view = cfg.get("view", "sideline")
    keep = _frame_points(template, spectators)
    cam = scene_camera(template, size, view, keep, camera)
    events, plays, triggers = _finalise(sc, trig, people, profile, variant)
    return Scene(
        profile=profile, variant=variant, template=template, cam=cam, fps=fps, t=t, seed=seed,
        people=people, pos=pos, heading=heading, phase=phase, amp=amp, pose=pose,
        pose_w=pose_w, aim=aim, ball=ball, events=events, plays=plays, triggers=triggers,
        sounds=sorted(sc.sounds, key=lambda s: s["t"]), style=style, spectators_m=spectators,
    )  # fmt: skip


def _frame_points(template: CourtTemplate, spectators: np.ndarray) -> np.ndarray:
    poly = template.polygon
    c = poly.mean(axis=0)
    grown = c + (poly - c) * (1 + 1.2 / np.maximum(np.abs(poly - c), 1e-6))
    pts = [np.column_stack([grown, np.full(len(grown), z)]) for z in (0.0, 2.0)]
    pts += [np.column_stack([spectators, np.full(len(spectators), z)]) for z in (0.0, 1.9)]
    if template.rims or template.rim is not None:
        rims = np.asarray(template.rims or [template.rim], dtype=float)
        pts.append(np.column_stack([rims, np.full(len(rims), 3.95)]))
    return np.vstack(pts)


def _hand(people, i, f, pos, heading, phase, amp, pose, pose_w, aim, which="r") -> np.ndarray:
    a = aim[f, i]
    j = rig(pos[f, i], heading[f, i], people[i].height, phase[f, i], amp[f, i],
            int(pose[f, i]), float(pose_w[f, i]), None if np.isnan(a).any() else a)  # fmt: skip
    if which == "both":
        return (j["hand_l"] + j["hand_r"]) / 2
    return j["hand_r"]


def _resolve_ball(sc, people, t, pos, pose, pose_w, aim, phase, amp, r_ball, heading):
    """Turn the script's ball intents into a (T, 3) track; floor contacts become sounds."""
    fps = 1.0 / (t[1] - t[0]) if len(t) > 1 else 30.0
    ball = np.full((len(t), 3), np.nan)
    sc.sounds[:] = [s for s in sc.sounds if s["kind"] != "dribble"]

    def frame(tt: float) -> int:
        return int(np.clip(round(tt * fps), 0, len(t) - 1))

    def point(p, tt: float) -> np.ndarray:
        if isinstance(p, tuple) and p[0] == "hand":
            return _hand(people, p[1], frame(tt), pos, heading, phase, amp, pose, pose_w, aim)
        return np.asarray(p, dtype=float)

    g = np.array([0.0, 0.0, -9.81])
    for item in sorted(sc.ball, key=lambda b: b[2] if b[0] == "hold" else b[1]):
        kind = item[0]
        if kind == "hold":
            _, i, t0, t1, mode = item
            sel = np.nonzero((t >= t0) & (t < t1))[0]
            for f in sel:
                which = "both" if mode in ("hold", "overhead") else "r"
                hnd = _hand(people, i, f, pos, heading, phase, amp, pose, pose_w, aim, which)
                if mode == "dribble":
                    z = r_ball + (0.95 - r_ball) * abs(math.cos(math.pi * 1.7 * t[f]))
                    hnd = np.array([hnd[0], hnd[1], z])
                ball[f] = hnd
            if mode == "dribble":
                # floor contacts: |cos| hits zero at t = (k + 0.5) / 1.7
                k0, k1 = math.ceil(t0 * 1.7 - 0.5), math.floor(t1 * 1.7 - 0.5)
                for k in range(k0, k1 + 1):
                    sc.sounds.append(
                        {"t": round((k + 0.5) / 1.7, 4), "kind": "dribble", "gain": 0.5}
                    )
        elif kind == "arc":
            _, t0, t1, p0, p1 = item
            a, b = point(p0, t0), point(p1, t1)
            T = max(t1 - t0, 1e-3)
            v = (b - a - 0.5 * g * T * T) / T
            sel = np.nonzero((t >= t0) & (t < t1))[0]
            s = (t[sel] - t0)[:, None]
            ball[sel] = a + v * s + 0.5 * g * s * s
        elif kind == "drop":
            _, t0, t1, p0, v0 = item
            p, v = np.asarray(p0, dtype=float).copy(), np.asarray(v0, dtype=float).copy()
            sel = np.nonzero((t >= t0) & (t < t1))[0]
            tt = t0
            for f in sel:
                dt = t[f] - tt
                tt = t[f]
                v = v + g * dt
                p = p + v * dt
                if p[2] < r_ball and v[2] < 0:
                    p[2] = r_ball
                    if v[2] < -1.0:
                        sc.sounds.append({"t": round(float(tt), 4), "kind": "dribble", "gain": 0.6})
                    v = np.array([v[0] * 0.8, v[1] * 0.8, -v[2] * 0.6])
                ball[f] = p
    return ball


def _headings(pos, vel, ball, template: CourtTemplate, fps: int) -> np.ndarray:
    """Face the ball (or the court centre without one); run where you are going when
    you are running fast."""
    centre = template.polygon.mean(axis=0)
    look = np.where(np.isfinite(ball[:, None, :2]), ball[:, None, :2], centre[None, None, :])
    d = look - pos
    want = np.arctan2(d[..., 1], d[..., 0])
    sp = np.linalg.norm(vel, axis=2)
    run = np.arctan2(vel[..., 1], vel[..., 0])
    wr = np.clip((sp - 1.5) / 1.5, 0.0, 1.0)
    vx = (1 - wr) * np.cos(want) + wr * np.cos(run)
    vy = (1 - wr) * np.sin(want) + wr * np.sin(run)
    # smooth with a ~0.2 s exponential filter on the unit vector
    a = 1.0 - math.exp(-1.0 / (0.2 * fps))
    for f in range(1, len(vx)):
        vx[f] = vx[f - 1] + a * (vx[f] - vx[f - 1])
        vy[f] = vy[f - 1] + a * (vy[f] - vy[f - 1])
    return np.arctan2(vy, vx)


def _finalise(sc: _Script, trig: list[dict], people, profile: Profile, variant: str):
    events = sorted(sc.events, key=lambda e: (e["t_key"], e["type"]))
    for n, e in enumerate(events, 1):
        e["id"] = f"e{n}"
    plays = []
    for n, p in enumerate(sorted(sc.plays, key=lambda p: p["t_start"]), 1):
        p["id"] = f"pl{n}"
        seen: dict[int, str] = {}
        for i, role in p["participants"]:
            seen.setdefault(i, role)
        plays.append(
            {
                "id": p["id"],
                "sport": profile.id,
                "grammar": p["grammar"],
                "t_start": p["t_start"],
                "t_end": p["t_end"],
                "event_ids": [e["id"] for e in p["events"]],
                "participants": [{"player_id": people[i].pid, "role": r} for i, r in seen.items()],
                "trigger": None,
                "confidence": 1.0,
                "team": p["team"],
                **({"winner_side": p["winner_side"]} if "winner_side" in p else {}),
            }  # fmt: skip
        )
    triggers = []
    for n, tr in enumerate(sorted(trig, key=lambda x: x.get("t", x.get("t_start", 0))), 1):
        play = tr.pop("play_ref")
        tr = {"id": f"tr{n}", **tr, "play_id": play["id"]}
        triggers.append(tr)
    by_id = {p["id"]: p for p in plays}
    for tr in triggers:
        by_id[tr["play_id"]]["trigger"] = {
            k: tr[k]
            for k in ("type", "t", "by_player_id", "subject_player_id", "transcript")
            if k in tr
        }
    return events, plays, triggers


# --- rendering ------------------------------------------------------------------


def _dense(pts: np.ndarray, step: float = 0.25) -> np.ndarray:
    pts = np.asarray(pts, dtype=np.float64)
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:], strict=True):
        n = max(1, int(np.linalg.norm(b - a) / step))
        out += [a + (b - a) * k / n for k in range(1, n + 1)]
    return np.asarray(out)


def _poly_px(cam: Camera, pts_xy, closed: bool) -> np.ndarray:
    pts = np.asarray(pts_xy, dtype=np.float64)
    if closed:
        pts = np.vstack([pts, pts[:1]])
    return cam.ground(_dense(pts)).round().astype(np.int32)


def render_plate(scene: Scene) -> np.ndarray:
    """Everything that never moves: wall, floor, apron, lines, backboards."""
    cam, tpl, st = scene.cam, scene.template, scene.style
    w, h = cam.size
    img = np.empty((h, w, 3), np.uint8)
    grad = np.linspace(0.75, 1.0, h)[:, None, None]
    img[:] = (np.array([70, 64, 60])[None, None, :] * grad).astype(np.uint8)
    poly = tpl.polygon
    c = poly.mean(axis=0)
    apron = c + (poly - c) * (1 + 3.0 / np.maximum(np.abs(poly - c), 1e-6))
    cv2.fillPoly(img, [_poly_px(cam, apron, True)], st["apron"], cv2.LINE_AA)
    cv2.fillPoly(img, [_poly_px(cam, poly, True)], st["floor"], cv2.LINE_AA)
    lw = max(2, int(round(w / 640)))
    cv2.polylines(img, [_poly_px(cam, poly, True)], False, (245, 245, 245), lw, cv2.LINE_AA)
    for line in tpl.features.values():
        cv2.polylines(img, [_poly_px(cam, line, False)], False, (245, 245, 245), lw, cv2.LINE_AA)
    for rim in tpl.rims or ([tpl.rim] if tpl.rim is not None else []):
        rim = np.asarray(rim, dtype=float)
        back = -1.0 if rim[1] < tpl.size[1] / 2 else 1.0
        base = np.array([rim[0], rim[1] + back * 1.8, 0.0])
        top = base + [0, 0, 3.5]
        board_y = rim[1] + back * (RIM_R_M + 0.15)
        _seg(img, None, 0, cam, base, top, 0.06, (60, 60, 70))
        _seg(
            img,
            None,
            0,
            cam,
            top,
            np.array([rim[0], board_y + back * 0.05, 3.5]),
            0.05,
            (60, 60, 70),
        )
        board = np.array(
            [
                [rim[0] + dx, board_y, z]
                for dx, z in ((-0.9, 2.9), (0.9, 2.9), (0.9, 3.95), (-0.9, 3.95))
            ]
        )
        px = cam.project(board).round().astype(np.int32)
        cv2.fillPoly(img, [px], (235, 235, 235), cv2.LINE_AA)
        cv2.polylines(img, [px], True, (40, 40, 200), lw, cv2.LINE_AA)
    return img


def _net_layer(scene: Scene) -> tuple[np.ndarray, np.ndarray] | None:
    tpl = scene.template
    if tpl.net_y is None:
        return None
    cam, net_h = scene.cam, scene.style["net_h"]
    w = tpl.size[0]
    x0, x1, y = -w / 2 - 0.3, w / 2 + 0.3, float(tpl.net_y)
    bottom = max(0.0, net_h - 0.9)
    layer = np.zeros((cam.size[1], cam.size[0], 3), np.uint8)
    alpha = np.zeros(layer.shape[:2], np.uint8)
    band = cam.project(np.array([[x0, y, bottom], [x1, y, bottom], [x1, y, net_h], [x0, y, net_h]]))
    band = band.round().astype(np.int32)
    cv2.fillPoly(layer, [band], (30, 30, 30), cv2.LINE_AA)
    cv2.fillPoly(alpha, [band], 110, cv2.LINE_AA)
    lw = max(2, int(round(cam.size[0] / 640)))
    for z in (net_h,):
        p = cam.project(np.array([[x0, y, z], [x1, y, z]])).round().astype(np.int32)
        cv2.line(layer, tuple(p[0]), tuple(p[1]), (240, 240, 240), lw + 1, cv2.LINE_AA)
        cv2.line(alpha, tuple(p[0]), tuple(p[1]), 255, lw + 1, cv2.LINE_AA)
    for x in (x0, x1):
        for img, col in ((layer, (50, 50, 55)), (alpha, 255)):
            _seg(
                img,
                None,
                0,
                cam,
                np.array([x, y, 0.0]),
                np.array([x, y, net_h + 0.05]),
                0.04,
                col,
                plain=True,
            )
    return layer, alpha


def _seg(img, lab, val, cam: Camera, a, b, r_m, color, plain=False, bounds=None) -> None:
    """A capsule from 3D point `a` to `b`, radius `r_m`, shaded like a cylinder."""
    pa, pb = cam.project(np.vstack([a, b]))
    if not (np.isfinite(pa).all() and np.isfinite(pb).all()):
        return
    da, db = cam.depth(np.vstack([a, b]))
    r = max(1.0, cam.K[0, 0] * r_m / max((da + db) / 2, 0.1))
    th = max(1, int(round(2 * r)))
    p0, p1 = tuple(pa.round().astype(int)), tuple(pb.round().astype(int))
    if plain or isinstance(color, int):
        cv2.line(img, p0, p1, color, th, cv2.LINE_AA)
    else:
        cv2.line(img, p0, p1, _shade(color, 0.55), th + 2, cv2.LINE_AA)
        cv2.line(img, p0, p1, color, th, cv2.LINE_AA)
        if th >= 4:
            off = np.array([-0.25 * r, -0.25 * r])
            q0, q1 = tuple((pa + off).round().astype(int)), tuple((pb + off).round().astype(int))
            cv2.line(img, q0, q1, _shade(color, 1.25), max(1, th // 3), cv2.LINE_AA)
    if lab is not None:
        cv2.line(lab, p0, p1, val, th)
    if bounds is not None:
        lo = np.minimum(pa, pb) - r
        hi = np.maximum(pa, pb) + r
        bounds[0] = np.minimum(bounds[0], lo)
        bounds[1] = np.maximum(bounds[1], hi)


def _disc(img, lab, val, cam: Camera, c3, r_m, color, bounds=None, shade=True) -> None:
    pc = cam.project(c3[None])[0]
    if not np.isfinite(pc).all():
        return
    r = max(1.0, cam.K[0, 0] * r_m / max(float(cam.depth(c3[None])[0]), 0.1))
    ctr, rad = tuple(pc.round().astype(int)), max(1, int(round(r)))
    if shade:
        cv2.circle(img, ctr, rad + 1, _shade(color, 0.55), -1, cv2.LINE_AA)
    cv2.circle(img, ctr, rad, color, -1, cv2.LINE_AA)
    if shade and rad >= 3:
        hl = tuple((pc - 0.3 * r).round().astype(int))
        cv2.circle(img, hl, max(1, rad // 3), _shade(color, 1.3), -1, cv2.LINE_AA)
    if lab is not None:
        cv2.circle(lab, ctr, rad, val, -1)
    if bounds is not None:
        bounds[0] = np.minimum(bounds[0], pc - r)
        bounds[1] = np.maximum(bounds[1], pc + r)


def _hull(img, lab, val, cam: Camera, pts3, color, bounds=None) -> None:
    px = cam.project(pts3)
    px = px[np.isfinite(px).all(axis=1)]
    if len(px) < 3:
        return
    hull = cv2.convexHull(px.astype(np.float32)).reshape(-1, 2)
    poly = hull.round().astype(np.int32)
    cv2.fillPoly(img, [poly], color, cv2.LINE_AA)
    cv2.polylines(img, [poly], True, _shade(color, 0.55), 1, cv2.LINE_AA)
    c = hull.mean(axis=0)
    hl = (c + (hull - c) * 0.55 + np.array([-0.12, -0.15]) * (hull.max(0) - hull.min(0))).round()
    cv2.fillPoly(img, [hl.astype(np.int32)], _shade(color, 1.12), cv2.LINE_AA)
    if lab is not None:
        cv2.fillPoly(lab, [poly], val)
    if bounds is not None:
        bounds[0] = np.minimum(bounds[0], hull.min(axis=0))
        bounds[1] = np.maximum(bounds[1], hull.max(axis=0))


def _ring(centre, axes, n=10) -> np.ndarray:
    """(n, 3) points on a horizontal ellipse: `axes` = (right vector * a, forward * b)."""
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return centre + np.cos(ang)[:, None] * axes[0] + np.sin(ang)[:, None] * axes[1]


def _draw_person(img, lab, val, cam: Camera, p: Person, j: dict, heading: float) -> np.ndarray:
    """Painter's-order mannequin; returns its pixel bounds [[x0, y0], [x1, y1]]."""
    h = p.height
    f = np.array([math.cos(heading), math.sin(heading), 0.0])
    r = np.array([math.sin(heading), -math.cos(heading), 0.0])
    up = (j["neck"] - j["pelvis"]) / np.linalg.norm(j["neck"] - j["pelvis"])
    bounds = [np.full(2, np.inf), np.full(2, -np.inf)]
    parts: list[tuple[float, Any]] = []

    def depth(pt) -> float:
        return float(cam.depth(pt[None])[0])

    def seg(a, b, rad, col):
        def draw():
            _seg(img, lab, val, cam, j[a], j[b], rad * h, col, bounds=bounds)

        parts.append((depth((j[a] + j[b]) / 2), draw))

    for s in ("l", "r"):
        j[f"thigh_{s}"] = (j[f"hip_{s}"] + j[f"knee_{s}"]) / 2
        seg(f"ankle_{s}", f"toe_{s}", 0.028, (35, 35, 40))
        seg(f"knee_{s}", f"ankle_{s}", 0.032, p.skin)
        seg(f"thigh_{s}", f"knee_{s}", 0.040, p.skin)
        seg(f"hip_{s}", f"thigh_{s}", 0.055, p.shorts)
        j[f"sleeve_{s}"] = j[f"shoulder_{s}"] + 0.45 * (j[f"elbow_{s}"] - j[f"shoulder_{s}"])
        seg(f"shoulder_{s}", f"elbow_{s}", 0.030, p.skin)
        seg(f"shoulder_{s}", f"sleeve_{s}", 0.036, p.jersey)
        seg(f"elbow_{s}", f"wrist_{s}", 0.025, p.skin)
        hand = j[f"hand_{s}"]
        parts.append(
            (depth(hand), lambda c=hand: _disc(img, lab, val, cam, c, 0.027 * h, p.skin, bounds))
        )
    pel, neck = j["pelvis"], j["neck"]
    shorts = np.vstack(
        [
            _ring(pel + 0.03 * h * up, (0.12 * h * r, 0.075 * h * f)),
            _ring(pel - 0.10 * h * up, (0.13 * h * r, 0.08 * h * f)),
        ]
    )
    torso = np.vstack(
        [
            _ring(neck - 0.05 * h * up, (0.15 * h * r, 0.07 * h * f)),
            _ring(pel + 0.02 * h * up, (0.115 * h * r, 0.07 * h * f)),
        ]
    )
    d_t = depth((neck + pel) / 2)
    parts.append((d_t + 0.001, lambda: _hull(img, lab, val, cam, shorts, p.shorts, bounds)))
    parts.append((d_t, lambda: _hull(img, lab, val, cam, torso, p.jersey, bounds)))
    seg("neck", "head", 0.03, p.skin)
    d_h = float(cam.depth(j["head"][None])[0])

    def head():
        _disc(
            img,
            lab,
            val,
            cam,
            j["head"] - 0.012 * h * f + 0.012 * h * up,
            0.068 * h,
            p.hair,
            bounds,
        )
        _disc(img, lab, val, cam, j["head"] + 0.012 * h * f, 0.060 * h, p.skin, bounds, shade=False)

    parts.append((d_h - 0.01, head))
    for _, draw in sorted(parts, key=lambda x: -x[0]):
        draw()
    return np.asarray(bounds)


def _shadow(mask, cam: Camera, xy, rad: float) -> None:
    ring = _ring(np.r_[xy, 0.0], (np.array([rad, 0, 0]), np.array([0, rad * 0.7, 0])), 14)
    px = cam.project(ring)
    if np.isfinite(px).all():
        cv2.fillPoly(mask, [px.round().astype(np.int32)], 1, cv2.LINE_AA)


def render_frame(
    scene: Scene, f: int, plate: np.ndarray, net=None
) -> tuple[np.ndarray, list[dict], list | None]:
    """Frame `f` and its ground-truth rows (one per person at least partly in frame)."""
    cam, people = scene.cam, scene.people
    w, h = cam.size
    img = plate.copy()
    lab = np.zeros((h, w), np.uint8)
    # contact shadows, multiplied in once
    mask = np.zeros((h, w), np.uint8)
    for i in range(len(people)):
        _shadow(mask, cam, scene.pos[f, i], 0.35)
    b = scene.ball[f]
    if np.isfinite(b).all():
        _shadow(mask, cam, b[:2], scene.style["ball_r"] * 1.2)
    img[mask > 0] = (img[mask > 0] * 0.62).astype(np.uint8)

    net_y = scene.template.net_y
    eye = -cam.R.T @ cam.t
    rigs, order = {}, []
    for i, p in enumerate(people):
        a = scene.aim[f, i]
        rigs[i] = rig(scene.pos[f, i], scene.heading[f, i], p.height, scene.phase[f, i],
                      scene.amp[f, i], int(scene.pose[f, i]), float(scene.pose_w[f, i]),
                      None if np.isnan(a).any() else a)  # fmt: skip
        near = net_y is not None and (scene.pos[f, i, 1] - net_y) * (eye[1] - net_y) > 0
        order.append((int(near), -float(cam.depth(rigs[i]["pelvis"][None])[0]), "p", i))
    if np.isfinite(b).all():
        near = net_y is not None and (b[1] - net_y) * (eye[1] - net_y) > 0
        order.append((int(near), -float(cam.depth(b[None])[0]), "b", -1))
    if net is not None:
        order.append((0, float("inf"), "n", -1))
    order.sort()

    full: dict[int, tuple[np.ndarray, int]] = {}
    for _, _, kind, i in order:
        if kind == "n":
            layer, alpha = net
            a = (alpha.astype(np.float32) / 255.0)[..., None]
            sel = alpha > 0
            img[sel] = (img[sel] * (1 - a[sel]) + layer[sel] * a[sel]).astype(np.uint8)
        elif kind == "b":
            _disc(img, None, 0, cam, b, scene.style["ball_r"], scene.style["ball"])
        else:
            bnd = _draw_person(img, lab, i + 1, cam, people[i], rigs[i], scene.heading[f, i])
            box = _clip_box(bnd, w, h)
            if box is not None:
                x0, y0, x1, y1 = box
                full[i] = (box, int(np.count_nonzero(lab[y0:y1, x0:x1] == i + 1)))
    for rim in scene.template.rims or (
        [scene.template.rim] if scene.template.rim is not None else []
    ):
        ring = _ring(
            np.array([rim[0], rim[1], RIM_H_M]),
            (np.array([RIM_R_M, 0, 0]), np.array([0, RIM_R_M, 0])),
            24,
        )
        px = cam.project(ring).round().astype(np.int32)
        cv2.polylines(img, [px], True, (30, 100, 235), max(2, w // 500), cv2.LINE_AA)

    rows = []
    for i, p in enumerate(people):
        if i not in full:
            continue
        (x0, y0, x1, y1), area = full[i]
        vis = np.count_nonzero(lab[y0:y1, x0:x1] == i + 1) / max(area, 1)
        kp3 = keypoints_3d(rigs[i], scene.heading[f, i], p.height)
        kp = cam.project(kp3)
        kps = []
        for x, y in kp:
            if not (np.isfinite(x) and 0 <= x < w and 0 <= y < h):
                kps.append([0, 0, 0])
                continue
            xi, yi = int(x), int(y)
            seen = (lab[max(0, yi - 2) : yi + 3, max(0, xi - 2) : xi + 3] == i + 1).any()
            kps.append([round(float(x), 1), round(float(y), 1), 2 if seen else 1])
        foot = cam.ground(scene.pos[f, i][None])[0]
        rows.append(
            {
                "id": p.id,
                "bb": [float(x0), float(y0), float(x1 - x0), float(y1 - y0)],
                "c": 0.95 if p.oncourt else 0.9,
                "ct": [round(float(v), 4) for v in scene.pos[f, i]],
                "px": [round(float(v), 2) for v in foot],
                "team": p.team,
                "oncourt": p.oncourt,
                "vis": round(float(vis), 3),
                "kp": kps,
                "kp3": np.round(kp3, 3).tolist(),  # same keypoints, court metres (z up)
            }  # fmt: skip
        )
    ball_px = None
    if np.isfinite(b).all():
        bp = cam.project(b[None])[0]
        ball_px = [round(float(bp[0]), 2), round(float(bp[1]), 2)]
    return img, rows, ball_px


def _clip_box(bnd: np.ndarray, w: int, h: int) -> tuple[int, int, int, int] | None:
    if not np.isfinite(bnd).all():
        return None
    x0, y0 = np.floor(np.maximum(bnd[0], 0)).astype(int)
    x1, y1 = np.ceil(np.minimum(bnd[1], [w, h])).astype(int)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return int(x0), int(y0), int(x1), int(y1)


# --- audio ----------------------------------------------------------------------


def voice_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        sr, n, ch = wf.getframerate(), wf.getnframes(), wf.getnchannels()
        data = np.frombuffer(wf.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if sr != AUDIO_SR:
        x = np.arange(int(len(data) * AUDIO_SR / sr)) * sr / AUDIO_SR
        data = np.interp(x, np.arange(len(data)), data).astype(np.float32)
    return data


def _tone_phrase(text: str) -> np.ndarray:
    """The labelled fallback when no TTS clip exists: one 90 ms chirp per syllable-ish."""
    n_syl = max(3, len(re.findall(r"[aeiouy]+", text.lower())))
    out = []
    for k in range(n_syl):
        n = int(0.09 * AUDIO_SR)
        tt = np.arange(n) / AUDIO_SR
        f0 = 300 + 60 * (k % 3)
        out += [0.4 * np.sin(2 * np.pi * f0 * tt) * np.hanning(n), np.zeros(int(0.04 * AUDIO_SR))]
    return np.concatenate(out).astype(np.float32)


def _noise(rng, n: int, lo: float, hi: float) -> np.ndarray:
    """Band-limited noise, shaped in the frequency domain (no scipy in this package)."""
    spec = rng.normal(size=n // 2 + 1) + 1j * rng.normal(size=n // 2 + 1)
    freqs = np.fft.rfftfreq(n, 1.0 / AUDIO_SR)
    spec *= ((freqs >= lo) & (freqs <= hi)) / np.sqrt(np.maximum(freqs, 20.0))
    x = np.fft.irfft(spec, n)
    return (x / max(float(np.sqrt((x**2).mean())), 1e-9)).astype(np.float32)


def synth_audio(scene: Scene, voice_dir: Path | None) -> tuple[np.ndarray, list[dict]]:
    """Mono `AUDIO_SR` track: crowd bed, contact/bounce/rim clicks, cheers after makes and
    points, and the voice triggers. Returns (float32 samples, voice segments)."""
    rng = np.random.default_rng(scene.seed + 1)
    n = int(round(scene.duration_s * AUDIO_SR))
    out = 0.02 * _noise(rng, n, 150, 3500)
    out *= (0.85 + 0.15 * np.sin(2 * np.pi * 0.1 * np.arange(n) / AUDIO_SR)).astype(np.float32)

    def add(x: np.ndarray, t: float) -> None:
        i = int(round(t * AUDIO_SR))
        if i >= n or i + len(x) <= 0:
            return
        x = x[max(0, -i) :]
        i = max(i, 0)
        m = min(len(x), n - i)
        out[i : i + m] += x[:m]

    def ping(freq: float, dur: float, decay: float, gain: float) -> np.ndarray:
        tt = np.arange(int(dur * AUDIO_SR)) / AUDIO_SR
        click = rng.normal(size=len(tt)) * np.exp(-tt / 0.002)
        return (gain * (np.sin(2 * np.pi * freq * tt) * np.exp(-tt / decay) + 0.3 * click)).astype(
            np.float32
        )

    hz = scene.style["contact_hz"]
    for s in scene.sounds:
        k, g = s["kind"], s["gain"]
        if k == "contact":
            add(ping(hz, 0.08, 0.015, 0.6 * g), s["t"])
        elif k == "dribble":
            add(ping(110, 0.12, 0.03, 0.5 * g), s["t"])
        elif k == "bounce":
            add(ping(140, 0.12, 0.03, 0.4 * g), s["t"])
        elif k == "catch":
            add(ping(700, 0.04, 0.006, 0.35 * g), s["t"])
        elif k == "rim":
            x = sum(ping(f, 0.5, 0.12, 0.25 * g) for f in (690, 1420, 2310))
            add(x, s["t"])
        elif k == "swish":
            m = int(0.25 * AUDIO_SR)
            add(0.08 * g * _noise(rng, m, 2000, 7000) * np.hanning(m), s["t"])
        elif k == "cheer":
            m = int(2.2 * AUDIO_SR)
            tt = np.arange(m) / AUDIO_SR
            env = np.minimum(tt / 0.2, 1.0) * np.exp(-np.maximum(tt - 0.4, 0) / 0.7)
            add(0.25 * g * _noise(rng, m, 300, 3000) * env, s["t"])

    voices = []
    for tr in scene.triggers:
        if tr["type"] != "voice":
            continue
        text = tr["transcript"]
        path = Path(voice_dir) / f"{voice_slug(text)}.wav" if voice_dir else None
        if path is not None and path.is_file():
            clip, source = _read_wav(path), "tts"
        else:
            clip, source = _tone_phrase(text), "tone-fallback"
        clip = 0.5 * clip / max(float(np.abs(clip).max()), 1e-6)
        add(clip, tr["t"])
        tr["t_end"] = round(tr["t"] + len(clip) / AUDIO_SR, 3)
        tr["voice_source"] = source
        voices.append({"t_start": tr["t"], "t_end": tr["t_end"], "text": text, "source": source})
    return np.tanh(out).astype(np.float32), voices


def write_wav(path: Path, samples: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(AUDIO_SR)
        wf.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


# --- export ---------------------------------------------------------------------


def calibration_doc(scene: Scene) -> dict[str, Any]:
    """`calibration.json` (contract shape) for the true camera."""
    cam, tpl = scene.cam, scene.template
    world = {k: [float(v[0]), float(v[1]), 0.0] for k, v in tpl.landmarks.items()}
    if tpl.rim is not None:
        # `rim` is the template's FLOOR point under the hoop; the hoop itself is `rim_top`
        # (calibrate.height_landmarks), so the pipeline's landmarks.json gets the floor point.
        world["rim_top"] = [float(tpl.rim[0]), float(tpl.rim[1]), RIM_H_M]
    if tpl.net_y is not None:
        w = tpl.size[0]
        for s, x in (("l", -w / 2), ("r", w / 2)):
            world[f"net_top_{s}"] = [x, float(tpl.net_y), scene.style["net_h"]]
    px = cam.project(np.asarray(list(world.values())))
    w, h = cam.size
    lm_px = {
        k: [round(float(p[0]), 3), round(float(p[1]), 3)]
        for k, p in zip(world, px, strict=True)
        if np.isfinite(p).all() and 0 <= p[0] < w and 0 <= p[1] < h
    }
    return {
        "schema": "replay.calibration.v1",
        "synthetic": True,
        "sport": scene.profile.id,
        "variant": scene.variant,
        "image_size": [w, h],
        "H": np.linalg.inv(cam.H_court_to_px).tolist(),
        "K": cam.K.tolist(),
        "R": cam.R.tolist(),
        "t": cam.t.tolist(),
        "dist": [cam.k1],
        "dist_model": "division_k1_about_image_centre (courtcam.distortion)",
        "reproj_err_px": 0.0,
        "landmarks_px": lm_px,
        "landmarks_world": {k: v for k, v in world.items() if k in lm_px},
    }


def pipeline_landmarks(scene: Scene, calib: dict[str, Any]) -> dict[str, Any]:
    """What a user would click: the template's floor landmarks that are in frame."""
    floor = {k: v for k, v in calib["landmarks_px"].items() if k in scene.template.landmarks}
    return {"sport": scene.profile.id, "variant": scene.variant, "landmarks_px": floor}


def generate(
    out_dir: Path,
    *,
    sport: str = "basketball",
    variant: str | None = None,
    duration_s: float = 40.0,
    fps: int = 30,
    size: tuple[int, int] = (1280, 720),
    seed: int = 7,
    camera: CameraSpec | None = None,
    voice_dir: Path | None = None,
    profile: Profile | None = None,
    video: bool = True,
) -> dict[str, Path]:
    """Write `clip.mp4` (with audio) and the ground truth into `out_dir`."""
    scene = build_scene(
        profile or sport,
        variant,
        duration_s=duration_s,
        fps=fps,
        size=size,
        seed=seed,
        camera=camera,
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    audio, voices = synth_audio(scene, voice_dir)
    plate = render_plate(scene)
    net = _net_layer(scene)
    frames = []
    proc = open_encoder(out_dir / "_video.mp4", scene.cam.size, fps) if video else None
    try:
        for f in range(len(scene.t)):
            img, rows, ball_px = render_frame(scene, f, plate, net)
            if proc is not None:
                assert proc.stdin is not None
                proc.stdin.write(np.ascontiguousarray(img).tobytes())
            b = scene.ball[f]
            frames.append(
                {
                    "f": f,
                    "t": round(float(scene.t[f]), 4),
                    "d": rows,
                    "ball": [round(float(v), 3) for v in b] if np.isfinite(b).all() else None,
                    "ball_px": ball_px,
                }  # fmt: skip
            )
    finally:
        if proc is not None:
            assert proc.stdin is not None
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError("ffmpeg failed writing the synthetic clip")
    paths = {"audio": write_wav(out_dir / "audio.wav", audio)}
    if video:
        paths["clip"] = _mux(out_dir / "_video.mp4", paths["audio"], out_dir / "clip.mp4")
    paths.update(write_truth(scene, out_dir, frames, voices))
    return paths


def _mux(video: Path, audio: Path, dest: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH")
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(video), "-i", str(audio), "-c:v", "copy",
         "-c:a", "aac", "-b:a", "64k", "-shortest", "-movflags", "+faststart", str(dest)],
        check=True,
    )  # fmt: skip
    video.unlink()
    return dest


def scene_meta(scene: Scene) -> dict[str, Any]:
    return {
        "synthetic": True,
        "generator": GT_SCHEMA,
        "sport": scene.profile.id,
        "variant": scene.variant,
        "fps": scene.fps,
        "width": scene.cam.size[0],
        "height": scene.cam.size[1],
        "duration_s": round(scene.duration_s, 4),
        "seed": scene.seed,
        "camera": scene.cam.as_dict(),
    }


def write_truth(
    scene: Scene, out_dir: Path, frames: list[dict] | None, voices: list[dict]
) -> dict[str, Path]:
    """The contract files; `ground_truth.json` (per-frame) only when `frames` is given."""
    out_dir = Path(out_dir)
    meta = scene_meta(scene)
    calib = calibration_doc(scene)
    lm = pipeline_landmarks(scene, calib)

    def dump(name: str, doc: dict, indent: int | None = 1) -> Path:
        path = out_dir / name
        path.write_text(json.dumps(doc, indent=indent), encoding="utf-8")
        return path

    gt = {
        "schema": GT_SCHEMA,
        **meta,
        "landmarks_px": lm["landmarks_px"],
        "H_court_to_px": scene.cam.H_court_to_px.tolist(),
        "spectators_m": scene.spectators_m.tolist(),
        "players": [
            {
                "id": p.id,
                "player_id": p.pid,
                "name": p.name,
                "team": p.team,
                "oncourt": p.oncourt,
                "height_m": round(p.height, 3),
            }
            for p in scene.people
        ],  # fmt: skip
        "keypoint_names": list(COCO_KEYPOINTS),
        "audio": {"sr": AUDIO_SR, "cues": scene.sounds, "voice": voices},
        "frames": frames,
    }
    paths = {"ground_truth": dump("ground_truth.json", gt, None)} if frames is not None else {}
    return paths | {
        "landmarks": dump("landmarks.json", lm),
        "calibration": dump("calibration.json", calib),
        "events": dump(
            "events.json", {"schema": "courtcam.synth_events.v1", **meta, "events": scene.events}
        ),
        "plays": dump("plays.json", {"schema": "replay.plays.v1", **meta, "plays": scene.plays}),
        "triggers": dump(
            "triggers.json", {"schema": "replay.triggers.v1", **meta, "triggers": scene.triggers}
        ),
    }


# --- golden digest (the CI drift check) --------------------------------------------

GOLDEN_SCHEMA = "courtcam.synth_golden.v1"
KEYFRAME_SIZE = (640, 360)


def keyframe_index(scene: Scene) -> int:
    """Mid-hold of the first X gesture (the frame a gesture test cares about), else 1/3 in."""
    g = [tr for tr in scene.triggers if tr["type"] == "gesture"]
    t = g[0]["t"] - 0.5 if g else scene.duration_s / 3
    return int(round(t * scene.fps))


def golden_digest(
    scene: Scene, voice_dir: Path | None, step: int = 15
) -> tuple[dict[str, Any], np.ndarray]:
    """A compact, tolerance-comparable summary of a scene (every `step`-th frame's boxes,
    court positions and visibility; keypoints every 4th of those and through the
    gesture; the ball; events/plays/triggers; a 0.5 s audio RMS envelope) plus the
    keyframe image downscaled to `KEYFRAME_SIZE`."""
    audio, voices = synth_audio(scene, voice_dir)
    plate, net = render_plate(scene), _net_layer(scene)
    key = keyframe_index(scene)
    frames, kps, ball = {}, {}, {}
    keyframe = None
    for f in sorted(set(range(0, len(scene.t), step)) | {key}):
        img, rows, _ = render_frame(scene, f, plate, net)
        if f == key:
            keyframe = cv2.resize(img, KEYFRAME_SIZE, interpolation=cv2.INTER_AREA)
        frames[str(f)] = [{k: r[k] for k in ("id", "bb", "ct", "vis")} for r in rows]
        if f % (4 * step) == 0 or f == key:
            kps[str(f)] = {str(r["id"]): r["kp"] for r in rows}
        b = scene.ball[f]
        ball[str(f)] = [round(float(v), 4) for v in b] if np.isfinite(b).all() else None
    win = AUDIO_SR // 2
    rms = np.sqrt((audio[: len(audio) // win * win].reshape(-1, win) ** 2).mean(axis=1))
    meta = scene_meta(scene)
    doc = {
        "schema": GOLDEN_SCHEMA,
        **meta,
        "regenerate": (
            f"courtcam synth --sport {scene.profile.id} --variant {scene.variant} "
            f"--duration {meta['duration_s']:g} --seed {scene.seed} "
            f"--size {scene.cam.size[0]}x{scene.cam.size[1]} --out <dir>"
        ),
        "step": step,
        "keyframe": key,
        "frames": frames,
        "keypoints": kps,
        "ball": ball,
        "audio_rms": [round(float(v), 5) for v in rms],
        "voice": voices,
        "events": scene.events,
        "plays": scene.plays,
        "triggers": scene.triggers,
    }
    assert keyframe is not None
    return doc, keyframe
