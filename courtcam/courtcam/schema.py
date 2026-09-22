"""Pydantic models for the `replay.*.v1` data contracts (REPLAY_PLAN.md §4.5).

Field names here are the contract. Read/write helpers keep every producer on the
same JSON shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Vec2 = tuple[float, float]
Rect = tuple[float, float, float, float]


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# --- replay.game.v1 ---------------------------------------------------------


class VideoInfo(_Model):
    duration_s: float
    fps: float
    width: int
    height: int


class CourtInfo(_Model):
    variant: str
    standard: str
    landmarks_px: dict[str, Vec2] = Field(default_factory=dict)


class Renditions(_Model):
    wide: str
    players: dict[str, str] = Field(default_factory=dict)


class Player(_Model):
    id: str
    name: str | None = None
    team: int
    color_hex: str
    tagged: bool = False


class Team(_Model):
    id: int
    color_hex: str


class TracksRef(_Model):
    rate_hz: int = 10
    chunk_s: int = 10
    url_template: str = "tracks/{chunk:05d}.json"
    chunks: int = 0


class CropPathsRef(_Model):
    rate_hz: int = 30
    url_template: str = "crops/{player_id}.json"


class Game(_Model):
    schema_: Literal["replay.game.v1"] = Field("replay.game.v1", alias="schema")
    id: str
    title: str
    recorded_at: str | None = None
    status: str = "processing"
    stages: dict[str, str] = Field(default_factory=dict)
    video: VideoInfo
    sport: str
    court: CourtInfo
    renditions: Renditions
    players: list[Player] = Field(default_factory=list)
    teams: list[Team] = Field(default_factory=list)
    tracks: TracksRef = Field(default_factory=TracksRef)
    croppaths: CropPathsRef = Field(default_factory=CropPathsRef)
    events_url: str = "events.json"


# --- replay.tracks.v1 -------------------------------------------------------


class TrackPoint(_Model):
    id: str
    bb: Rect  # [x, y, w, h] normalized to frame
    ct: Vec2  # court metres
    c: float  # confidence


class TrackFrame(_Model):
    t: float
    p: list[TrackPoint] = Field(default_factory=list)


class TracksChunk(_Model):
    schema_: Literal["replay.tracks.v1"] = Field("replay.tracks.v1", alias="schema")
    t0: float
    rate_hz: int = 10
    frames: list[TrackFrame] = Field(default_factory=list)


# --- replay.crops.v1 --------------------------------------------------------


class CropPath(_Model):
    schema_: Literal["replay.crops.v1"] = Field("replay.crops.v1", alias="schema")
    player_id: str
    rate_hz: int = 30
    t0: float = 0.0
    rects: list[Rect] = Field(default_factory=list)


# --- replay.events.v1 -------------------------------------------------------

EventType = Literal["shot", "possession_change", "rally", "point", "serve", "bookmark"]
EventSource = Literal["heuristic", "vlm", "user"]


class Event(_Model):
    id: str
    type: EventType
    t_start: float
    t_key: float
    t_end: float
    # `made` is Optional: the heuristic labeler cannot tell makes from misses, so it
    # leaves it null. Documented as a deviation in README.md ("Schema notes").
    made: bool | None = None
    player_id: str | None = None
    court: Vec2 | None = None
    confidence: float = 0.0
    source: EventSource = "heuristic"
    confirmed: bool = False
    contacts: int | None = None
    winner_side: int | None = None


class Events(_Model):
    schema_: Literal["replay.events.v1"] = Field("replay.events.v1", alias="schema")
    events: list[Event] = Field(default_factory=list)


# --- io helpers -------------------------------------------------------------

_MODELS: dict[str, type[_Model]] = {
    "replay.game.v1": Game,
    "replay.tracks.v1": TracksChunk,
    "replay.crops.v1": CropPath,
    "replay.events.v1": Events,
}


def dump(model: _Model) -> dict[str, Any]:
    """Model -> contract-shaped dict (``schema`` key, not ``schema_``)."""
    return model.model_dump(by_alias=True, mode="json")


def write_json(path: Path, model: _Model, *, indent: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dump(model), indent=indent), encoding="utf-8")
    return path


def read_json(path: Path, model_cls: type[_Model] | None = None) -> Any:
    """Read a contract file. Without ``model_cls`` the model is picked by ``schema``."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cls = model_cls or _MODELS[raw["schema"]]
    return cls.model_validate(raw)
