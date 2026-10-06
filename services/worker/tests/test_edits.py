"""D-61: user corrections (the API's edits.json) survive a worker re-run and reach the
stages downstream of the corrected file (toy stages, no courtcam)."""

from __future__ import annotations

import json

from replay_api import edits
from replay_worker import Cache, Stage, run

CALLS: list[str] = []
EVENTS = [
    {"id": "e_0001", "type": "shot", "t_start": 1.0, "t_key": 2.0, "t_end": 3.0, "made": None},
    {"id": "e_0002", "type": "shot", "t_start": 5.0, "t_key": 6.0, "t_end": 7.0, "made": None},
]


def _events(ctx, item):
    CALLS.append("events")
    evs = EVENTS[1:] if ctx.cfg.get("drop_first") else EVENTS  # a recompute renumbers ids
    evs = [{**e, "id": f"e_{i + 1:04d}"} for i, e in enumerate(evs)]
    doc = {"schema": "replay.events.v1", "events": evs}
    (ctx.game_dir / "events.json").write_text(json.dumps(doc))


def _made(ctx, item):
    CALLS.append("made")
    evs = json.loads((ctx.game_dir / "events.json").read_text())["events"]
    (ctx.game_dir / "made.json").write_text(json.dumps({e["t_key"]: e["made"] for e in evs}))


REG = {
    "events": Stage("events", "1", _events, outputs=("events.json",), params=("drop_first",)),
    "made": Stage("made", "1", _made, inputs=("events.json",), outputs=("made.json",),
                  after=("events",)),
}  # fmt: skip


def _go(gd, cache, **cfg):
    CALLS.clear()
    recs = run(gd, cfg, registry=REG, cache=cache)
    return {r["stage"]: r["cache"] for r in recs}


def _made_by_t(gd):
    return json.loads((gd / "made.json").read_text())


def test_user_edit_survives_rerun_and_rekeys_downstream(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    gd, cache = tmp_path / "game", Cache(tmp_path / "cache")
    assert _go(gd, cache) == {"events": "miss", "made": "miss"}

    # what PATCH /games/{id}/events/e_0002 {"made": true} does
    edits.patch(gd, "events.json", "e_0002", {"made": True, "confirmed": True, "source": "user"},
                anchor={"type": "shot", "t_key": 6.0})  # fmt: skip
    edits.apply(gd, ["events.json"])

    # re-run: events is a cache hit (restored), yet the correction is still there, and the
    # downstream stage is re-keyed by the corrected file and sees it
    assert _go(gd, cache) == {"events": "hit", "made": "miss"}
    ev = json.loads((gd / "events.json").read_text())["events"]
    assert ev[1]["made"] is True and ev[1]["source"] == "user" and ev[0]["made"] is None
    assert _made_by_t(gd) == {"2.0": None, "6.0": True}
    # the cache entry itself stays the pipeline's own output
    assert _go(gd, cache) == {"events": "hit", "made": "hit"}
    assert _made_by_t(gd) == {"2.0": None, "6.0": True}

    # a recompute that renumbers events: the edit follows its anchor, not the stale id
    assert _go(gd, cache, drop_first=True) == {"events": "miss", "made": "miss"}
    ev = json.loads((gd / "events.json").read_text())["events"]
    assert [(e["id"], e["t_key"], e["made"]) for e in ev] == [("e_0001", 6.0, True)]
