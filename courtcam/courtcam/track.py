"""Stage 4 — per-frame detections → tracklets (plan §4.4 step 4)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

TRACKLETS_SCHEMA = "courtcam.tracklets.v1"


@dataclass(frozen=True, slots=True)
class Tracklet:
    """One local track id's whole life. Arrays are parallel and time-ordered."""

    track_id: int
    frames: np.ndarray  # (N,) int frame indices
    times: np.ndarray  # (N,) float seconds
    boxes: np.ndarray  # (N, 4) float pixels, [x, y, w, h]
    confs: np.ndarray  # (N,) float

    @property
    def t_start(self) -> float:
        return float(self.times[0])

    @property
    def t_end(self) -> float:
        return float(self.times[-1])

    @property
    def lifetime_s(self) -> float:
        return self.t_end - self.t_start

    def feet_px(self) -> np.ndarray:
        """Bottom-centre of each box — the point that touches the floor (§4.4 step 5)."""
        return np.column_stack(
            [self.boxes[:, 0] + self.boxes[:, 2] / 2.0, self.boxes[:, 1] + self.boxes[:, 3]]
        )

    def at(self, t: float) -> np.ndarray:
        """Box interpolated (and clamped) at time `t`."""
        return np.asarray([np.interp(t, self.times, self.boxes[:, i]) for i in range(4)])


def read_dets(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_tracklets(dets: dict[str, Any], *, min_points: int = 2) -> list[Tracklet]:
    """Group detection rows by track id. Ids <= 0 are un-associated boxes and are dropped."""
    grouped: dict[int, list[tuple[int, float, list[float], float]]] = {}
    for frame in dets["frames"]:
        for row in frame["d"]:
            tid = int(row[0])
            if tid <= 0:
                continue
            grouped.setdefault(tid, []).append(
                (int(frame["f"]), float(frame["t"]), row[1:5], row[5])
            )
    out: list[Tracklet] = []
    for tid, rows in sorted(grouped.items()):
        rows.sort(key=lambda r: r[0])
        if len(rows) < min_points:
            continue
        out.append(
            Tracklet(
                track_id=tid,
                frames=np.asarray([r[0] for r in rows], dtype=np.int64),
                times=np.asarray([r[1] for r in rows], dtype=np.float64),
                boxes=np.asarray([r[2] for r in rows], dtype=np.float64),
                confs=np.asarray([r[3] for r in rows], dtype=np.float64),
            )
        )
    return out


def write_tracklets(path: Path, tracklets: list[Tracklet], meta: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": TRACKLETS_SCHEMA,
                **{k: v for k, v in meta.items() if k != "frames"},
                "tracklets": [
                    {
                        "track_id": t.track_id,
                        "frames": t.frames.tolist(),
                        "times": [round(v, 4) for v in t.times.tolist()],
                        "boxes": [[round(v, 2) for v in b] for b in t.boxes.tolist()],
                        "confs": [round(v, 4) for v in t.confs.tolist()],
                    }
                    for t in tracklets
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def read_tracklets(path: Path) -> tuple[list[Tracklet], dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tracklets = [
        Tracklet(
            track_id=int(t["track_id"]),
            frames=np.asarray(t["frames"], dtype=np.int64),
            times=np.asarray(t["times"], dtype=np.float64),
            boxes=np.asarray(t["boxes"], dtype=np.float64),
            confs=np.asarray(t["confs"], dtype=np.float64),
        )
        for t in raw["tracklets"]
    ]
    return tracklets, {k: v for k, v in raw.items() if k != "tracklets"}
