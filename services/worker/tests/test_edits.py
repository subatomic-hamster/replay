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


def _identity(ctx, item):
    CALLS.append("identity")
    work = ctx.game_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)
    row = {"player_id": "p1", "team": 0, "color_hex": "#111111", "team_source": "matchups"}
    (work / "players.json").write_text(json.dumps({"players": [row]}))


def _side(ctx, item):
    CALLS.append("side")
    p1 = json.loads((ctx.game_dir / "_work/players.json").read_text())["players"][0]
    (ctx.game_dir / "side.json").write_text(json.dumps(p1["team"]))


def test_team_pick_reaches_restored_players_json(tmp_path, monkeypatch):
    """A team picked on the phone is copied onto identity's players.json whether it was
    computed or restored from the cache, so the stages keyed on it (events) re-key."""
    import pytest

    pytest.importorskip("courtcam")
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    reg = {
        "identity": Stage("identity", "1", _identity, outputs=("_work/players.json",)),
        "side": Stage("side", "1", _side, inputs=("_work/players.json",),
                      outputs=("side.json",), after=("identity",)),
    }  # fmt: skip
    gd, cache = tmp_path / "game", Cache(tmp_path / "cache")
    run(gd, {}, registry=reg, cache=cache)
    assert json.loads((gd / "side.json").read_text()) == 0

    edits.patch(gd, "game.json", "p1", {"team": 1, "color_hex": "#EEEEEE"})
    recs = {r["stage"]: r["cache"] for r in run(gd, {}, registry=reg, cache=cache)}
    assert recs == {"identity": "hit", "side": "miss"}
    p1 = json.loads((gd / "_work/players.json").read_text())["players"][0]
    assert (p1["team"], p1["team_source"], p1["color_hex"]) == (1, "user", "#EEEEEE")
    assert json.loads((gd / "side.json").read_text()) == 1
