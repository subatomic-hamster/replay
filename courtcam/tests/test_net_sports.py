"""Tier-1 checks for the net-sport profiles (plan §4.9): pickleball and badminton.

A reduced-scope golden — player count, team split by side of the net, spectators
filtered — over a synthetic clip generated from each profile. The geometry the clip is
drawn from *is* the geometry the pipeline calibrates against, so this catches a broken
template, a broken `team_rule: net_side` and a `margin_m` that swallows the crowd. It
does not pretend to say anything about real footage: samples/real/RESULTS.md does that.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from courtcam import pipeline
from courtcam.identity import net_line_y, read_players
from courtcam.profiles import load_profile
from courtcam.schema import Game, read_json
from courtcam.synth import generate

NET_SPORTS = [("pickleball", "doubles"), ("badminton", "singles")]
COURT_TOL_M = 0.25
DURATION_S = 8.0


@pytest.fixture(scope="session", params=NET_SPORTS, ids=lambda p: f"{p[0]}_{p[1]}")
def net_run(request, tmp_path_factory: pytest.TempPathFactory) -> tuple[str, str, Path, Path]:
    """(sport, variant, synth_dir, pipeline_out) for one net sport."""
    sport, variant = request.param
    root = tmp_path_factory.mktemp(f"{sport}_{variant}")
    synth = root / "synth"
    generate(synth, sport=sport, variant=variant, duration_s=DURATION_S)
    out = root / "out"
    pipeline.run(
        synth / "clip.mp4",
        out,
        sport=sport,
        variant=variant,
        detector="synthetic",
        ground_truth=synth / "ground_truth.json",
        calib=synth / "landmarks.json",
        show_progress=False,
    )
    return sport, variant, synth, out


def test_profile_and_template_agree(net_run):
    sport, variant, _, _ = net_run
    profile = load_profile(sport)
    template = profile.template(variant)
    assert profile.team_rule == "net_side"
    assert len(profile.teams.colors) == 2, "net sports need two fixed team colours"
    assert profile.players.max == 4
    # Every landmark the uploader is asked for must exist in every variant's template.
    for name in profile.court.landmarks:
        assert name in template.landmarks, f"{template.name} is missing {name}"
    # The net posts sit on the net line, and the net halves the court.
    net = net_line_y(template)
    assert net == pytest.approx(template.size[1] / 2, abs=1e-6)
    for post in ("net_post_l", "net_post_r"):
        assert template.landmarks[post][1] == pytest.approx(net, abs=1e-6)


def test_every_profile_variant_calibrates_and_has_a_net(net_run):
    """The variants not exercised by the pipeline run still have to be usable."""
    sport, _, _, _ = net_run
    profile = load_profile(sport)
    for variant in profile.court.variants:
        template = profile.template(variant)
        assert template.polygon.shape == (4, 2)
        assert net_line_y(template) > 0


def test_players_are_capped_at_the_roster_and_split_by_side(net_run):
    sport, variant, _, out = net_run
    profile = load_profile(sport)
    game = read_json(out / "game.json", Game)
    players, _ = read_players(out / "_work" / "players.json")
    net = net_line_y(profile.template(variant))

    assert game.status == "ready"
    assert len(game.players) == profile.players.max
    assert len(players) == len(game.players)

    sides = set()
    for p in players:
        median_y = float(np.median(p.track.court_m[:, 1]))
        assert p.team == int(median_y > net), (
            f"{p.player_id} median y={median_y:.2f} vs net {net:.2f} but team={p.team}"
        )
        assert p.color_hex == profile.teams.colors[p.team]
        sides.add(p.team)
    assert sides == {0, 1}, "a doubles clip must put players on both sides of the net"
    assert {t.color_hex for t in game.teams} == set(profile.teams.colors)


def test_spectators_stay_off_the_roster(net_run):
    """`margin_m` is per profile; a crowd standing just outside it must be filtered."""
    _, _, synth, out = net_run
    gt = json.loads((synth / "ground_truth.json").read_text())
    players, _ = read_players(out / "_work" / "players.json")
    spectators = np.asarray(gt["spectators_m"], dtype=float)

    for p in players:
        centre = np.median(p.track.court_m, axis=0)
        gap = np.min(np.linalg.norm(spectators - centre, axis=1))
        assert gap > COURT_TOL_M, f"{p.player_id} sits on a spectator ({gap:.2f} m away)"


def test_court_positions_track_the_ground_truth(net_run):
    """Foot point → homography → metres, checked against the positions the clip was
    drawn from. This is the golden that would catch a wrong court template."""
    _, _, synth, out = net_run
    gt = json.loads((synth / "ground_truth.json").read_text())
    players, _ = read_players(out / "_work" / "players.json")
    truth = {
        frame["t"]: {row["id"]: row["ct"] for row in frame["d"] if row["oncourt"]}
        for frame in gt["frames"]
    }
    times = sorted(truth)[5:-5:20]
    checked = 0
    for p in players:
        for t in times:
            if not (p.t_start <= t <= p.t_end):
                continue
            want = truth[t].get(p.members[0])
            if want is None:
                continue
            assert np.allclose(p.track.court_at(t), want, atol=COURT_TOL_M)
            checked += 1
    assert checked > 10, "the golden checked almost nothing — synth or ids changed"


def test_no_events_are_emitted_yet(net_run):
    """Tier 1: `events: [rally]` is wired but the shared rally detector is a stub, so
    the honest output is an empty list, not a crash and not made-up rallies."""
    _, _, _, out = net_run
    assert json.loads((out / "events.json").read_text())["events"] == []
