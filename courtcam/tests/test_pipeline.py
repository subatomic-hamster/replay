"""Full synthetic run: every output file must validate, and drift is caught by a golden."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from courtcam.identity import read_players
from courtcam.pipeline import STAGES
from courtcam.schema import CropPath, Events, Game, TracksChunk, read_json

GOLDEN = (
    Path(__file__).resolve().parents[2]
    / "samples"
    / "synthetic"
    / "basketball_half"
    / "golden.json"
)
COURT_TOL_M = 0.25
EVENT_TOL = 3


@pytest.fixture(scope="session")
def game(pipeline_out: Path) -> Game:
    return read_json(pipeline_out / "game.json", Game)


def test_game_json_is_complete(game: Game, pipeline_out: Path):
    assert game.status == "ready"
    assert set(game.stages) == set(STAGES) and set(game.stages.values()) == {"done"}
    assert game.renditions.wide == "media/wide.mp4"  # D-3: progressive MP4, not HLS
    assert (pipeline_out / game.renditions.wide).exists()
    assert game.tracks.url_template == "tracks/{chunk:05d}.json"
    assert game.croppaths.url_template == "crops/{player_id}.json"
    assert game.events_url == "events.json"
    assert game.video.fps == 30 and (game.video.width, game.video.height) == (1280, 720)
    assert {lm for lm in game.court.landmarks_px} == {
        "corner_nl",
        "corner_nr",
        "corner_fl",
        "corner_fr",
        "rim",
    }
    for extra in ("media/thumb.jpg", "media/calib.jpg", "calib.json"):
        assert (pipeline_out / extra).exists()


def test_every_track_chunk_validates(game: Game, pipeline_out: Path):
    ids = {p.id for p in game.players}
    assert game.tracks.chunks == 2
    for c in range(game.tracks.chunks):
        chunk = read_json(pipeline_out / game.tracks.url_template.format(chunk=c), TracksChunk)
        assert chunk.t0 == c * game.tracks.chunk_s
        assert len(chunk.frames) <= game.tracks.rate_hz * game.tracks.chunk_s
        for frame in chunk.frames:
            for p in frame.p:
                assert p.id in ids
                assert all(0.0 <= v <= 1.0 for v in p.bb), "bb is normalised to the frame"
                assert 0.0 <= p.c <= 1.0


def test_every_crop_path_validates(game: Game, pipeline_out: Path):
    n = int(round(game.video.duration_s * 30))
    for player in game.players:
        crops = read_json(
            pipeline_out / game.croppaths.url_template.format(player_id=player.id), CropPath
        )
        assert crops.t0 == 0.0 and crops.rate_hz == 30
        assert len(crops.rects) == n, "one rect per video frame at 30 Hz"
        rects = np.asarray(crops.rects)
        assert rects.min() >= 0.0 and rects.max() <= 1.0
        assert np.abs(np.diff(rects[:, :2], axis=0)).max() < 0.05


def test_events_validate(pipeline_out: Path):
    events = read_json(pipeline_out / "events.json", Events)
    for e in events.events:
        assert e.type == "shot" and e.source == "heuristic" and e.confirmed is False
        assert e.made is None, "the heuristic labeler cannot judge makes"
        assert 0.0 <= e.t_start <= e.t_key <= e.t_end
        assert e.player_id is not None and e.court is not None
        assert 0.0 < e.confidence <= 1.0


def test_matches_the_golden_within_tolerance(game: Game, pipeline_out: Path):
    golden = json.loads(GOLDEN.read_text())
    players, _ = read_players(pipeline_out / "_work" / "players.json")

    assert len(game.players) == golden["players"]
    assert (
        sorted(len([p for p in game.players if p.team == t]) for t in (0, 1))
        == golden["team_sizes"]
    )

    members = {m for p in players for m in p.members}
    assert members == set(golden["kept_track_ids"])
    assert not members & set(golden["spectator_track_ids"]), "spectators must stay filtered out"

    by_track = {p.members[0]: p for p in players}
    for tid, samples in golden["court_by_track"].items():
        player = by_track[int(tid)]
        for t, x, y in samples:
            got = player.track.court_at(t)
            assert np.allclose(got, [x, y], atol=COURT_TOL_M), (
                f"track {tid} at t={t}: {got} != {[x, y]}"
            )

    n_events = len(read_json(pipeline_out / "events.json", Events).events)
    assert abs(n_events - golden["events"]) <= EVENT_TOL


def test_detection_moves_to_the_gpu_model_only_when_there_is_a_gpu(monkeypatch):
    from courtcam import detect
    from courtcam.profiles import DetectionCfg

    cfg = DetectionCfg(model="yolo11n.pt", gpu_model="yolo11m.pt")
    monkeypatch.setattr(detect, "gpu_available", lambda: True)
    d = detect.YoloDetector(cfg)
    assert (d.weights, d.device) == ("yolo11m.pt", "0")
    monkeypatch.setattr(detect, "gpu_available", lambda: False)
    d = detect.YoloDetector(cfg)
    assert (d.weights, d.device) == ("yolo11n.pt", "cpu")
