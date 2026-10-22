"""D-90: the ball at the rim (`courtcam.ball`), play logs (`courtcam.playlog`), the
event evaluation (`courtcam.eventeval`) and games to N (`plays.score_timeline`)."""

from __future__ import annotations

import numpy as np
import pytest

from courtcam import ball, eventeval, playlog
from courtcam.events import _team_by_hoop
from courtcam.plays import score_timeline
from courtcam.profiles import BallCfg
from courtcam.schema import Event

CFG = BallCfg(enabled=True)


def _path(points, t0=10.0, dt=1 / 30):
    """(t, u, v, area) samples along a polyline through `points` (u, v), one per frame."""
    pts = np.asarray(points, dtype=float)
    seg = np.linspace(0, len(pts) - 1, int(len(pts) * 6))
    u = np.interp(seg, np.arange(len(pts)), pts[:, 0])
    v = np.interp(seg, np.arange(len(pts)), pts[:, 1])
    return [
        [round(t0 + i * dt, 3), float(a), float(b), 0.25]
        for i, (a, b) in enumerate(zip(u, v, strict=True))
    ]


SWISH = [(2.5, -3.0), (1.2, -1.5), (0.3, -0.4), (0.0, 0.2), (0.0, 0.9), (0.1, 1.6), (0.1, 2.4)]
# hits the front of the rim and bounces up and out to the side
RIM_OUT = [
    (2.5, -3.0),
    (1.2, -1.5),
    (0.6, -0.4),
    (0.8, -1.0),
    (1.4, -1.6),
    (2.0, -1.4),
    (2.6, -0.6),
]
# off the side of the rim and down outside it
OFF_SIDE = [(2.5, -3.0), (1.4, -1.2), (0.9, -0.2), (1.1, 0.6), (1.4, 1.5), (1.6, 2.4)]
# D-92: down at the rim's edge: rolled in, or off the near side? Unknown, not a miss
EDGE = [(2.5, -3.0), (1.4, -1.4), (0.8, -0.7), (0.75, -0.1), (0.7, 0.7), (0.6, 1.5), (0.5, 2.4)]


@pytest.mark.parametrize(
    "path,made", [(SWISH, True), (RIM_OUT, False), (OFF_SIDE, False), (EDGE, None)]
)
def test_made_is_the_ball_dropping_through_the_rim(path, made):
    assert ball._made(np.asarray(_path(path)), CFG) is made


def test_a_body_under_the_rim_is_not_a_visit():
    """D-92: four or more blobs at the rim in a third of the visit's frames."""
    shot = _path(SWISH, t0=10.0)
    body = [[s[0], du, dv, 0.3] for s in shot[::3] for du, dv in ((-1, 0), (1, 0), (0, 1))]
    assert len(ball.arrivals(_doc(shot), CFG)) == 1
    assert ball.arrivals(_doc(shot + body), CFG) == []


def _doc(*hoop_samples):
    return {"hoops": [{"samples": s, "rim_m": [0.0, 1.575]} for s in hoop_samples]}


def test_arrivals_one_per_visit_and_a_pass_across_is_not_a_shot():
    shot = _path(SWISH, t0=10.0)
    second = _path(RIM_OUT, t0=20.0)
    # a pass at rim height: crosses the box sideways in 5 frames, never comes down into it
    # (a slower one, 6+ frames in the box, reads as a ball rolling on the rim: a shot)
    across = [[30.0 + i / 30, -2.4 + i * 0.8, -0.5, 0.25] for i in range(7)]
    arr = ball.arrivals(_doc(shot + second + across), CFG)
    assert [(round(a.t), a.made) for a in arr] == [(10, True), (20, False)]


def test_the_tapped_hoop_is_where_the_ball_is_watched():
    """D-93: `rim_top` from the calibration page wins over the camera's projection, and a
    fit with no camera still sizes the hoop from the floor homography."""
    from courtcam.profiles import load_profile

    prof = load_profile("basketball")
    tpl = prof.template("half")
    # a top-down view, 50 px per metre: no perspective, so no camera can be fitted
    clicks = {n: [400 + 50 * x, 900 - 50 * y] for n, (x, y) in tpl.landmarks.items()
              if n.startswith("corner")}  # fmt: skip
    calib = {"variant": "half", "image_size": [1920, 1080], "landmarks_px": clicks}
    assert ball.hoops(calib, prof) == []
    calib["landmarks_px"] = {**clicks, "rim_top": [431.0, 260.0]}
    (h,) = ball.hoops(calib, prof)
    assert h.px == (431.0, 260.0) and h.rim_px == pytest.approx(50 * 0.45, rel=0.01)


def test_arrivals_two_rims_at_once_keep_the_better_seen():
    a = _path(SWISH, t0=10.0)
    flicker = [[10.1 + i / 30, 0.1, 0.0, 0.25] for i in range(2)]  # two frames, no descent
    arr = ball.arrivals(_doc(a, flicker), CFG)
    assert [x.hoop for x in arr] == [0]


def _shot(t, team, made=True, points=2):
    return Event(id=f"e{int(t)}", type="shot", t_start=t, t_key=t, t_end=t, team=team,
                 made=made, points=points, confidence=0.8)  # fmt: skip


def test_team_by_hoop_follows_the_majority_at_each_basket():
    shots = [_shot(1, 0), _shot(2, 0), _shot(3, 1), _shot(4, 1), _shot(5, 1), _shot(6, 0)]
    hoops = [0, 0, 1, 1, 0, 1]  # shots 5 and 6: shooter picked from the wrong team
    _team_by_hoop(shots, hoops, window_s=600.0)
    assert [s.team for s in shots] == [0, 0, 1, 1, 0, 1]


def test_score_to_n_restarts_after_a_win():
    events = [_shot(t, t % 2, points=1) for t in range(1, 6)]  # 1,0,1,0,1 alternate
    events += [_shot(10 + t, 0, points=2) for t in range(3)]
    score = score_timeline(events, to=3)
    # 2-3 wins game 1; 4-0 wins game 2; the next basket opens game 3
    assert [s.scores for s in score][-4:] == [(2, 3), (2, 0), (4, 0), (2, 0)]


CSV = """t,team,player,type,result,points,note
# comment lines are skipped
0:12.5,red,Sam,shot,make,2,pull-up from the elbow
20,blue,Alex,rebound,,,
1:02,,,free throw,miss,,
"""


def test_playlog_csv_and_json_parse_the_same():
    log = playlog.parse(CSV)
    assert [(e.t, e.type, e.made, e.points) for e in log.entries] == [
        (12.5, "shot", True, 2), (20.0, "rebound", None, None), (62.0, "free_throw", False, 1)
    ]  # fmt: skip
    assert log.use == "notes" and log.label == "Your notes"
    again = playlog.parse(log.model_dump_json(by_alias=True))
    assert again.entries == log.entries
    with pytest.raises(ValueError, match="line 2"):
        playlog.parse("t,type\nsoon,shot\n")
    with pytest.raises(ValueError, match="unknown type"):
        playlog.parse("t,type\n3,dunkk\n")


def test_eval_matches_shots_and_scores_make_miss():
    truth = playlog.parse(
        '{"use": "evaluation", "entries": ['
        '{"t": 10, "t_rim": 11, "type": "shot", "made": true, "team": "red", "points": 2},'
        '{"t": 30, "t_rim": 31, "type": "shot", "made": false, "team": "blue"},'
        '{"t": 50, "t_rim": 51, "type": "shot", "made": true, "team": "blue", "points": 3}]}',
        use="evaluation",
    )
    pred = [
        {"type": "shot", "t_key": 11.2, "made": True, "team": 0, "points": 2},
        {"type": "shot", "t_key": 31.1, "made": True, "team": 1, "points": 2},
        {"type": "shot", "t_key": 70.0, "made": False, "team": 1},
    ]
    r = eventeval.evaluate(pred, truth)
    assert (r["shots"]["tp"], r["shots"]["fp"], r["shots"]["fn"]) == (2, 1, 1)
    assert r["make_miss"]["accuracy"] == 0.5
