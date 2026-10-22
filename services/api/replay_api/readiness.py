"""Tiered readiness for the TV (docs/ux/redesign.md "What the backend needs"): `watchable`,
`eta_s`, `stage_label` and per-feature `features`, derived from the stage states (merged
from the job record while a job runs) and from which files the game folder holds.

ETA heuristic (an estimate, never a measurement): every stage not yet done costs
`fixed_s + per_video_s * duration` (the running one only its unfinished fraction), plus
the worker's post-pipeline stages (`game`, `storyboard`, `moments`) and, in cloud mode,
one runner poll interval while the job is still queued. The per-stage rates are hfbox
wall times from docs/perf.md section 2 (90 s 1080p real clip: YOLO11m detect + BoT-SORT
and YOLO11m-pose on the RX 9070 XT) and this module's own storyboard/moments runs; they
ignore that some CPU stages overlap the GPU ones (so they lean high), queueing behind
other jobs on the box, and opt-in stages (`REPLAY_WORKER_STAGES`), which are not costed.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from . import moments as M

# stage -> (fixed seconds, seconds per second of video), hfbox
COST: dict[str, tuple[float, float]] = {
    "ingest": (1.0, 0.075),  # 6.8 s / 90 s: probe + H.264 mezzanine + stills
    "calibrate": (0.8, 0.0),
    "detect": (2.0, 0.263),  # 23.7 s / 90 s at ~114 fps
    "track": (0.2, 0.0013),
    "court": (0.2, 0.0013),
    "identity": (0.2, 0.0013),
    "tracks": (0.2, 0.0013),
    "crops": (0.2, 0.0013),
    "audio": (0.3, 0.011),
    "pose": (0.5, 0.167),  # 1.5 s per 10 s chunk
    "events": (0.2, 0.0007),
    "triggers": (0.2, 0.0007),
    "plays": (0.2, 0.0007),
    # worker stages after the reported ones, hfbox (6 threads, box loaded), 1080p30 H.264:
    # storyboard 2.1 s / 90 s, 51.9 s / 40 min; moments 0.3 s / 90 s, 5.7 s / 40 min
    # (one event per 15 s: 160 thumbs + hero)
    "storyboard": (0.2, 0.022),
    "_finish": (1.0, 0.0024),  # game (fixed, unmeasured) + moments
}
DEFAULT_COST = (0.5, 0.0)  # fake-pipeline stages and anything unknown
QUEUE_S = 30.0  # cloud: the hfbox runner polls every 30 s

# Plain words for the stage that is running (sentence case, no jargon).
LABELS = {
    "ingest": "Preparing the video",
    "calibrate": "Reading the court",
    "detect": "Finding players",
    "track": "Following players",
    "court": "Placing players on the court",
    "identity": "Telling players apart",
    "tracks": "Following players",
    "crops": "Framing each player",
    "render": "Framing each player",
    "audio": "Listening to the game",
    "pose": "Reading movement",
    "events": "Spotting the plays",
    "label": "Spotting the plays",
    "triggers": "Finding your clip calls",
    "plays": "Building the plays",
}

# feature -> (files that make it ready, the stage it waits for, opt-in worker stages)
# A stage of None waits for the whole run. An opt-in feature is only `pending` while the
# configured REPLAY_WORKER_STAGES will make it; otherwise it is `unavailable`.
FEATURES: dict[str, tuple[tuple[str, ...], str | None, tuple[str, ...]]] = {
    "moments": ((M.REL,), None, ()),
    "previews": ((M.STORYBOARD_REL,), "storyboard", ()),
    "follow": (("crops/*.json",), "crops", ()),
    "angles": (("replays/*/manifest.json",), None, ("replays", "tierc_manifest")),
    "free_view": (("replays/*/scene/layout.json",), None, ("scene",)),
    # each tracked player's virtual POV (Tier C, `pov:<pid>` angles)
    "pov": (("replays/*/tierc_pov_*.mp4",), None, ("tierc_manifest",)),
    "highlights": (("hype.json",), None, ("hype",)),
    "condensed": (("renditions/condensed.mp4",), None, ("condensed",)),
    "stats": (("events.json",), "events", ()),
    # GET /commentary writes a template script from events.json when no stage stored one
    "commentary": (("commentary/script.json", "events.json"), "events", ()),
}

Has = Callable[[str], bool]


def set_duration(game: dict, duration_s: float | None) -> None:
    """The upload's length, set at upload so a run has an ETA before ingest probes it
    (the pipeline then overwrites `video`)."""
    if duration_s:
        game["video"] = {**(game.get("video") or {}), "duration_s": round(duration_s, 3)}


def _waiting(game: dict) -> bool:
    """Queued, or a job no runner has picked up yet (the API reports a queued job as
    `processing` with every stage pending)."""
    stages = (game.get("stages") or {}).values()
    return game.get("status") == "queued" or (
        game.get("status") == "processing"
        and all(s == "pending" for s in stages)
        and not any((game.get("progress") or {}).values())
    )


def _cost(stage: str, duration: float) -> float:
    fixed, rate = COST.get(stage, DEFAULT_COST)
    return fixed + rate * duration


def eta(game: dict, duration: float, queue_s: float = 0.0) -> tuple[float, dict[str, float]]:
    """(seconds until the run ends, seconds until each stage is done), both estimates."""
    stages = game.get("stages") or {}
    progress = game.get("progress") or {}
    acc = queue_s if _waiting(game) else 0.0
    until: dict[str, float] = {}
    for name, state in stages.items():
        if state != "done":
            left = 1.0 - min(1.0, float(progress.get(name) or 0.0)) if state == "running" else 1.0
            acc += _cost(name, duration) * left
        until[name] = acc
        if name == "ingest":  # the storyboard runs right after ingest
            until["storyboard"] = acc + _cost("storyboard", duration)
    return acc + _cost("_finish", duration), until


def fields(game: dict, has: Has, worker_stages: tuple[str, ...] = (), cloud: bool = False) -> dict:
    """The readiness keys for GET /games/{id} and /games. `game` carries the merged
    status/stages/progress; `has(pattern)` says whether a game-relative glob matches."""
    status = game.get("status")
    stages = game.get("stages") or {}
    running = status in ("queued", "processing")
    out: dict = {
        # the earliest playable rendition: ingest's H.264 mezzanine, once ingest finished
        # (ffmpeg writes the file in place, so its mere presence is not enough)
        "watchable": has(M.WIDE_REL) and (status == "ready" or stages.get("ingest") == "done"),
    }
    duration = float((game.get("video") or {}).get("duration_s") or 0.0)
    total, until = eta(game, duration, QUEUE_S if cloud else 0.0) if running else (0.0, {})
    if running and duration > 0:
        out["eta_s"] = math.ceil(total)
    if _waiting(game):
        out["stage_label"] = "Waiting to start"
    elif status == "processing":
        now = next((n for n, s in stages.items() if s != "done"), None)
        out["stage_label"] = LABELS.get(now, "Finishing up") if now else "Finishing up"
    feats = {}
    for key, (pats, stage, optin) in FEATURES.items():
        if any(has(p) for p in pats):
            feats[key] = {"state": "ready"}
        elif running and (not optin or set(optin) & set(worker_stages)):
            f: dict = {"state": "pending"}
            if duration > 0 and not optin:
                f["eta_s"] = math.ceil(until.get(stage, total) if stage else total)
            feats[key] = f
        else:
            feats[key] = {"state": "unavailable"}
    out["features"] = feats
    return out
