"""Everything the director and the compositor read from a processed game dir.

Contract files only (game.json, calib.json, tracks/, crops/, events.json, and the
optional plays.json / score.json). Optional files are read tolerantly: until the plays
stage lands, the score timeline is derived from made shots in events.json and flagged
`provisional`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

PLAYER_HEIGHT_M = 1.85  # vertical scale for 3D points when calib has no K/R/t


def read_json(path: Path, default: Any = None) -> Any:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default


def _list(doc: Any, *keys: str) -> list:
    """A contract list whether the file is the bare list or {schema, <key>: [...]}."""
    if doc is None:
        return []
    if isinstance(doc, list):
        return doc
    for k in keys:
        if isinstance(doc.get(k), list):
            return doc[k]
    return []


@dataclass
class Tracks:
    """Players x samples at the tracks rate (10 Hz). NaN where a player is absent."""

    t: np.ndarray  # (T,)
    ids: list[str]
    box: np.ndarray  # (P, T, 4) x0, y0, x1, y1 in source px
    court: np.ndarray  # (P, T, 2) metres

    def index(self, pid: str) -> int | None:
        return self.ids.index(pid) if pid in self.ids else None

    def feet(self) -> np.ndarray:
        """(P, T, 2) bottom-centre of each box in source px."""
        b = self.box
        return np.stack([(b[..., 0] + b[..., 2]) / 2, b[..., 3]], axis=-1)

    def at(self, arr: np.ndarray, times: np.ndarray) -> np.ndarray:
        """Linear resample of a (P, T, D) array to `times`; NaN outside presence."""
        times = np.asarray(times, dtype=np.float64)
        out = np.full((arr.shape[0], len(times), arr.shape[2]), np.nan)
        for p in range(arr.shape[0]):
            ok = np.isfinite(arr[p, :, 0])
            if ok.sum() < 2:
                continue
            tt = self.t[ok]
            for d in range(arr.shape[2]):
                out[p, :, d] = np.interp(times, tt, arr[p, ok, d])
            # absent where the nearest sample is absent (no bridging across exits)
            near = np.clip(np.searchsorted(self.t, times), 0, len(self.t) - 1)
            prev = np.clip(near - 1, 0, len(self.t) - 1)
            gone = ~ok[near] & ~ok[prev]
            gone |= (times < tt[0] - 0.15) | (times > tt[-1] + 0.15)
            out[p, gone] = np.nan
        return out


def load_tracks(game_dir: Path, width: int, height: int) -> Tracks:
    frames: list[dict] = []
    for chunk in sorted((Path(game_dir) / "tracks").glob("*.json")):
        frames.extend(read_json(chunk).get("frames", []))
    t = np.asarray([f["t"] for f in frames], dtype=np.float64)
    ids = sorted({p["id"] for f in frames for p in f.get("p", [])}, key=_pid_key)
    col = {pid: i for i, pid in enumerate(ids)}
    box = np.full((len(ids), len(t), 4), np.nan)
    court = np.full((len(ids), len(t), 2), np.nan)
    for j, f in enumerate(frames):
        for p in f.get("p", []):
            x, y, w, h = p["bb"]
            box[col[p["id"]], j] = (x * width, y * height, (x + w) * width, (y + h) * height)
            court[col[p["id"]], j] = p["ct"]
    return Tracks(t=t, ids=ids, box=box, court=court)


def _pid_key(pid: str):
    digits = "".join(c for c in pid if c.isdigit())
    return (int(digits) if digits else 1 << 30, pid)


@dataclass
class Projector:
    """Court metres (x, y, z) -> source pixels.

    With a full camera (calib K, R, t) this is the pinhole projection. Otherwise the
    ground point comes from the homography and height from a vertical pixels-per-metre
    model fitted to tracked player boxes (box height ~ a + b * foot_y, people assumed
    `PLAYER_HEIGHT_M` tall): an approximation, good to a few tens of centimetres near
    the players, which is where the arcs are drawn.
    """

    h_inv: np.ndarray
    k1: float = 0.0
    image_size: tuple[int, int] = (1920, 1080)
    krt: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
    height_fit: tuple[float, float] = (0.0, 0.0)  # box_h_px = a + b * foot_y
    model: str = "vertical"  # calib | homography | vertical
    height_err: float = float("nan")  # median relative error on tracked player heights

    def ground(self, xy: np.ndarray) -> np.ndarray:
        xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        p = np.column_stack([xy, np.ones(len(xy))]) @ self.h_inv.T
        px = p[:, :2] / p[:, 2:3]
        if self.k1:
            from courtcam.distortion import distort_points

            px = distort_points(px, self.k1, self.image_size)
        return px

    def project(self, xyz: np.ndarray) -> np.ndarray:
        xyz = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
        if self.krt is not None:
            k, r, t = self.krt
            px = (xyz @ r.T + t) @ k.T
            px = px[:, :2] / px[:, 2:3]
            if self.k1:
                from courtcam.distortion import distort_points

                px = distort_points(px, self.k1, self.image_size)
            return px
        base = self.ground(xyz[:, :2])
        a, b = self.height_fit
        px_per_m = np.maximum(a + b * base[:, 1], 1.0) / PLAYER_HEIGHT_M
        return np.column_stack([base[:, 0], base[:, 1] - xyz[:, 2] * px_per_m])


def camera_from_homography(
    h_court_to_px: np.ndarray, image_size: tuple[int, int]
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """K, R, t of a pinhole camera (square pixels, principal point at the image centre)
    whose ground-plane homography is `h_court_to_px` (Zhang's constraints: the first two
    rotation columns are orthogonal and of equal norm). None if no positive focal fits."""
    cx, cy = image_size[0] / 2.0, image_size[1] / 2.0
    a = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1.0]]) @ h_court_to_px
    (a11, a12, _), (a21, a22, _), (a31, a32, _) = a
    cands = []
    if abs(a31 * a32) > 1e-12:
        cands.append(-(a11 * a12 + a21 * a22) / (a31 * a32))
    if abs(a31**2 - a32**2) > 1e-12:
        cands.append(-((a11**2 + a21**2) - (a12**2 + a22**2)) / (a31**2 - a32**2))
    f2 = [c for c in cands if c > 0]
    if not f2:
        return None
    f = float(np.sqrt(np.median(f2)))
    k = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1.0]])
    m = np.linalg.inv(k) @ h_court_to_px
    lam = 2.0 / (np.linalg.norm(m[:, 0]) + np.linalg.norm(m[:, 1]))
    r1, r2, t = m[:, 0] * lam, m[:, 1] * lam, m[:, 2] * lam
    if t[2] < 0:  # the court must be in front of the camera
        r1, r2, t = -r1, -r2, -t
    r = np.column_stack([r1, r2, np.cross(r1, r2)])
    u, _, vt = np.linalg.svd(r)
    r = u @ vt
    if (-r.T @ t)[2] < 0:  # z must point up, toward the camera
        r[:, 2] = -r[:, 2]
    return k, r, t


def height_check(proj: Projector, tracks: Tracks) -> tuple[float, float]:
    """(median, spread) of predicted / tracked box height for `PLAYER_HEIGHT_M` people;
    spread = median absolute deviation of the log ratio (scale-free)."""
    b = tracks.box.reshape(-1, 4)
    c = tracks.court.reshape(-1, 2)
    ok = np.isfinite(b).all(axis=1) & np.isfinite(c).all(axis=1)
    if ok.sum() < 10:
        return float("nan"), float("inf")
    idx = np.where(ok)[0][:: max(1, int(ok.sum()) // 2000)]
    foot = proj.project(np.column_stack([c[idx], np.zeros(len(idx))]))
    head = proj.project(np.column_stack([c[idx], np.full(len(idx), PLAYER_HEIGHT_M)]))
    ratio = np.linalg.norm(foot - head, axis=1) / np.maximum(b[idx, 3] - b[idx, 1], 1.0)
    lr = np.log(np.maximum(ratio, 1e-6))
    return float(np.median(ratio)), float(np.median(np.abs(lr - np.median(lr))))


def height_fit(tracks: Tracks) -> tuple[float, float]:
    """Least squares box_h ~ a + b * foot_y over every tracked sample (median per y bin
    first, so a crowded spot does not dominate)."""
    b = tracks.box.reshape(-1, 4)
    ok = np.isfinite(b).all(axis=1)
    if ok.sum() < 10:
        return (100.0, 0.0)
    y, h = b[ok, 3], b[ok, 3] - b[ok, 1]
    bins = np.linspace(y.min(), y.max() + 1e-6, 13)
    xs, ys = [], []
    for lo, hi in pairwise(bins):
        m = (y >= lo) & (y < hi)
        if m.sum() >= 5:
            xs.append(float(np.median(y[m])))
            ys.append(float(np.median(h[m])))
    if len(xs) < 2:
        return (float(np.median(h)), 0.0)
    slope, icpt = np.polyfit(xs, ys, 1)
    return (float(icpt), float(slope))


@dataclass
class Game:
    dir: Path
    game: dict
    calib: dict
    width: int
    height: int
    fps: float
    duration: float
    sport: str
    tracks: Tracks
    events: list[dict]
    plays: list[dict]
    score: list[dict]  # [{t, scores: [a, b], event_id, source}]
    score_provisional: bool
    projector: Projector | None
    rims: list[tuple[float, float]] = field(default_factory=list)

    @property
    def players(self) -> dict[str, dict]:
        return {p["id"]: p for p in self.game.get("players") or []}

    def team_colors(self) -> list[str]:
        teams = sorted(self.game.get("teams") or [], key=lambda t: t["id"])
        colors = [t.get("color_hex") or "#888888" for t in teams]
        return (colors + ["#1F6FEB", "#E5484D"])[:2] if len(colors) < 2 else colors[:2]

    def player_label(self, pid: str | None) -> str:
        """Roster name if tagged, else `#<player id>` (the tracker's id, not a jersey)."""
        if not pid:
            return ""
        name = (self.players.get(pid) or {}).get("name")
        return name if name else f"#{pid}"

    def crop_rects(self, pid: str) -> tuple[np.ndarray, float] | None:
        doc = read_json(self.dir / "crops" / f"{pid}.json")
        if not doc or not doc.get("rects"):
            return None
        return np.asarray(doc["rects"], dtype=np.float64), float(doc.get("rate_hz", 30))


def make_projector(calib: dict, tracks: Tracks, size: tuple[int, int]) -> Projector:
    """The calibration's own K/R/t when it has them; else a pinhole camera recovered
    from the homography if it is physically plausible — it must predict the tracked
    players' box heights to within 25 % for 1.85 m people, no less consistently than
    the vertical model — else the vertical-scale model fitted to those boxes.

    The fitted vertical model always matches box heights, but on a steeply tilted
    camera verticals lean, so an arc to a 3.05 m rim lands beside the hoop (synthetic:
    50 px at 1440p); the recovered camera is exact there. A stitched panorama is no
    pinhole camera (Kennesaw: ratio 1.31, rim projected off the frame), so it falls
    back to the vertical model (~80 source px from the far hoop; the near hoop sits at the
    barrelled frame edge and is worse)."""
    h_inv = np.asarray(calib["H_inv"], dtype=np.float64)
    base = {"h_inv": h_inv, "k1": float(calib.get("k1") or 0.0), "image_size": size}
    if all(k in calib for k in ("K", "R", "t")):
        k, r, t = (np.asarray(calib[n], dtype=np.float64) for n in ("K", "R", "t"))
        return Projector(**base, krt=(k, r, t.reshape(3)), model="calib")
    vert = Projector(**base, height_fit=height_fit(tracks), model="vertical")
    v_ratio, v_spread = height_check(vert, tracks)
    vert.height_err = abs(v_ratio - 1.0)
    krt = camera_from_homography(h_inv, size)
    if krt is not None:
        pin = Projector(**base, krt=krt, model="homography")
        ratio, spread = height_check(pin, tracks)
        pin.height_err = abs(ratio - 1.0)
        if 0.8 <= ratio <= 1.25 and spread <= 1.25 * v_spread + 0.01:
            return pin
    return vert


def score_from_events(events: list[dict]) -> list[dict]:
    """Running score from made shots (team from the event, else the shooter's side is
    unknown and the make is skipped). Used only when score.json does not exist."""
    a = [0, 0]
    out = []
    for e in sorted(events, key=lambda e: e["t_key"]):
        if e.get("type") != "shot" or e.get("made") is not True or e.get("team") not in (0, 1):
            continue
        a[e["team"]] += int(e.get("points") or 2)
        out.append({"t": e["t_key"], "scores": list(a), "event_id": e["id"], "source": "auto"})
    return out


def load_game(game_dir: Path) -> Game:
    gd = Path(game_dir)
    game = read_json(gd / "game.json") or {}
    calib = read_json(gd / "calib.json") or {}
    video = game.get("video") or {}
    width, height = int(video.get("width", 1920)), int(video.get("height", 1080))
    tracks = load_tracks(gd, width, height)
    events = _list(read_json(gd / "events.json"), "events")
    # team for events that lack it: the player's team from the roster
    team_of = {p["id"]: p.get("team") for p in game.get("players") or []}
    for e in events:
        if e.get("team") is None and e.get("player_id") in team_of:
            e["team"] = team_of[e["player_id"]]
    score_doc = read_json(gd / "score.json")
    score = _list(score_doc, "score", "scores", "entries")
    provisional = score_doc is None
    if provisional:
        score = score_from_events(events)
    projector = make_projector(calib, tracks, (width, height)) if calib.get("H_inv") else None
    rims: list[tuple[float, float]] = []
    sport = game.get("sport") or calib.get("sport") or "basketball"
    try:
        from courtcam.profiles import load_profile

        tpl = load_profile(sport).template((game.get("court") or {}).get("variant"))
        rims = [tuple(r) for r in (tpl.rims or ([tpl.rim] if tpl.rim else []))]
    except Exception:  # noqa: BLE001 - an unknown sport just has no rims to aim arcs at
        rims = []
    return Game(
        dir=gd,
        game=game,
        calib=calib,
        width=width,
        height=height,
        fps=float(video.get("fps", 30.0)),
        duration=float(video.get("duration_s", tracks.t[-1] if len(tracks.t) else 0.0)),
        sport=sport,
        tracks=tracks,
        events=events,
        plays=_list(read_json(gd / "plays.json"), "plays"),
        score=score,
        score_provisional=provisional,
        projector=projector,
        rims=rims,
    )
