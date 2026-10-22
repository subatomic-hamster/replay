"""Play logs: a person's own timestamped account of a game (`replay.playlog.v1`, D-90).

Two uses, never mixed with pipeline output:

* **evaluation** — a hand annotation is the ground truth `courtcam eval-events` scores the
  detectors against (samples/truth/*.json). It is never shown in the app.
* **notes** — the uploader's own descriptions of their game, shown in the app as
  "Your note" and stored in the game's `notes.json`, apart from `events.json`.

Format (docs/playlog.md): CSV with a header, or the same rows as JSON.

    t,team,player,type,result,points,note
    0:12.5,red,Sam,shot,make,2,pull-up from the elbow
    0:20,blue,Alex,rebound,,,
    1:02,,,note,,,great hustle play

`t` is seconds or m:ss(.s) from the start of the video; `type` one of `TYPES`; `result`
make|miss for shots. Unknown columns are kept in `extra`.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA = "replay.playlog.v1"
EVAL_LABEL = "hand annotation (ground truth for evaluation)"
TYPES = ("shot", "free_throw", "rebound", "steal", "turnover", "block", "assist", "foul",
         "highlight", "note")  # fmt: skip
_TIME = re.compile(r"^\s*(?:(\d+):)?(\d+(?:\.\d*)?)\s*$")


def parse_time(s: Any) -> float:
    """Seconds from `12.5`, `0:12.5` or `1:02`; raises ValueError otherwise."""
    if isinstance(s, (int, float)):
        return float(s)
    m = _TIME.match(str(s))
    if not m:
        raise ValueError(f"bad time {s!r}: use seconds or m:ss")
    return (int(m.group(1)) * 60 if m.group(1) else 0) + float(m.group(2))


class PlayEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    t: float  # when it happened (a shot: the release)
    type: str
    team: str | None = None  # the team's own name or colour, as the person wrote it
    player: str | None = None
    made: bool | None = None  # shots only
    points: int | None = None
    note: str | None = None
    # evaluation extras: when the ball reached the rim, which hoop, and whether the shot
    # counts (a shot after the whistle or one that was fouled does not)
    t_rim: float | None = None
    hoop: str | None = None
    counts: bool = True
    offensive: bool | None = None
    confidence: str | None = None

    @field_validator("type")
    @classmethod
    def _known(cls, v: str) -> str:
        v = v.strip().lower().replace(" ", "_")
        if v not in TYPES:
            raise ValueError(f"unknown type {v!r}; one of {', '.join(TYPES)}")
        return v

    @property
    def is_shot(self) -> bool:
        return self.type in ("shot", "free_throw")


class ScoreReading(BaseModel):
    t: float
    scores: dict[str, int]  # team -> points on the board


class PlayLog(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_: Literal["replay.playlog.v1"] = Field(SCHEMA, alias="schema")
    use: Literal["evaluation", "notes"] = "notes"
    label: str = "Your notes"
    source: str = "user"
    clip: dict[str, Any] = Field(default_factory=dict)
    teams: dict[str, Any] = Field(default_factory=dict)
    entries: list[PlayEntry] = Field(default_factory=list)
    # an independent score record (an in-arena scoreboard read over time), if any
    scoreboard: list[ScoreReading] = Field(default_factory=list)

    def shots(self, counted: bool = True) -> list[PlayEntry]:
        return [e for e in self.entries if e.is_shot and (e.counts or not counted)]


def _row(r: dict[str, Any]) -> PlayEntry:
    r = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k}
    res = (r.pop("result", "") or "").lower()
    out: dict[str, Any] = {k: v for k, v in r.items() if v not in ("", None)}
    out["t"] = parse_time(r.get("t", ""))
    if res:
        if res not in ("make", "made", "miss", "missed"):
            raise ValueError(f"bad result {res!r}: make or miss")
        out["made"] = res.startswith("make")
    if "points" in out:
        out["points"] = int(out["points"])
    if out.get("type", "").lower().replace(" ", "_") == "free_throw":
        out.setdefault("points", 1)
    return PlayEntry.model_validate(out)


def parse(text: str, *, use: str = "notes") -> PlayLog:
    """A play log from CSV text or JSON (a `replay.playlog.v1` doc or a bare list of rows).
    Raises ValueError naming the first bad row."""
    s = text.lstrip()
    if s.startswith("{") or s.startswith("["):
        doc = json.loads(s)
        if isinstance(doc, list):
            doc = {"entries": doc}
        rows = doc.get("entries") or []
        try:
            entries = [_row(r) if "result" in r else PlayEntry.model_validate(
                {**r, "t": parse_time(r.get("t", ""))}) for r in rows]  # fmt: skip
        except (ValueError, TypeError) as exc:
            raise ValueError(f"play log: {exc}") from exc
        return PlayLog.model_validate({"use": use, **doc, "entries": entries})
    lines = [ln for ln in s.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    entries = []
    for n, r in enumerate(csv.DictReader(io.StringIO("\n".join(lines))), start=2):
        try:
            entries.append(_row(r))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"play log line {n}: {exc}") from exc
    return PlayLog(use=use, entries=sorted(entries, key=lambda e: e.t))  # type: ignore[arg-type]


def load(path: Path, *, use: str = "notes") -> PlayLog:
    return parse(Path(path).read_text(encoding="utf-8"), use=use)


NOTES_REL = "notes.json"


def write_notes(game_dir: Path, log: PlayLog) -> Path:
    """`notes.json`: the uploader's notes, labelled as theirs. Replaces earlier notes."""
    doc = log.model_copy(update={"use": "notes", "label": "Your notes", "source": "user"})
    dest = Path(game_dir) / NOTES_REL
    dest.write_text(doc.model_dump_json(by_alias=True, indent=1, exclude_none=True))
    return dest


def read_notes(game_dir: Path) -> PlayLog | None:
    p = Path(game_dir) / NOTES_REL
    return load(p) if p.is_file() else None
