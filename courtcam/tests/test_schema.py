from __future__ import annotations

import json
from pathlib import Path

from courtcam.schema import (
    CourtInfo,
    CropPath,
    Event,
    Events,
    Game,
    Renditions,
    TrackFrame,
    TrackPoint,
    TracksChunk,
    VideoInfo,
    dump,
    read_json,
    write_json,
)


def _game() -> Game:
    return Game(
        id="g_7f3k2p",
        title="Tuesday run",
        video=VideoInfo(duration_s=2412.4, fps=30, width=3840, height=2160),
        sport="basketball",
        court=CourtInfo(variant="half", standard="fiba", landmarks_px={"rim": (1.0, 2.0)}),
        renditions=Renditions(wide="media/wide.mp4"),
    )


def test_schema_key_is_the_contract_name():
    assert dump(_game())["schema"] == "replay.game.v1"
    assert dump(TracksChunk(t0=0.0))["schema"] == "replay.tracks.v1"
    assert dump(CropPath(player_id="p3"))["schema"] == "replay.crops.v1"
    assert dump(Events())["schema"] == "replay.events.v1"


def test_round_trip_every_contract(tmp_path: Path):
    models = [
        _game(),
        TracksChunk(
            t0=120.0,
            frames=[
                TrackFrame(
                    t=120.0,
                    p=[TrackPoint(id="p3", bb=(0.4, 0.3, 0.04, 0.16), ct=(3.2, 5.8), c=0.91)],
                )
            ],
        ),
        CropPath(player_id="p3", rects=[(0.3, 0.22, 0.5, 0.5)]),
        Events(
            events=[
                Event(
                    id="e_0142",
                    type="shot",
                    made=True,
                    t_start=311.2,
                    t_key=313.9,
                    t_end=315.5,
                    player_id="p3",
                    court=(5.1, 2.4),
                    confidence=0.78,
                    source="vlm",
                )
            ]
        ),
    ]
    for i, model in enumerate(models):
        path = write_json(tmp_path / f"{i}.json", model)
        again = read_json(path)  # model chosen by the "schema" field
        assert dump(again) == dump(model)


def test_made_may_be_unknown(tmp_path: Path):
    """The heuristic labeler cannot tell makes from misses (see README schema notes)."""
    e = Event(id="e_0", type="shot", t_start=0.0, t_key=1.0, t_end=2.0)
    assert e.made is None
    assert (
        json.loads(write_json(tmp_path / "e.json", Events(events=[e])).read_text())["events"][0][
            "made"
        ]
        is None
    )
