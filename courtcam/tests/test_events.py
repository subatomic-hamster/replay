"""Rally segmentation (`events.detect_rallies`) on synthetic court tracks."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from courtcam.court import CourtTrack
from courtcam.events import detect_events
from courtcam.identity import PlayerTrack
from courtcam.profiles import load_profile
from courtcam.track import Tracklet

RATE = 15.0  # detection stride 2 on a 30 fps clip
RALLIES = [(5.0, 15.0), (24.0, 31.0), (44.0, 56.0)]
DURATION = 64.0


def _player(i: int, rng: np.random.Generator) -> PlayerTrack:
    t = np.arange(0.0, DURATION, 1.0 / RATE)
    home = np.array([-1.5 + 3.0 * (i % 2), 3.0 + 7.0 * (i // 2)])
    # smoothed tracking jitter
    pos = np.tile(home, (len(t), 1)) + rng.normal(0.0, 0.01, (len(t), 2))
    for a, b in RALLIES:  # in play: ~2.5 m/s shuffles, lunges and recoveries
        m = (t >= a) & (t < b)
        phase = rng.uniform(0, 2 * np.pi)
        pos[m, 0] += 1.2 * np.sin(2.1 * t[m] + phase)
        pos[m, 1] += 0.9 * np.sin(1.3 * t[m] + 2 * phase)
    if i == 0:  # between rallies someone strolls over to pick up the shuttle
        m = (t >= 17.0) & (t < 21.0)
        pos[m, 1] += 1.1 * (t[m] - 17.0) * (t[m] < 19.0) + 1.1 * (21.0 - t[m]) * (t[m] >= 19.0)
    boxes = np.column_stack([pos[:, 0], pos[:, 1], np.ones(len(t)), np.ones(len(t))])
    tracklet = Tracklet(i, np.arange(len(t)), t, boxes, np.ones(len(t)))
    return PlayerTrack(f"p{i}", i // 2, "#000000", CourtTrack(tracklet, pos, 1.0), (i,))


def _iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    return inter / (max(a[1], b[1]) - min(a[0], b[0]))


def test_rallies_are_the_bursts_of_movement_not_the_walk_between():
    rng = np.random.default_rng(7)
    players = [_player(i, rng) for i in range(4)]
    for sport in ("badminton", "pickleball"):
        events = detect_events(Path("unused.mp4"), players, load_profile(sport), {})
        found = [e for e in events if e.type == "rally"]
        assert len(found) == len(RALLIES), events
        # no audio: each rally brings exactly its serve and point, no contacts
        assert sorted({e.type for e in events}) == ["point", "rally", "serve"]
        assert len(events) == 3 * len(RALLIES)
        for e, truth in zip(found, RALLIES, strict=True):
            assert _iou((e.t_start, e.t_end), truth) >= 0.6, (e, truth)
            assert e.t_start <= truth[0] + 0.5, "the serve before the burst is inside the clip"


def test_a_hit_just_after_the_motion_ends_extends_the_rally():
    from courtcam.events import Signals, detect_rallies
    from courtcam.schema import Onset

    rng = np.random.default_rng(7)
    players = [_player(i, rng) for i in range(4)]
    profile = load_profile("badminton")
    bare = [e for e in detect_rallies(Path("x"), players, profile, {}) if e.type == "rally"]
    end = bare[0].t_end
    # hits inside the first rally, a last hit 1 s after its motion end (players stop
    # running before the shuttle lands), and a click 5 s later that belongs to nobody
    hits = [6.0, 9.0, 12.0, end + 1.0, end + 5.0]
    sig = Signals(onsets=[Onset(t=t, strength=60.0) for t in hits], has_audio=True)
    found = [e for e in detect_rallies(Path("x"), players, profile, {}, signals=sig)
             if e.type == "rally"]  # fmt: skip
    assert found[0].t_end == round(end + 1.0 + profile.rally.tail_s + 0.5, 3)
    assert found[0].contacts == 4
    assert [(e.t_start, e.t_end) for e in found[1:]] == [(e.t_start, e.t_end) for e in bare[1:]]
    off = profile.model_copy(
        update={"rally": profile.rally.model_copy(update={"audio_extend_end": False})}
    )
    plain = [
        e for e in detect_rallies(Path("x"), players, off, {}, signals=sig) if e.type == "rally"
    ]
    assert plain[0].t_end == end and plain[0].contacts == 3


def test_one_touch_sides_alternate_from_the_majority_side():
    from courtcam.events import Signals, alternate_contacts
    from courtcam.profiles import RallyCfg
    from courtcam.schema import Event

    def ev(kind, t, team=None):
        return Event(id="", type=kind, t_start=t, t_key=t, t_end=t, team=team)

    tpl = load_profile("badminton").template("doubles")
    rally = ev("rally", 1.0)
    rally.t_end = 9.0
    # wrist speed got contact 3 wrong; the other four agree on side 0 hitting first
    hits = [
        ev("contact", t, team) for t, team in ((1.0, 0), (3.0, 1), (5.0, 1), (7.0, 1), (9.0, 0))
    ]
    events = [rally, ev("serve", 1.0, team=1), *hits]
    alternate_contacts(events, [], Signals(), tpl, RallyCfg(one_touch=True))
    assert [c.team for c in hits] == [0, 1, 0, 1, 0]
    # no evidence either way: the serving side hit first
    blind = [ev("contact", t) for t in (1.0, 3.0)]
    events = [rally, ev("serve", 1.0, team=1), *blind]
    alternate_contacts(events, [], Signals(), tpl, RallyCfg(one_touch=True))
    assert [c.team for c in blind] == [1, 0]


def test_still_players_and_no_players_give_no_rallies():
    profile = load_profile("badminton")
    rng = np.random.default_rng(1)
    still = [_player(i, rng) for i in range(4)]
    for p in still:  # undo the rallies: everyone stands and jitters
        home = np.median(p.track.court_m, axis=0)
        p.track.court_m[:] = home + rng.normal(0.0, 0.01, p.track.court_m.shape)
    assert detect_events(Path("unused.mp4"), still, profile, {}) == []
    assert detect_events(Path("unused.mp4"), [], profile, {}) == []
