"""Lost man (`events.detect_lost_man`), the shooter from the ball's own path
(`events._shooter`), the ball's path into the rim (`ball._path_back`, `ball.arrivals`) and
the score by the user's team corrections (`plays.score_timeline`). Synthetic tracks and
ball samples (labelled synthetic: no footage)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from courtcam import ball
from courtcam.court import CourtTrack
from courtcam.events import Signals, _shooter, detect_lost_man
from courtcam.identity import PlayerTrack
from courtcam.plays import score_timeline
from courtcam.profiles import BallCfg, load_profile
from courtcam.schema import Event
from courtcam.track import Tracklet

PROF = load_profile("basketball")
CALIB = {"variant": "half"}
RATE = 10.0
T = np.arange(0.0, 20.0, 1.0 / RATE)


def _player(pid: str, team: int, path) -> PlayerTrack:
    """`path(t) -> (x, y)` court metres, sampled at RATE for 20 s (synthetic)."""
    pos = np.array([path(t) for t in T], dtype=float)
    boxes = np.column_stack([pos, np.ones((len(T), 2))])
    tracklet = Tracklet(0, np.arange(len(T)), T, boxes, np.ones(len(T)))
    return PlayerTrack(pid, team, "#000000", CourtTrack(tracklet, pos, 1.0), (0,))


def _walk(points):
    """Piecewise-linear court path through (t, x, y) points."""
    ts, xs, ys = (np.asarray(c, dtype=float) for c in zip(*points, strict=True))
    return lambda t: (np.interp(t, ts, xs), np.interp(t, ts, ys))


# The man on the left wing, the defender 1.5 m inside him; at 8 s the man cuts to the rim
# (0, 1.575) and the defender stays. The other pair stands together on the right.
MAN = _walk([(0, -4.5, 9.0), (8, -4.5, 9.0), (10.5, -1.0, 1.5), (20, -1.0, 1.5)])
DEFENDER = _walk([(0, -3.6, 7.8), (20, -3.6, 7.8)])
# both sides jog in place a little: live play, not a stoppage
JOG = lambda f: lambda t: (f(t)[0] + 0.4 * np.sin(3 * t), f(t)[1] + 0.4 * np.cos(3 * t))  # noqa: E731


def _game(defender=DEFENDER, team_of_defender=0):
    return [
        _player("man", 1, JOG(MAN)),
        _player("def", team_of_defender, JOG(defender)),
        _player("ball", 1, JOG(_walk([(0, 3.0, 6.0), (20, 3.0, 6.0)]))),
        _player("help", 0, JOG(_walk([(0, 2.6, 5.2), (20, 2.6, 5.2)]))),
    ]


def test_a_defender_left_behind_by_a_cut_lost_his_man():
    (e,) = detect_lost_man(Path("x.mp4"), _game(), PROF, CALIB)
    assert (e.type, e.player_id, e.opponent_id, e.team) == ("lost_man", "def", "man", 0)
    assert 8.0 <= e.t_start <= e.t_key <= e.t_end and e.max_sep_m > 6.0


def test_helping_teammates_and_a_basket_reset_are_not_lapses():
    # the defender goes to help on the other attacker: not a lapse
    helps = _walk([(0, -3.6, 7.8), (8, -3.6, 7.8), (9, 2.4, 6.0), (20, 2.4, 6.0)])
    assert detect_lost_man(Path("x.mp4"), _game(helps), PROF, CALIB) == []
    # the "defender" is the man's teammate: no matchup
    assert detect_lost_man(Path("x.mp4"), _game(team_of_defender=1), PROF, CALIB) == []
    # a made basket just before: the ball is being taken out
    made = Event(id="", type="shot", t_start=5, t_key=7.9, t_end=9, made=True, team=1)
    assert detect_lost_man(Path("x.mp4"), _game(), PROF, CALIB, events=[made]) == []


def test_the_shooter_is_the_hand_on_the_ball_not_the_nearest_defender():
    """Put-back: both under the rim with their arms up; the ball's path starts in the
    shooter's hands, the defender (nearer the rim, later arms-up) is a step behind."""
    shooter = _player("sh", 1, _walk([(0, 0.0, 3.0), (20, 0.0, 3.0)]))
    defender = _player("df", 0, _walk([(0, 0.4, 2.2), (20, 0.4, 2.2)]))
    hoop_px, rim_px = (1000.0, 300.0), 40.0
    sig = Signals(size=(1, 1))
    kp = np.zeros((1, 17, 3))
    kp[0, :, 2] = 1.0
    for pid, wrist in (
        ("sh", (1000 + 0.3 * 40, 300 + 2.6 * 40)),
        ("df", (1000 + 2.4 * 40, 300 + 2.0 * 40)),
    ):
        k = kp.copy()
        k[0, [9, 10], :2] = wrist
        sig.poses[pid] = (np.array([10.0]), k)
    rim = np.array([0.0, 1.575])
    rels = [(9.9, defender)]  # the contest is the only arms-up the poses saw
    who, _ = _shooter(10.3, rim, [shooter, defender], rels, PROF.shot,
                      ((10.0, 0.4, 2.7), hoop_px, rim_px), sig)  # fmt: skip
    assert who.player_id == "sh"
    # no ball path: the old rule (latest release in range) is still the fallback
    who, _ = _shooter(10.3, rim, [shooter, defender], rels, PROF.shot)
    assert who.player_id == "df"


def _samples(points, t0, dt=1 / 30):
    return [[round(t0 + i * dt, 3), u, v, 0.3] for i, (u, v) in enumerate(points)]


def _doc(samples):
    return {"hoops": [{"samples": samples, "rim_m": [0.0, 1.575]}]}


CFG = BallCfg(enabled=True)
DOWN = [(1.5 - 0.15 * i, -3.0 + 0.3 * i) for i in range(10)]  # into the rim from above
THROUGH = [(0.0, -0.1 + 0.25 * i) for i in range(12)]  # down through it and the net


def test_a_head_on_the_walkway_behind_the_hoop_is_not_the_ball():
    walker = _samples([(-4.0 + 0.15 * i, -0.4) for i in range(50)], 10.0)  # 1.6 s at rim height
    assert ball.arrivals(_doc(walker), CFG) == []


def test_a_bounce_off_the_board_is_the_same_shot_and_a_quick_return_was_no_make():
    # off the rim, up out of the rim's box for 0.9 s and back down to it, seen all the way
    up = [(0.3, -0.6 - 0.25 * i) for i in range(20)]
    arr = ball.arrivals(_doc(_samples(DOWN + up + up[::-1], 10.0)), CFG)
    assert len(arr) == 1 and arr[0].launch[0] == 10.0
    # a make, then the ball at that rim again 2 s later: it was a rebound
    make = _samples(DOWN + THROUGH, 20.0)
    again = _samples(DOWN, 20.0 + 22 / 30 + 2.0)
    arr = ball.arrivals(_doc(make + again), CFG)
    assert [a.made for a in arr] == [False, False]
    assert ball.arrivals(_doc(make), CFG)[0].made is True


def test_the_score_follows_the_users_team_corrections():
    shot = Event(id="e1", type="shot", t_start=0, t_key=1, t_end=2, made=True, points=2,
                 team=0, player_id="p3")  # fmt: skip
    assert score_timeline([shot])[-1].scores == (2, 0)
    assert score_timeline([shot], teams={"p3": 1})[-1].scores == (0, 2)
    assert score_timeline([shot], teams={"p9": 1})[-1].scores == (2, 0)
