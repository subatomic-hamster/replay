"""Highlight reel: one shareable MP4 of a game, the top plays and the user's own clips
back to back, with a short dip to black between them and a caption on each.

`plan(game)` picks the segments, in game time order, and ends on the game's best play
(`virtual.replays.best_play`: the user's pick in edits.json, else the game winner, else
the top hype play; kept first, so it is never skipped):

* the user's clips first (they asked for them): `clips.json` ("Replay, clip that", the X
  sign and phone taps resolved to a play), triggers that found no play (the
  `UNRESOLVED_S` before them) and bookmarks;
* then the top plays: the hype candidates by score (`hype.json`), else the highlight
  selection the replay angles use (`virtual.replays.select`);

skipping a segment that overlaps a chosen one by more than half, until `MAX_S` seconds.
`render_reel` cuts them from the wide camera (16:9: the full frame; 9:16: the window
follows the segment's key player, as the vertical export does) with `render_segments`
and writes `<out>.mp4` plus `<out>.plan.json` (`replay.reel.v1`: the segments and where
each starts in the reel). Captions come from the events only (`vertical.describe`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import vertical
from .compositor import render_segments
from .gamedata import Game, _list, load_game, read_json
from .graphics import blit

SCHEMA = "replay.reel.v1"
DIR = "exports/reel"
SIZES = {"16:9": (1280, 720), "9:16": (720, 1280)}
MAX_TOP = 5
MAX_TOP_S = 12.0  # longest top-play segment
MAX_S = 90.0
MIN_S = 2.0
FADE_S = 0.3  # the dip to black at each join
UNRESOLVED_S = 8.0
TRIGGER_WORDS = {"voice": "YOUR CLIP (VOICE)", "gesture": "YOUR CLIP (X SIGN)", "tap": "YOUR CLIP"}


def _seg(game: Game, a: float, b: float, kind: str, tag: str, pid: str | None,
         ref: dict) -> dict | None:  # fmt: skip
    a, b = max(0.0, a), min(b, game.duration) if game.duration else b
    if b - a < MIN_S:
        return None
    if pid is not None and game.tracks.index(pid) is None:
        pid = None
    return {"t_start": round(a, 3), "t_end": round(b, 3), "kind": kind, "tag": tag,
            "player_id": pid, "caption": vertical.describe(game, a, b, None, pid),
            "ref": ref}  # fmt: skip


def user_segments(game: Game) -> list[dict]:
    clips = _list(read_json(game.dir / "clips.json"), "clips")
    triggers = _list(read_json(game.dir / "triggers.json"), "triggers")
    kind_of = {t.get("id"): t.get("type") or "tap" for t in triggers}
    out = []
    for c in clips:
        att = c.get("attribution") or {}
        pid = att.get("subject_player_id") or att.get("owner_player_id")
        tag = TRIGGER_WORDS.get(kind_of.get(c.get("trigger_id")) or "tap", "YOUR CLIP")
        out.append(_seg(game, float(c["t_start"]), float(c["t_end"]), "clip", tag, pid,
                        {"clip_id": c.get("id")}))  # fmt: skip
    clipped = {c.get("trigger_id") for c in clips}
    for t in triggers:
        if t.get("id") in clipped or "t" not in t:
            continue
        tag = TRIGGER_WORDS.get(t.get("type") or "tap", "YOUR CLIP")
        pid = t.get("subject_player_id") or t.get("by_player_id")
        out.append(_seg(game, float(t["t"]) - UNRESOLVED_S, float(t["t"]), "clip", tag, pid,
                        {"trigger_id": t.get("id")}))  # fmt: skip
    for e in game.events:
        if e.get("type") == "bookmark" and not e.get("dismissed"):
            out.append(_seg(game, float(e["t_start"]), float(e["t_end"]), "clip",
                            "YOUR BOOKMARK", None, {"event_id": e["id"]}))  # fmt: skip
    return [s for s in out if s]


def top_segments(game: Game, n: int = MAX_TOP) -> list[dict]:
    hype = read_json(game.dir / "hype.json") or {}
    cands = sorted(hype.get("candidates") or [], key=lambda c: -float(c.get("score") or 0.0))
    out = []
    for c in cands[:n]:
        t = float(c["t"])
        a, b = float(c.get("t_start", t - 6.0)), float(c.get("t_end", t + 2.0))
        # a whole possession can run 20 s: keep its end, where the play pays off
        out.append(_seg(game, max(a, b - MAX_TOP_S), b, "top", "TOP PLAY", None, {"hype_t": t}))
    if not cands:
        from .virtual.replays import select

        for h in select(game, n)[0]:
            a, b = h["t_start"], h["t_end"]
            out.append(_seg(game, max(a, b - MAX_TOP_S), b, "top", "TOP PLAY", h.get("primary"),
                            {"play_id": h.get("play_id")}))  # fmt: skip
    return [s for s in out if s]


def _overlap(s: dict, c: dict) -> float:
    inter = min(s["t_end"], c["t_end"]) - max(s["t_start"], c["t_start"])
    return max(0.0, inter) / max(1e-6, min(s["t_end"] - s["t_start"], c["t_end"] - c["t_start"]))


def best_segment(game: Game) -> dict | None:
    """The game's best play (`virtual.replays.best_play`, the API's rule), at most
    MAX_TOP_S ending where it pays off; always tagged BEST PLAY (a last make is not
    known to have won the game)."""
    from .virtual.replays import best_play

    b = best_play(game)
    if b is None:
        return None
    ev = b["event"] or {}
    tag = "BEST PLAY"
    a, z = b["t_start"], max(b["t_end"], b["t"])
    return _seg(game, max(a, z - MAX_TOP_S), z, "best", tag, ev.get("player_id"),
                {"best_play": b["source"], "event_id": ev.get("id")})  # fmt: skip


def plan(game: Game, max_s: float = MAX_S) -> list[dict]:
    """The segments in time order, then the best play last (the reel ends on it)."""
    best = best_segment(game)
    chosen: list[dict] = [best] if best else []
    for s in user_segments(game) + top_segments(game):
        if any(_overlap(s, c) > 0.5 for c in chosen):
            continue
        if (
            chosen
            and sum(c["t_end"] - c["t_start"] for c in chosen) + s["t_end"] - s["t_start"] > max_s
        ):
            continue
        chosen.append(s)
    rest = sorted((s for s in chosen if s is not best), key=lambda s: s["t_start"])
    return rest + ([best] if best else [])


def render_reel(
    game_dir: Path,
    spec: dict,
    out_path: Path,
    *,
    crf: int = 23,
    progress: Callable[[float], None] | None = None,
) -> dict:
    game = load_game(Path(game_dir))
    segs = plan(game)
    if not segs:
        raise ValueError(f"{game_dir}: no clips or plays to put in a reel")
    aspect = spec.get("aspect") or "16:9"
    size = SIZES[aspect]
    fps = game.fps
    W, H = game.width, game.height
    if aspect == "9:16":
        paths = [vertical.path(game, s["t_start"], max(1, round((s["t_end"] - s["t_start"]) * fps)),
                               fps, s["player_id"]) for s in segs]  # fmt: skip
    else:
        full = np.array([W / 2, H / 2, min(W, H * size[0] / size[1])])
    title = (game.game.get("title") or "").upper()
    landscape = size[0] > size[1]
    # a lower third in 16:9 (the card is sized for a 1080-wide frame), full width in 9:16
    cap_w = round(size[0] * 0.55) if landscape else size[0]
    caps = [vertical.caption_sprite(cap_w, s["caption"], title) for s in segs]
    tags = [vertical.tag_sprite(min(size), f"{s['tag']}  {i + 1}/{len(segs)}")
            for i, s in enumerate(segs)]  # fmt: skip
    m = round(40 * min(size) / 720)

    def window(i: int, t: float) -> np.ndarray:
        if aspect == "9:16":
            p = paths[i]
            return p[min(round((t - segs[i]["t_start"]) * fps), len(p) - 1)]
        return full

    def draw(frame: np.ndarray, i: int, t: float) -> None:
        u, left = t - segs[i]["t_start"], segs[i]["t_end"] - t
        blit(frame, caps[i], 0, size[1] - caps[i].shape[0], alpha=min(1.0, u / 0.4))
        blit(frame, tags[i], m, m)
        fade = min(1.0, u / FADE_S, left / FADE_S)
        if fade < 1.0:  # dip to black between segments
            frame[:] = (frame * max(0.0, fade)).astype(np.uint8)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    spans = [(s["t_start"], s["t_end"]) for s in segs]
    info = render_segments(game.dir / "media" / "wide.mp4", spans, out, size=size, fps=fps,
                           window=window, draw=draw, crf=crf, progress=progress)  # fmt: skip
    at = 0.0
    for s in segs:
        s["reel_t"] = round(at, 3)
        at += max(1, round((s["t_end"] - s["t_start"]) * fps)) / fps
    doc = {"schema": SCHEMA, "id": spec.get("id"), "aspect": aspect, "size": list(size),
           "duration_s": info["seconds"], "segments": segs, "render": info}  # fmt: skip
    out.with_suffix(".plan.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc
