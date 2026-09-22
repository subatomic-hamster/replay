"""Stage 6 — team split and tracklet merging into stable player ids (plan §4.4 step 6).

Identity switches through occlusion are expected; the tag UI is the correction
mechanism, so nothing here tries to be clever.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .court import CourtTrack, track_from_json, track_json
from .profiles import CourtTemplate, Profile
from .schema import Player as PlayerModel
from .schema import Team as TeamModel
from .track import Tracklet

H_BINS, S_BINS = 12, 4


@dataclass(frozen=True, slots=True)
class PlayerTrack:
    """One merged player: a stable id over one or more local tracklets."""

    player_id: str
    team: int
    color_hex: str
    track: CourtTrack
    members: tuple[int, ...]  # local track ids that were merged in

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
    hist = cv2.calcHist([hsv], [0, 1], None, [H_BINS, S_BINS], [0, 180, 0, 256]).ravel()
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


def sample_appearance(
    video: str, tracks: list[CourtTrack], *, samples: int = 8
) -> tuple[np.ndarray, np.ndarray]:
    """Per-tracklet (HSV histogram, mean BGR) from `samples` torso crops each."""
    wanted: dict[int, list[tuple[int, np.ndarray]]] = {}
    for i, tr in enumerate(tracks):
        t = tr.tracklet
        idx = np.unique(np.linspace(0, len(t.frames) - 1, min(samples, len(t.frames))).astype(int))
        for j in idx:
            wanted.setdefault(int(t.frames[j]), []).append((i, t.boxes[j]))

    hists = [[] for _ in tracks]
    colors = [[] for _ in tracks]
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
    finally:
        cap.release()

    dim = H_BINS * S_BINS
    hist_arr = np.asarray(
        [np.mean(h, axis=0) if h else np.zeros(dim) for h in hists], dtype=np.float32
    )
    color_arr = np.asarray(
        [np.mean(c, axis=0) if c else np.full(3, 128.0) for c in colors], dtype=np.float64
    )
    return hist_arr, color_arr


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
        int(t): fixed[int(t) % len(fixed)]
        if fixed
        else bgr_to_hex(colors[teams == t].mean(axis=0))  # type: ignore[index]
        for t in np.unique(teams)
    }


# --- merging ----------------------------------------------------------------


def merge_groups(tracks: list[CourtTrack], teams: np.ndarray, profile: Profile) -> list[list[int]]:
    """Group tracklet indices that are the same person: small time gap, small court
    distance, same team (§4.4 step 6). Union-find, earliest-first."""
    cfg = profile.tracking
    parent = list(range(len(tracks)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    spans = [[t.tracklet.t_start, t.tracklet.t_end] for t in tracks]
    order = sorted(range(len(tracks)), key=lambda i: tracks[i].tracklet.t_start)
    for bi, b in enumerate(order):
        for a in order[:bi]:
            ra, rb = find(a), find(b)
            if ra == rb or teams[a] != teams[b]:
                continue
            gap = tracks[b].tracklet.t_start - tracks[a].tracklet.t_end
            if not 0.0 <= gap <= cfg.merge_max_gap_s:
                continue
            dist = float(np.linalg.norm(tracks[b].court_m[0] - tracks[a].court_m[-1]))
            if dist > cfg.merge_max_dist_m:
                continue
            if spans[rb][0] < spans[ra][1]:  # the two merged lives would overlap in time
                continue
            parent[rb] = ra
            spans[ra] = [min(spans[ra][0], spans[rb][0]), max(spans[ra][1], spans[rb][1])]

    groups: dict[int, list[int]] = {}
    for i in range(len(tracks)):
        groups.setdefault(find(i), []).append(i)
    out = [sorted(g, key=lambda i: tracks[i].tracklet.t_start) for g in groups.values()]
    return sorted(out, key=lambda g: tracks[g[0]].tracklet.t_start)


def _concat(tracks: list[CourtTrack], group: list[int]) -> CourtTrack:
    members = [tracks[i] for i in group]
    tl = [m.tracklet for m in members]
    merged = Tracklet(
        track_id=tl[0].track_id,
        frames=np.concatenate([t.frames for t in tl]),
        times=np.concatenate([t.times for t in tl]),
        boxes=np.concatenate([t.boxes for t in tl]),
        confs=np.concatenate([t.confs for t in tl]),
    )
    court = np.concatenate([m.court_m for m in members])
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


def _cap_concurrent(
    merged: list[tuple[list[int], CourtTrack]], max_n: int
) -> list[tuple[list[int], CourtTrack]]:
    """Keep at most `max_n` players alive at any instant, best score first.

    `players.max` is a *concurrency* cap, not a roster cap: the ten best merges over a
    240 s clip need not be contemporaneous, and capping globally left 2-3 selectable
    boxes late in the Kennesaw clip while ten people were on court (samples/real/
    RESULTS.md). Greedy by score; the output can hold more than `max_n` players.
    """
    kept: list[tuple[list[int], CourtTrack]] = []
    spans: list[tuple[float, float]] = []
    for g, c in merged:
        span = (c.tracklet.t_start, c.tracklet.t_end)
        if _fits(span, spans, max_n):
            kept.append((g, c))
            spans.append(span)
    return kept


def identify(
    video: str, tracks: list[CourtTrack], profile: Profile, variant: str | None = None
) -> list[PlayerTrack]:
    """Tracklets → `p1..pN` with team labels and team colours."""
    if not tracks:
        return []
    # Only `jersey_color` needs pixels, and decoding the clip for torso crops is the
    # expensive half of this stage — a net sport skips it entirely.
    hists, colors = (
        sample_appearance(video, tracks) if profile.team_rule == "jersey_color" else (None, None)
    )
    teams = assign_teams(hists, tracks, profile, profile.template(variant))
    groups = merge_groups(tracks, teams, profile)
    colours = team_colors(teams, profile, colors)
    merged = [(g, _concat(tracks, g)) for g in groups]
    # `players.max` caps *merged* players, not raw tracklets (§4.4 step 5 applied after
    # step 6): a player broken into six tracklets should still beat a bystander with one
    # long one. Score is the merged lifetime weighted by time spent on court, and the cap
    # is on how many are alive at once — so ids come out in acceptance (best-first) order.
    merged.sort(key=lambda gc: gc[1].score, reverse=True)
    merged = _cap_concurrent(merged, profile.players.max)
    players: list[PlayerTrack] = []
    for n, (group, track) in enumerate(merged, start=1):
        team = int(np.bincount(teams[group]).argmax())
        players.append(
            PlayerTrack(
                player_id=f"p{n}",
                team=team,
                color_hex=colours[team],
                track=track,
                members=tuple(tracks[i].track_id for i in group),
            )
        )
    return players


def to_models(players: list[PlayerTrack]) -> tuple[list[PlayerModel], list[TeamModel]]:
    teams = {p.team: p.color_hex for p in players}
    return (
        [
            PlayerModel(id=p.player_id, name=None, team=p.team, color_hex=p.color_hex, tagged=False)
            for p in players
        ],
        [TeamModel(id=t, color_hex=c) for t, c in sorted(teams.items())],
    )


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
        )
        for d in raw["players"]
    ]
    return players, {k: v for k, v in raw.items() if k != "players"}
