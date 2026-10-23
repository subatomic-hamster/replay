"""Stage 6 — team split and tracklet merging into stable player ids (plan §4.4 step 6).

Identity switches through occlusion are expected; the tag UI is the correction
mechanism, so nothing here tries to be clever.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import lap
import numpy as np

from .court import (
    CourtTrack,
    bystander,
    resample,
    stationary,
    to_court,
    track_from_json,
    track_json,
)
from .profiles import CourtTemplate, Profile
from .schema import Player as PlayerModel
from .schema import Team as TeamModel
from .track import Tracklet, box_iou

TEAM_BINS = (8, 4, 4)
"""H, S, V bins of the torso (kit) histogram. With brightness the kits separate: on the CC
BY Nottingham game (39 court tracklets matched to the hand-labelled player GT) k-means on
H-S only put 11 of 20 red-kit tracklets with the 15 dark ones; H-S-V puts 19 of 20 red and
14 of 15 dark apart (the referees fall in with the dark kit). A black kit and a grey shirt
have no hue to speak of, only their value tells them from the floor."""


@dataclass(frozen=True, slots=True)
class PlayerTrack:
    """One merged player: a stable id over one or more local tracklets."""

    player_id: str
    team: int
    color_hex: str
    track: CourtTrack
    members: tuple[int, ...]  # local track ids that were merged in
    # (tracker id, t_start, t_end) of every piece: a tracker id cut by `split_appearance`
    # can be in two players, so the id alone does not say which part is whose
    spans: tuple[tuple[int, float, float], ...] = ()
    # one person for the whole clip, box by box (`roster_label`): where no box is theirs
    # the id has none, so `tracks/` bridges only short gaps and the TV never hands the
    # follow to another id (D-89)
    solved: bool = False
    # share of the id's sampled torsos nearer the other kit (`jersey_color` only; None
    # elsewhere): above `TEAM_MIXED_SHARE` the UI does not show `team`
    off_kit: float | None = None
    # where `team` came from: "kit" (shirt colours), "matchups" (who guards whom,
    # `play_teams`), "user" (the phone's team pick, `apply_team_edits`), or the profile's
    # team_rule ("net_side")
    team_source: str | None = None

    @property
    def t_start(self) -> float:
        return self.track.tracklet.t_start

    @property
    def t_end(self) -> float:
        return self.track.tracklet.t_end


# --- appearance -------------------------------------------------------------


def torso_rect(box: np.ndarray) -> tuple[int, int, int, int]:
    """Middle of the upper half of a person box — jersey, not floor or face."""
    x, y, w, h = box
    return (
        int(round(x + 0.25 * w)),
        int(round(y + 0.15 * h)),
        max(1, int(round(0.5 * w))),
        max(1, int(round(0.35 * h))),
    )


def _hist(crop: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, list(TEAM_BINS), [0, 180, 0, 256, 0, 256]).ravel()
    total = hist.sum()
    return hist / total if total else hist


def _grab_frames(cap: cv2.VideoCapture, wanted: list[int]):
    """Yield (index, frame) for `wanted` (sorted) in one forward pass over `cap`."""
    todo = iter(wanted)
    nxt = next(todo, None)
    i = -1
    while nxt is not None:
        if not cap.grab():
            return
        i += 1
        if i < nxt:
            continue
        ok, frame = cap.retrieve()
        if ok:
            yield i, frame
        while nxt is not None and nxt <= i:
            nxt = next(todo, None)


BODY_BINS = (8, 4, 4)  # H, S, V per half of the body box


def body_hist(crop: np.ndarray) -> np.ndarray:
    """Re-ID descriptor of a whole person box: an HSV histogram of the upper half and one
    of the lower half (the middle 60 % of the width, off the background), concatenated.
    The jersey alone cannot tell teammates apart; skin, hair, shorts and shoes can a bit:
    same-team same-person ROC AUC 0.72-0.73 on synthetic basketball vs 0.57-0.61 for the
    torso histogram, and as good as CLIP / SigLIP embeddings (0.64-0.71) at no GPU cost."""
    h, w = crop.shape[:2]
    hsv = cv2.cvtColor(
        crop[:, int(0.2 * w) : max(int(0.2 * w) + 1, int(0.8 * w))], cv2.COLOR_BGR2HSV
    )
    out = []
    for part in (hsv[: max(1, h // 2)], hsv[h // 2 :]):
        hist = cv2.calcHist([part], [0, 1, 2], None, list(BODY_BINS), [0, 180, 0, 256, 0, 256])
        hist = hist.ravel()
        out.append(hist / max(float(hist.sum()), 1.0))
    return np.concatenate(out)


def app_distance(a: np.ndarray, b: np.ndarray) -> float:
    """1 - Bhattacharyya coefficient per half, averaged (0 same, 1 disjoint)."""
    n = len(a) // 2
    return 1.0 - 0.5 * float(np.sum(np.sqrt(a[:n] * b[:n])) + np.sum(np.sqrt(a[n:] * b[n:])))


def sample_appearance(
    video: str, tracks: list[CourtTrack], *, samples: int = 8
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-tracklet (torso HSV histogram, mean torso BGR, `body_hist`) from `samples`
    crops each."""
    wanted: dict[int, list[tuple[int, np.ndarray]]] = {}
    for i, tr in enumerate(tracks):
        t = tr.tracklet
        idx = np.unique(np.linspace(0, len(t.frames) - 1, min(samples, len(t.frames))).astype(int))
        for j in idx:
            wanted.setdefault(int(t.frames[j]), []).append((i, t.boxes[j]))

    hists = [[] for _ in tracks]
    colors = [[] for _ in tracks]
    bodies = [[] for _ in tracks]
    cap = cv2.VideoCapture(str(video))
    try:
        fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1
        fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
        # One sequential pass, decoding only the sampled frames. Seeking per frame cost
        # ~20 s per 10 tracklets on real footage and grew with the candidate count; this
        # is one decode of the file no matter how many tracklets there are.
        for frame_idx, frame in _grab_frames(cap, sorted(wanted)):
            for i, box in wanted[frame_idx]:
                x, y, w, h = torso_rect(box)
                x0, y0 = max(0, x), max(0, y)
                crop = frame[y0 : min(fh, y + h), x0 : min(fw, x + w)]
                if crop.size == 0:
                    continue
                hists[i].append(_hist(crop))
                colors[i].append(crop.reshape(-1, 3).mean(axis=0))
                bx, by, bw, bh = (int(round(v)) for v in box)
                full = frame[max(0, by) : min(fh, by + bh), max(0, bx) : min(fw, bx + bw)]
                if full.shape[0] >= 4 and full.shape[1] >= 4:
                    bodies[i].append(body_hist(full))
    finally:
        cap.release()

    dim = int(np.prod(TEAM_BINS))
    hist_arr = np.asarray(
        [np.mean(h, axis=0) if h else np.zeros(dim) for h in hists], dtype=np.float32
    )
    color_arr = np.asarray(
        [np.mean(c, axis=0) if c else np.full(3, 128.0) for c in colors], dtype=np.float64
    )
    bdim = 2 * int(np.prod(BODY_BINS))
    body_arr = np.asarray(
        [np.mean(b, axis=0) if b else np.full(bdim, 1.0 / (bdim // 2)) for b in bodies]
    )
    return hist_arr, color_arr, body_arr


def bgr_to_hex(bgr: np.ndarray) -> str:
    b, g, r = (int(np.clip(v, 0, 255)) for v in bgr)
    return f"#{r:02X}{g:02X}{b:02X}"


def split_teams(hists: np.ndarray, *, k: int = 2, seed: int = 0) -> np.ndarray:
    """k-means over per-tracklet HSV histograms → team label per tracklet."""
    if len(hists) < k:
        return np.zeros(len(hists), dtype=int)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-4)
    cv2.setRNGSeed(seed)
    _, labels, _ = cv2.kmeans(
        np.ascontiguousarray(hists, dtype=np.float32),
        k,
        None,
        criteria,
        5,
        cv2.KMEANS_PP_CENTERS,
    )
    return labels.ravel().astype(int)


JERSEY_MIN_AGREE = 0.85
"""`split_switches` on jersey colour only when at least this share of sampled torsos
agree with their tracklet's team: two real kits. Synthetic basketball 0.875-0.966; the
Kennesaw pickup game (mixed shirts, a grey referee) 0.80, where cutting on colour broke
the one stable referee row into four."""


OFF_KIT_EVERY = 5
"""`off_kit` reads every this-many-th box of each player (stride-2 detections: ~3 Hz)."""

TEAM_MIXED_SHARE = 0.3
"""A player whose `off_kit` is above this is `team_mixed` in game.json (the UI hides the
team). Tuned on the CC BY Nottingham game against a red-torso kit check (D-89)."""


def _runs(
    labels: np.ndarray, min_len: int, weight: np.ndarray | None = None
) -> list[tuple[int, int, int]]:
    """(start, end, label) runs of `labels`; a run shorter than `min_len` joins the run
    before it (or after it, at the start), so only sustained changes survive. With
    `weight` (1 = a trusted label, 0 = not), a run that is mostly untrusted is short too."""
    w = np.ones(len(labels)) if weight is None else np.asarray(weight, dtype=float)
    runs: list[list[int]] = []
    for i, x in enumerate(labels.tolist()):
        if runs and runs[-1][2] == x:
            runs[-1][1] = i + 1
        else:
            runs.append([i, i + 1, x])

    def short(r: list[int]) -> bool:
        return r[1] - r[0] < min_len or w[r[0] : r[1]].mean() < 0.5

    out: list[list[int]] = []
    for r in runs:
        if out and (short(r) or out[-1][2] == r[2]):
            out[-1][1] = r[1]
        elif out and short(out[-1]):
            out[-1] = [out[-1][0], r[1], r[2]]
        else:
            out.append(list(r))
    return [tuple(r) for r in out]  # type: ignore[misc]


JERSEY_MAX_COVER = 0.5
"""A torso sample whose rectangle another tracklet's box covers by more than this share
is untrusted for a jersey cut: it shows whoever stands in front. With the GT detector
(perfect tracks) D-70 found 15 off-team runs on synthetic basketball half s7 / s11 and
full s7, each with mean cover 0.59-0.98, against 0.28-0.30 over all samples; under
YOLO, which rarely keeps both boxes of an overlap, mean cover is 0.06-0.08
(docs/evidence/M1/README.md, Tracking v3)."""


def _cover(rect: tuple[int, int, int, int], boxes: np.ndarray) -> float:
    """Largest share of `rect` (x, y, w, h) that any one of `boxes` (n x xywh) covers."""
    if not len(boxes):
        return 0.0
    x, y, w, h = rect
    iw = np.minimum(x + w, boxes[:, 0] + boxes[:, 2]) - np.maximum(x, boxes[:, 0])
    ih = np.minimum(y + h, boxes[:, 1] + boxes[:, 3]) - np.maximum(y, boxes[:, 1])
    return float((np.clip(iw, 0, None) * np.clip(ih, 0, None)).max() / (w * h))


def jersey_labels(
    video: str, tracks: list[CourtTrack], hists: np.ndarray, teams: np.ndarray, every: int = 2
) -> tuple[list[dict[int, int]], list[dict[int, int]]]:
    """Team of every `every`-th sample of each tracklet: the nearer team centroid of its
    torso histogram. One decode pass, like `sample_appearance`. Returns all labels and
    the subset whose torso no other box covers by more than `JERSEY_MAX_COVER`."""
    cents = np.stack([hists[teams == k].mean(axis=0) for k in (0, 1)])
    wanted: dict[int, list[tuple[int, int]]] = {}
    for i, tr in enumerate(tracks):
        for j in range(0, len(tr.tracklet.frames), every):
            wanted.setdefault(int(tr.tracklet.frames[j]), []).append((i, j))
    boxes_at: dict[int, list[tuple[int, np.ndarray]]] = {}
    for i, tr in enumerate(tracks):
        for f, b in zip(tr.tracklet.frames.tolist(), tr.tracklet.boxes, strict=True):
            if int(f) in wanted:
                boxes_at.setdefault(int(f), []).append((i, b))
    lab: list[dict[int, int]] = [{} for _ in tracks]
    clear: list[dict[int, int]] = [{} for _ in tracks]
    cap = cv2.VideoCapture(str(video))
    try:
        fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1
        fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
        for frame_idx, frame in _grab_frames(cap, sorted(wanted)):
            for i, j in wanted[frame_idx]:
                x, y, w, h = rect = torso_rect(tracks[i].tracklet.boxes[j])
                crop = frame[max(0, y) : min(fh, y + h), max(0, x) : min(fw, x + w)]
                if crop.size:
                    d = np.linalg.norm(cents - _hist(crop)[None], axis=1)
                    lab[i][j] = int(np.argmin(d))
                    others = np.asarray([b for k, b in boxes_at[frame_idx] if k != i]).reshape(
                        -1, 4
                    )
                    if _cover(rect, others) <= JERSEY_MAX_COVER:
                        clear[i][j] = lab[i][j]
    finally:
        cap.release()
    return lab, clear


def split_switches(
    tracks: list[CourtTrack],
    lab: list[dict[int, int]],
    teams: np.ndarray,
    min_run_s: float = 1.0,
    clear: list[dict[int, int]] | None = None,
) -> tuple[list[CourtTrack], np.ndarray]:
    """Cut tracklets where their per-sample team label (`lab`: sample index -> team)
    changes and holds for `min_run_s`: the tracker swapped two players. Each piece takes
    the team it shows. With `clear` (the samples no one stands over, `jersey_labels`), a
    run where most torsos sit under another player's box is no change: it is the guard's
    jersey. The cut still falls where the labels change.

    No merge can undo a swap inside a tracklet. On synthetic basketball half s7 (YOLO11m
    + BoT-SORT) 28 of 109 court tracklets carry a swap, and 27 of their 43 swaps are with
    an opponent (a defender stays close), which the jersey shows.
    """
    out: list[CourtTrack] = []
    out_teams: list[int] = []
    for i, tr in enumerate(tracks):
        t = tr.tracklet
        idx = sorted(lab[i])
        if len(idx) < 2:
            out.append(tr)
            out_teams.append(int(teams[i]))
            continue
        step = max(float(np.median(np.diff(t.times[idx]))), 1e-3)
        weight = None if clear is None else np.asarray([j in clear[i] for j in idx])
        runs = _runs(np.asarray([lab[i][j] for j in idx]), max(1, round(min_run_s / step)), weight)
        for k, (a, _, team) in enumerate(runs):
            lo = 0 if k == 0 else idx[a]
            hi = len(t.frames) if k == len(runs) - 1 else idx[runs[k + 1][0]]
            if hi - lo < 2:
                continue
            piece = Tracklet(
                t.track_id, t.frames[lo:hi], t.times[lo:hi], t.boxes[lo:hi], t.confs[lo:hi]
            )
            out.append(CourtTrack(piece, tr.court_m[lo:hi], tr.inside_fraction))
            out_teams.append(int(team) if len(runs) > 1 else int(teams[i]))
    return out, np.asarray(out_teams, dtype=int)


# --- appearance switches (D-89) ---------------------------------------------

APP_EVERY_S = 0.5
"""`body_series` sampling period. Real-footage check (no labels needed): `body_hist`
tells two samples of one tracklet 1 s apart from two people in the same frame at ROC AUC
0.90 on the CC BY basketball game and 0.94 on the volleyball clip (0.88 / 0.89 for people
within two box heights of each other). Over a whole tracklet it was 0.53: the tracker
swaps people inside a tracklet, which is what `split_appearance` undoes."""
APP_WINDOW = 3
"""Samples each side of a candidate cut (about 1.5 s): a cut needs a sustained change."""


def body_series(
    video: str,
    tracks: list[CourtTrack],
    every_s: float = APP_EVERY_S,
    max_cover: float = JERSEY_MAX_COVER,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """(sample indices, `body_hist` per sample) of each tracklet, one sample per
    `every_s` (0: every box). Samples another box covers by more than `max_cover` are
    left out: they show whoever stands in front. One decode pass, like
    `sample_appearance`."""
    wanted: dict[int, list[tuple[int, int]]] = {}
    for i, tr in enumerate(tracks):
        t = tr.tracklet
        last = -np.inf
        for j, s in enumerate(t.times.tolist()):
            if s - last >= every_s - 1e-6:
                wanted.setdefault(int(t.frames[j]), []).append((i, j))
                last = s
    boxes_at: dict[int, list[tuple[int, np.ndarray]]] = {}
    for i, tr in enumerate(tracks):
        for f, b in zip(tr.tracklet.frames.tolist(), tr.tracklet.boxes, strict=True):
            if int(f) in wanted:
                boxes_at.setdefault(int(f), []).append((i, b))
    got: list[list[tuple[int, np.ndarray]]] = [[] for _ in tracks]
    cap = cv2.VideoCapture(str(video))
    try:
        fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1
        fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
        for frame_idx, frame in _grab_frames(cap, sorted(wanted)):
            for i, j in wanted[frame_idx]:
                box = tracks[i].tracklet.boxes[j]
                others = np.asarray([b for k, b in boxes_at[frame_idx] if k != i]).reshape(-1, 4)
                bx, by, bw, bh = (int(round(v)) for v in box)
                if _cover((bx, by, max(bw, 1), max(bh, 1)), others) > max_cover:
                    continue
                crop = frame[max(0, by) : min(fh, by + bh), max(0, bx) : min(fw, bx + bw)]
                if crop.shape[0] >= 4 and crop.shape[1] >= 4:
                    got[i].append((j, body_hist(crop)))
    finally:
        cap.release()
    bdim = 2 * int(np.prod(BODY_BINS))
    return [
        (
            np.asarray([j for j, _ in g], dtype=int),
            np.asarray([d for _, d in g]).reshape(-1, bdim),
        )
        for g in got
    ]


def _clear_every(
    track: CourtTrack, series: tuple[np.ndarray, np.ndarray], cover: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """What `body_series` would have sampled from a denser series: the clear samples
    (cover <= `JERSEY_MAX_COVER`), one per `APP_EVERY_S`."""
    idx, d = series
    times = track.tracklet.times
    keep, last = [], -np.inf
    for n, j in enumerate(idx.tolist()):
        if cover[j] <= JERSEY_MAX_COVER and times[j] - last >= APP_EVERY_S - 1e-6:
            keep.append(n)
            last = times[j]
    return idx[keep], d[keep].reshape(-1, d.shape[1])


def _cut_points(desc: np.ndarray, cut: float, window: int = APP_WINDOW) -> list[int]:
    """Sample positions k where the mean of the `window` samples before and the mean of
    the `window` after differ by more than `cut` (`app_distance`), strongest first, at
    least `window` apart."""
    n = len(desc)
    score = np.zeros(n)
    for k in range(window, n - window + 1):
        a = desc[k - window : k].mean(axis=0)
        b = desc[k : k + window].mean(axis=0)
        score[k] = app_distance(a, b)
    cuts: list[int] = []
    for k in np.argsort(-score):
        if score[k] <= cut:
            break
        if all(abs(int(k) - c) >= window for c in cuts):
            cuts.append(int(k))
    return sorted(cuts)


def split_appearance(
    tracks: list[CourtTrack],
    series: list[tuple[np.ndarray, np.ndarray]],
    cut: float,
    window: int = APP_WINDOW,
) -> tuple[list[CourtTrack], list[int], list[np.ndarray]]:
    """Cut tracklets where the person in the box changes for good (the tracker handed the
    id to someone else, often a teammate the jersey cannot tell apart). Returns the
    pieces, the index of the tracklet each came from, and each piece's mean `body_hist`
    (a piece without clear samples gets its tracklet's)."""
    out: list[CourtTrack] = []
    src: list[int] = []
    desc: list[np.ndarray] = []
    bdim = 2 * int(np.prod(BODY_BINS))
    for i, (tr, (idx, d)) in enumerate(zip(tracks, series, strict=True)):
        t = tr.tracklet
        whole = d.mean(axis=0) if len(d) else np.full(bdim, 1.0 / (bdim // 2))
        ks = _cut_points(d, cut, window) if len(d) >= 2 * window else []
        bounds = [0, *(int(idx[k]) for k in ks), len(t.frames)]
        for lo, hi in zip(bounds, bounds[1:], strict=False):
            if hi - lo < 2:
                continue
            piece = Tracklet(
                t.track_id, t.frames[lo:hi], t.times[lo:hi], t.boxes[lo:hi], t.confs[lo:hi]
            )
            out.append(CourtTrack(piece, tr.court_m[lo:hi], tr.inside_fraction))
            src.append(i)
            mine = (idx >= lo) & (idx < hi)
            desc.append(d[mine].mean(axis=0) if mine.any() else whole)
    return out, src, desc


# --- small rosters: K identities (D-89) -------------------------------------

ROSTER_STEP_S = 0.5
ROSTER_SHARE = 0.25
"""K = the most people on court at once for at least this share of the clip's live time
(occlusion hides one for a while; a ghost box adds one for a moment)."""
ROSTER_ROUNDS = 3


DISTANT_SHARE = 0.35
"""A person whose usual box is shorter than this share of the tall players' (the 90th
percentile of the tracklets' median heights) stands far beyond a small game: people
across the park, behind the fence. The court fit cannot drop them when it is not trusted
(D-94), and counting them breaks the roster (the JaiArtHub clip, D-89 round 5)."""


def near_tracks(tracks: list[CourtTrack]) -> list[CourtTrack]:
    """`tracks` without the distant people (`DISTANT_SHARE`)."""
    h = np.array([np.median(np.asarray(t.tracklet.boxes)[:, 3]) for t in tracks])
    keep = h >= DISTANT_SHARE * np.percentile(h, 90)
    return [t for t, k in zip(tracks, keep, strict=True) if k]


def roster_size(tracks: list[CourtTrack], step_s: float = ROSTER_STEP_S) -> int:
    if not tracks:
        return 0
    t0 = min(t.tracklet.t_start for t in tracks)
    t1 = max(t.tracklet.t_end for t in tracks)
    ts = np.arange(t0, t1 + 1e-9, step_s)
    live = np.zeros(len(ts), dtype=int)
    for t in tracks:
        live += (ts >= t.tracklet.t_start) & (ts <= t.tracklet.t_end)
    live = live[live > 0]
    k = 0
    for c in range(1, int(live.max()) + 1):
        if np.mean(live >= c) >= ROSTER_SHARE:
            k = c
    return k


ROSTER_SWITCH = 0.5
"""Viterbi cost of the person in one tracklet changing (`app_distance` units): a swap
must out-look this over a few samples, a single odd crop never does."""


ROSTER_MARGIN = 0.08
"""How much worse than its best look a piece's person may look (`app_distance`)."""
ROSTER_EXTRA_S = 3.0
"""A piece that looks like none of the roster is kept as its own player if it lasts."""


def _app_matrix(x: np.ndarray, protos: np.ndarray) -> np.ndarray:
    """`app_distance` of every row of `x` to every prototype, vectorised."""
    n = x.shape[1] // 2
    rx, rp = np.sqrt(np.clip(x, 0, None)), np.sqrt(np.clip(protos, 0, None))
    return 1.0 - 0.5 * (rx[:, :n] @ rp[:, :n].T + rx[:, n:] @ rp[:, n:].T)


def _viterbi(cost: np.ndarray, switch: float) -> np.ndarray:
    """Cheapest label path through `cost` (samples x labels) with `switch` per change."""
    acc, back = cost[0].copy(), np.zeros(cost.shape, dtype=int)
    for i in range(1, len(cost)):
        stay, jump = acc, acc.min() + switch
        back[i] = np.where(stay <= jump, np.arange(cost.shape[1]), int(acc.argmin()))
        acc = np.minimum(stay, jump) + cost[i]
    path = np.empty(len(cost), dtype=int)
    path[-1] = int(acc.argmin())
    for i in range(len(cost) - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    return path


def roster_pieces(
    tracks: list[CourtTrack],
    series: list[tuple[np.ndarray, np.ndarray]],
    k: int,
    profile: Profile,
) -> tuple[list[CourtTrack], list[int], list[list[int]], np.ndarray | None]:
    """Solve a game of `k` people as `k` identities (D-89).

    Looks: seeded from the `k` tracklets alive together for longest (different people by
    construction), refined by k-means over every `body_hist` sample. Each tracklet's
    samples are labelled with a person by Viterbi (`ROSTER_SWITCH` per change) and the
    tracklet is cut where the label changes: that undoes the tracker's swaps with the
    roster's looks, not only with a local before/after test. Pieces are then placed,
    longest first, on their best-looking person who is free then (no two pieces of one
    person at once, nobody faster than a sprint between pieces); a piece nobody can
    take (a ghost box, a duplicate, a passer-by) stays on its own. Looks are re-estimated
    from the placement and everything is labelled again (`ROSTER_ROUNDS`).

    Returns the pieces, the tracklet each came from, the groups (`k` people, then one
    group per leftover piece) and the people's looks (None: no seeds to solve from)."""
    cfg = profile.tracking
    s = np.asarray([t.tracklet.t_start for t in tracks])
    e = np.asarray([t.tracklet.t_end for t in tracks])
    best, seeds = -1.0, np.zeros(0, dtype=int)
    for t in np.arange(s.min(), e.max() + 1e-9, ROSTER_STEP_S):
        alive = np.flatnonzero((s <= t) & (e >= t))
        if len(alive) < k:
            continue
        top = alive[np.argsort(-np.minimum(e[alive], t + 60))][:k]
        if (together := float(min(e[top].min(), t + 60) - t)) > best:
            best, seeds, t_seed = together, top, t
    if sum(len(series[i][1]) > 0 for i in seeds) < k:
        return tracks, list(range(len(tracks))), [[i] for i in range(len(tracks))], None
    looks = []
    for i in seeds:  # the seed's samples from the moment all k are together
        idx, d = series[i]
        w = tracks[i].tracklet.times[idx] >= t_seed - 1e-6
        looks.append(d[w].mean(axis=0) if w.any() else d.mean(axis=0))
    protos = np.stack(looks)
    allx = np.concatenate([d for _, d in series if len(d)])
    for _ in range(5):
        lab = _app_matrix(allx, protos).argmin(axis=1)
        protos = np.stack(
            [allx[lab == p].mean(axis=0) if (lab == p).any() else protos[p] for p in range(k)]
        )
    for _ in range(ROSTER_ROUNDS):
        pieces, src, costs, samples = [], [], [], []
        for i, (tr, (idx, d)) in enumerate(zip(tracks, series, strict=True)):
            t = tr.tracklet
            path = _viterbi(_app_matrix(d, protos), ROSTER_SWITCH) if len(d) else np.zeros(0, int)
            change = [j for j in range(1, len(path)) if path[j] != path[j - 1]]
            bounds = [0, *(int(idx[j]) for j in change), len(t.frames)]
            for lo, hi in zip(bounds, bounds[1:], strict=False):
                if hi - lo < 2:
                    continue
                piece = Tracklet(
                    t.track_id, t.frames[lo:hi], t.times[lo:hi], t.boxes[lo:hi], t.confs[lo:hi]
                )
                pieces.append(CourtTrack(piece, tr.court_m[lo:hi], tr.inside_fraction))
                src.append(i)
                mine = (idx >= lo) & (idx < hi)
                samples.append(d[mine])
                costs.append(_app_matrix(d[mine], protos).mean(axis=0) if mine.any() else None)
        ps = np.asarray([p.tracklet.t_start for p in pieces])
        pe = np.asarray([p.tracklet.t_end for p in pieces])
        owner = np.full(len(pieces), -1)
        # best-seen first (most clear samples, then longest): a long piece seen once in a
        # crowd must not take a slot from the person a well-seen piece clearly shows
        for i in sorted(range(len(pieces)), key=lambda i: (-len(samples[i]), ps[i] - pe[i])):
            c = costs[i]
            # a piece with no clear look goes to whoever was last seen nearest
            order = (
                np.argsort(c)
                if c is not None
                else np.argsort(
                    [_roster_gap(i, np.flatnonzero(owner == p), pieces, ps, pe) for p in range(k)]
                )
            )
            for p in order:
                # only a near-tie may go to its second choice: a second box on someone
                # already placed is a duplicate, not the next most similar person
                if c is not None and c[p] > min(c.min() + ROSTER_MARGIN, cfg.appearance_max * 2):
                    break
                if _roster_fits(i, np.flatnonzero(owner == p), pieces, ps, pe, cfg):
                    owner[i] = p
                    break
        protos = np.stack(
            [
                np.concatenate(
                    [samples[i] for i in np.flatnonzero(owner == p)] or [protos[p][None]]
                )
                .reshape(-1, protos.shape[1])
                .mean(axis=0)
                for p in range(k)
            ]
        )
    # A leftover that looks like someone placed is that person seen twice (a second box
    # on them, a long handover): its stretches where they are free join them, the rest
    # is dropped. A leftover that looks like nobody is someone else if it lasts.
    own = owner.tolist()
    for i in np.flatnonzero(owner < 0):
        c, t = costs[i], pieces[i].tracklet
        if c is None or c.min() > cfg.appearance_max * 2:
            own[i] = -1 if pe[i] - ps[i] >= ROSTER_EXTRA_S else -2
            continue
        own[i], p = -2, int(c.argmin())
        free = np.ones(len(t.times), dtype=bool)
        for j in np.flatnonzero(owner == p):
            free &= (t.times < ps[j]) | (t.times > pe[j])
        edges = np.flatnonzero(np.diff(np.r_[0, free.astype(int), 0]))
        for lo, hi in zip(edges[::2], edges[1::2], strict=True):
            if hi - lo < 2:
                continue
            sub = Tracklet(
                t.track_id, t.frames[lo:hi], t.times[lo:hi], t.boxes[lo:hi], t.confs[lo:hi]
            )
            pieces.append(CourtTrack(sub, pieces[i].court_m[lo:hi], pieces[i].inside_fraction))
            src.append(src[i])
            ps, pe = np.r_[ps, sub.t_start], np.r_[pe, sub.t_end]
            mine = [j for j, o in enumerate(own) if o == p]
            own.append(
                p
                if _roster_fits(len(pieces) - 1, np.asarray(mine, dtype=int), pieces, ps, pe, cfg)
                else -2
            )
    own = np.asarray(own)
    groups = [sorted(np.flatnonzero(own == p).tolist(), key=lambda i: ps[i]) for p in range(k)]
    return pieces, src, groups + [[int(i)] for i in np.flatnonzero(own == -1)], protos


def _roster_gap(
    i: int, mine: np.ndarray, tracks: list[CourtTrack], s: np.ndarray, e: np.ndarray
) -> float:
    """Court metres from piece `i` to the nearest-in-time piece of a person (inf: none)."""
    if not len(mine):
        return np.inf
    j = min(mine, key=lambda j: min(abs(s[i] - e[j]), abs(s[j] - e[i])))
    a = tracks[j].court_m[-1] if e[j] <= s[i] else tracks[j].court_m[0]
    b = tracks[i].court_m[0] if e[j] <= s[i] else tracks[i].court_m[-1]
    return float(np.linalg.norm(a - b))


def _roster_fits(
    i: int, mine: np.ndarray, tracks: list[CourtTrack], s: np.ndarray, e: np.ndarray, cfg
) -> bool:
    """Piece `i` joins a person's pieces `mine`: no overlap (beyond the handover slack)
    and each neighbour in time within sprinting reach."""
    for j in mine:
        if s[i] < e[j] - cfg.merge_overlap_s and s[j] < e[i] - cfg.merge_overlap_s:
            return False
    before = [j for j in mine if e[j] <= s[i] + cfg.merge_overlap_s]
    after = [j for j in mine if s[j] >= e[i] - cfg.merge_overlap_s]
    near = []
    if before:
        j = max(before, key=lambda j: e[j])
        near.append((tracks[j].court_m[-1], tracks[i].court_m[0], s[i] - e[j]))
    if after:
        j = min(after, key=lambda j: s[j])
        near.append((tracks[i].court_m[-1], tracks[j].court_m[0], s[j] - e[i]))
    return all(
        float(np.linalg.norm(b - a)) <= cfg.merge_max_dist_m + cfg.max_speed_mps * max(g, 0.0)
        for a, b, g in near
    )


TRACKS_MAX_GAP_S = 0.3
"""`tracks/` bridges a solved player's gaps up to this long (a box the labelling left
out); longer, the id has no box. Unsolved players are interpolated across every gap
(D-89: on the full games that kept the ring on the right kit longer). CC BY 2v2 proxy,
1000 picks: 0.3 s 93.7 % right while visible / 6.4 % wrong, 1 s 94.2 / 9.9, no cap
95.3 / 12.5."""
TRACKS_MAX_GAP_UNSOLVED_S = 2.0
"""The same for players not solved box by box (D-97; was every gap). A straight line
across a longer gap is a box on nobody: on the CC BY Nottingham game, hand-labelled
instants, 2.2 such boxes an instant with no cap, 0.6 at 2 s, 0.2 at 1 s, for 0.9 and 2.6
points of the players boxed. `fill_gaps` has already put in the boxes it could find."""


def max_gap_s(p: PlayerTrack) -> float:
    """Longest gap `tracks/` bridges for `p`."""
    return TRACKS_MAX_GAP_S if p.solved else TRACKS_MAX_GAP_UNSOLVED_S


BOX_SWITCH = 0.6
"""`roster_label` Viterbi cost of a tracklet's person changing, with a sample per box
(~15 Hz). Swept 0.3 / 0.6 / 1.2 on the CC BY 2v2 proxy: within 1 point of each other."""
BOX_NOBODY = 0.35
"""Look cost of "nobody" (a box on no one of the roster): above a clear look of anyone.
0.25 / 0.35 / 1.0 on the proxy: within a point."""
BOX_MAX_CLASH = 0.05
"""Share of labelled boxes that met another box of the same person in one frame above
which `roster_label` gives up: people who look alike (one kit) would trade boxes frame
by frame, where the pieces' no-two-places rule keeps them apart."""


def box_covers(tracks: list[CourtTrack]) -> list[np.ndarray]:
    """Per tracklet, per box: the largest share of it another box covers (`_cover`)."""
    at: dict[int, list[tuple[int, int]]] = {}
    for i, tr in enumerate(tracks):
        for j, f in enumerate(tr.tracklet.frames.tolist()):
            at.setdefault(int(f), []).append((i, j))
    out = [np.zeros(len(tr.tracklet.frames)) for tr in tracks]
    for here in at.values():
        boxes = np.asarray([tracks[i].tracklet.boxes[j] for i, j in here]).reshape(-1, 4)
        for n, (i, j) in enumerate(here):
            x, y, w, h = boxes[n]
            out[i][j] = _cover((x, y, max(w, 1), max(h, 1)), np.delete(boxes, n, axis=0))
    return out


def roster_label(
    tracks: list[CourtTrack],
    looks: list[tuple[np.ndarray, np.ndarray]],
    covers: list[np.ndarray],
    protos: np.ndarray,
) -> tuple[list[CourtTrack], list[int], list[list[int]]] | None:
    """Label every sampled box with one of the roster's people or nobody (D-89).

    `looks` has a `body_hist` per box, covered ones too: a covered box's look is blended
    toward "anyone" by its cover, so it keeps its tracklet's person unless the look says
    otherwise. Viterbi along each tracklet (`BOX_SWITCH` per change, `BOX_NOBODY` for
    nobody); then one box per person per frame, the best-looking. A piece is a run of
    one person's boxes in a tracklet; a box between two people's runs or on nobody is
    left out, so the ring shows no box there rather than the wrong person.
    Returns the pieces, the tracklet each came from, and `len(protos)` groups; None when
    more than `BOX_MAX_CLASH` of the boxes clashed."""
    k = len(protos)
    at: dict[int, list[tuple[int, int]]] = {}
    for i, (idx, _) in enumerate(looks):
        for n, j in enumerate(idx.tolist()):
            at.setdefault(int(tracks[i].tracklet.frames[j]), []).append((i, n))
    labs, costs = [], []
    for (idx, d), cov in zip(looks, covers, strict=True):
        c = _app_matrix(d.reshape(-1, protos.shape[1]), protos)
        w = np.clip(cov[idx], 0, 1)[:, None]
        c = (1 - w) * c + w * c.min(axis=1, keepdims=True, initial=1.0)
        c = np.hstack([c, np.full((len(c), 1), BOX_NOBODY)])
        labs.append(_viterbi(c, BOX_SWITCH) if len(c) else np.zeros(0, dtype=int))
        costs.append(c)
    clash = 0
    for here in at.values():
        for p in range(k):
            mine = [(i, n) for i, n in here if labs[i][n] == p]
            for i, n in sorted(mine, key=lambda m: costs[m[0]][m[1], p])[1:]:
                labs[i][n] = k
                clash += 1
    if clash > BOX_MAX_CLASH * max(sum(int((lab < k).sum()) for lab in labs), 1):
        return None
    pieces: list[CourtTrack] = []
    src: list[int] = []
    groups: list[list[int]] = [[] for _ in range(k)]
    for i, ((idx, _), lab) in enumerate(zip(looks, labs, strict=True)):
        t, tr = tracks[i].tracklet, tracks[i]
        edges = np.flatnonzero(np.diff(lab)) + 1
        for a, b in zip([0, *edges], [*edges, len(lab)], strict=True):
            if lab[a] == k or b - a < 2:
                continue
            lo, hi = int(idx[a]), int(idx[b - 1]) + 1
            piece = Tracklet(
                t.track_id, t.frames[lo:hi], t.times[lo:hi], t.boxes[lo:hi], t.confs[lo:hi]
            )
            groups[int(lab[a])].append(len(pieces))
            pieces.append(CourtTrack(piece, tr.court_m[lo:hi], tr.inside_fraction))
            src.append(i)
    for g in groups:
        g.sort(key=lambda n: pieces[n].tracklet.t_start)
    return pieces, src, groups


# --- net side ---------------------------------------------------------------

NET_WINDOW_S = 60.0


def net_line_y(template: CourtTemplate) -> float:
    """The net's court y. Templates state it; failing that the net is the court's
    mid-line, which is the geometry of every net sport."""
    if template.net_y is not None:
        return float(template.net_y)
    return float(np.mean(template.polygon[:, 1]))


def net_side(
    tracks: list[CourtTrack], net_y: float, *, window_s: float = NET_WINDOW_S
) -> np.ndarray:
    """Team = which side of the net the player stands on (§4.4 step 6).

    Per fixed `window_s` slice of the clip: sign of (median court y - net y). The
    tracklet's team is the majority over the slices it touches; a tie goes to side 0.

    # ponytail: fixed windows, not rallies. §4.4 wants the side re-evaluated per rally
    # so an end change is picked up exactly, but `events.detect_rallies` is a stub, so
    # there are no rally bounds to slice on. Ceiling: an end change *inside* a 60 s
    # window is invisible, and a tracklet straddling one gets whichever side it spent
    # more windows on. Upgrade: feed rally bounds in place of the fixed window.
    """
    out = np.zeros(len(tracks), dtype=int)
    for i, tr in enumerate(tracks):
        slot = (tr.tracklet.times // window_s).astype(int)
        far = [float(np.median(tr.court_m[slot == s, 1])) > net_y for s in np.unique(slot)]
        out[i] = int(sum(far) * 2 > len(far))
    return out


def assign_teams(
    hists: np.ndarray | None,
    tracks: list[CourtTrack],
    profile: Profile,
    template: CourtTemplate,
) -> np.ndarray:
    rule = profile.team_rule
    if rule == "jersey_color":
        assert hists is not None, "jersey_color needs sampled appearance"
        return split_teams(hists)
    if rule == "net_side":
        return net_side(tracks, net_line_y(template))
    raise ValueError(f"unknown team_rule {rule!r}")


def team_colors(teams: np.ndarray, profile: Profile, colors: np.ndarray | None) -> dict[int, str]:
    """Fixed colours when the profile names them (net sports: four people, four shirts,
    so the jersey tells you nothing), otherwise the mean torso colour per team."""
    fixed = profile.teams.colors
    return {
        int(t): fixed[int(t) % len(fixed)] if fixed else bgr_to_hex(colors[teams == t].mean(axis=0))  # type: ignore[index]
        for t in np.unique(teams)
    }


# --- teams from play (pickup games where every shirt differs) ----------------

KIT_MAX_RATIO = 0.6
"""Kits split the players only when teammates' torso histograms are this much closer
than opponents' (mean teammate distance / mean opponent distance, `kit_ratio`). Two real
kits put teammates near-identical; a pickup game where every shirt differs does not."""
MATCHUP_STEP_S = 0.5
MATCHUP_GUARD_M = 3.5
"""A pair counts as guarding at an instant when they are this close (court metres)."""
MATCHUP_SMOOTH_S = 5.5
"""Roles are read off the nearer-the-basket difference averaged over this long: a cut
to the rim flips it for a second, a possession lasts several."""
MATCHUP_MIN_CORR = 0.2
"""`matchup_teams` is believed when the defend/attack roles of its pairs agree at least
this much (mean |correlation|, 0 = no relation). Owner's 2v2 game (tuned there, the only
game measured): 0.40, the right teams; the sign was right for every guard distance and
window tried (2.5-3.5 m, 0.5-10 s), the size 0.06-0.41. Matchup colours are fixed
(`MATCHUP_COLORS`): a team of different shirts has no colour of its own."""
MATCHUP_COLORS = ("#E8A33D", "#3D7BE8")


def _nan_smooth(x: np.ndarray, n: int) -> np.ndarray:
    """Centred mean over `n` samples, ignoring NaN; NaN where fewer than a third are seen."""
    ok = np.isfinite(x)
    k = np.ones(max(n, 1))
    num = np.convolve(np.where(ok, x, 0.0), k, "same")
    den = np.convolve(ok.astype(float), k, "same")
    return np.where(den > len(k) / 3, num / np.maximum(den, 1.0), np.nan)


def kit_ratio(hists: np.ndarray, teams: np.ndarray) -> float | None:
    """Mean torso-histogram distance between teammates over that between opponents, one
    histogram per player; None without both kinds of pair."""
    d = np.linalg.norm(hists[:, None] - hists[None], axis=-1)
    i, j = np.triu_indices(len(hists), 1)
    same = teams[i] == teams[j]
    if not same.any() or same.all():
        return None
    return float(d[i, j][same].mean() / max(d[i, j][~same].mean(), 1e-9))


def _matchings(idx: list[int]) -> list[list[tuple[int, int]]]:
    """Every way to split `idx` (even length) into pairs."""
    if not idx:
        return [[]]
    a, rest = idx[0], idx[1:]
    return [[(a, b), *m] for k, b in enumerate(rest) for m in _matchings(rest[:k] + rest[k + 1 :])]


def matchup_teams(
    tracks: list[CourtTrack], rims: list[tuple[float, float]], max_gap_s: float = 1.0
) -> tuple[np.ndarray, float] | None:
    """Teams from who guards whom, for a 2v2 or 3v3 where the shirts say nothing.

    Defenders shadow their man, so over a game the pairing whose pairs stay closest
    (median court distance) is the opponents. Which partner is whose teammate comes from
    roles: while guarding, the defender is the one nearer the basket, and teammates defend
    (and attack) at the same time. Returns (team per track, mean |role correlation|), or
    None when the roster is not 4 or 6, there is no basket, or too little overlap.
    """
    n = len(tracks)
    if n % 2 or not 4 <= n <= 6 or not rims:
        return None
    t0 = min(t.tracklet.t_start for t in tracks)
    t1 = max(t.tracklet.t_end for t in tracks)
    times = np.arange(t0, t1, MATCHUP_STEP_S)
    pos = np.stack([resample(t, times, max_gap_s)[1] for t in tracks])  # (n, T, 2)
    dist = np.linalg.norm(pos[:, None] - pos[None], axis=-1)  # (n, n, T)
    seen = np.isfinite(dist)
    if (seen.sum(axis=-1) + np.eye(n, dtype=int) * 10**9).min() < 20:
        return None
    med = np.nanmedian(np.where(seen, dist, np.nan), axis=-1)
    pairs = min(_matchings(list(range(n))), key=lambda m: sum(med[a, b] for a, b in m))
    rim = np.asarray(rims, dtype=np.float64)
    roles = []
    for a, b in pairs:
        mid = (pos[a] + pos[b]) / 2
        near = rim[np.argmin(np.linalg.norm(mid[:, None] - rim[None], axis=-1), axis=1)]
        ra, rb = (np.linalg.norm(pos[k] - near, axis=1) for k in (a, b))
        guarding = np.where(dist[a, b] < MATCHUP_GUARD_M, rb - ra, np.nan)
        roles.append(np.sign(_nan_smooth(guarding, round(MATCHUP_SMOOTH_S / MATCHUP_STEP_S))))
    corr = np.zeros((len(pairs), len(pairs)))
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            both = np.isfinite(roles[i]) & np.isfinite(roles[j])
            corr[i, j] = corr[j, i] = (
                float(np.mean(roles[i][both] * roles[j][both])) if both.any() else 0.0
            )
    # flip +1: the pair's first player is on team 0. The flips whose roles agree most.
    best = max(
        (
            np.array([1, *(1 - 2 * np.asarray(f, dtype=int))])
            for f in np.ndindex(*(2,) * (len(pairs) - 1))
        ),
        key=lambda flips: float(flips @ corr @ flips),
    )
    teams = np.zeros(n, dtype=int)
    for (a, b), f in zip(pairs, best, strict=True):
        teams[a], teams[b] = (0, 1) if f > 0 else (1, 0)
    iu = np.triu_indices(len(pairs), 1)
    return teams, float(np.mean(np.abs(corr[iu])))


def _player_means(merged: list[tuple[list[int], CourtTrack]], per_piece: np.ndarray) -> np.ndarray:
    return np.stack([per_piece[g].mean(axis=0) for g, _ in merged])


def play_teams(
    merged: list[tuple[list[int], CourtTrack]],
    kit_teams: np.ndarray,
    hists: np.ndarray | None,
    template: CourtTemplate,
) -> np.ndarray | None:
    """`matchup_teams` for the merged players when the kits do not split them: an uneven
    split (3 v 1 in a 2v2) or teammates' shirts no closer than opponents' (`kit_ratio`).
    None when the kits stand or the matchups are not clear."""
    n = len(merged)
    if n % 2 or not 4 <= n <= 6:
        return None
    even = np.bincount(kit_teams, minlength=2).tolist() == [n // 2, n // 2]
    ratio = None if hists is None else kit_ratio(_player_means(merged, hists), kit_teams)
    if even and (ratio is None or ratio < KIT_MAX_RATIO):
        return None
    rims = list(template.rims) or ([template.rim] if template.rim else [])
    found = matchup_teams([c for _, c in merged], rims)
    if found is None or found[1] < MATCHUP_MIN_CORR:
        return None
    return found[0]


# --- merging ----------------------------------------------------------------

# Link cost (merge_groups): court distance in units of LINK_SCALE_M + LINK_SPEED_MPS x gap
# (where the player can plausibly have got to), plus LINK_GAP_COST per second of gap; a
# link that costs more than LINK_MAX_COST is left unmade. Tuned on synthetic basketball
# seeds 13 and 17 (not the M1 seeds 7 / 11), docs/evidence/M1/README.md.
LINK_SCALE_M = 1.0
LINK_SPEED_MPS = 3.0
LINK_GAP_COST = 0.3
LINK_MAX_COST = 2.0


def merge_groups(
    tracks: list[CourtTrack],
    teams: np.ndarray,
    profile: Profile,
    body: np.ndarray | None = None,
) -> list[list[int]]:
    """Group tracklet indices that are the same person: small time gap, small court
    distance, same team (§4.4 step 6).

    Each tracklet gets at most one predecessor and one successor, so a group is a chain
    through time, and the links are one global assignment (Hungarian, `lap`) over a cost
    that grows with distance per second of gap (LINK_* above). Cheapest-first greedy
    linking used to take a long-gap link that happened to land close over the short-gap
    one that was right; earliest-first before it handed a fragment to whichever old
    track *started* first.

    A link may overlap by up to `merge_overlap_s`: ByteTrack gives a person a new id a
    frame or so before it drops the old one, and on the badminton clip that one-frame
    overlap alone kept a 57 s tracklet out of every group (samples/real/RESULTS.md).

    With `body` descriptors (`body_hist`) and `tracking.appearance_weight` > 0, the weight
    times the appearance distance is added to a link's cost, and links above
    `appearance_max` are refused. It stays off: it did not move IDF1 (D-61, and again
    with the global assignment).
    """
    cfg = profile.tracking
    use_app = body is not None and cfg.appearance_weight > 0
    n = len(tracks)
    starts = np.asarray([t.tracklet.t_start for t in tracks])
    ends = np.asarray([t.tracklet.t_end for t in tracks])
    links: list[tuple[float, int, int]] = []
    for a in range(n):
        gap = starts - ends[a]
        cand = np.flatnonzero(
            (gap >= -cfg.merge_overlap_s)
            & (gap <= cfg.merge_max_gap_s)
            & (ends > ends[a])  # a continuation outlives what it continues
            & (teams == teams[a])
        )
        for b in cand:
            here = tracks[a].court_at(starts[b]) if gap[b] < 0 else tracks[a].court_m[-1]
            dist = float(np.linalg.norm(tracks[b].court_m[0] - here))
            reach = cfg.merge_max_dist_m
            if cfg.merge_reach_m > 0:  # nobody covers 7 m in a tenth of a second
                reach = min(reach, cfg.merge_reach_m + cfg.max_speed_mps * max(gap[b], 0.0))
            if dist > reach:
                continue
            g = max(float(gap[b]), 0.0)
            cost = dist / (LINK_SCALE_M + LINK_SPEED_MPS * g) + LINK_GAP_COST * g
            if use_app:
                d_app = app_distance(body[a], body[b])  # type: ignore[index]
                if d_app > cfg.appearance_max:
                    continue
                cost += cfg.appearance_weight * d_app
            links.append((cost, a, int(b)))

    if links:  # one global assignment of successors to predecessors
        mat = np.full((n, n), 1e6)
        for c, a, b in links:
            mat[a, b] = c
        _, x, _ = lap.lapjv(mat, extend_cost=True, cost_limit=LINK_MAX_COST)
        links = [(mat[a, b], a, int(b)) for a, b in enumerate(x) if b >= 0 and mat[a, b] < 1e6]

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    has_next, has_prev = [False] * n, [False] * n
    for _, a, b in sorted(links):
        if has_next[a] or has_prev[b] or find(a) == find(b):
            continue
        parent[find(b)] = find(a)
        has_next[a] = has_prev[b] = True

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = [sorted(g, key=lambda i: starts[i]) for g in groups.values()]
    return sorted(out, key=lambda g: starts[g[0]])


def _concat(tracks: list[CourtTrack], group: list[int], interleave: bool = False) -> CourtTrack:
    """One track from a time-ordered group; where two members overlap (a handover),
    the later member's samples before the earlier one's end are dropped. `interleave`:
    members never share a frame (`roster_label`), so a member inside another's hole
    fills it instead."""
    members = [tracks[i] for i in group]
    keep, last = [], -np.inf
    for m in members:
        k = m.tracklet.times > last
        keep.append(np.ones_like(k) if interleave else k)
        if k.any():
            last = float(m.tracklet.times[k][-1])
    tl = [m.tracklet for m in members]
    merged = Tracklet(
        track_id=tl[0].track_id,
        frames=np.concatenate([t.frames[k] for t, k in zip(tl, keep, strict=True)]),
        times=np.concatenate([t.times[k] for t, k in zip(tl, keep, strict=True)]),
        boxes=np.concatenate([t.boxes[k] for t, k in zip(tl, keep, strict=True)]),
        confs=np.concatenate([t.confs[k] for t, k in zip(tl, keep, strict=True)]),
    )
    court = np.concatenate([m.court_m[k] for m, k in zip(members, keep, strict=True)])
    if interleave:
        o = np.argsort(merged.times, kind="stable")
        merged = Tracklet(
            merged.track_id, merged.frames[o], merged.times[o], merged.boxes[o], merged.confs[o]
        )
        court = court[o]
    lifetime = sum(t.lifetime_s for t in tl) or 1.0
    frac = sum(m.inside_fraction * (t.lifetime_s or 1.0) for m, t in zip(members, tl, strict=True))
    return CourtTrack(merged, court, frac / lifetime)


def _fits(span: tuple[float, float], accepted: list[tuple[float, float]], max_n: int) -> bool:
    """True if `span` can join `accepted` without ever exceeding `max_n` at once."""
    s, e = span
    live = [a for a in accepted if a[0] < e and a[1] > s]
    if len(live) < max_n:
        return True
    # The overlap count is a step function that only steps up at an interval start, so
    # checking `s` and every accepted start inside the span finds its maximum exactly.
    return all(
        sum(a[0] <= t < a[1] for a in live) < max_n for t in (s, *(a[0] for a in live if a[0] > s))
    )


def on_court_cap(profile: Profile) -> int:
    """Most people identity keeps alive at once: the players plus the officials (D-97).
    Referees are tracked like anyone else, so with a cap of `players.max` alone the three
    referees of the CC BY Nottingham game held three of ten slots and 32 % of the players'
    hand-labelled boxes had no id; with 13, 13 %."""
    return profile.players.max + profile.tracking.officials


def _cap_concurrent(
    merged: list[tuple[list[int], CourtTrack]], max_n: int, overlap_s: float = 0.0
) -> list[tuple[list[int], CourtTrack]]:
    """Keep at most `max_n` players alive at any instant, best score first.

    `players.max` is a *concurrency* cap, not a roster cap: the ten best merges over a
    240 s clip need not be contemporaneous, and capping globally left 2-3 selectable
    boxes late in the Kennesaw clip while ten people were on court (samples/real/
    RESULTS.md). Greedy by score; the output can hold more than `max_n` players.

    An id handover overlaps the old id by a frame or two; the last `overlap_s` of each
    life is not counted, or that one frame rejects the whole new player.
    """
    kept: list[tuple[list[int], CourtTrack]] = []
    spans: list[tuple[float, float]] = []
    for g, c in merged:
        t0, t1 = c.tracklet.t_start, c.tracklet.t_end
        span = (t0, max(t0, t1 - overlap_s))
        if _fits(span, spans, max_n):
            kept.append((g, c))
            spans.append(span)
    return kept


STITCH_SLACK_S = 1.0
"""A player half hidden by the net, a partner or the frame edge has a foot point that is
off by about a second of running at either end of the break."""


def _group_desc(tracks: list[CourtTrack], group: list[int], body: np.ndarray) -> np.ndarray:
    """A merged player's appearance: its pieces' `body_hist`, weighted by lifetime."""
    w = np.asarray([max(tracks[i].tracklet.lifetime_s, 0.1) for i in group])
    return (body[group] * w[:, None]).sum(axis=0) / w.sum()


def _stitch(
    tracks: list[CourtTrack],
    groups: list[list[int]],
    teams: np.ndarray,
    profile: Profile,
    body: np.ndarray | None = None,
) -> list[list[int]]:
    """Chain whole players into one when the roster says they must be one person.

    Walk players in start order and keep "lanes" per team. A player who appears while
    their team has fewer than its share of `players.max` alive continues the nearest
    lane that ended within `stitch_max_gap_s` and is within running reach. This is what
    the concurrency cap (D-21) knows and `merge_groups` cannot: on the badminton clip
    every remaining break was a 3-9 m foot jump at an occlusion by the net or at the
    frame edge, past `merge_max_dist_m`, while the other three players were all still
    tracked.

    The stitched player's box is interpolated across the gap (`court.resample`), so a
    stitch whose gap would take the frame past `players.max` boxes is refused.

    With `body` (piece descriptors) and `tracking.appearance_weight` > 0, a stitch to a
    lane whose appearance differs by more than `appearance_max` is refused: the roster
    argument says *someone* continues the lane, not who.
    """
    cfg = profile.tracking
    use_app = body is not None and cfg.appearance_weight > 0
    cap = on_court_cap(profile)
    per_team = -(-cap // max(1, len(np.unique(teams))))
    lanes: list[list[int]] = []  # each lane is a list of group indices, in time order
    start = [tracks[g[0]].tracklet.t_start for g in groups]
    ends = [max(tracks[i].tracklet.t_end for i in g) for g in groups]
    alive = [(s, max(s, e - cfg.merge_overlap_s)) for s, e in zip(start, ends, strict=True)]

    def last_pos(gi: int) -> np.ndarray:
        last = max(groups[gi], key=lambda i: tracks[i].tracklet.t_end)
        return tracks[last].court_m[-1]

    for gi in sorted(range(len(groups)), key=lambda i: start[i]):
        team, s = teams[groups[gi][0]], start[gi]
        mine = [ln for ln in lanes if teams[groups[ln[0]][0]] == team]
        busy = sum(ends[ln[-1]] > s + cfg.merge_overlap_s for ln in mine)
        best, best_d = None, np.inf
        if busy < per_team:
            for ln in mine:
                gap = s - ends[ln[-1]]
                if not -cfg.merge_overlap_s <= gap <= cfg.stitch_max_gap_s:
                    continue
                d = float(np.linalg.norm(tracks[groups[gi][0]].court_m[0] - last_pos(ln[-1])))
                reach = cfg.merge_max_dist_m + cfg.max_speed_mps * max(gap, STITCH_SLACK_S)
                if d > reach or d >= best_d:
                    continue
                if gap > 0 and not _fits((ends[ln[-1]], s), alive, cap):
                    continue
                if use_app and (
                    app_distance(
                        _group_desc(tracks, groups[gi], body),  # type: ignore[arg-type]
                        _group_desc(tracks, groups[ln[-1]], body),  # type: ignore[arg-type]
                    )
                    > cfg.appearance_max
                ):
                    continue
                best, best_d = ln, d
        if best is None:
            lanes.append([gi])
        else:
            if s > ends[best[-1]]:
                alive.append((ends[best[-1]], s))
            best.append(gi)
    return [[i for gi in ln for i in groups[gi]] for ln in lanes]


def identify(
    video: str,
    tracks: list[CourtTrack],
    profile: Profile,
    variant: str | None = None,
    *,
    court_ok: bool = True,
    standard: str | None = None,
) -> list[PlayerTrack]:
    """Tracklets → `p1..pN` with team labels and team colours. `court_ok` false (the
    court fit disagrees with the people, `court.fit_check`): nobody is dropped as a
    bystander for where they stand, only for standing still. `standard`: the court
    markings calib.json was fitted with.

    Teams come from the kits (`team_source` "kit"); in a 2v2 or 3v3 the kits cannot split
    (every shirt differs) from who guards whom ("matchups", `play_teams`)."""
    if not tracks:
        return []
    # Only `jersey_color` needs pixels, and decoding the clip for torso crops is the
    # expensive half of this stage — a net sport skips it entirely.
    need = profile.team_rule == "jersey_color" or profile.tracking.appearance_weight > 0
    hists, colors, body = sample_appearance(video, tracks) if need else (None, None, None)
    teams = assign_teams(hists, tracks, profile, profile.template(variant, standard))
    kits = None  # (torso histograms, teams) the kit centroids come from, for `off_kit`
    if profile.team_rule == "jersey_color" and len(np.unique(teams)) == 2:
        kits = (hists, teams)
        n = len(tracks)
        lab, clear = jersey_labels(video, tracks, hists, teams)  # type: ignore[arg-type]
        # The gate reads every sample, as D-70 measured it (Kennesaw 0.80); only the cut
        # skips torsos another player stands over.
        agree = np.mean([v == teams[i] for i, d in enumerate(lab) for v in d.values()] or [0])
        if agree >= JERSEY_MIN_AGREE:
            tracks, teams = split_switches(tracks, lab, teams, clear=clear)
        if len(tracks) != n:  # the pieces need their own appearance (team colours)
            hists, colors, body = sample_appearance(video, tracks)
    cfg = profile.tracking
    roster, groups, labelled = 0, [], False
    if cfg.appearance_cut > 0:  # D-89: undo the tracker's swaps, then link by look too
        # people far beyond a small game do not count toward its size (`DISTANT_SHARE`)
        roster = roster_size(near_tracks(tracks)) if cfg.roster_max > 0 else 0
        if 0 < roster <= cfg.roster_max:
            # every box's look, covered ones too; the piece solve reads the clear ones at
            # its own pace (`APP_EVERY_S`) for the people's looks, then every box is labelled
            looks = body_series(video, tracks, every_s=0.0, max_cover=1.0)
            covers = box_covers(tracks)
            series = [_clear_every(tracks[i], d, covers[i]) for i, d in enumerate(looks)]
            pieces, src, groups, protos = roster_pieces(tracks, series, roster, profile)
            boxwise = None if protos is None else roster_label(tracks, looks, covers, protos)
            if boxwise is None:
                tracks = pieces
            else:
                tracks, src, groups = boxwise
                groups = [g for g in groups if g]
                labelled = True
        else:
            series = body_series(video, tracks)
            tracks, src, pieces = split_appearance(tracks, series, cfg.appearance_cut)
            body = np.asarray(pieces)
        teams = teams[src]
        colors = None if colors is None else colors[src]
        hists = None if hists is None else hists[src]
    colours = team_colors(teams, profile, colors)
    if not (0 < roster <= cfg.roster_max):
        groups = merge_groups(tracks, teams, profile, body)
        polygon = profile.template(variant, standard).polygon
        merged = [
            (g, c)
            for g in groups
            for c in [_concat(tracks, g)]
            if not (
                bystander(c, polygon, profile.tracking)
                if court_ok
                else stationary(c, profile.tracking)
            )
        ]
        # `players.max` caps *merged* players, not raw tracklets (§4.4 step 5 applied
        # after step 6): a player broken into six tracklets should still beat a bystander
        # with one long one. Score is the merged lifetime weighted by time spent on court,
        # and the cap is on how many are alive at once. Ids follow the score of the
        # stitched players.
        merged.sort(key=lambda gc: gc[1].score, reverse=True)
        merged = _cap_concurrent(merged, on_court_cap(profile), profile.tracking.merge_overlap_s)
        # ponytail: no re-identification across gaps longer than _stitch's. A mutual-best,
        # margin-gated relink over these descriptors was built and measured (D-89): it
        # made 4-5 links per game and the ring sat on the right kit slightly less often.
        # Upgrade path: a stronger cue (jersey numbers, a licence-clean re-ID model).
        groups = _stitch(tracks, [g for g, _ in merged], teams, profile, body)
    merged = sorted(
        ((g, _concat(tracks, g, labelled)) for g in groups),
        key=lambda gc: gc[1].score,
        reverse=True,
    )
    team_of = np.asarray([int(np.bincount(teams[g]).argmax()) for g, _ in merged], dtype=int)
    source = "kit" if profile.team_rule == "jersey_color" else profile.team_rule
    if kits is not None and merged:
        by_play = play_teams(merged, team_of, hists, profile.template(variant, standard))
        if by_play is not None:
            team_of, source = by_play, "matchups"
            colours = dict(enumerate(MATCHUP_COLORS))
    off = [None] * len(merged)
    if kits is not None and merged and source == "kit":
        lab, _ = jersey_labels(video, [c for _, c in merged], *kits, every=OFF_KIT_EVERY)
        off = [
            round(float(np.mean([v != int(team_of[k]) for v in d.values()])), 3) if d else None
            for k, d in enumerate(lab)
        ]
    players: list[PlayerTrack] = []
    for n, (group, track) in enumerate(merged, start=1):
        team = int(team_of[n - 1])
        players.append(
            PlayerTrack(
                player_id=f"p{n}",
                team=team,
                team_source=source,
                color_hex=colours[team],
                track=track,
                members=tuple(dict.fromkeys(tracks[i].track_id for i in group)),
                spans=tuple(
                    (
                        tracks[i].track_id,
                        round(tracks[i].tracklet.t_start, 3),
                        round(tracks[i].tracklet.t_end, 3),
                    )
                    for i in group
                ),
                solved=labelled,
                off_kit=off[n - 1],
            )
        )
    return players


# --- gap fill (D-97) --------------------------------------------------------

FILL_MIN_IOU = 0.3
"""A free detection continues a player's chain through a gap when it overlaps the chain's
last box this much (one sampled frame apart, ~1/15 s: a sprinter moves a fraction of a box)."""
FILL_SKIP = 3
"""Sampled frames a chain may coast over without a box before it gives up."""


def _chain(
    frames: list[int], start: np.ndarray, by_f: dict[int, np.ndarray], free: dict[int, np.ndarray]
) -> dict[int, int]:
    """Follow free detections from `start` through `frames` by overlap with the last box
    taken; claims what it takes. Returns frame -> detection row."""
    last, miss, got = start, 0, {}
    for f in frames:
        a, ok = by_f[f], free[f]
        if ok.any():
            v = np.where(ok, box_iou(last, a), 0.0)
            k = int(v.argmax())
            if v[k] >= FILL_MIN_IOU:
                got[f], last, miss = k, a[k, :4], 0
                free[f][k] = False
                continue
        miss += 1
        if miss > FILL_SKIP:
            break
    return got


def fill_gaps(
    players: list[PlayerTrack],
    dets: dict,
    h: np.ndarray,
    *,
    k1: float = 0.0,
    image_size: tuple[int, int] | None = None,
    smooth_window: int = 5,
) -> list[PlayerTrack]:
    """Fill each player's gaps with the detections no player holds (D-97).

    Merging and stitching join a person's pieces across gaps, and `tracks/` used to draw a
    straight line across each one: on the CC BY Nottingham game a third of the players'
    slots at a hand-labelled instant were such a line, a box on nobody. The person is often
    still detected there, in a tracklet too short to keep or one the concurrency cap
    dropped, or as a box the tracker never gave an id. Here every detection in `dets` that
    no player's box covers (IoU >= 0.5) is free; best-scored player first, a chain is
    followed forward from the box before each gap, then backward from the box after it,
    by overlap with the last box taken (`FILL_MIN_IOU`, coasting `FILL_SKIP` frames).
    What is still missing stays a gap for `tracks/` to bridge."""

    by_f = {
        int(fr["f"]): np.asarray([r[1:6] for r in fr["d"]], dtype=np.float64).reshape(-1, 5)
        for fr in dets["frames"]
    }
    t_of = {int(fr["f"]): float(fr["t"]) for fr in dets["frames"]}
    free = {f: np.ones(len(a), dtype=bool) for f, a in by_f.items()}
    for p in players:
        t = p.track.tracklet
        for f, b in zip(t.frames.tolist(), t.boxes, strict=True):
            if f in by_f and len(by_f[f]):
                free[f] &= box_iou(b, by_f[f]) < 0.5
    ordered = np.asarray(sorted(by_f), dtype=np.int64)
    out: list[PlayerTrack] = []
    for p in players:
        t = p.track.tracklet
        add: dict[int, np.ndarray] = {}
        for j in range(len(t.frames) - 1):
            lo, hi = int(t.frames[j]), int(t.frames[j + 1])
            a, b = np.searchsorted(ordered, lo, "right"), np.searchsorted(ordered, hi, "left")
            gap = ordered[a:b].tolist()
            if not gap:
                continue
            fwd = _chain(gap, t.boxes[j], by_f, free)
            rest = [f for f in gap if f > max(fwd, default=lo)]
            bwd = _chain(rest[::-1], t.boxes[j + 1], by_f, free)
            add.update({f: by_f[f][k] for f, k in {**fwd, **bwd}.items()})
        if not add:
            out.append(p)
            continue
        fs = np.concatenate([t.frames, np.asarray(sorted(add), dtype=np.int64)])
        o = np.argsort(fs, kind="stable")
        new = Tracklet(
            t.track_id,
            fs[o],
            np.concatenate([t.times, [t_of[f] for f in sorted(add)]])[o],
            np.concatenate([t.boxes, [add[f][:4] for f in sorted(add)]])[o],
            np.concatenate([t.confs, [add[f][4] for f in sorted(add)]])[o],
        )
        court_m = to_court([new], h, smooth_window=smooth_window, k1=k1, image_size=image_size)[0]
        out.append(replace(p, track=CourtTrack(new, court_m, p.track.inside_fraction)))
    return out


def seen_s(p: PlayerTrack, rate_hz: int = 10) -> float:
    """Seconds `p` has a box in `tracks/`: the frames of the export's time grid
    (`pipeline.stage_tracks`: multiples of 1/rate_hz) its box is on, over rate_hz."""
    t = p.track.tracklet
    k = np.arange(np.ceil(t.t_start * rate_hz - 1e-6), np.floor(t.t_end * rate_hz + 1e-6) + 1)
    boxes, _, _ = resample(p.track, k / rate_hz, max_gap_s(p))
    return round(float(np.isfinite(boxes).all(axis=1).sum()) / rate_hz, 1)


def to_models(players: list[PlayerTrack]) -> tuple[list[PlayerModel], list[TeamModel]]:
    teams = {p.team: p.color_hex for p in players}
    # additive `team_source` (extra field): a team any of whose players the user placed
    # is the user's; otherwise how the pipeline split it
    sources: dict[int, str | None] = {}
    for p in players:
        was = sources.get(p.team)
        sources[p.team] = "user" if "user" in (was, p.team_source) else was or p.team_source
    return (
        [
            PlayerModel(
                id=p.player_id,
                name=None,
                team=p.team,
                color_hex=p.color_hex,
                tagged=False,
                seen_s=seen_s(p),
                team_mixed=None if p.off_kit is None else p.off_kit > TEAM_MIXED_SHARE,
                team_source=p.team_source,
            )
            for p in players
        ],
        [
            TeamModel(id=t, color_hex=c, team_source=sources.get(t))
            for t, c in sorted(teams.items())
        ],
    )


def apply_team_edits(game_dir: Path) -> bool:
    """The user's team picks win (`PATCH /players/{pid}` with `team`, recorded in the
    game's edits.json as a game.json patch): copied onto `_work/players.json`, which events,
    plays and the score read, with `team_source` "user". Run after identity computes or
    restores players.json, so a pick survives every re-process. Returns whether the file
    changed; written tmp + rename (a worker cache may hard-link it)."""
    edits, path = Path(game_dir) / "edits.json", Path(game_dir) / "_work" / "players.json"
    if not edits.is_file() or not path.is_file():
        return False
    patch = (json.loads(edits.read_text(encoding="utf-8")).get("patch") or {}).get(
        "game.json"
    ) or {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for d in raw.get("players", []):
        pick = (patch.get(d["player_id"]) or {}).get("team")
        if pick is None or (int(pick) == d["team"] and d.get("team_source") == "user"):
            continue
        color = (patch.get(d["player_id"]) or {}).get("color_hex")
        d.update(
            team=int(pick), team_source="user", off_kit=None, color_hex=color or d["color_hex"]
        )
        changed = True
    if changed:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(raw), encoding="utf-8")
        tmp.replace(path)
    return changed


# --- io ---------------------------------------------------------------------

PLAYERS_SCHEMA = "courtcam.players.v1"


def write_players(path, players: list[PlayerTrack], meta: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": PLAYERS_SCHEMA,
                **meta,
                "players": [
                    {
                        "player_id": p.player_id,
                        "team": p.team,
                        "color_hex": p.color_hex,
                        "members": list(p.members),
                        "spans": [list(s) for s in p.spans],
                        "solved": p.solved,
                        "off_kit": p.off_kit,
                        "team_source": p.team_source,
                        **track_json(p.track),
                    }
                    for p in players
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def read_players(path: Path) -> tuple[list[PlayerTrack], dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    players = [
        PlayerTrack(
            player_id=d["player_id"],
            team=int(d["team"]),
            color_hex=d["color_hex"],
            track=track_from_json(d),
            members=tuple(d.get("members", ())),
            spans=tuple((int(s[0]), float(s[1]), float(s[2])) for s in d.get("spans", ())),
            solved=bool(d.get("solved", False)),
            off_kit=d.get("off_kit"),
            team_source=d.get("team_source"),
        )
        for d in raw["players"]
    ]
    return players, {k: v for k, v in raw.items() if k != "players"}
