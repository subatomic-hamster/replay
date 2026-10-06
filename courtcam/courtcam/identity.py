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

from .court import CourtTrack, bystander, track_from_json, track_json
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

    dim = H_BINS * S_BINS
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


# --- merging ----------------------------------------------------------------


def merge_groups(
    tracks: list[CourtTrack],
    teams: np.ndarray,
    profile: Profile,
    body: np.ndarray | None = None,
) -> list[list[int]]:
    """Group tracklet indices that are the same person: small time gap, small court
    distance, same team (§4.4 step 6).

    Links are taken cheapest (closest) first, and each tracklet gets at most one
    predecessor and one successor, so a group is a chain through time. Earliest-first
    used to hand a fragment to whichever old track *started* first even when another
    one had ended right where it appeared.

    A link may overlap by up to `merge_overlap_s`: ByteTrack gives a person a new id a
    frame or so before it drops the old one, and on the badminton clip that one-frame
    overlap alone kept a 57 s tracklet out of every group (samples/real/RESULTS.md).

    With `body` descriptors (`body_hist`) and `tracking.appearance_weight` > 0, a link's
    cost is its court distance in units of `merge_max_dist_m` plus the weight times the
    appearance distance, and links above `appearance_max` are refused: on synthetic
    basketball 61 % of the distance-only links joined two different people.
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
            if use_app:
                d_app = app_distance(body[a], body[b])  # type: ignore[index]
                if d_app > cfg.appearance_max:
                    continue
                dist = dist / cfg.merge_max_dist_m + cfg.appearance_weight * d_app
            links.append((dist, a, int(b)))

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


def _concat(tracks: list[CourtTrack], group: list[int]) -> CourtTrack:
    """One track from a time-ordered group; where two members overlap (a handover),
    the later member's samples before the earlier one's end are dropped."""
    members = [tracks[i] for i in group]
    keep, last = [], -np.inf
    for m in members:
        k = m.tracklet.times > last
        keep.append(k)
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


def _stitch(
    tracks: list[CourtTrack], groups: list[list[int]], teams: np.ndarray, profile: Profile
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
    """
    cfg = profile.tracking
    per_team = -(-profile.players.max // max(1, len(np.unique(teams))))
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
                if gap > 0 and not _fits((ends[ln[-1]], s), alive, profile.players.max):
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
    video: str, tracks: list[CourtTrack], profile: Profile, variant: str | None = None
) -> list[PlayerTrack]:
    """Tracklets → `p1..pN` with team labels and team colours."""
    if not tracks:
        return []
    # Only `jersey_color` needs pixels, and decoding the clip for torso crops is the
    # expensive half of this stage — a net sport skips it entirely.
    need = profile.team_rule == "jersey_color" or profile.tracking.appearance_weight > 0
    hists, colors, body = sample_appearance(video, tracks) if need else (None, None, None)
    teams = assign_teams(hists, tracks, profile, profile.template(variant))
    groups = merge_groups(tracks, teams, profile, body)
    colours = team_colors(teams, profile, colors)
    polygon = profile.template(variant).polygon
    merged = [
        (g, c) for g in groups if not bystander(c := _concat(tracks, g), polygon, profile.tracking)
    ]
    # `players.max` caps *merged* players, not raw tracklets (§4.4 step 5 applied after
    # step 6): a player broken into six tracklets should still beat a bystander with one
    # long one. Score is the merged lifetime weighted by time spent on court, and the cap
    # is on how many are alive at once. Ids follow the score of the stitched players.
    merged.sort(key=lambda gc: gc[1].score, reverse=True)
    merged = _cap_concurrent(merged, profile.players.max, profile.tracking.merge_overlap_s)
    groups = _stitch(tracks, [g for g, _ in merged], teams, profile)
    merged = sorted(
        ((g, _concat(tracks, g)) for g in groups), key=lambda gc: gc[1].score, reverse=True
    )
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
