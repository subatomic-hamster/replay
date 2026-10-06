"""Stage registry. To add stages: write one module exposing `STAGES: list[Stage]` and add
it to `MODULES` below — that is the one registration line. Order matters: a module's
stages may only depend (`after=`) on stages registered before them."""

from __future__ import annotations

import importlib

from ..dag import Stage

MODULES = [
    "replay_worker.stages.courtcam",
    "replay_worker.stages.broadcast",
    "replay_worker.stages.narrate",
    "replay_worker.stages.virtual",
    "replay_worker.stages.discovery",
]


def load_registry(modules: list[str] | None = None) -> dict[str, Stage]:
    registry: dict[str, Stage] = {}
    for mod in modules or MODULES:
        for stage in importlib.import_module(mod).STAGES:
            if stage.name in registry:
                raise ValueError(f"stage {stage.name!r} registered twice ({mod})")
            registry[stage.name] = stage
    return registry
