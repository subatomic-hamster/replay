"""Highlight selection, play-window frame IO and the per-play replay manifest.

`replays/highlights.json` (replay.highlights.v1) is the fan-out list for the segment /
Tier A / Tier B / Tier C stages. `select` picks the plays where the story is, in order
(each entry's `why`):

1. `best`: the game's best play, by the API's rule (`best_play`): the user's pick, else
   the last make in the final `WINNER_S` of the video, else the top hype play;
2. `trigger`: every play the user asked for (the X sign, "clip that", a phone tap);
3. `event`: every `STORY` event (lost his man, a save, a forced out-of-bounds);
4. `fill`: the top hype plays, up to `auto_n` plays in all (one per `PER_PLAY_S`).

1-3 are kept up to `MAX_N`; a play mostly inside a chosen one is skipped. Fill plays are
`lite`: real-video angles only (no masks, Tier B or Player's views). `max_pov` caps a
play's Player's views (`POVS`). Windows are at most `MAX_S` long, ending shortly after
the key moment; the best play and a lost man get a long one (`LONG_MIN_S`-`LONG_MAX_S`,
a whole Player's view, ending `LONG_POST_S` after the make / the separation).
Every angle of one play is rendered over exactly that window, so the videos are
time-aligned and a TV cut keeps the playback position.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..gamedata import Game, _list, load_game, read_json
from ..hype import REL as HYPE_REL

HIGHLIGHTS_REL = "replays/highlights.json"
HIGHLIGHTS_SCHEMA = "replay.highlights.v1"
MANIFEST_SCHEMA = "replay.replay_manifest.v1"
MAX_S = 8.0
# the best play and a lost man get a whole stretch to watch in a player's view
LONG_MIN_S, LONG_MAX_S = 16.0, 20.0
LONG_POST_S = 2.0  # a long window ends this long after the make / the separation
EVENT_LEAD_S = 2.0  # a story event's window starts this long before it
WINNER_S = 30.0  # = replay_api.moments.WINNER_S: a last make this near the end
BEST_LEAD_S = 4.0  # = replay_api.moments.LEAD_S: the best play includes its build-up
EDITS_REL = "edits.json"  # = replay_api.edits.REL: the user's `best_play` pick
# titles as the API's moments say them (replay_api.moments.label)
STORY = {"lost_man": "Lost his man", "save": "Save", "forced_out": "Forced out"}
LONG_STORY = ("lost_man",)  # the defender's long view of the separation
MAX_LONG_EVENTS = 2  # more lost men than this get a short window
# Player's views per play by why it has angles (the key player's first); fill plays none
POVS = {"best": 2, "trigger": 1, "event": 1, "long_event": 2, "fill": 0}
MIN_S = 2.0
POST_S = 1.5  # kept after the key moment (the ball dropping, the celebration)
RELEASE_LEAD_S = 1.0  # a shot's release this long before the rim (courtcam ShotCfg)
# plays with angles: ~1.5 a minute of game (fill plays are real-video angles only, cheap)
PER_PLAY_S, MIN_N, MAX_N = 40.0, 3, 10
TIER_A = ("wide", "follow", "tight")
TIER_B = ("broadcast_high", "orbit", "push_in")
LABELS = {
    "wide": "Wide",
    "follow": "Follow",
    "tight": "Tight iso",
    "broadcast_high": "Broadcast high",
    "orbit": "Orbit",
    "push_in": "Push-in",
}


def _window(t_start: float, t_end: float, key: float, duration: float) -> tuple[float, float]:
    t1 = min(duration, max(t_end, key + POST_S) if key <= t_end else t_end)
    return round(max(t_start, t1 - MAX_S, 0.0), 3), round(t1, 3)


def _long(start: float, end: float, duration: float) -> tuple[float, float]:
    """A long window ending at `end`, reaching back to `start` (LONG_MIN_S-LONG_MAX_S)."""
    t1 = min(duration, end) if duration else end
    return round(max(0.0, t1 - float(np.clip(t1 - start, LONG_MIN_S, LONG_MAX_S))), 3), round(t1, 3)


def _primary(play: dict, events: dict[str, dict]) -> str | None:
    for role in ("shooter", "scorer", "attacker", "server", "blocker"):
        for p in play.get("participants") or []:
            if p.get("role") == role:
                return p["player_id"]
    for eid in play.get("event_ids") or []:
        if events.get(eid, {}).get("player_id"):
            return events[eid]["player_id"]
    parts = play.get("participants") or []
    return parts[0]["player_id"] if parts else None


def _shot(game: Game, evs: list[dict]) -> dict | None:
    shots = [e for e in evs if e.get("type") == "shot" and e.get("player_id")]
    if not shots or not game.rims:
        return None
    e = shots[-1]
    return {
        "event_id": e.get("id"),
        "player_id": e["player_id"],
        "t_release": round(float(e["t_key"]) - RELEASE_LEAD_S, 3),
        "t_rim": float(e["t_key"]),
        "made": e.get("made"),
    }


def player_name(names: dict[str, str | None], pid: str) -> str:
    """The name the TV shows everywhere: the user's (or enrolled) name, else "Player N"
    (the track number, not a jersey)."""
    return names.get(pid) or f"Player {pid.removeprefix('p')}"


def _names(game_or_doc) -> dict[str, str | None]:
    players = game_or_doc.players.values() if isinstance(game_or_doc, Game) else (
        game_or_doc.get("players") or [])  # fmt: skip
    return {p["id"]: p.get("name") for p in players}


def _label(kind: str, pid: str | None, shot: dict | None) -> tuple[str, str | None]:
    """A play's title as a template with `{player}` for the name (the API fills it in
    from the live roster, so a rename shows at once), and that player's id."""
    if shot:
        made = {True: " (make)", False: " (miss)"}.get(shot.get("made"), "")
        return f"Shot · {{player}}{made}", shot["player_id"]
    title = STORY.get(kind) or kind.replace("_", " ").capitalize()
    return (f"{title} · {{player}}", pid) if pid else (title, None)


def label_of(h: dict, names: dict[str, str | None]) -> str:
    tpl = h.get("label_template") or h.get("label") or ""
    pid = h.get("label_player")
    return tpl.format(player=player_name(names, pid)) if pid else tpl


def auto_n(duration: float) -> int:
    """How many plays get angles: one per PER_PLAY_S of game, at least 3, at most 10."""
    return int(np.clip(round(duration / PER_PLAY_S), MIN_N, MAX_N))


def _entry(game: Game, play_id: str, kind: str, window: tuple[float, float], pid: str | None,
           participants: list[str], shot: dict | None, why: str,
           povs: str | None = None) -> dict:  # fmt: skip
    tpl, who = _label(kind, pid, shot)
    h = {"play_id": play_id, "kind": kind, "t_start": window[0], "t_end": window[1],
         "primary": pid, "participants": participants, "shot": shot, "label_template": tpl,
         "label_player": who, "why": why, "lite": why == "fill",
         "max_pov": POVS[povs or why]}  # fmt: skip
    return {**h, "label": label_of(h, _names(game))}


def _from_play(game: Game, p: dict, by_id: dict, why: str,
               window: tuple[float, float] | None = None, ev: dict | None = None) -> dict:  # fmt: skip
    """A plays.json play: its own window (after its key moment) unless `window`; `ev`
    (the best play's make) is its key player and shot."""
    evs = [by_id[i] for i in p.get("event_ids") or [] if i in by_id]
    if window is None:
        key = max([float(e["t_key"]) for e in evs] or [float(p["t_end"])])
        window = _window(float(p["t_start"]), float(p["t_end"]), key, game.duration)
    parts = list(dict.fromkeys(q["player_id"] for q in p.get("participants") or []))
    pid = (ev or {}).get("player_id") or _primary(p, by_id)
    return _entry(game, p["id"], p.get("grammar") or "play", window, pid, parts,
                  _shot(game, [ev] if ev else evs), why)  # fmt: skip


def _makes(game: Game) -> list[dict]:
    """Made baskets (a made shot or a point) inside the video, in time order."""
    return sorted(
        (e for e in game.events if not e.get("dismissed") and e.get("t_key") is not None
         and (e.get("type") == "point" or (e.get("type") == "shot" and e.get("made") is True))
         and not (game.duration and float(e["t_key"]) > game.duration)),
        key=lambda e: (float(e["t_key"]), str(e.get("id"))),
    )  # fmt: skip


def best_play(game: Game) -> dict | None:
    """The game's best play by the API's rule (replay_api.moments.best_play): the user's
    pick (edits.json `best_play`), else the last make when it falls in the final
    WINNER_S of the video (the game winner), else the top hype candidate.
    {t, t_start, t_end, source, event}: `event` is its make or picked event, if any."""
    makes = _makes(game)

    def make_in(a: float, b: float) -> dict | None:
        return next((e for e in reversed(makes) if a <= float(e["t_key"]) <= b), None)

    user = (read_json(game.dir / EDITS_REL) or {}).get("best_play")
    if user:
        a, b = float(user["t_start"]), float(user["t_end"])
        ev = next((e for e in game.events if e.get("id") == user.get("moment_id")), None)
        return {"t": float(user["t"]), "t_start": a, "t_end": b, "source": "user",
                "event": ev or make_in(a, b)}  # fmt: skip
    if makes and game.duration and float(makes[-1]["t_key"]) >= game.duration - WINNER_S:
        e = makes[-1]
        t = float(e["t_key"])
        return {"t": t, "t_start": min(float(e.get("t_start", t)), t - BEST_LEAD_S),
                "t_end": float(e.get("t_end", t)), "source": "auto:last_make", "event": e}  # fmt: skip
    cands = (read_json(game.dir / HYPE_REL) or {}).get("candidates") or []
    if not cands:
        return None
    c = max(cands, key=lambda c: float(c.get("score") or 0.0))
    t = float(c["t"])
    a, b = float(c.get("t_start", t - 3.0)), float(c.get("t_end", t + 1.0))
    e = make_in(a, b)
    return {"t": float(e["t_key"]) if e else t, "t_start": a, "t_end": b, "source": "auto:hype",
            "event": e}  # fmt: skip


def _best(game: Game, by_id: dict) -> list[dict]:
    b = best_play(game)
    if b is None:
        return []
    ev = b["event"]
    window = _long(b["t_start"], b["t"] + LONG_POST_S, game.duration)
    p = next((p for p in game.plays if ev and ev.get("id") in (p.get("event_ids") or [])),
             None) or next((p for p in game.plays if p["t_start"] <= b["t"] <= p["t_end"]), None)  # fmt: skip
    if p:
        return [_from_play(game, p, by_id, "best", window, ev)]
    pid = (ev or {}).get("player_id")
    name = f"ev_{ev['id']}" if ev else f"best_{round(b['t'] * 10)}"
    return [_entry(game, name, (ev or {}).get("type") or "play", window, pid,
                   [pid] if pid else [], _shot(game, [ev] if ev else []), "best")]  # fmt: skip


def _triggered(game: Game, by_id: dict) -> list[dict]:
    """The plays the user asked for: a play with a trigger, a clip's play, else the clip."""
    clips = _list(read_json(game.dir / "clips.json"), "clips")
    want = {p["id"] for p in game.plays if p.get("trigger")} | {c.get("play_id") for c in clips}
    out = [_from_play(game, p, by_id, "trigger") for p in game.plays if p["id"] in want]
    for c in clips:
        if c.get("play_id") in {p["id"] for p in game.plays}:
            continue
        t1 = float(c["t_end"])
        pid = next(iter(c.get("participants") or []), None)
        out.append(_entry(game, f"clip_{c['id']}", "clip",
                          _window(float(c["t_start"]), t1, t1 - 1.0, game.duration), pid,
                          list(c.get("participants") or []), None, "trigger"))  # fmt: skip
    return out


def _story(game: Game) -> list[dict]:
    """Lost his man, saves, forced outs: the defender's (`player_id`) view; a lost man's
    window covers the whole separation."""
    out = []
    evs = [e for e in game.events
           if e.get("type") in STORY and not e.get("dismissed") and e.get("t_key") is not None]  # fmt: skip
    # a long view costs ~3 min of renders: the widest separations get one
    longs = sorted((e for e in evs if e["type"] in LONG_STORY),
                   key=lambda e: -float(e.get("max_sep_m") or 0.0))[:MAX_LONG_EVENTS]  # fmt: skip
    for e in sorted(evs, key=lambda e: float(e["t_key"])):
        kind = e["type"]
        t = float(e["t_key"])
        a, b = float(e.get("t_start", t)), float(e.get("t_end", t))
        long = any(e is x for x in longs)
        window = (_long(a - EVENT_LEAD_S, b + LONG_POST_S, game.duration) if long
                  else _window(a - EVENT_LEAD_S, b, t, game.duration))  # fmt: skip
        parts = [p for p in (e.get("player_id"), e.get("opponent_id")) if p]
        # its one-event play (grammar lost_man) keeps the replay's id = the play's
        pl = next((p for p in game.plays if p.get("grammar") == kind
                   and e["id"] in (p.get("event_ids") or [])), None)  # fmt: skip
        out.append(_entry(game, pl["id"] if pl else f"ev_{e['id']}", kind, window, e.get("player_id"), parts, None,
                          "event", "long_event" if long else None))  # fmt: skip
    return out


def _fill(game: Game, by_id: dict) -> list[dict]:
    """The top hype plays, best first; without hype.json the plays with a shot by
    confidence, else shots and rallies from the events."""
    plays = {p["id"]: p for p in game.plays}
    cands = (read_json(game.dir / HYPE_REL) or {}).get("candidates") or []
    shots = sorted((e for e in game.events if e.get("type") == "shot" and not e.get("dismissed")
                    and e.get("t_key") is not None), key=lambda e: float(e["t_key"]))  # fmt: skip
    if cands:
        out = []
        for c in sorted(cands, key=lambda c: -float(c.get("score") or 0.0)):
            if c.get("play_id") in plays:
                out.append(_from_play(game, plays[c["play_id"]], by_id, "fill"))
                continue
            t = float(c["t"])
            a, b = float(c.get("t_start", t - 6.0)), float(c.get("t_end", t + 2.0))
            # no play found: the last shot inside the window is its key moment
            e = next((e for e in reversed(shots) if a <= float(e["t_key"]) <= b), None)
            pid = (e or {}).get("player_id")
            w = _window(a, b, float(e["t_key"]) if e else t, game.duration)
            out.append(_entry(game, f"hype_{round(t * 10)}", "shot" if e else "play", w, pid,
                              [pid] if pid else [], _shot(game, [e] if e else []), "fill"))  # fmt: skip
        return out
    if game.plays:
        ranked = sorted(game.plays, key=lambda p: (
            not any(by_id.get(i, {}).get("type") == "shot" for i in p.get("event_ids") or []),
            -float(p.get("confidence") or 0.0), p["t_start"]))  # fmt: skip
        return [_from_play(game, p, by_id, "fill") for p in ranked]
    evs = [e for e in game.events if e.get("type") in ("shot", "rally", "point")]
    evs.sort(key=lambda e: (e["type"] != "shot", -(e["t_end"] - e["t_start"])))
    out = []
    for e in evs:
        w = _window(float(e["t_start"]) - 4.0, float(e["t_end"]), float(e["t_key"]),
                    game.duration)  # fmt: skip
        pid = e.get("player_id")
        out.append(_entry(game, f"ev_{e['id']}", e["type"], w, pid, [pid] if pid else [],
                          _shot(game, [e]), "fill"))  # fmt: skip
    return out


def _overlap(a: dict, b: dict) -> float:
    inter = min(a["t_end"], b["t_end"]) - max(a["t_start"], b["t_start"])
    return max(0.0, inter) / max(1e-6, min(a["t_end"] - a["t_start"], b["t_end"] - b["t_start"]))


def select(game: Game, n: int = 3) -> tuple[list[dict], str]:
    """The plays with angles, in time order, and where they came from (`plays` |
    `events`): the best play, the user's, the story events (up to `MAX_N`), then the top
    hype plays while there are fewer than `n`. A play mostly inside a chosen one (more
    than half of the shorter) is skipped: its moment already has angles."""
    by_id = {e.get("id"): e for e in game.events}
    out: list[dict] = []
    for h in _best(game, by_id) + _triggered(game, by_id) + _story(game) + _fill(game, by_id):
        if len(out) >= (n if h["why"] == "fill" else MAX_N) or h["t_end"] - h["t_start"] < MIN_S:
            continue
        if any(h["play_id"] == c["play_id"] or _overlap(h, c) > 0.5 for c in out):
            continue
        out.append(h)
    return sorted(out, key=lambda h: h["t_start"]), "plays" if game.plays else "events"


def _present(game: Game, pid: str, t0: float, t1: float) -> float:
    i = game.tracks.index(pid)
    if i is None:
        return 0.0
    m = (game.tracks.t >= t0) & (game.tracks.t <= t1)
    return float(np.isfinite(game.tracks.box[i, m, 0]).mean()) if m.any() else 0.0


def write_highlights(game_dir: Path, *, n: int | None = None, synthetic: bool = False) -> dict:
    """`n` plays, else `auto_n` of the game's length."""
    game = load_game(game_dir)
    plays, source = select(game, n or auto_n(game.duration))
    for h in plays:
        # Tier A's player angles need a player who is actually tracked in the window
        if not h["primary"] or _present(game, h["primary"], h["t_start"], h["t_end"]) < 0.5:
            best = max(game.tracks.ids, key=lambda p: _present(game, p, h["t_start"], h["t_end"]),
                       default=None)  # fmt: skip
            h["primary"] = best
    doc = {
        "schema": HIGHLIGHTS_SCHEMA,
        "source": source,
        "synthetic": synthetic,
        "sport": game.sport,
        "fps": game.fps,
        "plays": plays,
    }
    path = Path(game_dir) / HIGHLIGHTS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


def read_highlights(game_dir: Path) -> dict:
    path = Path(game_dir) / HIGHLIGHTS_REL
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"plays": []}


def play(game_dir: Path, play_id: str) -> dict:
    for h in read_highlights(game_dir)["plays"]:
        if h["play_id"] == play_id:
            return h
    raise KeyError(f"{play_id} is not in {HIGHLIGHTS_REL}")


def angle_files(h: dict) -> list[tuple[str, str, str]]:
    """(file stem, angle id, tier) per angle of a highlight, in cut order."""
    out = [("wide", "wide", "A")]
    if h.get("primary"):
        pid = h["primary"]
        out += [(f"follow_{pid}", f"follow:{pid}", "A"), (f"tight_{pid}", f"tight:{pid}", "A")]
    return out + ([] if h.get("lite") else [(a, a, "B") for a in TIER_B])


def frame_count(h: dict, fps: float) -> int:
    return round((h["t_end"] - h["t_start"]) * fps)


def read_window(video: Path, t0: float, n: int) -> Iterator[tuple[int, np.ndarray]]:
    """(source frame index, BGR) for `n` frames from `t0` (sequential after one seek)."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    start = round(t0 * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    last = None
    try:
        for i in range(n):
            ok, frame = cap.read()
            if ok:
                last = frame
            if last is None:
                return
            yield start + i, last  # a short read holds the last frame: lengths stay equal
    finally:
        cap.release()


def probe_video(path: Path) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(path))
    out = {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": cap.get(cv2.CAP_PROP_FPS) or 30.0,
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
    }
    cap.release()
    out["duration_s"] = round(out["frames"] / out["fps"], 3) if out["fps"] else 0.0
    return out


def poster(game_dir: Path, rel: str, width: int = 480) -> str | None:
    """`<angle>.jpg` beside an angle video: its middle frame, so each tile in the TV's
    angle row shows its own view. Rewritten when the video is newer. Game-relative."""
    video = Path(game_dir) / rel
    out = video.with_suffix(".jpg")
    if out.is_file() and out.stat().st_mtime_ns >= video.stat().st_mtime_ns:
        return Path(rel).with_suffix(".jpg").as_posix()
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) // 2))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    h, w = frame.shape[:2]
    if w > width:
        frame = cv2.resize(
            frame, (width, round(h * width / w / 2) * 2), interpolation=cv2.INTER_AREA
        )
    cv2.imwrite(str(out), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Path(rel).with_suffix(".jpg").as_posix()


def write_manifest(game_dir: Path, play_id: str, sport: str | None = None) -> dict:
    """`replays/{play_id}/manifest.json` from the angle videos that exist on disk.
    URLs are game-relative; the API resolves them."""
    gd = Path(game_dir)
    doc = read_highlights(gd)
    h = play(gd, play_id)
    game = json.loads((gd / "game.json").read_text()) if (gd / "game.json").exists() else {}
    names = _names(game)
    angles = []
    for stem, aid, tier in angle_files(h):
        rel = f"replays/{play_id}/{stem}.mp4"
        if not (gd / rel).is_file():
            continue
        info = probe_video(gd / rel)
        kind, _, pid = aid.partition(":")
        label = LABELS.get(kind, kind)
        angles.append(
            {
                "id": aid,
                "tier": tier,
                # `player_id`: the API re-labels from the live roster (renames show at once)
                "label": f"{label} · {player_name(names, pid)}" if pid else label,
                **({"player_id": pid} if pid else {}),
                "url": rel,
                "poster": poster(gd, rel),
                "duration_s": info["duration_s"],
                "width": info["width"],
                "height": info["height"],
            }
        )
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "play_id": play_id,
        "label": label_of(h, names),
        "label_template": h.get("label_template"),
        "label_player": h.get("label_player"),
        "sport": sport or doc.get("sport"),
        "t_start": h["t_start"],
        "t_end": h["t_end"],
        "source": doc.get("source"),
        "synthetic": bool(doc.get("synthetic")),
        "angles": angles,
        "commentary": None,
    }
    path = gd / "replays" / play_id / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest
