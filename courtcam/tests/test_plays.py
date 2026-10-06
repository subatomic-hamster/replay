"""Play grammars (`courtcam.plays`), triggers and their resolution (`courtcam.triggers`)."""

from __future__ import annotations

import numpy as np

from courtcam.events import Signals, label_makes, x_pose
from courtcam.plays import build_plays, score_timeline
from courtcam.profiles import TriggerCfg, load_profile
from courtcam.schema import Event, Play, ScoreEntry, Trigger
from courtcam.triggers import (
    apply,
    detect_gestures,
    detect_voice,
    number,
    parse_command,
    resolve,
    subject_from_transcript,
    tokens,
)

CFG = TriggerCfg()


def ev(eid, kind, t, team=None, pid=None, **kw) -> Event:
    return Event(id=eid, type=kind, t_start=t, t_key=t, t_end=t, team=team, player_id=pid,
                 confidence=0.8, **kw)  # fmt: skip


def test_basketball_possessions_become_plays():
    events = [
        ev("e1", "possession_change", 1.0, 0, "a", cause="inbound"),
        ev("e2", "shot", 5.0, 0, "b"),
        ev("e3", "possession_change", 7.0, 1, "c", cause="inbound"),
        # the turnover ends team 1's possession, the steal at the same instant starts ours
        ev("e4", "turnover", 12.0, 1),
        ev("e5", "possession_change", 12.0, 0, "d", cause="steal"),
        ev("e6", "shot", 14.0, 1, "c"),  # the other team's shot does not end our play
        ev("e7", "shot", 16.0, 0, "d"),
    ]
    plays = build_plays(events, load_profile("basketball").plays, "basketball")
    assert [(p.t_start, p.t_end, p.team) for p in plays] == [
        (1.0, 5.0, 0),
        (7.0, 12.0, 1),
        (12.0, 16.0, 0),
    ]
    assert [p.id for p in plays] == ["pl_0001", "pl_0002", "pl_0003"]
    assert [(x.player_id, x.role) for x in plays[0].participants] == [
        ("a", "inbounder"),
        ("b", "shooter"),
    ]
    assert ("d", "stealer") in [(x.player_id, x.role) for x in plays[2].participants]
    assert plays[1].event_ids == ["e3", "e4"]


def test_rally_and_attack_grammars():
    events = [
        ev("s", "serve", 1.0, 0, "p1"),
        ev("c1", "contact", 1.0, 0, "p1"),
        ev("c2", "contact", 2.0, 1, "p5"),
        ev("c3", "contact", 3.0, 1, "p6"),
        ev("c4", "contact", 4.0, 1, "p7"),  # pass -> set -> attack on side 1
        ev("c5", "contact", 5.0, 0, "p2"),
        ev("pt", "point", 6.0),
    ]
    plays = build_plays(events, load_profile("volleyball").plays, "volleyball")
    rally = [p for p in plays if p.grammar == "rally"]
    attack = [p for p in plays if p.grammar == "attack"]
    assert [(p.t_start, p.t_end) for p in rally] == [(1.0, 6.0)]
    assert len(attack) == 1 and attack[0].team == 1
    assert [(x.player_id, x.role) for x in attack[0].participants] == [
        ("p5", "passer"),
        ("p6", "setter"),
        ("p7", "attacker"),
    ]


def test_long_rally_gets_a_last_n_window():
    events = [ev("s", "serve", 0.0), *[ev(f"c{i}", "contact", float(i)) for i in range(8)],
              ev("pt", "point", 9.0)]  # fmt: skip
    (play,) = build_plays(events, load_profile("badminton").plays, "badminton")
    assert play.last_n == {"n": 3, "t_start": 4.5}


def test_score_counts_makes_and_points_and_honours_user_corrections():
    events = [
        ev("e1", "shot", 2.0, 0, made=True, points=3),
        ev("e2", "shot", 4.0, 1, made=False, points=2),
        ev("e3", "shot", 6.0, 1, made=True, points=2),
        ev("e4", "shot", 12.0, 0, made=True, points=2),
        ev("e5", "point", 13.0, winner_side=1),
    ]
    user = [ScoreEntry(t=10.0, scores=(5, 5), source="user")]
    score = score_timeline(events, user)
    assert [(s.t, s.scores, s.source) for s in score] == [
        (2.0, (3, 0), "auto"),
        (6.0, (3, 2), "auto"),
        (10.0, (5, 5), "user"),
        (12.0, (7, 5), "auto"),
        (13.0, (7, 6), "auto"),
    ]


def test_label_makes_from_what_follows():
    shots = [ev("s1", "shot", 1.0, 0), ev("s2", "shot", 10.0, 0), ev("s3", "shot", 12.0, 0)]
    changes = [
        ev("c1", "possession_change", 3.0, 1, cause="inbound"),
        ev("c2", "possession_change", 20.0, 1, cause="defensive_rebound"),
    ]
    label_makes(shots, changes, 6.0)
    assert [s.made for s in shots] == [True, False, None]  # s2: the same team shot again


def test_pose_crop_and_pick():
    from courtcam.pose import crop_rect, pick

    assert crop_rect((100, 50, 20, 40), (640, 360), 0.25) == (95, 40, 125, 100)
    assert crop_rect((0, 0, 20, 40), (640, 360), 0.25) == (0, 0, 25, 50)  # clamped
    boxes = np.array([[300.0, 50, 20, 40], [101, 52, 20, 40]])  # a neighbour, then us
    kps = np.ones((2, 17, 3))
    kps[1, 3, 2] = 0.0  # an undetected keypoint
    kp, conf = pick((100, 50, 20, 40), boxes, kps, [0.9, 0.8], 0.3)
    assert conf == 0.8 and kp[3].tolist() == [0.0, 0.0, 0.0]
    assert pick((500, 300, 20, 40), boxes, kps, [0.9, 0.8], 0.3) is None


# --- triggers ---------------------------------------------------------------------


def _pose(crossed: bool) -> np.ndarray:
    """One COCO pose in px, facing the camera (the person's left is image right)."""
    kp = np.zeros((17, 3))
    kp[:, 2] = 0.9
    kp[0, :2] = (100, 50)  # nose
    kp[5, :2], kp[6, :2] = (120, 100), (80, 100)  # shoulders
    kp[11, :2], kp[12, :2] = (115, 200), (85, 200)  # hips
    if crossed:  # elbows out, wrists crossed above the head
        kp[7, :2], kp[8, :2] = (130, 60), (70, 60)
        kp[9, :2], kp[10, :2] = (85, 20), (115, 20)
    else:  # both arms straight up, not crossed
        kp[7, :2], kp[8, :2] = (130, 60), (70, 60)
        kp[9, :2], kp[10, :2] = (135, 20), (65, 20)
    return kp


def test_x_pose():
    kp = np.stack([_pose(True), _pose(False)])
    assert x_pose(kp).tolist() == [True, False]
    low = _pose(True)
    low[[9, 10], 1] = 150  # wrists below the shoulders
    assert not x_pose(low[None])[0]


def test_gesture_must_be_held():
    ts = np.round(np.arange(0.0, 6.0, 0.1), 3)
    kp = np.stack([_pose(1.0 <= t <= 2.0 or 4.0 <= t <= 4.4) for t in ts])
    found = detect_gestures(Signals(poses={"p3": (ts, kp)}), CFG)
    assert [(g.t_start, g.t, g.by_player_id) for g in found] == [(1.0, 2.0, "p3")]


def test_parse_command_is_fuzzy_and_needs_both_words():
    roster = {"Jordan Lee": "p3", "Sam": "p7"}
    assert parse_command(tokens("Replay, clip that."), roster, CFG)[2] is None
    assert parse_command(tokens("Re play, clip Jordan!"), roster, CFG)[2] == "p3"
    assert parse_command(tokens("okay replay clips sam"), roster, CFG)[2] == "p7"
    assert parse_command(tokens("clip that"), roster, CFG) is None
    assert parse_command(tokens("replay that one"), roster, CFG) is None
    assert subject_from_transcript("Replay Clip Jordan.", roster, CFG) == "p3"
    assert subject_from_transcript("Replay Clip Jordan.", {}, CFG) is None


def test_detect_voice_keeps_only_commands():
    texts = iter(["nice shot", " Replay, clip Sam."])

    def asr(clips, sr):
        return [next(texts) for _ in clips]

    samples = np.zeros(16000 * 10, np.float32)
    found = detect_voice(samples, 16000, [(1.0, 2.0), (5.0, 6.5)], asr, {"Sam": "p7"}, CFG)
    assert [(v.t, v.t_end, v.subject_player_id, v.transcript) for v in found] == [
        (5.0, 6.5, "p7", "Replay, clip Sam.")
    ]


def test_resolution_picks_the_play_that_just_ended():
    plays = [
        Play(id="pl_0001", sport="x", grammar="g", t_start=0.0, t_end=10.0),
        Play(id="pl_0002", sport="x", grammar="g", t_start=12.0, t_end=20.0),
    ]
    assert resolve(13.0, plays, CFG).id == "pl_0001"
    assert resolve(20.3, plays, CFG).id == "pl_0002"  # pressed a moment before the end
    assert resolve(17.5, plays, CFG).id == "pl_0001"  # mid-play: the previous one
    assert resolve(19.0, plays, CFG) is None  # mid-play, the previous one too long ago
    assert resolve(35.0, plays, CFG) is None  # longer than max_lag_s after anything

    trig = number([
        Trigger(id="", type="gesture", t=13.0, by_player_id="p1"),
        Trigger(id="", type="tap", t=22.0, source="user"),
        Trigger(id="", type="voice", t=40.0, subject_player_id="p2"),
    ])  # fmt: skip
    clips = apply(trig, plays, CFG, duration_s=20.5)
    assert [(c.id, c.play_id, c.t_start, c.t_end, c.source) for c in clips] == [
        ("c_0001", "pl_0001", 0.0, 11.0, "auto"),
        ("c_0002", "pl_0002", 11.0, 20.5, "user"),
    ]
    assert clips[0].attribution.owner_player_id == "p1"
    assert plays[0].trigger.id == "tr_0001" and plays[1].trigger.type == "tap"
    assert trig[2].play_id is None and trig[2].clip_id is None
