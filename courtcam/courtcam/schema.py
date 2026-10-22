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
    # Additive (D-94): false when the court fit disagrees with the people (most of them
    # off its court, or the wrong height for its camera). Nobody was dropped for where
    # they stand, but court positions, zones and shot charts are unreliable. Older games
    # lack it.
    trusted: bool | None = None


class Renditions(_Model):
    wide: str
    players: dict[str, str] = Field(default_factory=dict)


class Player(_Model):
    id: str
    name: str | None = None
    team: int
    color_hex: str
    tagged: bool = False
    # Additive (D-89): seconds this id has a box in tracks/, and whether its box time is
    # split between kits so much that `team` is unreliable. Older games lack both.
    seen_s: float | None = None
    team_mixed: bool | None = None


class Team(_Model):
    id: int
    color_hex: str


class TracksRef(_Model):
    rate_hz: int = 10
    chunk_s: int = 10
    url_template: str = "tracks/{chunk:05d}.json"
    chunks: int = 0
    # every id is one person for the whole clip (D-89): a follow never moves to another id
    people: bool = False


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

EventType = Literal[
    "shot",
    "possession_change",
    "rally",
    "point",
    "serve",
    "bookmark",
    # M4, additive: a lost possession, a racket/hand contact (audio onset attributed to a
    # player by pose), a volleyball block, and a crowd/hype loudness spike.
    "turnover",
    "contact",
    "block",
    "hype",
]
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
    # M4, additive and optional: the team the event belongs to (offense for a shot, the
    # gaining team for a possession change, the hitter's side for a contact), a shot's
    # value from the 3-pt line, and why a possession changed (inbound / steal /
    # defensive_rebound) or a point ended.
    team: int | None = None
    points: int | None = None
    cause: str | None = None


class Events(_Model):
    schema_: Literal["replay.events.v1"] = Field("replay.events.v1", alias="schema")
    events: list[Event] = Field(default_factory=list)


# --- replay.poses.v1 --------------------------------------------------------

COCO_KEYPOINTS = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)  # fmt: skip


class PosePoint(_Model):
    id: str  # player id, as in tracks
    # 17 COCO keypoints [x, y, score]; x/y normalized to the frame like `TrackPoint.bb`.
    # A keypoint the model did not find has score 0.
    kp: list[tuple[float, float, float]]
    c: float  # the person detection's confidence


class PoseFrame(_Model):
    t: float
    p: list[PosePoint] = Field(default_factory=list)


class PosesChunk(_Model):
    """`poses/{chunk:05d}.json`: one file per tracks chunk, same `t0` and sample times."""

    schema_: Literal["replay.poses.v1"] = Field("replay.poses.v1", alias="schema")
    t0: float
    rate_hz: int = 10
    keypoints: list[str] = Field(default_factory=lambda: list(COCO_KEYPOINTS))
    source: str = "none"  # yolo model name | "synthetic" | "none"
    frames: list[PoseFrame] = Field(default_factory=list)


# --- replay.audio.v1 --------------------------------------------------------


class Onset(_Model):
    t: float
    strength: float  # spectral-flux peak height over the local threshold


class AudioDoc(_Model):
    """`audio.json`: what the audio stage measured. Hype spikes become `hype` events."""

    schema_: Literal["replay.audio.v1"] = Field("replay.audio.v1", alias="schema")
    has_audio: bool
    sr: int = 16000
    wav: str | None = None  # 16 kHz mono PCM, game-relative
    full: str | None = None  # the source's own audio stream, copied
    rate_hz: int = 10
    loudness_db: list[float] = Field(default_factory=list)  # RMS dBFS at `rate_hz`
    onsets: list[Onset] = Field(default_factory=list)
    # [t_start, t_peak, t_end, dB above the rolling baseline] per crowd/hype spike
    hype: list[tuple[float, float, float, float]] = Field(default_factory=list)


# --- replay.plays.v1 / triggers / clips / score -----------------------------

TriggerType = Literal["gesture", "voice", "tap"]


class Participant(_Model):
    player_id: str
    role: str


class Trigger(_Model):
    id: str
    type: TriggerType
    t: float  # when the trigger was given (end of the held X, speech onset, the tap)
    t_start: float | None = None  # gesture: start of the hold
    t_end: float | None = None  # voice: end of the utterance
    by_player_id: str | None = None  # gesture-maker / enrolled speaker / tapping phone
    subject_player_id: str | None = None  # "Replay, clip <name>"
    transcript: str | None = None
    confidence: float = 0.0
    source: Literal["auto", "user"] = "auto"
    play_id: str | None = None  # what it resolved to (None: no play in the window)
    clip_id: str | None = None


class Play(_Model):
    id: str
    sport: str
    grammar: str
    t_start: float
    t_end: float
    event_ids: list[str] = Field(default_factory=list)
    participants: list[Participant] = Field(default_factory=list)
    trigger: Trigger | None = None  # the latest trigger that resolved to this play
    confidence: float = 0.0
    team: int | None = None
    # option for long rallies: the window covering only the last N contacts
    last_n: dict[str, float] | None = None  # {"n": N, "t_start": t}


class Plays(_Model):
    schema_: Literal["replay.plays.v1"] = Field("replay.plays.v1", alias="schema")
    plays: list[Play] = Field(default_factory=list)


class Triggers(_Model):
    schema_: Literal["replay.triggers.v1"] = Field("replay.triggers.v1", alias="schema")
    triggers: list[Trigger] = Field(default_factory=list)


class Attribution(_Model):
    owner_player_id: str | None = None  # whose clip it is: by > subject > none
    by_player_id: str | None = None
    subject_player_id: str | None = None


class Clip(_Model):
    id: str
    play_id: str
    trigger_id: str
    t_start: float
    t_end: float
    attribution: Attribution = Field(default_factory=Attribution)
    participants: list[str] = Field(default_factory=list)  # cross-links: key players
    source: Literal["auto", "user"] = "auto"  # "user" once trimmed or tapped


class Clips(_Model):
    schema_: Literal["replay.clips.v1"] = Field("replay.clips.v1", alias="schema")
    clips: list[Clip] = Field(default_factory=list)


class ScoreEntry(_Model):
    t: float
    scores: tuple[int, int]  # team 0, team 1 after this entry
    event_id: str | None = None
    source: Literal["auto", "user"] = "auto"


class Score(_Model):
    schema_: Literal["replay.score.v1"] = Field("replay.score.v1", alias="schema")
    score: list[ScoreEntry] = Field(default_factory=list)


# --- io helpers -------------------------------------------------------------

_MODELS: dict[str, type[_Model]] = {
    "replay.game.v1": Game,
    "replay.tracks.v1": TracksChunk,
    "replay.crops.v1": CropPath,
    "replay.events.v1": Events,
    "replay.poses.v1": PosesChunk,
    "replay.audio.v1": AudioDoc,
    "replay.plays.v1": Plays,
    "replay.triggers.v1": Triggers,
    "replay.clips.v1": Clips,
    "replay.score.v1": Score,
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
