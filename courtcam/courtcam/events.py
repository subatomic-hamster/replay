"""Stage 10 — event detection (plan §4.4 step 10).

Which detectors run comes from the profile's `events:` list, never from the sport id.
Detectors see the identified players and, when the audio and pose stages ran, their
`Signals`: audio onsets and hype spikes, and per-player 2D keypoints.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

from .court import moving_average, resample
from .identity import PlayerTrack
from .profiles import Profile, RallyCfg
from .schema import Event, Onset

# COCO keypoint indices
NOSE, L_SH, R_SH, L_EL, R_EL, L_WR, R_WR, L_HIP, R_HIP = 0, 5, 6, 7, 8, 9, 10, 11, 12


@dataclass
class Signals:
    """What the audio and pose stages measured. Every field may be empty."""

    onsets: list[Onset] = field(default_factory=list)
    hype: list[tuple[float, float, float, float]] = field(default_factory=list)
    # player_id -> (times (n,), keypoints (n, 17, 3) normalized to the frame)
    poses: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)
    size: tuple[int, int] = (1, 1)  # frame (W, H), to un-normalize keypoints
    has_audio: bool = False

    def kp_px(self, pid: str, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray]:
        """(times, keypoints in px) of one player inside [t0, t1]."""
        if pid not in self.poses:
            return np.zeros(0), np.zeros((0, 17, 3))
        ts, kp = self.poses[pid]
        m = (ts >= t0) & (ts <= t1)
        out = kp[m].copy()
        out[..., 0] *= self.size[0]
        out[..., 1] *= self.size[1]
        return ts[m], out


@dataclass(frozen=True, slots=True)
class ShotCandidate:
    t_key: float
    player_id: str | None
    court: tuple[float, float] | None
    confidence: float


class Labeler(Protocol):
    """Turns a clip around `t_key` into shot facts. The default one cannot see the
    video, so it leaves `made` unknown; a VLM labeler fills it in (§4.4 step 10)."""

    source: str

    def label(self, video: Path, candidate: ShotCandidate) -> dict[str, Any]: ...


class HeuristicLabeler:
    """Pass-through: keeps the heuristic's own confidence, `made` stays unknown."""

    source = "heuristic"

    def label(self, video: Path, candidate: ShotCandidate) -> dict[str, Any]:
        return {"is_shot": True, "made": None, "confidence": candidate.confidence}


# --- rim motion -------------------------------------------------------------


def rim_energy(
    video: Path,
    rim_px: tuple[float, float],
    *,
    roi_px: int,
    stride: int,
    active: Callable[[float], bool] | None = None,
    fps: float = 30.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Frame-differencing energy inside the rim ROI. Returns (times, energy).

    Frames where `active(t)` is False are grabbed but never decoded, so a long game
    only pays for the moments a player is actually near the basket.
    """
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {video}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cx, cy = int(round(rim_px[0])), int(round(rim_px[1]))
    x0, x1 = max(0, cx - roi_px), min(w, cx + roi_px)
    y0, y1 = max(0, cy - roi_px), min(h, cy + roi_px)
    times: list[float] = []
    energy: list[float] = []
    prev: np.ndarray | None = None
    i = -1
    try:
        if x1 <= x0 or y1 <= y0:  # rim projects outside the frame
            return np.zeros(0), np.zeros(0)
        while True:
            ok = cap.grab()
            if not ok:
                break
            i += 1
            if i % stride:
                continue
            t = i / fps
            if active is not None and not active(t):
                prev = None
                continue
            ok, frame = cap.retrieve()
            if not ok:
                break
            roi = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
            if prev is not None and prev.shape == roi.shape:
                times.append(t)
                energy.append(float(np.mean(np.abs(roi - prev))))
            prev = roi
    finally:
        cap.release()
    return np.asarray(times), np.asarray(energy)


def bursts(
    times: np.ndarray, energy: np.ndarray, *, sigma: float, min_gap_s: float
) -> list[tuple[float, float]]:
    """Local maxima above mean + sigma*std, thinned to one per `min_gap_s`.

    Returns (time, z-score) pairs, strongest first within each gap window.
    """
    if len(energy) < 3:
        return []
    mu, sd = float(np.mean(energy)), float(np.std(energy))
    if sd <= 1e-6:
        return []
    z = (energy - mu) / sd
    order = np.argsort(z)[::-1]
    picked: list[tuple[float, float]] = []
    for i in order:
        if z[i] < sigma:
            break
        t = float(times[i])
        if any(abs(t - pt) < min_gap_s for pt, _ in picked):
            continue
        picked.append((t, float(z[i])))
    return sorted(picked)


# --- detectors --------------------------------------------------------------


def detect_shots(
    video: Path,
    players: list[PlayerTrack],
    profile: Profile,
    calib: dict[str, Any],
    *,
    fps: float = 30.0,
    labeler: Labeler | None = None,
    signals: Signals | None = None,
    **_: Any,
) -> list[Event]:
    """Shots near the calibrated rim.

    With poses (`_pose_shots`): a release — both arms up briefly (not the X gesture) by a
    player in range of the rim — confirmed by a motion burst at the hoop ROI after it. The
    shooter is that player and the spot (so 2 vs 3 points) is where they stood at release.
    Without poses (the M1 heuristic): a motion burst in the rim ROI while a foot point is
    within `shot.rim_radius_m`, credited to the nearest player."""
    signals = signals or Signals()
    zones = _two_pt_zones(profile, calib)
    rim_m = calib.get("rim_m")
    rim_px = calib.get("rim_px")
    if rim_m is None or rim_px is None:
        return []
    cfg = profile.shot
    labeler = labeler or HeuristicLabeler()
    rim = np.asarray(rim_m, dtype=np.float64)
    if signals.poses:
        found = _pose_shots(video, players, signals, _rims(profile, calib), profile, fps)
        return [
            _shot_event(video, labeler, cfg, zones, t_key, shooter, t_rel, conf)
            for t_key, shooter, t_rel, conf in found
        ]

    def nearest(t: float) -> tuple[PlayerTrack | None, np.ndarray | None, float]:
        best, best_pos, best_d = None, None, np.inf
        for p in players:
            if not (p.t_start <= t <= p.t_end):
                continue
            pos = p.track.court_at(t)
            d = float(np.linalg.norm(pos - rim))
            if d < best_d:
                best, best_pos, best_d = p, pos, d
        return best, best_pos, best_d

    def active(t: float) -> bool:
        return nearest(t)[2] <= cfg.rim_radius_m

    # ponytail: mean abs frame difference in the rim ROI. It fires on any motion there,
    # so a defender under the basket scores like a shot; `shot.burst_sigma` is the knob
    # and the plan says to tune it on real footage. Measured ~1/3 precision on
    # samples/real (8 events in 240 s, 3 hand-checked); burst_sigma was left alone
    # because the events land in the right place at the wrong moment, and the metre
    # gate that would help needs a lens model first. Upgrade path: vertical optical flow
    # in the ROI, or hand the candidates to a VLM labeler (the `Labeler` seam is here).
    times, energy = rim_energy(
        video,
        tuple(rim_px),
        roi_px=cfg.roi_px,
        stride=profile.detection.stride,
        active=active if players else None,
        fps=fps,
    )
    out: list[Event] = []
    for t_key, z in bursts(times, energy, sigma=cfg.burst_sigma, min_gap_s=cfg.min_gap_s):
        player, _, dist = nearest(t_key)
        if player is None or dist > cfg.rim_radius_m:
            continue
        conf = float(min(0.95, 0.4 + 0.1 * (z - cfg.burst_sigma)))
        out.append(
            _shot_event(video, labeler, cfg, zones, t_key, player, t_key - cfg.release_lead_s, conf)
        )
    return [e for e in out if e is not None]


def _shot_event(video, labeler, cfg, zones, t_key, shooter, t_rel, conf) -> Event | None:
    t_rel = max(shooter.t_start, min(shooter.t_end, t_rel))
    spot = shooter.track.court_at(t_rel)
    candidate = ShotCandidate(
        t_key=t_key,
        player_id=shooter.player_id,
        court=(float(spot[0]), float(spot[1])),
        confidence=conf,
    )
    label = labeler.label(video, candidate)
    if not label.get("is_shot", True):
        return None
    return Event(
        id="",
        type="shot",
        t_start=round(max(0.0, t_key - cfg.pre_s), 3),
        t_key=round(t_key, 3),
        t_end=round(t_key + cfg.post_s, 3),
        made=label.get("made"),
        player_id=label.get("shooter_player_id", candidate.player_id),
        court=(round(candidate.court[0], 3), round(candidate.court[1], 3)),
        confidence=round(float(label.get("confidence", candidate.confidence)), 3),
        source=getattr(labeler, "source", "heuristic"),
        confirmed=False,
        team=shooter.team,
        points=_points(candidate.court, zones),
    )


def hoop_roi(
    rim_px, rim_m: np.ndarray, players: list[PlayerTrack], height_m: float = 3.05
) -> tuple[tuple[float, float], int] | None:
    """The hoop in pixels: `rim_px` is the floor point under it, so lift it by 3.05 m at
    the pixels-per-metre of the people standing near it (median box height / 1.8 m).
    ROI half-size: a third of a person. None when nobody comes within 4 m of the rim."""
    hs = []
    for p in players:
        t = p.track.tracklet
        near = np.linalg.norm(p.track.court_m - rim_m, axis=1) <= 4.0
        hs += list(t.boxes[near, 3])
    if not hs:
        return None
    h = float(np.median(hs))
    return (float(rim_px[0]), float(rim_px[1]) - h * height_m / 1.8), max(12, int(0.35 * h))


def _runs(ts: np.ndarray, hit: np.ndarray, max_gap: float) -> list[tuple[float, float]]:
    """(first, last) sample time of each run of `hit`, bridging gaps <= max_gap."""
    out: list[list[float]] = []
    for t, h in zip(ts, hit, strict=True):
        if not h:
            continue
        if out and t - out[-1][1] <= max_gap:
            out[-1][1] = float(t)
        else:
            out.append([float(t), float(t)])
    return [(a, b) for a, b in out]


def _rims(profile: Profile, calib: dict[str, Any]) -> list[tuple[np.ndarray, Any]]:
    """[(rim_m, rim_px)]: the calibrated rim, plus every other rim of the template (the
    far basket of a full court) projected through the homography when it is in frame."""
    out = [(np.asarray(calib["rim_m"], dtype=np.float64), calib["rim_px"])]
    if not profile.shot.extra_rims:
        return out
    h_inv = calib.get("H_inv")
    try:
        tpl = profile.template(calib.get("variant"))
    except (ValueError, KeyError):
        return out
    if h_inv is None:
        return out
    size = calib.get("image_size")
    for r in tpl.rims:
        r = np.asarray(r, dtype=np.float64)
        if np.linalg.norm(r - out[0][0]) < 1.0:
            continue
        px = cv2.perspectiveTransform(r.reshape(1, 1, 2), np.asarray(h_inv, float))[0, 0]
        if size and calib.get("k1"):
            from .distortion import distort_points

            px = distort_points([px], float(calib["k1"]), tuple(size))[0]
        if size and not (0 <= px[0] < size[0] and 0 <= px[1] < size[1]):
            continue
        out.append((r, [float(px[0]), float(px[1])]))
    return out


def _pose_shots(video, players, signals, rims, profile, fps):
    """[(t_key, shooter, t_release, confidence)] — see `detect_shots`. A release counts
    for the rim nearest the shooter; each rim confirms its own shots."""
    out = []
    for i, (rim, rim_px) in enumerate(rims):
        others = [r for j, (r, _) in enumerate(rims) if j != i]
        out += _pose_shots_at(video, players, signals, rim, rim_px, others, profile, fps)
    return sorted(out, key=lambda s: s[0])


def _pose_shots_at(video, players, signals, rim, rim_px, others, profile, fps):
    cfg = profile.shot
    rel = []
    for p in players:
        ts, kp = signals.kp_px(p.player_id, -np.inf, np.inf)
        if not len(ts):
            continue
        up = arms_up(kp) & ~x_pose(kp)
        for a, b in _runs(ts, up, 0.15):
            if b - a > cfg.release_max_s:
                continue  # held: a gesture or a celebration, not a release
            pos = p.track.court_at(b)
            d = float(np.linalg.norm(pos - rim))
            if d <= cfg.max_range_m and all(d <= np.linalg.norm(pos - o) for o in others):
                rel.append((b, p, d))
    rel.sort(key=lambda r: r[0])
    # a contested shot raises two pairs of arms: keep the one farther from the rim
    groups: list[list] = []
    for r in rel:
        if groups and r[0] - groups[-1][0][0] <= cfg.min_gap_s:
            groups[-1].append(r)
        else:
            groups.append([r])
    picks = [max(g, key=lambda r: r[2]) for g in groups]
    hoop = hoop_roi(rim_px, rim, players)
    if hoop is None:
        return [(t + cfg.release_lead_s, p, t, 0.3) for t, p, _ in picks]
    lo, hi = cfg.confirm_window_s

    def active(t: float) -> bool:
        return any(r - 0.5 <= t <= r + hi for r, _, _ in picks)

    times, energy = rim_energy(
        video, hoop[0], roi_px=hoop[1], stride=profile.detection.stride, active=active, fps=fps
    )
    out = []
    for t, p, _ in picks:
        base = energy[(times >= t - 0.5) & (times <= t + hi)]
        m = (times >= t + lo) & (times <= t + hi)
        if len(base) < 4 or not m.any():
            continue
        med = float(np.median(base))
        mad = float(np.median(np.abs(base - med))) * 1.4826 + 1e-6
        z = (energy[m] - med) / mad
        k = int(np.argmax(z))
        if z[k] >= cfg.confirm_sigma:
            out.append((float(times[m][k]), p, t, float(min(0.95, 0.4 + 0.05 * z[k]))))
    return out


def _two_pt_zones(profile: Profile, calib: dict[str, Any]) -> list[np.ndarray]:
    """`shot.two_pt_zones` features of this variant's template, as closed polygons."""
    if not profile.shot.two_pt_zones:
        return []
    tpl = profile.template(calib.get("variant"))
    return [
        np.asarray(tpl.features[name], dtype=np.float32)
        for name in profile.shot.two_pt_zones
        if name in tpl.features
    ]


def _points(spot: tuple[float, float] | None, zones: list[np.ndarray]) -> int | None:
    """2 inside any two-point zone (the 3-pt line closed by the baseline), else 3."""
    if spot is None or not zones:
        return None
    p = (float(spot[0]), float(spot[1]))
    return 2 if any(cv2.pointPolygonTest(z, p, False) >= 0 for z in zones) else 3


def arms_up(kp: np.ndarray, min_score: float = 0.3) -> np.ndarray:
    """(n,) bool: both wrists above the nose (or, without a nose, a torso-third above the
    shoulders). `kp` is (n, 17, 3) in pixels."""
    ok = (kp[:, [L_SH, R_SH, L_WR, R_WR], 2] >= min_score).all(axis=1)
    sh_y = kp[:, [L_SH, R_SH], 1].mean(axis=1)
    hip_y = kp[:, [L_HIP, R_HIP], 1].mean(axis=1)
    torso = np.where(
        (kp[:, [L_HIP, R_HIP], 2] >= min_score).all(axis=1),
        np.abs(hip_y - sh_y),
        np.abs(kp[:, L_SH, 0] - kp[:, R_SH, 0]) * 1.5,
    )
    head_y = np.where(kp[:, NOSE, 2] >= min_score, kp[:, NOSE, 1], sh_y - 0.35 * torso)
    wr_y = kp[:, [L_WR, R_WR], 1].max(axis=1)  # the lower wrist (image y grows down)
    return ok & (wr_y < head_y) & (torso > 0)


def _cross(a, b, c, d) -> np.ndarray:
    """(n,) bool: segment a-b intersects segment c-d (all (n, 2))."""

    def orient(p, q, r):
        return np.sign(
            (q[:, 0] - p[:, 0]) * (r[:, 1] - p[:, 1]) - (q[:, 1] - p[:, 1]) * (r[:, 0] - p[:, 0])
        )

    return (orient(a, b, c) != orient(a, b, d)) & (orient(c, d, a) != orient(c, d, b))


def x_pose(kp: np.ndarray, min_score: float = 0.3) -> np.ndarray:
    """(n,) bool per pose sample (`kp` (n, 17, 3) in pixels): arms crossed overhead —
    both wrists above the head, and the wrists on the opposite sides of the elbows or the
    forearm segments intersecting."""
    if not len(kp):
        return np.zeros(0, bool)
    up = arms_up(kp, min_score)
    el_ok = (kp[:, [L_EL, R_EL], 2] >= min_score).all(axis=1)
    lw, rw, le, re_ = kp[:, L_WR, :2], kp[:, R_WR, :2], kp[:, L_EL, :2], kp[:, R_EL, :2]
    swapped = np.sign(lw[:, 0] - rw[:, 0]) != np.sign(le[:, 0] - re_[:, 0])
    return up & el_ok & (swapped | _cross(le, lw, re_, rw))


def court_activity(
    players: list[PlayerTrack], *, rate_hz: float, smooth_s: float, max_speed_mps: float
) -> tuple[np.ndarray, np.ndarray]:
    """Median court speed (m/s) of the players on court at each tick, smoothed.

    Median, not mean: one player strolling to pick up the shuttle is not a rally, and
    one tracker jump does not drag the other three along. Speeds above `max_speed_mps`
    are an id switch or a homography jump, not a person, and are dropped.
    Returns (times, speed).
    """
    if not players:
        return np.zeros(0), np.zeros(0)
    times = np.arange(0.0, max(p.t_end for p in players) + 1e-9, 1.0 / rate_hz)
    speeds = np.full((len(players), len(times)), np.nan)
    for i, p in enumerate(players):
        _, court, _ = resample(p.track, times)
        if len(times) > 1:
            speeds[i] = np.linalg.norm(np.gradient(court, axis=0), axis=1) * rate_hz
    speeds[speeds > max_speed_mps] = np.nan
    live = np.isfinite(speeds).any(axis=0)
    median = np.zeros(len(times))
    median[live] = np.nanmedian(speeds[:, live], axis=0)
    return times, moving_average(median[:, None], max(1, int(round(smooth_s * rate_hz))))[:, 0]


def rally_segments(
    times: np.ndarray, activity: np.ndarray, cfg: RallyCfg
) -> list[tuple[float, float, float]]:
    """Runs above `off_mps` that peak above `on_mps`. A run ends `tail_s` after its last
    peak above `on_mps` — the walk back after a point is still above `off_mps` — then
    gaps under `max_gap_s` are bridged and runs under `min_duration_s` dropped.
    Returns (start, end, peak) per rally."""
    runs: list[list[float]] = []
    start = None
    for i, a in enumerate(np.append(activity, -np.inf)):
        if start is None and a > cfg.off_mps:
            start = i
        elif start is not None and a <= cfg.off_mps:
            hot = np.nonzero(activity[start:i] >= cfg.on_mps)[0]
            if len(hot):
                t0 = float(times[start])
                t1 = min(float(times[i - 1]), float(times[start + hot[-1]]) + cfg.tail_s)
                peak = float(activity[start:i].max())
                if runs and t0 - runs[-1][1] < cfg.max_gap_s:
                    runs[-1][1], runs[-1][2] = t1, max(runs[-1][2], peak)
                else:
                    runs.append([t0, t1, peak])
            start = None
    return [(t0, t1, pk) for t0, t1, pk in runs if t1 - t0 >= cfg.min_duration_s]


def detect_rallies(
    video: Path,
    players: list[PlayerTrack],
    profile: Profile,
    calib: dict[str, Any],
    *,
    signals: Signals | None = None,
    **_: Any,
) -> list[Event]:
    """Shared net-sport rally detector: bursts of player movement on court (plan §4.4
    step 10), refined by audio onsets when there are any (`fuse_rallies`). Every rally
    also yields a `serve` at its start and a `point` at its end — the play grammar's
    start and end — and, with audio, one `contact` per onset inside it.
    Nothing sport-specific; the thresholds are the profile's `rally:` block."""
    # ponytail: a slow dinking exchange still looks like people standing still: the
    # motion segmenter must fire first; audio only moves its ends and counts contacts.
    cfg = profile.rally
    signals = signals or Signals()
    times, activity = court_activity(
        players, rate_hz=cfg.rate_hz, smooth_s=cfg.smooth_s, max_speed_mps=cfg.max_speed_mps
    )
    out: list[Event] = []
    used: set[float] = set()
    t_max = float(times[-1]) if len(times) else np.inf

    def bounds(hits: list[Onset]) -> tuple[float, float]:
        return max(0.0, hits[0].t - 0.3), min(t_max, hits[-1].t + cfg.tail_s + 0.5)

    for m0, m1, peak in rally_segments(times, activity, cfg):
        m0 = max(0.0, m0 - cfg.lead_s)
        conf = round(min(0.95, 0.5 + 0.2 * (peak / cfg.on_mps - 1.0)), 3)
        if not cfg.audio_fusion:  # motion bounds the rally; strong onsets are its contacts
            hits = [o for o in signals.onsets
                    if m0 <= o.t <= m1 and o.strength >= cfg.contact_min_strength]  # fmt: skip
            out += _rally(m0, m1, conf, hits, players, signals, cfg)
            continue
        runs = fuse_rallies(m0, m1, signals.onsets, cfg)
        for hits in runs or [[]]:
            t0, t1 = m0, m1
            if hits:  # the contacts bound the rally; one motion run may hold several
                t0, t1 = bounds(hits)
                used.update(o.t for o in hits)
            out += _rally(t0, t1, conf, hits, players, signals, cfg)
    # Audio-only rallies: a run of contacts the motion segmenter missed (twelve volleyball
    # players mostly stand still, so their median speed stays low through a rally).
    if cfg.audio_fusion and cfg.audio_only_min_contacts and signals.onsets:
        free = [o for o in signals.onsets if o.t not in used]
        for hits in fuse_rallies(-np.inf, np.inf, free, cfg):
            if len(hits) >= cfg.audio_only_min_contacts:
                out += _rally(*bounds(hits), 0.4, hits, players, signals, cfg)
    return out


def _rally(t0, t1, conf, hits, players, signals, cfg) -> list[Event]:
    """rally + serve (start) + point (end) + one contact per onset."""
    contacts = [_contact(o, players, signals, cfg) for o in hits]
    first, last = (contacts[0], contacts[-1]) if contacts else (None, None)
    t_serve = first.t_key if first else t0
    return [
        _ev("rally", t0, t0, t1, conf, contacts=len(hits) if signals.has_audio else None),
        _ev("serve", t0, t_serve, t_serve, conf, player_id=first and first.player_id,
            team=first and first.team),
        _ev("point", t1, t1, t1, conf, player_id=last and last.player_id,
            team=last and last.team),
        *contacts,
    ]  # fmt: skip


def _ev(kind: str, t0: float, tk: float, t1: float, conf: float, **kw: Any) -> Event:
    """A heuristic event; ids are assigned when all detectors are merged."""
    return Event(
        id="",
        type=kind,
        t_start=round(t0, 3),
        t_key=round(tk, 3),
        t_end=round(t1, 3),
        confidence=round(conf, 3),
        source="heuristic",
        **kw,
    )


def fuse_rallies(t0: float, t1: float, onsets: list[Onset], cfg: RallyCfg) -> list[list[Onset]]:
    """Contact onsets (strength >= `contact_min_strength`) in the motion rally [t0, t1]
    padded by `onset_pad_s`, split at every silence longer than 1.5 periods of the slowest
    expected contact rate. Each run of >= 2 is one rally: a stray click before the serve
    or a bounce after the point does not stretch it, and two rallies the motion segmenter
    merged (players never stood still between them) come apart."""
    near = [
        o
        for o in onsets
        if t0 - cfg.onset_pad_s <= o.t <= t1 + cfg.onset_pad_s
        and o.strength >= cfg.contact_min_strength
    ]
    if not near:
        return []
    max_gap = 1.5 / min(cfg.expected_contact_hz)
    runs, cur = [], [near[0]]
    for o in near[1:]:
        if o.t - cur[-1].t <= max_gap:
            cur.append(o)
        else:
            runs.append(cur)
            cur = [o]
    runs.append(cur)
    return [r for r in runs if len(r) >= 2]


def _wrist_speed(kp: np.ndarray, ts: np.ndarray) -> float:
    """Max wrist speed in body heights per second over consecutive samples."""
    if len(kp) < 2:
        return 0.0
    ok = (kp[:, [L_WR, R_WR], 2] >= 0.3).all(axis=1) & (kp[:, [L_SH, R_SH], 2] >= 0.3).all(axis=1)
    if ok.sum() < 2:
        return 0.0
    kp, ts = kp[ok], ts[ok]
    scale = np.maximum(
        np.abs(kp[:, [L_HIP, R_HIP], 1].mean(1) - kp[:, [L_SH, R_SH], 1].mean(1)), 1.0
    )
    d = np.linalg.norm(np.diff(kp[:, [L_WR, R_WR], :2], axis=0), axis=2).max(axis=1)
    return float(np.max(d / scale[1:] / np.maximum(np.diff(ts), 1e-3)))


def _contact(onset: Onset, players: list[PlayerTrack], signals: Signals, cfg: RallyCfg) -> Event:
    """A contact at an onset, credited to the player whose wrists moved fastest around it
    (pose), its team the player's side. No pose: nobody is credited."""
    w = cfg.contact_window_s
    best, best_v = None, 0.0
    for p in players:
        ts, kp = signals.kp_px(p.player_id, onset.t - w, onset.t + w)
        v = _wrist_speed(kp, ts)
        if v > best_v:
            best, best_v = p, v
    conf = min(0.95, 0.3 + 0.05 * onset.strength)
    return _ev("contact", onset.t, onset.t, onset.t, conf,
               player_id=best and best.player_id, team=best and best.team)  # fmt: skip


# --- basketball possession ----------------------------------------------------


def team_geometry(
    players: list[PlayerTrack], rims: np.ndarray, times: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per tick: mean distance of each team to the attacked rim (the rim nearest the
    players' centroid), and which rim that is. Returns (dist (n, 2), rim index (n,),
    court positions (P, n, 2))."""
    pos = (
        np.stack([resample(p.track, times)[1] for p in players])
        if players
        else np.zeros((0, len(times), 2))
    )
    team = np.array([p.team for p in players])
    cen = np.nanmean(pos, axis=0) if len(players) else np.full((len(times), 2), np.nan)
    rim_i = np.argmin(np.linalg.norm(cen[:, None, :] - rims[None], axis=2), axis=1)
    d = np.linalg.norm(pos - rims[rim_i][None], axis=2)  # (P, n)
    dist = np.full((len(times), 2), np.nan)
    for k in (0, 1):
        if (team == k).any():
            with np.errstate(all="ignore"):
                dist[:, k] = np.nanmean(d[team == k], axis=0)
    return dist, rim_i, pos


def detect_possessions(
    video: Path,
    players: list[PlayerTrack],
    profile: Profile,
    calib: dict[str, Any],
    *,
    events: list[Event] | None = None,
    **_: Any,
) -> list[Event]:
    """Possession changes from team geometry, cause from what surrounds the flip.

    Offense is the team farther from the attacked rim on average (defenders stand between
    their man and the basket). A flip that holds `min_hold_s` is a possession change:
    * a new-offense player behind the attacked end line around it -> `inbound`;
    * else a shot by the old offense within `rebound_window_s` before it -> `defensive_rebound`;
    * else -> `steal`, plus a `turnover` for the old offense.
    Shots before an inbound / a rebound are then labelled made / missed (`label_makes`)."""
    cfg = profile.possession
    tpl = profile.template(calib.get("variant"))
    rims = np.asarray(tpl.rims or ([tpl.rim] if tpl.rim else []), dtype=np.float64)
    if not len(rims) or not players:
        return []
    t_end = max(p.t_end for p in players)
    times = np.arange(0.0, t_end + 1e-9, 1.0 / cfg.rate_hz)
    dist, rim_i, pos = team_geometry(players, rims, times)
    raw = np.where(
        np.abs(dist[:, 0] - dist[:, 1]) >= cfg.min_gap_m,
        np.argmax(np.nan_to_num(dist, nan=-1), axis=1),
        -1,
    )
    win = max(1, int(round(cfg.smooth_s * cfg.rate_hz)))
    label = np.full(len(times), -1)
    for i in range(len(times)):
        seg = raw[max(0, i - win // 2) : i + win // 2 + 1]
        seg = seg[seg >= 0]
        if len(seg):
            label[i] = int(np.bincount(seg, minlength=2).argmax())
    # runs of one label at least min_hold_s long
    hold = int(round(cfg.min_hold_s * cfg.rate_hz))
    runs: list[tuple[int, int, int]] = []  # (label, i0, i1)
    i = 0
    while i < len(label):
        j = i
        while j + 1 < len(label) and label[j + 1] == label[i]:
            j += 1
        if label[i] >= 0 and j - i + 1 >= hold:
            if runs and runs[-1][0] == label[i]:
                runs[-1] = (label[i], runs[-1][1], j)
            else:
                runs.append((int(label[i]), i, j))
        i = j + 1
    shots = [e for e in events or [] if e.type == "shot"]
    teams = np.array([p.team for p in players])
    out: list[Event] = []
    for n, (lab, i0, _) in enumerate(runs):
        # the flip happened somewhere in the unclear gap before this run; take its middle
        prev_end = runs[n - 1][2] if n else i0
        t_flip = float(times[(prev_end + i0) // 2]) if n else float(times[i0])
        old = runs[n - 1][0] if n else None
        rim = rims[rim_i[i0]]
        cause, who = _possession_cause(t_flip, lab, old, rim, tpl, times, pos, teams, shots, cfg)
        pid = players[who].player_id if who is not None else None
        out.append(
            _ev("possession_change", t_flip, t_flip, t_flip + 0.5, 0.5,
                player_id=pid, team=lab, cause=cause)
        )  # fmt: skip
        if cause == "steal":
            out.append(_ev("turnover", t_flip, t_flip, t_flip, 0.4, team=old, cause="steal"))
    label_makes(shots, out, profile.shot.made_window_s)
    return out


def _possession_cause(t_flip, lab, old, rim, tpl, times, pos, teams, shots, cfg):
    """(cause, index of the player who gained it or None)."""
    length = float(tpl.size[1])
    end_y = 0.0 if rim[1] < length / 2 else length
    window = (times >= t_flip - 3.0) & (times <= t_flip + 2.0)
    mine = np.nonzero(teams == lab)[0]
    behind = (
        (end_y - pos[mine][:, window, 1]) if end_y == 0.0 else (pos[mine][:, window, 1] - end_y)
    )
    with np.errstate(all="ignore"):
        deepest = (
            np.nanmax(np.where(np.isfinite(behind), behind, -np.inf), axis=1)
            if len(mine)
            else np.zeros(0)
        )
    if len(deepest) and deepest.max() >= cfg.inbound_depth_m:
        return "inbound", int(mine[int(np.argmax(deepest))])
    k = int(np.argmin(np.abs(times - t_flip)))
    near = np.linalg.norm(pos[mine, k] - rim, axis=1) if len(mine) else np.zeros(0)
    who = int(mine[int(np.nanargmin(near))]) if len(near) and np.isfinite(near).any() else None
    if old is None:
        return "inbound", who
    if any(
        t_flip - cfg.rebound_window_s <= s.t_key <= t_flip + 1.0 and s.team == old for s in shots
    ):
        return "defensive_rebound", who
    return "steal", who


def label_makes(shots: list[Event], changes: list[Event], window_s: float) -> None:
    """Make/miss from what follows a shot (in place): the other team inbounding within
    `window_s` means it went in; a defensive rebound, or the same team shooting again
    first, means it did not. Anything else leaves `made` as it was."""
    later = sorted([*changes, *shots], key=lambda e: e.t_key)
    for s in shots:
        if s.made is not None:
            continue
        nxt = next((e for e in later if s.t_key < e.t_key <= s.t_key + window_s), None)
        if nxt is None:
            continue
        if nxt.type == "possession_change" and nxt.cause == "inbound":
            s.made = True
        elif nxt.type == "possession_change" and nxt.cause == "defensive_rebound":
            s.made = False
        elif nxt.type == "shot" and nxt.team == s.team:
            s.made = False


# --- volleyball block ------------------------------------------------------------


def detect_blocks(
    video: Path,
    players: list[PlayerTrack],
    profile: Profile,
    calib: dict[str, Any],
    *,
    signals: Signals | None = None,
    **_: Any,
) -> list[Event]:
    """Front-row jump at the net + a contact sound: a `block`.

    A jump is the box bottom (the feet) rising by >= 12 % of the box height for 0.2-1.2 s
    against its own 2 s median, by a player whose pre-jump court spot is within 1.5 m of
    the net. With audio, an onset within 0.4 s of the apex is required. Both sides
    jumping together is an attack met by a block: the side with more jumpers (the later
    apex on a tie) is the block.
    Not validated: no synthetic or labelled real footage has a block yet."""
    tpl = profile.template(calib.get("variant"))
    if tpl.net_y is None or not players:
        return []
    signals = signals or Signals()
    rate = 10.0
    times = np.arange(0.0, max(p.t_end for p in players) + 1e-9, 1.0 / rate)
    jumps: list[tuple[float, PlayerTrack]] = []
    for p in players:
        boxes, court, _ = resample(p.track, times)
        foot = boxes[:, 1] + boxes[:, 3]
        h = boxes[:, 3]
        live = np.isfinite(foot)
        if live.sum() < 25:
            continue
        base = np.full(len(times), np.nan)
        idx = np.nonzero(live)[0]
        for i in idx:
            seg = foot[max(0, i - 10) : i + 11]
            base[i] = np.nanmedian(seg)
        rise = (base - foot) / np.maximum(h, 1.0)
        up = live & (rise >= 0.12)
        i = 0
        while i < len(up):
            if not up[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(up) and up[j + 1]:
                j += 1
            dur = (j - i + 1) / rate
            k0 = max(0, i - 3)
            if (
                0.2 <= dur <= 1.2
                and np.isfinite(court[k0]).all()
                and abs(court[k0, 1] - tpl.net_y) <= 1.5
            ):
                apex = i + int(np.nanargmax(rise[i : j + 1]))
                jumps.append((float(times[apex]), p))
            i = j + 1
    jumps.sort(key=lambda x: x[0])
    out: list[Event] = []
    used: set[int] = set()
    for a, (t, _) in enumerate(jumps):
        if a in used:
            continue
        group = [b for b in range(a, len(jumps)) if jumps[b][0] - t <= 0.6 and b not in used]
        used |= set(group)
        sides: dict[int, list[tuple[float, PlayerTrack]]] = {}
        for b in group:
            sides.setdefault(jumps[b][1].team, []).append(jumps[b])
        side = max(sides, key=lambda s: (len(sides[s]), max(x[0] for x in sides[s])))
        apex = max(x[0] for x in sides[side])
        onset = [o for o in signals.onsets if abs(o.t - apex) <= 0.4]
        if signals.has_audio and not onset:
            continue
        out.append(
            _ev("block", apex - 0.8, apex, apex + 0.8, 0.4 if onset else 0.25,
                player_id=sides[side][0][1].player_id, team=side, contacts=len(onset) or None)
        )  # fmt: skip
    return out


def detect_hype(
    video: Path,
    players: list[PlayerTrack],
    profile: Profile,
    calib: dict[str, Any],
    *,
    signals: Signals | None = None,
    **_: Any,
) -> list[Event]:
    """Crowd/hype loudness spikes from the audio stage as `hype` events."""
    cfg = profile.audio
    return [
        _ev("hype", t0, tk, t1, min(0.95, 0.4 + 0.05 * (db - cfg.hype_db)))
        for t0, tk, t1, db in (signals.hype if signals else [])
    ]


DETECTORS: dict[str, Callable[..., list[Event]]] = {
    "shot": detect_shots,
    "rally": detect_rallies,
    "possession": detect_possessions,
    "block": detect_blocks,
    "hype": detect_hype,
}


def detect_events(
    video: Path,
    players: list[PlayerTrack],
    profile: Profile,
    calib: dict[str, Any],
    *,
    fps: float = 30.0,
    labeler: Labeler | None = None,
    signals: Signals | None = None,
) -> list[Event]:
    """Run every detector the profile enables, in profile order (each sees what the
    earlier ones found: possession reads the shots), and renumber the merged result."""
    out: list[Event] = []
    for name in profile.events:
        detector = DETECTORS.get(name)
        if detector is None:
            raise ValueError(f"{profile.id}: no detector registered for event type {name!r}")
        out += detector(
            video, players, profile, calib, fps=fps, labeler=labeler, signals=signals, events=out
        )
    out.sort(key=lambda e: (e.t_key, e.type))
    for n, e in enumerate(out):
        e.id = f"e_{n:04d}"
    return out
