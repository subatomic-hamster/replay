"""Clip labeler provider (plan §4.4 step 10 / §4.2).

Phase 1 default is `heuristic`: pass the detector's own guess through unchanged and
mark it low-confidence so it lands in the review queue (R5). The pipeline calls this;
no route does. Phase 2 swaps in Bedrock/Nova behind the same Protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Labeler(Protocol):
    def label_shot(self, clip_path: Path, hint: dict) -> dict: ...


class HeuristicLabeler:
    name = "heuristic"

    def label_shot(self, clip_path: Path, hint: dict) -> dict:
        return {
            "is_shot": True,
            "made": hint.get("made"),
            "shooter_player_id": hint.get("player_id"),
            "confidence": float(hint.get("confidence", 0.5)),
            "source": "heuristic",
        }


def get_labeler(name: str) -> Labeler:
    if name != "heuristic":
        raise ValueError(f"labeler {name!r} is not available in Phase 1")
    return HeuristicLabeler()
