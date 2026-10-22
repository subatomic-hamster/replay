"""Cross-game views of one profile, read from its linked games' JSON (nothing stored).

- `load_links` resolves `[{game_id, player_id}]` to game docs (a deleted game or a player
  merged away is reported as missing, not an error)
- `stats_by_sport` sums each linked player's numbers per sport and overlays the user's
  corrections (user values win; every corrected stat is listed in `edited` with its auto
  value kept alongside). Numbers come from what the pipeline already computes: the box
  score row (`stats.compute`: points, makes, threes, rebounds, steals, blocks, distance)
  and the events / plays (2-pt split, rallies, rallies won, contacts, serves). Shooting
  keys appear only for games with shot events, rally keys only for games with rallies,
  so nothing branches on the sport name.
- `moments` / `reel`: the player's plays across games with hype and points, ordered.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .. import pipeline_adapter as adapter
from .. import stats as stats_mod
from ..narrate import commentary as C

REEL_SCHEMA = "replay.reel.v1"
SHOT_KEYS = ("points", "shots_made", "shots_attempted", "twos_made", "twos_attempted",
             "threes_made", "threes_attempted", "rebounds", "steals", "blocks")  # fmt: skip
RALLY_KEYS = ("rallies", "rallies_won", "contacts", "serves")


@dataclass
class Linked:
    game_id: str
    player_id: str
    dir: Path
    game: dict
    events: list[dict]
    plays: list[dict]
    score: list[dict]

    @property
    def sport(self) -> str:
        return self.game.get("sport") or "unknown"

    @property
    def team(self):
        return next((p.get("team") for p in self.game["players"] if p["id"] == self.player_id),
                    None)  # fmt: skip


def frames(game_dir: Path) -> Iterator[dict]:
    for chunk in sorted((Path(game_dir) / "tracks").glob("*.json")):
        try:
            yield from json.loads(chunk.read_text()).get("frames", [])
        except (OSError, ValueError):
            continue


def _order(lk: Linked) -> tuple:
    return (lk.game.get("recorded_at") or "", lk.game_id, lk.player_id)


# what a linked game is read for: its docs (load_docs), tracks (box score, the card's
# frame box), hype.json, clips.json and media/ (the card's frame)
LINKED_RELS = ("game.json", "events.json", "plays.json", "score.json", "tracks",
               "hype.json", "clips.json", "media")  # fmt: skip


def load_links(
    links: list[dict], game_dir: Callable[[str], Path]
) -> tuple[list[Linked], list[dict]]:
    """(resolved links in game order, missing links with a reason)."""
    ok, missing = [], []
    for ln in links:
        gd = game_dir(ln["game_id"])
        if not (gd / "game.json").is_file():
            missing.append({**ln, "missing": "game"})
            continue
        game, events, plays, score = C.load_docs(gd)
        if ln["player_id"] not in {p["id"] for p in game.get("players") or []}:
            missing.append({**ln, "missing": "player"})  # e.g. merged into another id
            continue
        ok.append(Linked(ln["game_id"], ln["player_id"], gd, game, events, plays, score))
    return sorted(ok, key=_order), missing


def player_plays(lk: Linked) -> list[dict]:
    """The plays this player took part in (participant, or actor of one of its events)."""
    by_id = {e["id"]: e for e in lk.events}
    pid = lk.player_id
    return [
        p for p in C.game_plays(lk.plays, lk.events)
        if any(q.get("player_id") == pid for q in p.get("participants") or [])
        or any(by_id.get(i, {}).get("player_id") == pid for i in p.get("event_ids") or [])
    ]  # fmt: skip


def game_stats(lk: Linked) -> dict:
    """One linked player's numbers in one game."""
    pid, evs = lk.player_id, lk.events
    profile = adapter.get_profile(lk.sport, (lk.game.get("court") or {}).get("variant"))
    box = stats_mod.compute(lk.game, evs, frames(lk.dir), profile)["box_score"]
    row = next(r for r in box if r["player_id"] == pid)
    out = {"games": 1, "plays": len(player_plays(lk)), "distance_m": row["distance_m"]}

    def mine(typ: str) -> list[dict]:
        return [e for e in evs if e.get("type") == typ and e.get("player_id") == pid]

    if any(e.get("type") == "shot" for e in evs):
        shots = mine("shot")
        two = [s for s in shots if s.get("points") in (2, None)]  # stats.py: no value = 2
        three = [s for s in shots if s.get("points") == 3]
        out.update(
            points=row["points"],
            shots_made=row["makes"],
            shots_attempted=row["attempts"],
            twos_made=sum(1 for s in two if s.get("made") is True),
            twos_attempted=len(two),
            threes_made=row["threes"],
            threes_attempted=len(three),
            rebounds=row["rebounds"],
            steals=row["steals"],
            blocks=row["blocks"],
        )
    if any(e.get("type") == "rally" for e in evs):
        played = rallies_played(lk)
        out.update(rallies=len(played), contacts=len(mine("contact")), serves=len(mine("serve")))
        if any(e.get("winner_side") is not None for e in played):  # else unknown, not 0
            out["rallies_won"] = sum(1 for e in played if e.get("winner_side") == lk.team)
    return out


def rallies_played(lk: Linked) -> list[dict]:
    """Rally events overlapping the player's plays. A rally play lists its serve, contacts
    and point, not the rally event itself, so they are joined on time."""
    spans = [(p["t_start"], p["t_end"]) for p in player_plays(lk)]
    return [
        e for e in lk.events
        if e.get("type") == "rally"
        and any(e["t_start"] < b and e["t_end"] > a for a, b in spans)
    ]  # fmt: skip


def stats_by_sport(linked: list[Linked], stats_user: dict) -> dict:
    """`{sport: {stats, auto, edited, games}}`: `stats` is what to show (user values win),
    `auto` the pipeline's sums, `edited` the stats a user corrected."""
    out: dict[str, dict] = {}
    for lk in linked:
        s = out.setdefault(lk.sport, {"auto": {}, "games": []})
        g = game_stats(lk)
        s["games"].append({"game_id": lk.game_id, "player_id": lk.player_id, **g})
        for k, v in g.items():
            total = s["auto"].get(k, 0) + v
            s["auto"][k] = round(total, 1) if k == "distance_m" else total
    for sport in stats_user or {}:  # a correction for a sport with no linked game yet
        out.setdefault(sport, {"auto": {}, "games": []})
    for sport, s in out.items():
        user = (stats_user or {}).get(sport, {})
        s["stats"] = {**s["auto"], **user}
        s["edited"] = sorted(user)
        s["label"] = "auto-detected"
    return {k: out[k] for k in sorted(out)}


def edited_fields(doc: dict) -> list[str]:
    fields = {f for f in doc.get("user_edited_fields") or [] if not f.startswith("stats_by_sport.")}
    for sport, vals in (doc.get("stats_user") or {}).items():
        fields.update(f"stats_by_sport.{sport}.{k}" for k in vals)
    return sorted(fields)


def _hype(lk: Linked, play: dict) -> float:
    p = lk.dir / "hype.json"
    if not p.is_file():
        return 0.0
    doc = json.loads(p.read_text(encoding="utf-8"))
    cands = [c["score"] for c in doc.get("candidates") or [] if c.get("play_id") == play["id"]]
    if cands:
        return float(max(cands))
    rate, vals = float(doc.get("rate_hz") or 2.0), doc.get("values") or []
    a, b = int(play["t_start"] * rate), int(play["t_end"] * rate) + 1
    return float(max(vals[a:b], default=0.0))


def moments(linked: list[Linked]) -> list[dict]:
    """Every play of the player across the linked games, in game order."""
    out = []
    for gi, lk in enumerate(linked):
        by_id = {e["id"]: e for e in lk.events}
        clips = C._read(lk.dir / "clips.json", "clips")
        for p in sorted(player_plays(lk), key=lambda p: (p["t_start"], p["id"])):
            evs = [by_id[i] for i in p.get("event_ids") or [] if i in by_id]
            mine = [e for e in evs if e.get("player_id") == lk.player_id]
            shots = [e for e in mine if e.get("type") == "shot"]
            key = (shots or mine or [None])[0]
            t = key.get("t_key") if key else None
            out.append({
                "game_id": lk.game_id,
                "player_id": lk.player_id,
                "play_id": p["id"],
                "sport": lk.sport,
                "t_start": p["t_start"],
                "t_end": p["t_end"],
                "t": round(float(t if t is not None else (p["t_start"] + p["t_end"]) / 2), 2),
                "points": sum(int(e.get("points") or 2) for e in shots if e.get("made") is True),
                "hype": round(_hype(lk, p), 3),
                "event_ids": [e["id"] for e in mine],
                "clip_ids": [c["id"] for c in clips if c.get("play_id") == p["id"]],
                "game_index": gi,
            })  # fmt: skip
    return out


def best_moment(ms: list[dict]) -> dict | None:
    """Top play by hype, then points; ties go to the earlier game and time."""
    return min(ms, key=lambda m: (-m["hype"], -m["points"], m["game_index"], m["t_start"]),
               default=None)  # fmt: skip


def reel(profile_id: str, linked: list[Linked], ms: list[dict]) -> dict:
    """Career reel manifest: the player's plays across games, oldest game first. Each item
    points into the game's wide rendition (`media_rel` + t_start/t_end)."""
    games = {lk.game_id: lk.game for lk in linked}
    items = [
        {**{k: v for k, v in m.items() if k != "game_index"},
         "game_title": games[m["game_id"]].get("title"),
         "media_rel": (games[m["game_id"]].get("renditions") or {}).get("wide")}
        for m in ms
    ]  # fmt: skip
    return {"schema": REEL_SCHEMA, "profile_id": profile_id, "items": items,
            "duration_s": round(sum(i["t_end"] - i["t_start"] for i in items), 2)}  # fmt: skip


def frame_box(game_dir: Path, player_id: str, t: float) -> list[float] | None:
    """The player's normalised [x, y, w, h] in the track frame nearest t (≤ 0.5 s away)."""
    best = None
    for f in frames(game_dir):
        dt = abs(float(f.get("t") or 0.0) - t)
        if dt > 0.5 or (best and dt >= best[0]):
            continue
        hit = next((p["bb"] for p in f.get("p", []) if p.get("id") == player_id), None)
        if hit:
            best = (dt, hit)
    return best[1] if best else None
