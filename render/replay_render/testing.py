"""A tiny, fully synthetic game dir for tests (render/ and the worker's broadcast stage).

640x360 test-pattern video with a tone, a pinhole camera (its ground homography in
calib.json), four players who stand still for 6 s and then run, and two made shots.
Labelled synthetic in game.json.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np

W, H, FPS = 640, 360, 30


def _camera() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A pinhole camera 20 m off the left sideline, 10 m up, looking at centre court."""
    eye, target = np.array([-20.0, 14.0, 10.0]), np.array([0.0, 14.0, 0.0])
    f = (target - eye) / np.linalg.norm(target - eye)
    r = np.cross(f, [0.0, 0.0, 1.0])
    r /= np.linalg.norm(r)
    rot = np.vstack([r, np.cross(f, r), f])
    k = np.array([[420.0, 0, W / 2], [0, 420.0, H / 2], [0, 0, 1]])
    return k, rot, -rot @ eye


K, R, T = _camera()
H_INV = (K @ np.column_stack([R[:, 0], R[:, 1], T])).tolist()  # court (x, y) -> px


def project(xyz: np.ndarray) -> np.ndarray:
    p = (np.asarray(xyz, dtype=np.float64) @ R.T + T) @ K.T
    return p[:, :2] / p[:, 2:3]


SHOTS = [
    {"id": "e1", "t_key": 9.0, "player_id": "p1", "team": 0, "points": 2},
    {"id": "e2", "t_key": 19.0, "player_id": "p3", "team": 1, "points": 3},
]


def _court_to_px(xy: np.ndarray) -> np.ndarray:
    p = np.column_stack([xy, np.ones(len(xy))]) @ np.asarray(H_INV).T
    return p[:, :2] / p[:, 2:3]


def positions(t: float) -> dict[str, tuple[float, float]]:
    """Still until 6 s, then running up and down the court (~3 m/s)."""
    run = max(0.0, t - 6.0)
    out = {}
    for k, pid in enumerate(("p1", "p2", "p3", "p4")):
        x = -4.5 + 3.0 * k
        y = 14.0 + 9.0 * np.sin(run / 3.0 + 0.3 * k) if run else 10.0 + 2.0 * k
        out[pid] = (x, float(y))
    return out


def make_toy_game(gd: Path, duration: float = 24.0, video: bool = True) -> Path:
    gd = Path(gd)
    (gd / "media").mkdir(parents=True, exist_ok=True)
    if video:
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        subprocess.run(
            [ffmpeg, "-y", "-v", "error",
             "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:duration={duration}",
             "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(gd / "media" / "wide.mp4")],
            check=True,
        )  # fmt: skip
    h_inv = np.asarray(H_INV)
    corners = np.asarray([[-7.5, 0], [7.5, 0], [7.5, 28], [-7.5, 28]], dtype=np.float64)
    calib = {
        "schema": "courtcam.calib.v1",
        "sport": "basketball",
        "variant": "full",
        "H": np.linalg.inv(h_inv).tolist(),
        "H_inv": H_INV,
        "court_polygon_px": _court_to_px(corners).tolist(),
        "k1": 0.0,
    }
    (gd / "calib.json").write_text(json.dumps(calib))
    players = [
        {"id": f"p{i}", "name": "Avery" if i == 1 else None, "team": 0 if i <= 2 else 1,
         "color_hex": "#C0392B" if i <= 2 else "#2E86C1", "tagged": i == 1}
        for i in range(1, 5)
    ]  # fmt: skip
    game = {
        "schema": "replay.game.v1",
        "id": gd.name,
        "title": "toy (synthetic)",
        "synthetic": True,
        "status": "ready",
        "stages": {},
        "video": {"duration_s": duration, "fps": FPS, "width": W, "height": H},
        "sport": "basketball",
        "court": {"variant": "full", "standard": "fiba"},
        "renditions": {"wide": "media/wide.mp4", "players": {}},
        "players": players,
        "teams": [{"id": 0, "color_hex": "#C0392B"}, {"id": 1, "color_hex": "#2E86C1"}],
    }
    (gd / "game.json").write_text(json.dumps(game))
    (gd / "tracks").mkdir(exist_ok=True)
    for c in range(int(np.ceil(duration / 10))):
        frames = []
        for t in np.arange(c * 10, min((c + 1) * 10, duration + 1e-6), 0.1):
            pts = []
            for pid, (x, y) in positions(float(t)).items():
                (fx, fy), (_, hy) = project(np.asarray([[x, y, 0.0], [x, y, 1.85]]))
                bh = fy - hy  # a 1.85 m person
                bb = [(fx - 0.2 * bh) / W, hy / H, 0.4 * bh / W, bh / H]
                pts.append({"id": pid, "bb": [round(v, 5) for v in bb], "ct": [x, y], "c": 0.9})
            frames.append({"t": round(float(t), 3), "p": pts})
        doc = {"schema": "replay.tracks.v1", "t0": c * 10.0, "rate_hz": 10, "frames": frames}
        (gd / "tracks" / f"{c:05d}.json").write_text(json.dumps(doc))
    (gd / "crops").mkdir(exist_ok=True)
    events = [
        {"id": s["id"], "type": "shot", "t_start": s["t_key"] - 3, "t_key": s["t_key"],
         "t_end": s["t_key"] + 2, "made": True, "player_id": s["player_id"],
         "team": s["team"], "points": s["points"], "court": list(positions(s["t_key"])[
             s["player_id"]]), "confidence": 0.9, "source": "heuristic"}
        for s in SHOTS
    ]  # fmt: skip
    (gd / "events.json").write_text(json.dumps({"schema": "replay.events.v1", "events": events}))
    return gd
