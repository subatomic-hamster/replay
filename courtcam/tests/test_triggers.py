"""The front-on X gesture (triggers.front_samples / faces_camera) on hand-built COCO poses
in px: torso 100 px (shoulders y 100, hips y 200), facing the camera unless turned."""

from __future__ import annotations

import numpy as np

from courtcam.events import Signals
from courtcam.profiles import TriggerCfg
from courtcam.triggers import detect_gestures

CFG = TriggerCfg()
TS = np.round(np.arange(0.0, 6.0, 0.1), 3)


def pose(wrists, elbows, facing: bool = True) -> np.ndarray:
    kp = np.zeros((17, 3))
    kp[:, 2] = 0.9
    kp[0, :2], kp[1, :2], kp[2, :2] = (100, 50), (105, 45), (95, 45)  # nose, eyes
    kp[5, :2], kp[6, :2] = (120, 100), (80, 100)  # shoulders
    kp[11, :2], kp[12, :2] = (115, 200), (85, 200)  # hips
    kp[7, :2], kp[8, :2] = elbows
    kp[9, :2], kp[10, :2] = wrists
    if not facing:
        kp[:5, 2] = 0.1  # from behind: no face
    return kp


DOWN = pose(((130, 190), (70, 190)), ((130, 150), (70, 150)))
# crossed in front of the chin: wrists touching at shoulder height, elbows lifted and wide
LOW = pose(((95, 95), (105, 95)), ((140, 125), (60, 125)))
# hands together at the mouth, elbows down by the sides (a clap, a hand to the mouth)
MOUTH = pose(((95, 95), (105, 95)), ((115, 145), (85, 145)))
# arms crossed at the chest, elbows down; then the X overhead as a pose model labels it
# (wrists by side: touching, not crossed)
CHEST = pose(((95, 140), (105, 140)), ((125, 170), (75, 170)))
HIGH = pose(((105, 20), (95, 20)), ((130, 60), (70, 60)))
# a throw's follow-through: wrists pass each other at different heights
THROW = pose(((95, 75), (105, 115)), ((140, 125), (60, 125)))


def found(timeline) -> list[tuple[float, float]]:
    kp = np.stack([next((p for a, b, p in timeline if a <= t <= b), DOWN) for t in TS])
    return [(g.t_start, g.t) for g in detect_gestures(Signals(poses={"p1": (TS, kp)}), CFG)]


def test_x_in_front_of_the_chin_counts_a_hand_to_the_mouth_does_not():
    assert found([(1.0, 1.5, LOW)]) == [(1.0, 1.5)]
    assert found([(1.0, 2.5, MOUTH)]) == []
    # 3 of the 5 samples in a 0.4 s window carry the vote (the owner's game: 0:20 X),
    # 2 do not
    assert found([(1.0, 1.2, LOW)]) == [(1.0, 1.2)]
    assert found([(1.0, 1.1, LOW)]) == []
    assert found([(1.0, 1.5, THROW)]) == []


def test_x_crossed_at_the_chest_then_raised():
    assert found([(1.0, 1.5, CHEST), (1.6, 2.1, HIGH)]) == [(1.0, 2.1)]
    # a shot or a catch: the ball overhead 0.7 s after a one-sample gather, or arms
    # crossed at the chest for a while with no overhead part
    assert found([(0.9, 0.9, CHEST), (1.0, 1.6, HIGH)]) == []
    assert found([(1.0, 2.5, CHEST)]) == []


def test_only_a_player_facing_the_camera_makes_the_x():
    held = [(1.0, 2.5, HIGH)]
    assert found(held) == [(1.0, 2.5)]
    turned = pose(((105, 20), (95, 20)), ((130, 60), (70, 60)), facing=False)
    assert found([(1.0, 2.5, turned)]) == []  # hands clasped on the head, from behind
