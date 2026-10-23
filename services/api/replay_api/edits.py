"""User corrections as an overlay that survives worker re-runs (D-61).

The pipeline owns game.json, tracks/, crops/, events.json, triggers.json, plays.json,
clips.json and score.json: `python -m replay_worker run` restores them from its cache (or
recomputes them), which used to drop every correction the API had written into them.
Now each correction is recorded in `edits.json` (never a stage output) and then applied
to those files (write-through, so every reader, `/media` included, sees it). The worker
re-applies the overlay to each of those files right after it restores or recomputes it
(`replay_worker.dag`), so corrections survive any re-run and downstream stages hash and
read the corrected files (a corrected `made` re-keys plays, highlights, Tier C...). The
cache itself keeps the uncorrected outputs.

    {"schema": "replay.edits.v1",
     "patch":   {"events.json": {"e_0003": {"made": true, "confirmed": true}},
                 "game.json": {"p2": {"name": "Ana", "tagged": true}}, ...},
     "anchors": {"events.json": {"e_0003": {"type": "shot", "t_key": 12.4}}},
     "add":     {"events.json": [bookmark], "triggers.json": [tap], "clips.json": [clip]},
     "merges":  {"p7": "p3"},
     "score":   [{"t", "scores", "event_id", "source": "user"}]}

`patch` is keyed by record id (player id for game.json, where a null value removes the
key: a profile unlink). courtcam numbers events in time order, so a recompute can move
an id onto another event: an event patch therefore follows its anchor (the event as it
was first edited) to an event of the same type within ANCHOR_S, and is skipped when
nothing matches. Applying is idempotent.
"""

from __future__ import annotations

import copy
import json
import threading
from collections.abc import Callable, Iterable
from pathlib import Path

REL = "edits.json"
SCHEMA = "replay.edits.v1"
LISTS = {
    "events.json": ("replay.events.v1", "events"),
    "triggers.json": ("replay.triggers.v1", "triggers"),
    "plays.json": ("replay.plays.v1", "plays"),
    "clips.json": ("replay.clips.v1", "clips"),
}
# application order: events before score (the score is recomputed from the events)
FILES = ("game.json", "tracks", "crops", *LISTS, "score.json")
ANCHOR_S = 1.0

# ponytail: one lock for every game's edits.json; the API is one process with a small
# threadpool, so contention is nil. Per-game locks if that ever changes.
_lock = threading.Lock()


def load(game_dir: Path) -> dict:
    p = Path(game_dir) / REL
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _write(path: Path, data: dict, indent: int | None = 1) -> None:
    """tmp + rename: never rewrites a file in place (the worker cache hard-links media)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent), encoding="utf-8")
    tmp.replace(path)


def record(game_dir: Path, change: Callable[[dict], None]) -> dict:
    """Read-modify-write edits.json; returns the new overlay."""
    with _lock:
        ov = load(game_dir)
        change(ov)
        ov["schema"] = SCHEMA
        Path(game_dir).mkdir(parents=True, exist_ok=True)
        _write(Path(game_dir) / REL, ov)
        return ov


def patch(game_dir: Path, rel: str, rid: str, fields: dict, anchor: dict | None = None) -> dict:
    def change(ov: dict) -> None:
        ov.setdefault("patch", {}).setdefault(rel, {}).setdefault(rid, {}).update(fields)
        if anchor is not None:  # the first edit's view of the record wins
            ov.setdefault("anchors", {}).setdefault(rel, {}).setdefault(rid, anchor)

    return record(game_dir, change)


def add(game_dir: Path, rel: str, item: dict) -> dict:
    return record(game_dir, lambda ov: ov.setdefault("add", {}).setdefault(rel, []).append(item))


def merge(game_dir: Path, src: str, dst: str) -> dict:
    return record(game_dir, lambda ov: ov.setdefault("merges", {}).update({src: dst}))


# --------------------------------------------------------------------------- apply


def apply(game_dir: Path, rels: Iterable[str] = FILES) -> None:
    """Re-apply the overlay to those of `rels` it covers (other paths are ignored)."""
    gd = Path(game_dir)
    wanted = set(rels)
    todo = [r for r in FILES if r in wanted]
    if not todo:
        return
    ov = load(gd)
    if not ov:
        return
    for rel in todo:
        if rel == "game.json":
            _apply_game_file(gd, ov)
        elif rel == "tracks":
            _apply_tracks(gd, ov.get("merges") or {})
        elif rel == "crops":
            for src in ov.get("merges") or {}:
                (gd / "crops" / f"{src}.json").unlink(missing_ok=True)
        elif rel == "score.json":
            _apply_score(gd, ov)
        else:
            _apply_list(gd, ov, rel)


def apply_game(game: dict, ov: dict) -> dict:
    """The roster side of the overlay on a game.json dict: names / tags / profile links,
    merged-away players removed with their follow-cam renditions."""
    merges = ov.get("merges") or {}
    patches = (ov.get("patch") or {}).get("game.json") or {}
    if not merges and not patches:
        return game
    players = [p for p in game.get("players") or [] if p.get("id") not in merges]
    for p in players:
        for k, v in (patches.get(p.get("id")) or {}).items():
            if v is None:
                p.pop(k, None)
            else:
                p[k] = v
    game["players"] = players
    for src in merges:
        ((game.get("renditions") or {}).get("players") or {}).pop(src, None)
    return game


def final_id(pid: str | None, merges: dict) -> str | None:
    """Where a player id ends up after a chain of merges (a -> b, b -> c)."""
    seen: set[str] = set()
    while pid in merges and pid not in seen:
        seen.add(pid)
        pid = merges[pid]
    return pid


def _apply_game_file(gd: Path, ov: dict) -> None:
    path = gd / "game.json"
    if not path.is_file():
        return
    game = json.loads(path.read_text(encoding="utf-8"))
    before = json.dumps(game)
    if json.dumps(apply_game(game, ov)) != before:
        _write(path, game)


def _apply_tracks(gd: Path, merges: dict) -> None:
    """Rewrite merged ids in every chunk; a frame that now holds two boxes for one player
    keeps the more confident one."""
    if not merges:
        return
    for chunk in sorted((gd / "tracks").glob("*.json")):
        data = json.loads(chunk.read_text(encoding="utf-8"))
        changed = False
        for frame in data.get("frames", []):
            entries = frame.get("p", [])
            if not any(e.get("id") in merges for e in entries):
                continue
            changed = True
            keep: dict = {}
            for entry in entries:
                entry["id"] = final_id(entry.get("id"), merges)
                prev = keep.get(entry["id"])
                if prev is None or (entry.get("c") or 0) > (prev.get("c") or 0):
                    keep[entry["id"]] = entry
            frame["p"] = list(keep.values())
        if changed:
            _write(chunk, data, indent=None)


def _near(rec: dict, anchor: dict) -> bool:
    return (
        rec.get("type") == anchor.get("type")
        and abs(float(rec.get("t_key") or 0.0) - float(anchor.get("t_key") or 0.0)) <= ANCHOR_S
    )


def _target(items: list[dict], rid: str, fields: dict, anchor: dict | None) -> dict | None:
    hit = next((r for r in items if r.get("id") == rid), None)
    if anchor is None:
        return hit
    if hit is not None and (_near(hit, anchor) or all(hit.get(k) == v for k, v in fields.items())):
        return hit
    near = [r for r in items if _near(r, anchor)]
    return min(
        near, key=lambda r: abs(float(r.get("t_key") or 0.0) - anchor["t_key"]), default=None
    )


def _apply_list(gd: Path, ov: dict, rel: str) -> None:
    schema, key = LISTS[rel]
    patches = (ov.get("patch") or {}).get(rel) or {}
    adds = (ov.get("add") or {}).get(rel) or []
    merges = (ov.get("merges") or {}) if rel == "events.json" else {}
    path = gd / rel
    if not (patches or adds or merges) or not (path.is_file() or adds):
        return
    doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"schema": schema}
    items = doc.setdefault(key, [])
    before = json.dumps(items)
    ids = {r.get("id") for r in items}
    items.extend(copy.deepcopy(a) for a in adds if a.get("id") not in ids)
    anchors = (ov.get("anchors") or {}).get(rel) or {}
    for rid, fields in patches.items():
        target = _target(items, rid, fields, anchors.get(rid))
        if target is not None:
            target.update(copy.deepcopy(fields))
    for e in items:
        if e.get("player_id") in merges:
            e["player_id"] = final_id(e["player_id"], merges)
    if rel == "triggers.json":
        items.sort(key=lambda t: t.get("t") or 0.0)
    if json.dumps(items) != before:
        _write(path, doc)


def _apply_score(gd: Path, ov: dict) -> None:
    """score.json = the running score over the live (corrected, undismissed) events plus
    the user's own score entries, baskets counted for the side the user put the shooter
    on: what `GET /games/{id}/score` answers."""
    from .pipeline_adapter import score_timeline, user_teams, with_scoring

    user, teams = ov.get("score") or [], user_teams(ov)
    events_edited = bool((ov.get("patch") or {}).get("events.json"))
    path = gd / "score.json"
    if not (user or ((events_edited or teams or ov.get("scoring")) and path.is_file())):
        return

    ev_path = gd / "events.json"
    events = (
        json.loads(ev_path.read_text(encoding="utf-8")).get("events", [])
        if ev_path.is_file()
        else []
    )
    game_p = gd / "game.json"
    sport = (
        json.loads(game_p.read_text(encoding="utf-8")).get("sport") if game_p.is_file() else None
    )
    doc = {"schema": "replay.score.v1",
           "score": score_timeline(with_scoring([e for e in events if not e.get("dismissed")], ov),
                                   user, sport, teams)}  # fmt: skip
    if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != doc:
        _write(path, doc)
