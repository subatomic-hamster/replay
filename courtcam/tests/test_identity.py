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
            update={"merge_max_gap_s": 1.5, "merge_max_dist_m": 2.0, "officials": 0}
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


def test_people_far_beyond_a_small_game_do_not_count_toward_its_size():
    """The JaiArtHub 2v2 (D-89 round 5): people across the park behind the fence are a
    third the players' height and there all clip long; counted, the 2v2 reads as 7."""
    from courtcam.identity import near_tracks, roster_size

    players = [_track(i, 0.0, 60.0, (float(i), 5.0), (float(i), 6.0)) for i in range(4)]
    far = [_track(10 + j, 0.0, 60.0, (float(j), 20.0), (float(j), 20.0)) for j in range(3)]
    for t in far:
        t.tracklet.boxes[:, 3] = 35.0  # vs 120 px players
    assert roster_size(players + far) == 7
    assert roster_size(near_tracks(players + far)) == 4
    assert near_tracks(players) == players  # nobody is far when all are alike


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

    # an untrusted court fit (D-94): nobody is dropped for where the fit puts them
    roomy = MERGE.model_copy(update={"players": MERGE.players.model_copy(update={"max": 20})})
    with patch("courtcam.identity.sample_appearance", return_value=(hists, colors, None)):
        kept = identify("unused.mp4", tracks, roomy, court_ok=False)
    assert len(kept) == 11


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


def test_an_opponent_standing_in_front_does_not_cut_a_track(tmp_path):
    """Two red and two blue players, perfect tracks. Blue p2 stands over red p1 for 1.3 s,
    so p1's torso box shows blue jersey: a guard, not a tracker swap. D-70 cut p1 there
    and gave the piece to the blue team (GT-detector basketball, Tracking v3)."""
    import cv2

    from courtcam.identity import identify

    n, fps = 60, 15
    t = np.arange(n) / fps
    px = {1: np.full(n, 60.0), 2: np.where((t >= 20 / fps) & (t < 40 / fps), 60.0, 140.0)}
    px |= {3: np.full(n, 200.0), 4: np.full(n, 260.0)}
    bgr = {1: (0, 0, 220), 3: (0, 0, 220), 2: (220, 0, 0), 4: (220, 0, 0)}
    video = tmp_path / "clip.avi"
    out = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), fps, (320, 240))
    for f in range(n):
        img = np.full((240, 320, 3), 128, np.uint8)
        for k in (1, 3, 4, 2):  # p2 drawn last: in front of p1
            x = int(px[k][f])
            img[40:160, x : x + 40] = bgr[k]
        out.write(img)
    out.release()
    tracks = []
    for k in (1, 2, 3, 4):
        boxes = np.column_stack([px[k], np.full(n, 40.0), np.full(n, 40.0), np.full(n, 120.0)])
        court = np.column_stack([np.linspace(2, 6, n), np.full(n, 3.0 * k)])
        tracks.append(CourtTrack(Tracklet(k, np.arange(n), t, boxes, np.full(n, 0.9)), court, 1.0))

    players = identify(str(video), tracks, PROFILE)
    assert sorted(p.members for p in players) == [(1,), (2,), (3,), (4,)]
    team = {p.members[0]: p.team for p in players}
    assert team[1] == team[3] != team[2] == team[4]


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


# --- D-89: appearance cuts and small rosters (synthetic descriptors) -----------------


def _look(bin_: int) -> np.ndarray:
    """A `body_hist`-shaped descriptor with all mass in one bin of each half."""
    from courtcam.identity import BODY_BINS

    n = int(np.prod(BODY_BINS))
    d = np.zeros(2 * n)
    d[bin_] = d[n + bin_] = 1.0
    return d


def test_split_appearance_cuts_where_the_person_changes_for_good():
    from courtcam.identity import split_appearance

    tr = _track(7, 0.0, 6.0, (0.0, 5.0), (3.0, 5.0))  # 90 samples
    idx = np.arange(0, 90, 7)[:12]  # 12 clear samples
    swap = np.stack([_look(0)] * 6 + [_look(5)] * 6)  # the tracker handed the id on
    same = np.stack([_look(0)] * 12)
    pieces, src, desc = split_appearance([tr, tr], [(idx, swap), (idx, same)], cut=0.18)
    assert src == [0, 0, 1]
    assert pieces[0].tracklet.t_end < pieces[1].tracklet.t_start  # cut at sample 6
    assert pieces[1].tracklet.frames[0] == tr.tracklet.frames[idx[6]]
    assert len(pieces[0].tracklet.frames) + len(pieces[1].tracklet.frames) == 90
    assert np.allclose(desc[0], _look(0)) and np.allclose(desc[1], _look(5))


def test_stitch_refuses_a_lane_the_newcomer_does_not_look_like():
    """The roster says someone continues the lane; appearance says whether it is them."""
    from courtcam.identity import _stitch

    profile = MERGE.model_copy(
        update={
            "players": MERGE.players.model_copy(update={"max": 4}),
            "tracking": MERGE.tracking.model_copy(
                update={"appearance_weight": 1.0, "appearance_max": 0.15}
            ),
        }
    )
    partner = _track(1, 0.0, 10.0, (0.0, 2.0), (1.0, 2.0))
    before = _track(2, 0.0, 5.0, (-2.0, 3.0), (-2.0, 3.0))
    after = _track(3, 5.2, 10.0, (1.5, 3.0), (1.0, 3.0))
    far = _track(4, 0.0, 10.0, (0.0, 10.0), (0.0, 11.0))
    tracks, teams = [partner, before, after, far], np.array([0, 0, 0, 1])
    alike = np.stack([_look(1), _look(0), _look(0), _look(2)])
    assert sorted(_stitch(tracks, [[0], [1], [2], [3]], teams, profile, alike)) == [
        [0],
        [1, 2],
        [3],
    ]
    unlike = np.stack([_look(1), _look(0), _look(5), _look(2)])
    assert sorted(_stitch(tracks, [[0], [1], [2], [3]], teams, profile, unlike)) == [
        [0],
        [1],
        [2],
        [3],
    ]


def _series(track: CourtTrack, looks: list[tuple[float, int]], every: int = 7):
    """`body_series` for a synthetic track: a sample every `every` frames, wearing
    `looks` = [(from time, look bin), ...]."""
    idx = np.arange(0, len(track.tracklet.times), every)
    t = track.tracklet.times[idx]
    bins = [
        max(b for s, b in looks if s <= x) if any(s <= x for s, _ in looks) else looks[0][1]
        for x in t
    ]
    return idx, np.stack([_look(b) for b in bins])


def test_roster_cuts_a_swap_and_solves_two_people_as_two_ids():
    from courtcam.identity import roster_pieces, roster_size

    # Two people, looks 0 and 3. The tracker follows person 0 then swaps to person 1 at
    # 5 s (track 1); person 1 is on track 2 until then, person 0 comes back on track 3.
    swap = _track(1, 0.0, 10.0, (0.0, 5.0), (2.0, 5.0))
    other = _track(2, 0.0, 4.9, (2.0, 5.0), (2.0, 5.0))
    back = _track(3, 5.2, 10.0, (0.5, 5.0), (0.0, 5.0))
    tracks = [swap, other, back]
    series = [
        _series(swap, [(0.0, 0), (5.0, 3)]),
        _series(other, [(0.0, 3)]),
        _series(back, [(0.0, 0)]),
    ]
    assert roster_size(tracks) == 2
    pieces, src, groups, protos = roster_pieces(tracks, series, 2, PROFILE)
    assert len(groups) == 2  # two people, nothing left over
    spans = sorted(sorted((src[i], round(pieces[i].tracklet.t_start)) for i in g) for g in groups)
    assert spans == [[(0, 0), (2, 5)], [(0, 5), (1, 0)]]  # (tracklet, start s)

    # Every box labelled with those looks gives the same two people; a box nobody
    # looks like (the last second of track 3) is left out rather than given to anyone.
    from courtcam.identity import box_covers, roster_label

    dense = [
        _series(swap, [(0.0, 0), (5.0, 3)], every=1),
        _series(other, [(0.0, 3)], every=1),
        _series(back, [(0.0, 0), (9.0, 6)], every=1),
    ]
    pieces, src, groups = roster_label(tracks, dense, box_covers(tracks), protos)
    spans = sorted(sorted((src[i], round(pieces[i].tracklet.t_start)) for i in g) for g in groups)
    assert spans == [[(0, 0), (2, 5)], [(0, 5), (1, 0)]]
    assert max(pieces[i].tracklet.t_end for i in groups[0] + groups[1] if src[i] == 2) < 9.0


def test_game_players_carry_seen_seconds_and_a_mixed_kit_flag(tmp_path):
    from courtcam.identity import PlayerTrack, read_players, to_models, write_players

    def joined(a: CourtTrack, b: CourtTrack) -> CourtTrack:
        cat = lambda f: np.concatenate([getattr(a.tracklet, f), getattr(b.tracklet, f)])  # noqa: E731
        tl = Tracklet(a.track_id, cat("frames"), cat("times"), cat("boxes"), cat("confs"))
        return CourtTrack(tl, np.vstack([a.court_m, b.court_m]), 1.0)

    # boxes 0-1 s and 3-4 s: tracks/ fills the 2 s hole unless the id is a solved person
    holed = joined(_track(1, 0.0, 1.0, (1, 1), (1, 1)), _track(1, 3.0, 4.0, (1, 1), (1, 1)))
    players = [
        PlayerTrack("p1", 0, "#FF0000", holed, (1,), off_kit=0.1),
        PlayerTrack("p2", 1, "#0000FF", holed, (1,), solved=True, off_kit=0.6),
        PlayerTrack("p3", 1, "#0000FF", _track(3, 0.0, 2.0, (1, 1), (1, 1)), (3,)),
    ]
    write_players(tmp_path / "players.json", players, {})
    back, _ = read_players(tmp_path / "players.json")
    models, _ = to_models(back)
    got = {m.id: (m.seen_s, m.team_mixed) for m in models}
    assert got == {"p1": (4.1, False), "p2": (2.2, True), "p3": (2.1, None)}


def test_fill_gaps_takes_the_free_detections_in_a_players_gap():
    from courtcam.identity import PlayerTrack, fill_gaps

    def track(tid, frames, x0, dx):
        f = np.asarray(frames)
        boxes = np.column_stack([x0 + dx * f, np.full(len(f), 100.0), np.full(len(f), 40.0),
                                 np.full(len(f), 120.0)])  # fmt: skip
        return CourtTrack(Tracklet(tid, f, f / 10.0, boxes, np.full(len(f), 0.9)),
                          np.zeros((len(f), 2)), 1.0)  # fmt: skip

    # p1 walks right 2 px a frame and has no box in frames 3-7; p2 stands still at x 500
    p1 = track(1, [0, 1, 2, 8, 9], 100.0, 2.0)
    p2 = track(2, list(range(10)), 500.0, 0.0)
    walker = [[-1, 100.0 + 2 * f, 100.0, 40.0, 120.0, 0.6] for f in range(10)]
    stander = [[7, 500.0, 100.0, 40.0, 120.0, 0.9] for _ in range(10)]
    stray = [[-2, 900.0, 100.0, 40.0, 120.0, 0.5]]  # someone else, nowhere near p1
    dets = {
        "fps": 10.0,
        "frames": [
            {"f": f, "t": f / 10.0, "d": [walker[f], stander[f]] + (stray if f == 5 else [])}
            for f in range(10)
        ],
    }
    players = [PlayerTrack("p1", 0, "#FF0000", p1, (1,)), PlayerTrack("p2", 1, "#0000FF", p2, (2,))]
    out = fill_gaps(players, dets, np.eye(3))
    t1 = out[0].track.tracklet
    assert t1.frames.tolist() == list(range(10))
    assert np.allclose(t1.boxes[:, 0], 100.0 + 2 * np.arange(10))  # the walker, not the stray
    assert np.allclose(out[0].track.court_m[3:8, 1], 220.0)  # feet projected (H = identity)
    assert out[1] is players[1]  # nothing missing, untouched


def _pickup_2v2(seed: int = 0) -> list[CourtTrack]:
    """Synthetic half-court 2v2, labelled synthetic: players 0 and 2 are one team, 1 and
    3 the other; 1 guards 0 and 3 guards 2. Possessions of 15 s alternate; the attacker
    wanders 5-7 m out and the defender stays ~1 m goal-side of him, sometimes beaten."""
    rng = np.random.default_rng(seed)
    t = np.arange(0.0, 180.0, 1 / 15)
    rim = np.array([0.0, 1.575])
    pos = np.zeros((4, len(t), 2))
    for pair, side in ((0, -1.0), (1, 1.0)):
        ang = np.pi / 2 + side * 0.7 + np.cumsum(rng.normal(0, 0.02, len(t)))
        far = 6.0 + np.sin(t / 3.0 + pair)
        man = rim + np.c_[np.cos(ang), np.sin(ang)] * far[:, None]
        guard = (
            rim
            + np.c_[np.cos(ang), np.sin(ang)] * (far - 1.0 + rng.normal(0, 0.6, len(t)))[:, None]
        )
        offence = (t // 15) % 2 == 0  # team (0, 2) attacks first
        a, b = 2 * pair, 2 * pair + 1
        pos[a] = np.where(offence[:, None], man, guard)
        pos[b] = np.where(offence[:, None], guard, man)
    tracks = []
    for k in range(4):
        boxes = np.column_stack([pos[k] * 50, np.full((len(t), 2), 100.0)])
        tl = Tracklet(k, np.arange(len(t)), t, boxes, np.full(len(t), 0.9))
        tracks.append(CourtTrack(tl, pos[k], 1.0))
    return tracks


def test_matchups_split_a_pickup_game_whose_shirts_say_nothing():
    from courtcam.identity import matchup_teams, play_teams

    tracks = _pickup_2v2()
    teams, corr = matchup_teams(tracks, [(0.0, 1.575)])
    assert teams[0] == teams[2] != teams[1] == teams[3]
    assert corr > 0.5
    assert matchup_teams(tracks[:3], [(0.0, 1.575)]) is None  # not a 2v2 / 3v3
    assert matchup_teams(tracks, []) is None  # no basket, no roles

    merged = [([k], tr) for k, tr in enumerate(tracks)]
    template = PROFILE.template("half")
    shirts = np.eye(4)  # four different shirts: teammates no closer than opponents
    kits = np.array([0, 0, 0, 1])  # what k-means made of them: 3 v 1
    assert (play_teams(merged, kits, shirts, template) == teams).all()
    # two real kits split evenly and teammates look alike: the kits stand
    two_kits = np.array([[1.0, 0], [0, 1.0], [1.0, 0.05], [0.05, 1.0]])
    assert play_teams(merged, np.array([0, 1, 0, 1]), two_kits, template) is None


def test_the_users_team_pick_wins_over_the_pipelines(tmp_path):
    import json

    from courtcam.identity import (
        PlayerTrack,
        apply_team_edits,
        read_players,
        to_models,
        write_players,
    )

    tr = _track(1, 0.0, 2.0, (1, 1), (1, 1))
    players = [
        PlayerTrack("p1", 0, "#E8A33D", tr, (1,), team_source="matchups"),
        PlayerTrack("p2", 1, "#3D7BE8", tr, (2,), team_source="matchups"),
    ]
    (tmp_path / "_work").mkdir()
    write_players(tmp_path / "_work" / "players.json", players, {})
    assert not apply_team_edits(tmp_path)  # no edits.json: nothing to do
    (tmp_path / "edits.json").write_text(
        json.dumps(
            {
                "patch": {
                    "game.json": {"p2": {"team": 0, "color_hex": "#E8A33D"}, "p1": {"name": "Ravi"}}
                }
            }
        )
    )
    assert apply_team_edits(tmp_path)
    assert not apply_team_edits(tmp_path)  # idempotent
    back, _ = read_players(tmp_path / "_work" / "players.json")
    assert [(p.team, p.team_source, p.color_hex) for p in back] == [
        (0, "matchups", "#E8A33D"),
        (0, "user", "#E8A33D"),
    ]
    _, teams = to_models(back)
    assert [(t.id, t.team_source) for t in teams] == [(0, "user")]
