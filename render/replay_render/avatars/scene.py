"""`scene/{play_id}.json` (`replay.scene.v1`): per-frame 3D joints of every on-court
player over one highlight window, in court metres, plus the modelled ball.

Pipeline per play (see README "Tier C"): 2D keypoints per tracked player at every video
frame -> H36M-17 -> placement (MotionBERT lift, else analytic rays + bone lengths) ->
smoothing -> fixed bone lengths -> grounding -> collision avoidance between players ->
foot contacts pinned (two-bone IK). Quality numbers before/after go into the file.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
from courtcam.calibrate import RIM_HEIGHT_M
from courtcam.profiles import load_profile

from ..gamedata import load_game
from ..virtual.replays import frame_count, play, read_highlights, read_window
from . import lift as lift_mod
from . import motion
from .place import (
    Camera,
    fill_keypoints,
    lift_inputs,
    place_analytic,
    place_lifted,
    player_height,
)
from .skeleton import JOINTS, PARENT, WRISTS, coco_to_h36m

SCHEMA = "replay.scene.v1"
SCENE_REL = "scene/{play_id}.json"
MIN_FRAMES = 15  # a player seen for less than this in the window is left out
G = 9.81
BALL_R_M = 0.12
HOLD_S = 0.7  # ball shown in the shooter's hands this long before the release
PALETTE = ("#C0392B", "#2E86C1", "#7F8C8D")
YOLO_POSE = Path("/workspace/wt/replay-env/models/yolo/yolo11m-pose.pt")


# --- 2D keypoints --------------------------------------------------------------------


def _boxes(tracks, times: np.ndarray) -> np.ndarray:
    """(P, F, 4) x, y, w, h boxes at the frame times."""
    b = tracks.at(tracks.box, times)
    return np.concatenate([b[..., :2], b[..., 2:] - b[..., :2]], axis=-1)


def keypoints(
    game_dir: Path,
    video: Path,
    h: dict,
    fps: float,
    tracks,
    keep: list[int],
    *,
    source: str,
    sport: str,
    ground_truth: Path | None = None,
    pose_model: str | None = None,
) -> dict[int, np.ndarray]:
    """COCO-17 keypoints (F, 17, 3) in source pixels + score, per kept track index, at
    every frame of the window. `source`: gt (synthetic ground truth, the oracle), yolo
    (YOLO-pose on the track crops, courtcam.pose), poses (courtcam's 10 Hz poses/,
    interpolated)."""
    n = frame_count(h, fps)
    times = h["t_start"] + np.arange(n) / fps
    out = {p: np.zeros((n, 17, 3)) for p in keep}
    if source == "poses":
        from courtcam.pose import read_poses

        game = load_game(game_dir)
        poses = read_poses(Path(game_dir) / "poses")
        for p in keep:
            if tracks.ids[p] not in poses:
                continue
            ts, kp = poses[tracks.ids[p]]
            for j in range(17):
                ok = kp[:, j, 2] > 0
                if ok.sum() < 2:
                    continue
                for c, scale in ((0, game.width), (1, game.height), (2, 1.0)):
                    out[p][:, j, c] = np.interp(times, ts[ok], kp[ok, j, c]) * scale
                out[p][(times < ts[ok][0]) | (times > ts[ok][-1]), j, 2] = 0
        return out
    from courtcam import pose as pose_mod

    cfg = load_profile(sport).pose
    if source == "gt":
        poser = pose_mod.synthetic_poser(Path(ground_truth), cfg)
    elif source == "yolo":
        model = pose_model or os.environ.get("COURTCAM_POSE_MODEL")
        poser = pose_mod.yolo_poser(cfg, model or (str(YOLO_POSE) if YOLO_POSE.exists() else None))
    else:
        raise ValueError(f"unknown keypoint source {source!r}")
    boxes = _boxes(tracks, times)
    frames = read_window(video, h["t_start"], n) if source == "yolo" else None
    start = round(h["t_start"] * fps)
    for f in range(n):
        index, img = next(frames) if frames is not None else (start + f, None)
        live = [p for p in keep if np.isfinite(boxes[p, f]).all()]
        if not live:
            continue
        found = poser(index, img, [tuple(boxes[p, f]) for p in live])
        for p, res in zip(live, found, strict=True):
            if res is not None:
                out[p][f] = res[0]
    return out


# --- the ball -------------------------------------------------------------------------


def ball_arc(shot: dict, shooter: np.ndarray, rims: list, times: np.ndarray) -> dict | None:
    """Parabola from the shooter's higher wrist at the release to the rim (3.05 m):
    through the hoop and down the net on a make, off the front of the rim on a miss,
    and nothing after the rim when the outcome is unknown (no outcome is invented).
    Before the release the ball is held between the hands for `HOLD_S`."""
    if not rims:
        return None
    t0, t1 = float(shot["t_release"]), float(shot["t_rim"])
    i0 = int(np.clip(np.searchsorted(times, t0), 0, len(times) - 1))
    w = shooter[i0, list(WRISTS)]
    if not np.isfinite(w).all():
        return None
    p0 = w[np.argmax(w[:, 2])] + [0, 0, BALL_R_M]
    rim = min(rims, key=lambda r: np.hypot(r[0] - p0[0], r[1] - p0[1]))
    rim = np.array([rim[0], rim[1], RIM_HEIGHT_M])
    made = shot.get("made")
    toward = (p0 - rim)[:2] / max(np.linalg.norm((p0 - rim)[:2]), 1e-6)
    target = rim if made is not False else rim + np.r_[toward * 0.2, 0.05]
    dt = max(t1 - t0, 0.3)
    g = np.array([0.0, 0.0, -G])
    v0 = (target - p0 - 0.5 * g * dt * dt) / dt
    pos = np.full((len(times), 3), np.nan)
    for f, t in enumerate(times):
        s = t - t0
        if -HOLD_S <= s < 0:
            hands = shooter[f, list(WRISTS)]
            if np.isfinite(hands).all():
                pos[f] = hands.mean(axis=0) + [0, 0, BALL_R_M]
        elif 0 <= s <= dt:
            pos[f] = p0 + v0 * s + 0.5 * g * s * s
        elif s > dt:
            q = s - dt
            if made is True:  # down through the net to the floor
                z = RIM_HEIGHT_M - 1.0 * q - 0.5 * G * q * q
                if z > BALL_R_M:
                    pos[f] = [rim[0], rim[1], z]
            elif made is False:  # off the front of the rim, back toward the shooter
                v = np.r_[toward * 1.5, 2.0]
                p = target + v * q + 0.5 * g * q * q
                if p[2] > BALL_R_M:
                    pos[f] = p
    return {
        "model": "parabola",
        "event_id": shot.get("event_id"),
        "shooter": shot.get("player_id"),
        "t_release": t0,
        "t_rim": t1,
        "made": made,
        "release": np.round(p0, 3).tolist(),
        "target": np.round(target, 3).tolist(),
        "radius_m": BALL_R_M,
        "positions": [None if not np.isfinite(p).all() else np.round(p, 3).tolist() for p in pos],
    }


# --- the scene ------------------------------------------------------------------------


def _on_court(court: np.ndarray, polygon: np.ndarray, margin: float = 1.0) -> bool:
    xy = np.nanmedian(court, axis=0)
    if not np.isfinite(xy).all():
        return False
    lo, hi = polygon.min(axis=0) - margin, polygon.max(axis=0) + margin
    return bool(((xy >= lo) & (xy <= hi)).all())


def _colors(game) -> dict[str, tuple[int | None, str]]:
    teams = {t["id"]: t.get("color_hex") for t in game.game.get("teams") or []}
    out = {}
    for pid, p in game.players.items():
        team = p.get("team")
        out[pid] = (team, teams.get(team) or PALETTE[team if team in (0, 1) else 2])
    return out


def build(
    game_dir: Path,
    play_id: str,
    video: Path,
    *,
    method: str = "auto",
    kp_source: str = "auto",
    ground_truth: Path | None = None,
    pose_model: str | None = None,
    keep_raw: bool = False,
) -> dict[str, Any]:
    """The scene document for one highlight. `method`: auto | motionbert | analytic."""
    started = time.time()
    gd = Path(game_dir)
    game = load_game(gd)
    h = play(gd, play_id)
    synthetic = bool(read_highlights(gd).get("synthetic"))
    cal = json.loads((gd / "calibration.json").read_text(encoding="utf-8"))
    cam = Camera.from_calibration(cal)
    fps = game.fps
    n = frame_count(h, fps)
    times = h["t_start"] + np.arange(n) / fps
    tracks = game.tracks
    court = tracks.at(tracks.court, times)
    tpl = load_profile(cal.get("sport") or game.sport).template(cal.get("variant"))
    rims = [tuple(r) for r in (tpl.rims or ([tpl.rim] if tpl.rim else []))]
    keep = [
        p
        for p in range(len(tracks.ids))
        if np.isfinite(court[p, :, 0]).sum() >= MIN_FRAMES and _on_court(court[p], tpl.polygon)
    ]
    if kp_source == "auto":
        kp_source = "gt" if ground_truth else "yolo"
    if method == "auto":
        method = "motionbert" if lift_mod.available() else "analytic"
    kps = keypoints(gd, video, h, fps, tracks, keep, source=kp_source, sport=game.sport,
                    ground_truth=ground_truth, pose_model=pose_model)  # fmt: skip

    placed: dict[int, np.ndarray] = {}
    heights: dict[int, float] = {}
    todo = []  # (p, slice, kp, court, height, inputs, r_virt) for the lifter
    for p in keep:
        kp = fill_keypoints(coco_to_h36m(kps[p]))
        xy = court[p]
        ok = np.isfinite(kp[:, 0, 0]) & np.isfinite(xy[:, 0])
        if ok.sum() < MIN_FRAMES:
            continue
        height = player_height(cam, kp, xy)
        heights[p] = height
        joints = np.full((n, 17, 3), np.nan)
        for s, e in motion._segments(ok):
            if e - s < MIN_FRAMES:
                continue
            if method == "motionbert":
                x, rv = lift_inputs(cam, kp[s:e], xy[s:e], height)
                todo.append((p, s, e, kp[s:e], xy[s:e], height, x, rv))
            else:
                joints[s:e] = place_analytic(cam, kp[s:e], xy[s:e], height)
        placed[p] = joints
    if todo:
        lifted = lift_mod.lift([t[6] for t in todo], fps)
        for (p, s, e, kp, xy, height, _, rv), y in zip(todo, lifted, strict=True):
            placed[p][s:e] = place_lifted(cam, kp, y, rv, xy, height)

    order = [p for p in keep if p in placed and np.isfinite(placed[p][:, 0, 0]).any()]
    raw = [motion.ground(placed[p], fps) for p in order]
    clean = [motion.ground(motion.fix_bones(motion.smooth_joints(j, fps)), fps) for j in raw]
    clean = motion.separate(clean, fps)
    final, planted = [], []
    for j in clean:
        c = motion.contacts(j, fps)
        final.append(motion.pin_feet(j, c))
        planted.append(c)

    quality = _quality(raw, final, planted, fps)
    colors = _colors(game)
    players = []
    for k, p in enumerate(order):
        pid = tracks.ids[p]
        team, color = colors.get(pid, (None, PALETTE[2]))
        players.append(
            {
                "id": pid,
                "team": team,
                "color": color,
                "label": game.player_label(pid),
                "height_m": round(heights[p], 3),
                "joints": [
                    None if not np.isfinite(fr).all() else np.round(fr, 3).tolist()
                    for fr in final[k]
                ],
                "planted": planted[k].astype(int).tolist(),
            }
        )
    ball = None
    shot = h.get("shot")
    if shot and shot.get("player_id") in tracks.ids:
        p = tracks.index(shot["player_id"])
        if p in order:
            ball = ball_arc(shot, final[order.index(p)], rims, times)
    doc = {
        "schema": SCHEMA,
        "play_id": play_id,
        "label": h.get("label"),
        "sport": game.sport,
        "variant": cal.get("variant"),
        "synthetic": synthetic,
        "fps": fps,
        "t_start": h["t_start"],
        "t_end": h["t_end"],
        "frames": n,
        "units": "m",
        "axes": "court template frame: x, y on the floor, z up",
        "method": method,
        "keypoints": kp_source,
        "skeleton": {"format": "h36m17", "joints": list(JOINTS), "parents": list(PARENT)},
        "camera": {k: cal[k] for k in ("K", "R", "t", "dist", "image_size") if k in cal},
        "court": {"rims": [list(r) for r in rims], "rim_height_m": RIM_HEIGHT_M},
        "primary": h.get("primary"),
        "shooter": (shot or {}).get("player_id"),
        "players": players,
        "ball": ball,
        "quality": {**quality, "build_s": round(time.time() - started, 2)},
    }
    if keep_raw:
        doc["_raw"] = {tracks.ids[p]: r for p, r in zip(order, raw, strict=True)}
        doc["_final"] = {tracks.ids[p]: f for p, f in zip(order, final, strict=True)}
    return doc


def _quality(raw: list, final: list, planted: list, fps: float) -> dict[str, Any]:
    def mean(fn, arrs) -> float:
        v = [fn(a) for a in arrs]
        v = [x for x in v if np.isfinite(x)]
        return round(float(np.mean(v)), 4) if v else float("nan")

    pairs = list(zip(raw, final, planted, strict=True))
    return {
        "players": len(final),
        "jitter_ms2": {
            "before": mean(lambda j: motion.jitter(j, fps), raw),
            "after": mean(lambda j: motion.jitter(j, fps), final),
        },
        "foot_slide_cms": {
            "before": mean(lambda q: motion.foot_slide(q[0], q[2], fps), pairs),
            "after": mean(lambda q: motion.foot_slide(q[1], q[2], fps), pairs),
        },
        "bone_cv": {"before": mean(motion.bone_cv, raw), "after": mean(motion.bone_cv, final)},
        "penetration": {
            "before": round(motion.penetration(raw), 4),
            "after": round(motion.penetration(final), 4),
        },
        "planted_frac": round(float(np.mean([c.mean() for c in planted])), 3) if planted else 0,
    }


def write(game_dir: Path, play_id: str, doc: dict) -> Path:
    path = Path(game_dir) / SCENE_REL.format(play_id=play_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {k: v for k, v in doc.items() if not k.startswith("_")}
    path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    return path


def read(game_dir: Path, play_id: str) -> dict:
    return json.loads((Path(game_dir) / SCENE_REL.format(play_id=play_id)).read_text("utf-8"))


def joints_array(doc: dict) -> list[np.ndarray]:
    """Players' joints as (F, 17, 3) arrays (NaN where absent)."""
    out = []
    for p in doc["players"]:
        a = np.full((doc["frames"], 17, 3), np.nan)
        for f, fr in enumerate(p["joints"]):
            if fr is not None:
                a[f] = fr
        out.append(a)
    return out
