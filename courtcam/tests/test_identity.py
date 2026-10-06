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


def test_appearance_and_running_reach_gate_merges():
    """Two candidates continue `a`: the nearer one looks like someone else. With
    appearance on, the look-alike wins; with running reach, a 1.8 m jump in 0.1 s is
    refused even though it is inside merge_max_dist_m."""
    from courtcam.identity import app_distance, body_hist

    red = np.zeros((40, 20, 3), np.uint8)
    red[:20] = (0, 0, 210)  # BGR: red shirt, dark shorts
    blue = np.full((40, 20, 3), 230, np.uint8)
    blue[:20] = (200, 0, 0)  # blue shirt, white shorts
    noisy = red.copy()
    noisy[:20] = (0, 0, 225)  # the same red under other light
    noisy[:3] = (90, 120, 160)  # and a few rows of someone's head
    assert app_distance(body_hist(red), body_hist(noisy)) < 0.3
    assert app_distance(body_hist(red), body_hist(blue)) > 0.7
    a = _track(1, 0.0, 4.0, (0.0, 5.0), (2.0, 6.0))
    near_other = _track(2, 4.5, 8.0, (2.3, 6.0), (3.0, 7.0))  # 0.3 m, looks different
    far_same = _track(3, 4.5, 8.0, (3.4, 6.0), (4.0, 7.0))  # 1.4 m, looks the same
    body = np.stack([body_hist(red), body_hist(blue), body_hist(noisy)])
    teams = np.zeros(3, int)
    assert merge_groups([a, near_other, far_same], teams, MERGE)[0] == [0, 1]
    look = {"appearance_weight": 2.0, "appearance_max": 0.6}
    app = MERGE.model_copy(update={"tracking": MERGE.tracking.model_copy(update=look)})
    assert sorted(merge_groups([a, near_other, far_same], teams, app, body)) == [[0, 2], [1]]
    jump = _track(4, 4.1, 8.0, (3.8, 6.0), (4.0, 7.0))  # 1.8 m in 0.1 s
    reach = MERGE.model_copy(
        update={"tracking": MERGE.tracking.model_copy(update={"merge_reach_m": 0.5})}
    )
    assert merge_groups([a, jump], np.zeros(2, int), MERGE) == [[0, 1]]
    assert sorted(merge_groups([a, jump], np.zeros(2, int), reach)) == [[0], [1]]


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
    loners = [
        _track(100 + j, 0.0, 6.0, (-6.0 + 1.3 * j, 9.0), (-5.8 + 1.3 * j, 9.0)) for j in range(10)
    ]
    tracks = fragments + loners
    hists = np.zeros((len(tracks), 48), dtype=np.float32)
    colors = np.full((len(tracks), 3), 128.0)
    profile = MERGE.model_copy(update={"players": MERGE.players.model_copy(update={"max": 4})})
    with patch("courtcam.identity.sample_appearance", return_value=(hists, colors, None)):
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


def _at(tid: int, times: np.ndarray, ys: np.ndarray) -> CourtTrack:
    """A tracklet parked at x=0 whose court y follows `ys` — the only input net_side
    looks at."""
    court = np.column_stack([np.zeros(len(times)), ys])
    boxes = np.column_stack([court, np.full(len(times), 40.0), np.full(len(times), 120.0)])
    tl = Tracklet(
        track_id=tid,
        frames=(times * 15).astype(int),
        times=times,
        boxes=boxes,
        confs=np.full(len(times), 0.9),
    )
    return CourtTrack(tl, court, 1.0)


def test_net_side_splits_by_which_half_of_the_court_they_stand_in():
    from courtcam.identity import assign_teams, net_line_y

    profile = load_profile("pickleball")
    template = profile.template()
    net = net_line_y(template)
    assert net == pytest.approx(6.705)

    t = np.linspace(0.0, 20.0, 60)
    near = _at(1, t, np.full(60, 2.0))
    far = _at(2, t, np.full(60, 11.0))
    straddling = _at(3, t, np.linspace(net - 0.3, net + 0.9, 60))  # median just past it
    teams = assign_teams(None, [near, far, straddling], profile, template)
    assert teams.tolist() == [0, 1, 1]


def test_net_side_majority_votes_over_fixed_windows():
    """Ends change between games; the coarse window vote gives the side they played
    most. Two windows near, one far -> near."""
    from courtcam.identity import net_side

    t = np.linspace(0.0, 179.0, 360)
    ys = np.where(t < 120.0, 2.0, 11.0)
    assert net_side([_at(1, t, ys)], 6.7, window_s=60.0).tolist() == [0]
    assert net_side([_at(1, t, 13.4 - ys)], 6.7, window_s=60.0).tolist() == [1]


def test_unknown_team_rule_still_fails_loudly():
    from courtcam.identity import assign_teams

    bogus = PROFILE.model_copy(update={"team_rule": "coin_toss"})
    with pytest.raises(ValueError, match="coin_toss"):
        assign_teams(np.zeros((4, 48), dtype=np.float32), [], bogus, PROFILE.template("half"))


def test_team_colors_prefer_the_profile_over_the_video():
    from courtcam.identity import team_colors

    profile = load_profile("pickleball")
    teams = np.array([0, 1, 0])
    assert team_colors(teams, profile, None) == {0: "#1F7A8C", 1: "#E07A25"}
    # basketball fixes no colours, so the torso means stand
    means = np.array([[160.0, 79.0, 31.0], [232.0, 232.0, 232.0], [160.0, 79.0, 31.0]])
    assert team_colors(teams, PROFILE, means) == {0: "#1F4FA0", 1: "#E8E8E8"}


def test_concurrency_cap_keeps_non_overlapping_players_beyond_max():
    """`players.max` bounds how many are on court at once, not the roster."""
    from courtcam.identity import _cap_concurrent

    seq = [([i], _track(i, 10.0 * i, 10.0 * i + 8.0, (0.0, 5.0), (1.0, 5.0))) for i in range(3)]
    assert len(_cap_concurrent(seq, 2)) == 3

    both = [([i], _track(i, 0.0, 10.0, (float(i), 5.0), (float(i), 6.0))) for i in range(3)]
    assert len(_cap_concurrent(both, 2)) == 2


def test_a_one_frame_handover_overlap_still_merges():
    """ByteTrack re-ids a person a frame before it drops the old id."""
    a = _track(1, 0.0, 4.0, (0.0, 5.0), (2.0, 6.0))
    b = _track(2, 3.95, 9.0, (2.0, 6.0), (5.0, 8.0))
    assert merge_groups([a, b], np.array([0, 0]), MERGE) == [[0, 1]]


def test_merge_takes_the_closest_continuation_not_the_earliest():
    early = _track(1, 0.0, 4.0, (0.0, 5.0), (0.0, 5.0))
    late = _track(2, 1.0, 4.1, (1.5, 5.0), (1.5, 5.0))
    new = _track(3, 4.5, 9.0, (1.6, 5.0), (3.0, 5.0))  # within reach of both
    groups = merge_groups([early, late, new], np.zeros(3, dtype=int), MERGE)
    assert sorted(groups) == [[0], [1, 2]]


def test_merge_is_one_global_assignment_not_closest_first():
    """Two players run left through a 0.5 s gap. Closest-first hands the nearest new
    tracklet to the rear runner and leaves the front one a 4 m link; the assignment that
    is cheapest overall pairs each with the one ahead of it."""
    front = _track(1, 0.0, 4.0, (8.0, 5.0), (0.0, 5.0))
    rear = _track(2, 0.0, 4.0, (10.0, 5.0), (2.0, 5.0))
    ahead_of_front = _track(3, 4.5, 8.0, (-2.2, 5.0), (-9.0, 5.0))
    ahead_of_rear = _track(4, 4.5, 8.0, (0.2, 5.0), (-6.0, 5.0))
    groups = merge_groups([front, rear, ahead_of_front, ahead_of_rear], np.zeros(4, int), PROFILE)
    assert sorted(groups) == [[0, 2], [1, 3]]


def test_split_switches_cuts_a_tracklet_where_the_jersey_changes_for_good():
    from courtcam.identity import split_switches

    tr = _track(7, 0.0, 4.0, (0.0, 5.0), (4.0, 5.0))  # 60 samples at 15 fps
    swap = {j: int(j >= 30) for j in range(60)}
    blip = {j: int(30 <= j < 35) for j in range(60)}  # 1/3 s: noise, not a swap
    pieces, teams = split_switches([tr, tr], [swap, blip], np.array([0, 0]))
    assert [len(p.tracklet.frames) for p in pieces] == [30, 30, 60]
    assert teams.tolist() == [0, 1, 0]
    assert pieces[1].tracklet.t_start == pytest.approx(tr.tracklet.times[30])
    assert pieces[1].court_m[0] == pytest.approx(tr.court_m[30])


def test_concurrency_cap_ignores_a_handover_overlap():
    from courtcam.identity import _cap_concurrent

    a = ([0], _track(0, 0.0, 10.0, (0.0, 5.0), (1.0, 5.0)))
    b = ([1], _track(1, 9.95, 20.0, (1.0, 5.0), (2.0, 5.0)))
    assert len(_cap_concurrent([a, b], 1)) == 1
    assert len(_cap_concurrent([a, b], 1, overlap_s=1.0)) == 2


def test_stitch_joins_a_break_only_when_the_roster_says_it_is_one_person():
    """Doubles: two a side. A near player whose foot point jumps 3.5 m at an occlusion
    is still one person while their partner is the only other near player alive."""
    from courtcam.identity import _stitch

    profile = MERGE.model_copy(update={"players": MERGE.players.model_copy(update={"max": 4})})
    partner = _track(1, 0.0, 10.0, (0.0, 2.0), (1.0, 2.0))
    before = _track(2, 0.0, 5.0, (-2.0, 3.0), (-2.0, 3.0))
    after = _track(3, 5.2, 10.0, (1.5, 3.0), (1.0, 3.0))  # 3.5 m > merge_max_dist_m
    far = _track(4, 0.0, 10.0, (0.0, 10.0), (0.0, 11.0))
    tracks, teams = [partner, before, after, far], np.array([0, 0, 0, 1])
    groups = _stitch(tracks, [[0], [1], [2], [3]], teams, profile)
    assert sorted(groups) == [[0], [1, 2], [3]]

    # a third near player alive means the side is full: the newcomer is someone else
    extra = _track(5, 0.0, 10.0, (2.0, 4.0), (2.0, 4.0))
    tracks, teams = [*tracks, extra], np.array([0, 0, 0, 1, 0])
    groups = _stitch(tracks, [[0], [1], [2], [3], [4]], teams, profile)
    assert sorted(groups) == [[0], [1], [2], [3], [4]]
