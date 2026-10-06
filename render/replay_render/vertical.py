"""Vertical 9:16 share export of a clip, play or event (vision item 27).

The window follows the clip's key player the way every Replay camera moves (D-44): the
player's box as a raw target, then `camera.smooth` (dead zone, EMA-velocity lead,
critically damped spring, zoom in log space) on 9:16 windows clamped to the frame.
Without a key player (or while they are off the tracks) it frames the players' median.
Captions are burned in: one deterministic line describing the play from its events (no
LLM), the game title and clock, in the broadcast package's type and colours.

`resolve()` turns a clip / play / event id (or explicit times) into a spec; `export()`
renders a spec; `spec_id()` is its content key (`exports/vertical/<id>.mp4`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import camera as cam
from .compositor import render_segments
from .gamedata import Game, _list, load_game, read_json
from .graphics import ACCENT, FONT_BOLD, FONT_SEMI, MUTED, PANEL, WHITE, _rgba, blit
from .graphics import font as get_font

ASPECT = 9.0 / 16.0
SIZE = (720, 1280)
# stiffer than the broadcast's TIGHT_FEEL: a 9:16 window is ~3x narrower around the player
FEEL = cam.Feel(omega=3.0, zoom_omega=1.0, dead_frac=0.08, lead_s=0.3)
PAD_S = (1.0, 1.0)  # around a play or event
KEY_ROLES = ("shooter", "attacker", "blocker", "stealer", "rebounder", "server", "hitter")
DIR = "exports/vertical"


# --------------------------------------------------------------------------- spec


def _shot_text(e: dict) -> str:
    pts = f"{e['points']}-PT " if e.get("points") else ""
    made = e.get("made")
    return pts + ("MAKE" if made is True else "MISS" if made is False else "SHOT")


def describe(
    game: Game,
    t0: float,
    t1: float,
    event_ids: list[str] | None = None,
    player_id: str | None = None,
) -> str:
    """One caption line from the play's own events (else the events in [t0, t1]); a
    rally is looked up in the window, as plays list its serve / contacts / point. An
    event without a player is credited to `player_id` (the play's key participant)."""
    window = sorted(
        (e for e in game.events if not e.get("dismissed") and t0 <= e["t_key"] <= t1),
        key=lambda e: e["t_key"],
    )
    evs = [e for e in window if e["id"] in set(event_ids or ())] or window

    def who(e: dict, text: str) -> str:
        name = game.player_label(e.get("player_id") or player_id)
        return f"{name}  ·  {text}" if name else text

    shots = [e for e in evs if e["type"] == "shot"]
    if shots:
        return who(shots[-1], _shot_text(shots[-1]))
    for e in evs:
        if e["type"] == "block":
            return who(e, "BLOCK")
    rally = next((e for e in window if e["type"] == "rally"), None)
    if rally:
        n = rally.get("contacts") or sum(
            1
            for e in window
            if e["type"] == "contact" and rally["t_start"] <= e["t_key"] <= rally["t_end"]
        )
        shots_txt = f"{n} SHOTS  ·  " if n else ""
        return f"RALLY  ·  {shots_txt}{rally['t_end'] - rally['t_start']:.1f} S"
    for e in reversed(evs):
        cause = e.get("cause")
        if cause == "steal":
            return who(e, "STEAL")
        if cause == "defensive_rebound":
            return who(e, "DEFENSIVE REBOUND")
    return "HIGHLIGHT"


def _key_player(play: dict | None) -> str | None:
    parts = (play or {}).get("participants") or []
    for role in KEY_ROLES:
        for p in parts:
            if p.get("role") == role:
                return p["player_id"]
    return parts[0]["player_id"] if parts else None


def resolve(
    game: Game,
    *,
    clip_id: str | None = None,
    play_id: str | None = None,
    event_id: str | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
    player_id: str | None = None,
) -> dict:
    """A render spec {t_start, t_end, player_id, caption, ref} from one reference.
    Raises KeyError for an unknown id, ValueError for an empty window."""
    plays = {p["id"]: p for p in game.plays}
    play = None
    ref: dict = {}
    if clip_id:
        clips = {c["id"]: c for c in _list(read_json(game.dir / "clips.json"), "clips")}
        clip = clips[clip_id]
        play = plays.get(clip.get("play_id") or "")
        att = clip.get("attribution") or {}
        t0, t1 = float(clip["t_start"]), float(clip["t_end"])
        pid = att.get("subject_player_id") or _key_player(play) or att.get("owner_player_id")
        ref = {"clip_id": clip_id}
    elif play_id:
        play = plays[play_id]
        t0, t1 = play["t_start"] - PAD_S[0], play["t_end"] + PAD_S[1]
        pid = _key_player(play)
        ref = {"play_id": play_id}
    elif event_id:
        ev = {e["id"]: e for e in game.events}[event_id]
        t0, t1 = ev["t_start"] - PAD_S[0], ev["t_end"] + PAD_S[1]
        pid = ev.get("player_id")
        ref = {"event_id": event_id}
    else:
        if t_start is None or t_end is None:
            raise ValueError("give clip_id, play_id, event_id or t_start + t_end")
        t0, t1, pid = float(t_start), float(t_end), None
    pid = player_id or pid
    t0, t1 = max(0.0, t0), min(t1, game.duration or t1)
    if t1 - t0 < 0.5:
        raise ValueError(f"window [{t0}, {t1}] is too short")
    if pid is not None and game.tracks.index(pid) is None:
        pid = None
    return {
        "t_start": round(t0, 3),
        "t_end": round(t1, 3),
        "player_id": pid,
        "caption": describe(game, t0, t1, (play or {}).get("event_ids"), pid),
        "ref": ref,
    }


def spec_id(spec: dict, size: tuple[int, int] = SIZE) -> str:
    """Content key of a spec: the same request is the same file."""
    keyed = {k: spec[k] for k in ("t_start", "t_end", "player_id", "caption")}
    blob = json.dumps({**keyed, "size": list(size)}, sort_keys=True).encode()
    return "v_" + hashlib.sha256(blob).hexdigest()[:12]


# --------------------------------------------------------------------------- camera


def path(game: Game, t0: float, n: int, fps: float, pid: str | None) -> np.ndarray:
    """(n, 3) smoothed 9:16 windows [cx, cy, w] following `pid`."""
    W, H = game.width, game.height
    times = t0 + np.arange(n) / fps
    tr = game.tracks
    box = np.full((n, 4), np.nan)
    i = tr.index(pid) if pid else None
    if i is not None:
        box = tr.at(tr.box[i : i + 1], times)[0]
    if len(tr.t):
        allb = tr.at(tr.box, times)  # fallback: the players' median box
        with np.errstate(all="ignore"):
            med = np.nanmedian(allb, axis=0)
        gap = ~np.isfinite(box).all(axis=1)
        box[gap] = med[gap]
    h_min, h_max = 0.5 * H, float(H)
    raw = np.full((n, 3), np.nan)
    ok = np.isfinite(box).all(axis=1)
    bh = box[ok, 3] - box[ok, 1]
    hwin = np.clip(bh * 3.2, h_min, h_max)
    raw[ok] = np.column_stack(
        [(box[ok, 0] + box[ok, 2]) / 2, box[ok, 1] + 0.45 * bh, hwin * ASPECT]
    )
    if not ok.any():
        raw[:] = (W / 2, H / 2, h_max * ASPECT)
    else:  # hold the last target through gaps; start on the first one
        idx = np.where(ok, np.arange(n), 0)
        np.maximum.accumulate(idx, out=idx)
        raw = raw[idx]
        raw[: int(np.argmax(ok))] = raw[int(np.argmax(ok))]
    min_w = h_min * ASPECT
    raw = np.asarray([cam.fit_window(*r, W, H, min_w, ASPECT) for r in raw])
    return cam.smooth(raw, FEEL, fps, W, H, min_w, ASPECT)


# --------------------------------------------------------------------------- captions


def caption_sprite(width: int, caption: str, line2: str) -> np.ndarray:
    """Bottom caption card: amber rule, big caption (wrapped to two lines), muted line 2."""
    s = width / 1080.0
    f1, f2 = get_font(str(FONT_BOLD), round(84 * s)), get_font(str(FONT_SEMI), round(46 * s))
    pad, max_w = round(56 * s), width - 2 * round(56 * s)
    words, lines = caption.upper().split(), [""]
    for wd in words:
        trial = f"{lines[-1]} {wd}".strip()
        if f1.getlength(trial) <= max_w or not lines[-1]:
            lines[-1] = trial
        else:
            lines.append(wd)
    lines = lines[:2]
    lh1, lh2 = round(96 * s), round(60 * s)
    h = pad + lh1 * len(lines) + lh2 + pad
    img = Image.new("RGBA", (width, h), (*PANEL, 0))
    d = ImageDraw.Draw(img)
    for y in range(h):  # soft fade from transparent into the panel
        d.line([(0, y), (width, y)], fill=(*PANEL, int(225 * min(1.0, y / (0.35 * h)))))
    d.rectangle([pad, pad - round(18 * s), pad + round(120 * s), pad - round(8 * s)],
                fill=(*ACCENT, 255))  # fmt: skip
    y = pad
    for ln in lines:
        d.text((pad, y), ln, font=f1, fill=WHITE)
        y += lh1
    d.text((pad, y + round(6 * s)), line2, font=f2, fill=MUTED)
    return _rgba(img)


def tag_sprite(width: int, text: str = "REPLAY") -> np.ndarray:
    s = width / 1080.0
    f = get_font(str(FONT_BOLD), round(44 * s))
    w, h = round(f.getlength(text)) + round(40 * s), round(64 * s)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=round(10 * s), fill=(*ACCENT, 240))
    d.text((w / 2, h / 2), text, font=f, fill=PANEL, anchor="mm")
    return _rgba(img)


# --------------------------------------------------------------------------- render


def export(
    game_dir: Path,
    spec: dict,
    out_path: Path,
    *,
    size: tuple[int, int] = SIZE,
    crf: int = 23,
    label: str | None = None,
    progress: Callable[[float], None] | None = None,
    game: Game | None = None,
) -> dict:
    game = game or load_game(Path(game_dir))
    fps = game.fps
    t0, t1 = float(spec["t_start"]), float(spec["t_end"])
    n = max(1, round((t1 - t0) * fps))
    p = path(game, t0, n, fps, spec.get("player_id"))
    title = (game.game.get("title") or "").upper()
    cap = caption_sprite(size[0], spec.get("caption") or "HIGHLIGHT", title)
    tag = tag_sprite(size[0], "REPLAY")
    lab = tag_sprite(size[0], label) if label else None
    m = round(48 * size[0] / 1080)

    def window(i: int, t: float) -> np.ndarray:
        return p[min(round((t - t0) * fps), n - 1)]

    def draw(frame: np.ndarray, i: int, t: float) -> None:
        a = min(1.0, (t - t0) / 0.4)
        blit(frame, cap, 0, size[1] - cap.shape[0], alpha=a)
        blit(frame, tag, m, m)
        if lab is not None:
            blit(frame, lab, size[0] - m - lab.shape[1], m, alpha=0.8)

    info = render_segments(
        game.dir / "media" / "wide.mp4", [(t0, t1)], Path(out_path), size=size, fps=fps,
        window=window, draw=draw, crf=crf, progress=progress,
    )  # fmt: skip
    info["jitter"] = cam.jitter(p, size[0])
    return {**spec, "render": info}
