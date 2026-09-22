from __future__ import annotations

import numpy as np
import pytest

from courtcam.court import CourtTrack
from courtcam.identity import bgr_to_hex, merge_groups, split_teams, torso_rect
from courtcam.profiles import load_profile
from courtcam.track import Tracklet

PROFILE = load_profile("basketball")
# The merge rules are tested against fixed thresholds, not against whatever the shipped
# profile is tuned to this week.
MERGE = PROFILE.model_copy(
    update={
        "tracking": PROFILE.tracking.model_copy(
            update={"merge_max_gap_s": 1.5, "merge_max_dist_m": 2.0}
        )
    }
)


def _track(tid: int, t0: float, t1: float, start_m, end_m, fps: int = 15) -> CourtTrack:
    n = max(2, int((t1 - t0) * fps))
    times = np.linspace(t0, t1, n)
    court = np.column_stack(
        [np.linspace(start_m[0], end_m[0], n), np.linspace(start_m[1], end_m[1], n)]
    )
    boxes = np.column_stack(
        [court[:, 0] * 10, court[:, 1] * 10, np.full(n, 40.0), np.full(n, 120.0)]
    )
    tl = Tracklet(
        track_id=tid,
        frames=(times * fps).astype(int),
        times=times,
        boxes=boxes,
        confs=np.full(n, 0.9),
    )
    return CourtTrack(tl, court, 1.0)


def test_merges_across_a_short_gap_on_the_same_team():
    a = _track(1, 0.0, 4.0, (0.0, 5.0), (2.0, 6.0))
    b = _track(2, 4.8, 9.0, (2.5, 6.4), (5.0, 8.0))  # gap 0.8 s, 0.64 m away
    groups = merge_groups([a, b], np.array([0, 0]), MERGE)
    assert groups == [[0, 1]]


def test_does_not_merge_across_a_long_gap_a_long_distance_or_teams():
    a = _track(1, 0.0, 4.0, (0.0, 5.0), (2.0, 6.0))
    late = _track(2, 8.0, 12.0, (2.2, 6.1), (3.0, 7.0))  # gap 4 s
    far = _track(3, 4.5, 8.0, (12.0, 6.0), (13.0, 7.0))  # 10 m away
    other = _track(4, 4.5, 8.0, (2.2, 6.1), (3.0, 7.0))  # other team
    groups = merge_groups([a, late, far, other], np.array([0, 0, 0, 1]), MERGE)
    assert sorted(groups) == [[0], [1], [2], [3]]


def test_does_not_merge_tracklets_that_overlap_in_time():
    a = _track(1, 0.0, 5.0, (0.0, 5.0), (2.0, 6.0))
    b = _track(2, 2.0, 7.0, (2.1, 6.1), (3.0, 7.0))
    assert sorted(merge_groups([a, b], np.array([0, 0]), MERGE)) == [[0], [1]]


def test_identify_caps_merged_players_at_max_and_prefers_fragmented_ones(tmp_path):
    """A player split into four 4 s tracklets must outrank a bystander with one 6 s
    track — the cap is scored on merged lifetime, not on the longest raw tracklet."""
    from unittest.mock import patch

    from courtcam.identity import identify

    fragments = [
        _track(10 + i, 5.0 * i, 5.0 * i + 4.0, (float(i), 5.0), (float(i) + 0.3, 5.2))
        for i in range(4)
    ]
    loners = [_track(100 + j, 0.0, 6.0, (7.0 + j, 5.0), (7.2 + j, 5.0)) for j in range(10)]
    tracks = fragments + loners
    hists = np.zeros((len(tracks), 48), dtype=np.float32)
    colors = np.full((len(tracks), 3), 128.0)
    profile = MERGE.model_copy(update={"players": MERGE.players.model_copy(update={"max": 4})})
    with patch("courtcam.identity.sample_appearance", return_value=(hists, colors)):
        players = identify("unused.mp4", tracks, profile)

    assert len(players) == 4
    merged = [p for p in players if len(p.members) > 1]
    assert merged and set(merged[0].members) == {10, 11, 12, 13}


def test_split_teams_separates_two_jersey_clusters():
    rng = np.random.default_rng(0)
    dark = np.tile(np.eye(48)[3], (5, 1)) + rng.normal(0, 0.01, (5, 48))
    light = np.tile(np.eye(48)[40], (5, 1)) + rng.normal(0, 0.01, (5, 48))
    labels = split_teams(np.vstack([dark, light]).astype(np.float32))
    assert len(set(labels[:5])) == 1 and len(set(labels[5:])) == 1
    assert labels[0] != labels[5]


def test_torso_rect_sits_in_the_upper_middle_of_the_box():
    x, y, w, h = torso_rect(np.array([100.0, 200.0, 40.0, 120.0]))
    assert (x, y, w, h) == (110, 218, 20, 42)


def test_bgr_to_hex():
    assert bgr_to_hex(np.array([160, 79, 31])) == "#1F4FA0"


def test_net_side_team_rule_fails_loudly():
    """Net sports are not supported yet; the stub must say so, not mislabel teams."""
    from courtcam.identity import assign_teams

    net_sport = PROFILE.model_copy(update={"team_rule": "net_side"})
    with pytest.raises(NotImplementedError, match="net_side"):
        assign_teams(np.zeros((4, 48), dtype=np.float32), net_sport)
