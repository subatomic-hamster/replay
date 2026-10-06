"""Speaker provider: opt-in voice enrollment for "Replay, clip that" attribution (vision
"clip that" (b)). Only enrolled speakers are ever returned. AWS: the same local model on
a SageMaker endpoint (`aws.SageMakerSpeaker`).

Local: SpeechBrain ECAPA-VoxCeleb (Apache-2.0, D-39) in the box's `venvs/speaker`, through
the model runner. Opt-in twice over: nothing works until `REPLAY_SPEAKER_DIR` names the
enrollment store, and `identify` only ever compares against profiles that enrolled there
(one mean embedding per profile, `<dir>/<profile_id>.json`). `forget` deletes it.
The 0.5 cosine threshold is from synthetic voices only (same voice 0.66-0.80, different
-0.02-0.29, docs/models.md); real enrollment data must re-tune it (REPLAY_SPEAKER_THRESHOLD).
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Protocol

from . import NotConfiguredError, _runner


class Speaker(Protocol):
    def enroll(self, profile_id: str, clips: list[Path]) -> dict: ...

    def identify(self, audio: Path, t_start: float, t_end: float) -> list[dict]:
        """`[{profile_id, score}]` for the enrolled speakers heard in [t_start, t_end]."""
        ...

    def forget(self, profile_id: str) -> None: ...


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class LocalSpeaker:
    def __init__(self, store_dir: Path | None = None, threshold: float | None = None):
        d = store_dir or os.environ.get("REPLAY_SPEAKER_DIR")
        self.dir = Path(d) if d else None
        self.threshold = threshold or float(os.environ.get("REPLAY_SPEAKER_THRESHOLD", "0.5"))

    def _ready(self) -> Path:
        if self.dir is None:
            raise NotConfiguredError(
                "speaker: opt-in only; set REPLAY_SPEAKER_DIR (enrollment store) and "
                "REPLAY_MODEL_VENVS (ECAPA `speaker` venv, docs/models.md)"
            )
        _runner.require("speaker", "speaker")
        return self.dir

    def _path(self, profile_id: str) -> Path:
        store = self._ready()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(profile_id)):
            raise ValueError(f"bad profile id {profile_id!r}")
        return store / f"{profile_id}.json"

    def _embed(self, clips: list[dict]) -> list[list[float]]:
        root = _runner.venvs_root()
        savedir = os.environ.get("REPLAY_ECAPA_DIR") or str(root.parent / "models" / "ecapa")
        return _runner.call("speaker", {"clips": clips, "savedir": savedir})["embeddings"]

    def enroll(self, profile_id: str, clips: list[Path]) -> dict:
        path = self._path(profile_id)
        embs = self._embed([{"path": str(c)} for c in clips])
        mean = _unit([sum(col) / len(embs) for col in zip(*embs)])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"profile_id": profile_id, "clips": len(clips), "e": mean}))
        return {"profile_id": profile_id, "clips": len(clips), "voice_enrolled": True}

    def identify(self, audio: Path, t_start: float, t_end: float) -> list[dict]:
        store = self._ready()
        enrolled = [json.loads(p.read_text()) for p in sorted(store.glob("*.json"))]
        if not enrolled:
            return []  # nobody opted in: never run the model on bystanders' voices
        clip = {"path": str(audio), "t_start": t_start, "t_end": t_end}
        e = self._embed([clip])[0]
        hits = [
            {
                "profile_id": d["profile_id"],
                "score": round(sum(a * b for a, b in zip(e, d["e"])), 3),
            }
            for d in enrolled
        ]
        return sorted((h for h in hits if h["score"] >= self.threshold), key=lambda h: -h["score"])

    def forget(self, profile_id: str) -> None:
        self._path(profile_id).unlink(missing_ok=True)
