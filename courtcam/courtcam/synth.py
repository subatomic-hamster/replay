"""Synthetic test clip generator (plan §7.4).

Renders a sport profile's court template through a plausible elevated-sideline
camera, moves `players.max` coloured figures on it plus a couple of off-court
spectators, and writes ground-truth boxes/positions. YOLO will not detect these
shapes, so `--detector synthetic` replays the ground truth instead and the rest of
the pipeline is exercised unchanged in CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .profiles import CourtTemplate, Profile, load_profile
from .render import open_encoder

GT_SCHEMA = "courtcam.synth.v1"
PLAYER_H_M = 1.82
BALL_R_M = 0.12
TEAM_BGR = ((160, 79, 31), (232, 232, 232))  # #1F4FA0, #E8E8E8
SPECTATOR_BGR = (60, 120, 60)
FLOOR_BGR = (120, 170, 205)
LINE_BGR = (250, 250, 250)


@dataclass(frozen=True, slots=True)
class Camera:
    """Pinhole camera looking at the court; ground plane z = 0 is the court."""

    P: np.ndarray  # (3, 4) projection matrix

    def project(self, pts_xyz: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts_xyz, dtype=np.float64).reshape(-1, 3)
        hom = np.column_stack([pts, np.ones(len(pts))]) @ self.P.T
        return hom[:, :2] / hom[:, 2:3]

    def ground(self, pts_xy: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts_xy, dtype=np.float64).reshape(-1, 2)
        return self.project(np.column_stack([pts, np.zeros(len(pts))]))

    @property
    def H_court_to_px(self) -> np.ndarray:
        h = self.P[:, [0, 1, 3]]
        return h / h[2, 2]


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
    """Elevated sideline camera, auto-framed so the court and `extra_xy` all fit."""
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
    return Camera(k @ np.column_stack([r, t]))


# --- choreography -----------------------------------------------------------


def _paths(
    template: CourtTemplate, n: int, duration_s: float, fps: int, rng: np.random.Generator
) -> np.ndarray:
    """(T, n, 2) smooth court-metre paths, kept a little inside the lines."""
    w_m, l_m = template.size
    t = np.arange(int(duration_s * fps)) / fps
    half_w, inset = w_m / 2 - 1.0, 1.0
    out = np.empty((len(t), n, 2))
    for i in range(n):
        cx = rng.uniform(-half_w * 0.6, half_w * 0.6)
        cy = rng.uniform(inset + 1.5, l_m - inset - 1.5)
        ax, ay = rng.uniform(1.5, half_w * 0.55), rng.uniform(1.5, (l_m - 2 * inset) * 0.35)
        wx, wy = rng.uniform(0.15, 0.5), rng.uniform(0.15, 0.5)
        px, py = rng.uniform(0, 2 * np.pi, 2)
        out[:, i, 0] = np.clip(cx + ax * np.sin(2 * np.pi * wx * t + px), -half_w, half_w)
        out[:, i, 1] = np.clip(cy + ay * np.sin(2 * np.pi * wy * t + py), inset, l_m - inset)
    return out


def _drive_to(paths: np.ndarray, player: int, fps: int, t_key: float, spot: np.ndarray) -> None:
    """Blend one player's path toward `spot` around `t_key` so a shot has a shooter."""
    t = np.arange(len(paths)) / fps
    w = np.clip(1.0 - np.abs(t - t_key) / 2.0, 0.0, 1.0)[:, None]
    paths[:, player] = (1 - w) * paths[:, player] + w * spot


def _ball(rim_xy: np.ndarray, shooter: np.ndarray, t: np.ndarray, t_key: float) -> np.ndarray:
    """(T, 3) ball position: arc up to the rim at `t_key`, then drop through it."""
    rim = np.array([rim_xy[0], rim_xy[1], 3.05])
    start = np.array([shooter[0], shooter[1], 2.0])
    out = np.full((len(t), 3), np.nan)
    up = (t >= t_key - 0.9) & (t <= t_key)
    s = np.clip((t[up] - (t_key - 0.9)) / 0.9, 0, 1)[:, None]
    out[up] = start + (rim - start) * s + np.array([0, 0, 1.6]) * (s * (1 - s) * 4)
    down = (t > t_key) & (t <= t_key + 0.7)
    s = np.clip((t[down] - t_key) / 0.7, 0, 1)[:, None]
    out[down] = rim + (np.array([rim[0], rim[1], 0.0]) - rim) * (s**2)
    return out


# --- drawing ----------------------------------------------------------------


def _draw_court(frame: np.ndarray, cam: Camera, template: CourtTemplate) -> None:
    cv2.fillPoly(frame, [cam.ground(template.polygon).astype(np.int32)], FLOOR_BGR)
    cv2.polylines(frame, [cam.ground(template.polygon).astype(np.int32)], True, LINE_BGR, 3)
    for line in template.features.values():
        cv2.polylines(frame, [cam.ground(np.asarray(line)).astype(np.int32)], False, LINE_BGR, 2)
    if template.rim is not None:
        rim = np.asarray(template.rim)
        top = cam.project(np.array([[rim[0], rim[1], 3.05]]))[0]
        base = cam.ground(rim[None, :])[0]
        cv2.line(frame, base.astype(int), top.astype(int), (40, 40, 40), 3)
        cv2.circle(frame, top.astype(int), 8, (0, 120, 240), 3)


def _figure(frame: np.ndarray, cam: Camera, xy: np.ndarray, bgr) -> list[float] | None:  # noqa: ANN001
    """Draw one person standing at court point `xy`; returns their px box [x, y, w, h]."""
    feet = cam.ground(xy[None, :])[0]
    head = cam.project(np.array([[xy[0], xy[1], PLAYER_H_M]]))[0]
    h = float(feet[1] - head[1])
    if not np.isfinite(h) or h < 6:
        return None
    w = max(4.0, h * 0.34)
    cx = float(feet[0])
    top = float(head[1])
    # legs, torso (the jersey the team split reads), head
    cv2.rectangle(
        frame,
        (int(cx - w * 0.35), int(top + h * 0.55)),
        (int(cx + w * 0.35), int(feet[1])),
        (70, 70, 80),
        -1,
    )
    cv2.ellipse(
        frame, (int(cx), int(top + h * 0.33)), (int(w * 0.5), int(h * 0.26)), 0, 0, 360, bgr, -1
    )
    cv2.circle(frame, (int(cx), int(top + h * 0.09)), max(2, int(h * 0.09)), (120, 160, 200), -1)
    return [cx - w / 2, top, w, h]


def generate(
    out_dir: Path,
    *,
    sport: str = "basketball",
    variant: str | None = None,
    duration_s: float = 20.0,
    fps: int = 30,
    size: tuple[int, int] = (1280, 720),
    seed: int = 7,
    shots_at: tuple[float, ...] = (6.0, 13.5),
    profile: Profile | None = None,
) -> dict[str, Path]:
    """Write `clip.mp4`, `ground_truth.json` and `landmarks.json` into `out_dir`."""
    profile = profile or load_profile(sport)
    variant = variant or profile.default_variant()
    template = profile.template(variant)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    n_players = profile.players.max
    w_m, l_m = template.size
    spectators = np.array([[-w_m / 2 - 1.8, l_m * 0.25], [-w_m / 2 - 2.4, l_m * 0.7]])
    cam = make_camera(template, size, spectators)

    paths = _paths(template, n_players, duration_s, fps, rng)
    rim = np.asarray(template.rim if template.rim is not None else [0.0, 2.0])
    for k, t_key in enumerate(shots_at):
        spot = rim + np.array([2.5 * (1 if k % 2 else -1), 3.2])
        _drive_to(paths, 0, fps, t_key, spot)

    t = np.arange(len(paths)) / fps
    balls = np.full((len(t), 3), np.nan)
    for t_key in shots_at:
        b = _ball(rim, paths[min(int(t_key * fps), len(paths) - 1), 0], t, t_key)
        balls = np.where(np.isfinite(b), b, balls)

    teams = [i % 2 for i in range(n_players)]
    clip = out_dir / "clip.mp4"
    proc = open_encoder(clip, size, fps)
    assert proc.stdin is not None
    frames: list[dict] = []
    try:
        for f in range(len(t)):
            frame = np.full((size[1], size[0], 3), (45, 40, 38), np.uint8)
            _draw_court(frame, cam, template)
            rows = []
            for i in range(n_players):
                box = _figure(frame, cam, paths[f, i], TEAM_BGR[teams[i]])
                if box:
                    rows.append(
                        {
                            "id": i + 1,
                            "bb": [round(v, 2) for v in box],
                            "c": 0.95,
                            "ct": [round(float(v), 4) for v in paths[f, i]],
                            "team": teams[i],
                            "oncourt": True,
                        }
                    )
            for j, s in enumerate(spectators):
                box = _figure(frame, cam, s, SPECTATOR_BGR)
                if box:
                    rows.append(
                        {
                            "id": n_players + 1 + j,
                            "bb": [round(v, 2) for v in box],
                            "c": 0.9,
                            "ct": [round(float(v), 4) for v in s],
                            "team": -1,
                            "oncourt": False,
                        }
                    )
            if np.isfinite(balls[f]).all():
                p = cam.project(balls[f][None, :])[0]
                r = max(3, int(abs(cam.ground(rim[None, :])[0][1] - p[1]) * 0 + 9))
                cv2.circle(frame, p.astype(int), r, (30, 120, 235), -1)
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
            frames.append({"f": f, "t": round(float(t[f]), 4), "d": rows})
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed writing the synthetic clip")

    landmarks_px = {
        name: [round(float(v), 3) for v in cam.ground(np.asarray(xy)[None, :])[0]]
        for name, xy in template.landmarks.items()
    }
    gt = {
        "schema": GT_SCHEMA,
        "sport": profile.id,
        "variant": variant,
        "fps": fps,
        "width": size[0],
        "height": size[1],
        "duration_s": float(duration_s),
        "seed": seed,
        "shots_at": list(shots_at),
        "landmarks_px": landmarks_px,
        "H_court_to_px": cam.H_court_to_px.tolist(),
        "spectators_m": spectators.tolist(),
        "frames": frames,
    }
    gt_path = out_dir / "ground_truth.json"
    gt_path.write_text(json.dumps(gt), encoding="utf-8")
    lm_path = out_dir / "landmarks.json"
    lm_path.write_text(
        json.dumps(
            {"sport": profile.id, "variant": variant, "landmarks_px": landmarks_px}, indent=1
        ),
        encoding="utf-8",
    )
    return {"clip": clip, "ground_truth": gt_path, "landmarks": lm_path}
