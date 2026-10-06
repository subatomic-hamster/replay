"""Highlight selection, play-window frame IO and the per-play replay manifest.

`replays/highlights.json` (replay.highlights.v1) is the fan-out list for the segment /
Tier A / Tier B stages: the best few plays from `plays.json` (triggered ones first,
then plays with a shot, then confidence), else shots and rallies from `events.json`.
Each window is at most `MAX_S` long, ending shortly after the play's key moment.
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

from ..gamedata import Game, load_game

HIGHLIGHTS_REL = "replays/highlights.json"
HIGHLIGHTS_SCHEMA = "replay.highlights.v1"
MANIFEST_SCHEMA = "replay.replay_manifest.v1"
MAX_S = 8.0
MIN_S = 2.0
POST_S = 1.5  # kept after the key moment (the ball dropping, the celebration)
RELEASE_LEAD_S = 1.0  # a shot's release this long before the rim (courtcam ShotCfg)
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
    t0 = max(t_start, t1 - MAX_S, 0.0)
    return round(t0, 3), round(t1, 3)


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


def _label(game: Game, kind: str, pid: str | None, shot: dict | None) -> str:
    who = game.player_label(pid) if pid else ""
    if shot:
        made = {True: " (make)", False: " (miss)"}.get(shot.get("made"), "")
        return f"Shot · {game.player_label(shot['player_id'])}{made}"
    return f"{kind.replace('_', ' ').capitalize()}" + (f" · {who}" if who else "")


def select(game: Game, n: int = 3) -> tuple[list[dict], str]:
    """Up to `n` highlight windows and where they came from (`plays` | `events`)."""
    by_id = {e.get("id"): e for e in game.events}
    out: list[dict] = []
    if game.plays:
        ranked = sorted(
            game.plays,
            key=lambda p: (
                p.get("trigger") is None,
                not any(by_id.get(i, {}).get("type") == "shot" for i in p.get("event_ids") or []),
                -float(p.get("confidence") or 0.0),
                p["t_start"],
            ),
        )
        for p in ranked:
            evs = [by_id[i] for i in p.get("event_ids") or [] if i in by_id]
            key = max([float(e["t_key"]) for e in evs] or [float(p["t_end"])])
            t0, t1 = _window(float(p["t_start"]), float(p["t_end"]), key, game.duration)
            if t1 - t0 < MIN_S:
                continue
            shot = _shot(game, evs)
            pid = _primary(p, by_id)
            out.append(
                {
                    "play_id": p["id"],
                    "kind": p.get("grammar") or "play",
                    "t_start": t0,
                    "t_end": t1,
                    "primary": pid,
                    "participants": list(
                        dict.fromkeys(q["player_id"] for q in p.get("participants") or [])
                    ),
                    "shot": shot,
                    "label": _label(game, p.get("grammar") or "play", pid, shot),
                }
            )
            if len(out) == n:
                break
        if out:
            return sorted(out, key=lambda h: h["t_start"]), "plays"
    cands = [e for e in game.events if e.get("type") in ("shot", "rally", "point")]
    cands.sort(key=lambda e: (e["type"] != "shot", -(e["t_end"] - e["t_start"])))
    for e in cands:
        t0, t1 = _window(
            float(e["t_start"]) - 4.0, float(e["t_end"]), float(e["t_key"]), game.duration
        )
        if t1 - t0 < MIN_S or any(t0 < h["t_end"] and h["t_start"] < t1 for h in out):
            continue
        shot = _shot(game, [e])
        out.append(
            {
                "play_id": f"ev_{e['id']}",
                "kind": e["type"],
                "t_start": t0,
                "t_end": t1,
                "primary": e.get("player_id"),
                "participants": [e["player_id"]] if e.get("player_id") else [],
                "shot": shot,
                "label": _label(game, e["type"], e.get("player_id"), shot),
            }
        )
        if len(out) == n:
            break
    return sorted(out, key=lambda h: h["t_start"]), "events"


def _present(game: Game, pid: str, t0: float, t1: float) -> float:
    i = game.tracks.index(pid)
    if i is None:
        return 0.0
    m = (game.tracks.t >= t0) & (game.tracks.t <= t1)
    return float(np.isfinite(game.tracks.box[i, m, 0]).mean()) if m.any() else 0.0


def write_highlights(game_dir: Path, *, n: int = 3, synthetic: bool = False) -> dict:
    game = load_game(game_dir)
    plays, source = select(game, n)
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
    return out + [(a, a, "B") for a in TIER_B]


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


def write_manifest(game_dir: Path, play_id: str, sport: str | None = None) -> dict:
    """`replays/{play_id}/manifest.json` from the angle videos that exist on disk.
    URLs are game-relative; the API resolves them."""
    gd = Path(game_dir)
    doc = read_highlights(gd)
    h = play(gd, play_id)
    angles = []
    for stem, aid, tier in angle_files(h):
        rel = f"replays/{play_id}/{stem}.mp4"
        if not (gd / rel).is_file():
            continue
        info = probe_video(gd / rel)
        kind, _, pid = aid.partition(":")
        label = LABELS.get(kind, kind)
        if pid:
            game = json.loads((gd / "game.json").read_text()) if (gd / "game.json").exists() else {}
            name = next((p.get("name") for p in game.get("players") or [] if p["id"] == pid), None)
            label += f" · {name or '#' + pid}"
        angles.append(
            {
                "id": aid,
                "tier": tier,
                "label": label,
                "url": rel,
                "duration_s": info["duration_s"],
                "width": info["width"],
                "height": info["height"],
            }
        )
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "play_id": play_id,
        "label": h["label"],
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
