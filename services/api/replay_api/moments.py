"""Moments, seek previews and hero art for the TV redesign (docs/ux/redesign.md, "What the
backend needs"). Shared by the worker's `storyboard` / `moments` stages, the fake pipeline
and the API's `/games/{id}/moments` and `/games/{id}/storyboard` routes.

* `moments(events, game)`: one moment per detected event worth jumping to, with a plain
  label built only from what the event says (a shot whose `made` is unknown is "Shot",
  never a basket) plus the player's name when the roster has one. No jersey numbers: no
  stage reads them yet, so `player.number` is never set.
* `clip_moments(triggers, clips, game)`: the user's clips ("Replay, clip that", the X
  sign, phone taps) as moments of kind `bookmark` with an extra `trigger` key;
  `all_moments` merges both.
* `write_storyboard(video, game_dir)`: one 320x180 frame every 2 s (letterboxed to 16:9),
  tiled 10x10 per JPEG sheet, plus `storyboard/manifest.json`. One ffmpeg decode pass.
* `write_moments(game_dir, video)`: `moments.json` (the labels at run time and which
  thumbs exist), `moments/<event id>.jpg` (480x270, the frame at `t_key`) and
  `media/hero.jpg` (1280x720): the top hype candidate's scoring moment (else its peak),
  else the best detected event, else the middle of the game.

The API recomputes labels from the live events.json on every read, so a renamed player or
a dismissed event shows at once; `moments.json` only tells it which thumbs exist.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

SCHEMA = "replay.moments.v1"
REL = "moments.json"
THUMB_DIR = "moments"
HERO_REL = "media/hero.jpg"
WIDE_REL = "media/wide.mp4"
STORYBOARD_DIR = "storyboard"
STORYBOARD_REL = "storyboard/manifest.json"
INTERVAL_S, TILE_W, TILE_H, COLS, ROWS = 2, 320, 180, 10, 10
THUMB = (480, 270)
HERO = (1280, 720)
JPEG_Q = 82

# Rally length words per sport (volleyball counts touches; racket sports count shots).
RALLY_WORD = {"volleyball": "touches"}


def label(e: dict, player: dict | None, sport: str) -> str | None:
    """Plain words for one event, or None when it is not a moment (contacts, serves,
    inbounds, crowd spikes)."""
    typ, cause, pts, made = e.get("type"), e.get("cause"), e.get("points"), e.get("made")
    name = (player or {}).get("name")
    if typ == "bookmark":
        return "Your bookmark"
    if typ == "shot":
        if made is True:
            base = {3: "Three-pointer", 2: "Two-pointer", 1: "Free throw"}.get(pts, "Basket")
        elif made is False:
            base = "Missed three" if pts == 3 else "Missed shot"
        else:  # the detector could not tell: say only that a shot went up
            base = "Three-point attempt" if pts == 3 else "Shot"
    elif typ == "possession_change":
        base = {"steal": "Steal", "defensive_rebound": "Rebound",
                "offensive_rebound": "Offensive rebound"}.get(cause)  # fmt: skip
    elif typ == "turnover":
        base = None if cause == "steal" else "Turnover"  # the steal is its own moment
    elif typ == "block":
        base = "Block"
    elif typ == "point":
        # whose fault an out / net ball was is not in the event: name only the winner
        base = {"winner": "Winner", "out": "Point, ball out", "net": "Point, into the net"}
        base = base.get(cause, "Point")
        name = name if cause == "winner" else None
    elif typ == "rally":
        n = e.get("contacts")
        word = RALLY_WORD.get(sport, "shots")
        base = f"Rally, {n} {word}" if isinstance(n, int) and n > 0 else "Rally"
        name = None
    else:
        return None
    if base is None:
        return None
    return f"{base}, {name}" if name else base


def kind(e: dict) -> str:
    if e.get("type") == "bookmark":
        return "bookmark"
    if (e.get("type") == "shot" and e.get("made") is True) or e.get("type") == "point":
        return "score"
    return "play"


def _rank(e: dict) -> tuple:
    """Best moment first: scores (by value), then your bookmarks, then other plays;
    a confirmed event over a guessed one, then detector confidence."""
    k = kind(e)
    return ({"score": 2, "bookmark": 1}.get(k, 0), e.get("points") or 0,
            bool(e.get("confirmed")), float(e.get("confidence") or 0.0))  # fmt: skip


def moments(events: list[dict], game: dict) -> list[dict]:
    """`GET /games/{id}/moments` rows (without thumb_url), sorted by time."""
    players = {p["id"]: p for p in game.get("players") or []}
    sport = game.get("sport") or ""
    out = []
    for e in events:
        if e.get("dismissed") or "t_key" not in e:
            continue
        p = players.get(e.get("player_id"))
        text = label(e, p, sport)
        if text is None:
            continue
        m = {
            "id": e["id"],
            "t": round(float(e["t_key"]), 3),
            "t_start": round(float(e.get("t_start", e["t_key"])), 3),
            "t_end": round(float(e.get("t_end", e["t_key"])), 3),
            "kind": kind(e),
            "label": text,
            # honesty: where the label came from (heuristic / vlm / user) and how sure
            "source": e.get("source") or "heuristic",
            "confidence": e.get("confidence"),
            "confirmed": bool(e.get("confirmed")),
        }
        if p:
            m["player"] = {k: p[k] for k in ("id", "name", "color_hex") if p.get(k) is not None}
        out.append(m)
    out.sort(key=lambda m: (m["t"], m["id"]))
    return out


CLIP_WORDS = {"voice": "Your clip (voice)", "gesture": "Your clip (X sign)", "tap": "Your clip"}
UNRESOLVED_S = 8.0  # a trigger that found no play: the seconds before it


def clip_moments(triggers: list[dict], clips: list[dict], game: dict) -> list[dict]:
    """ "Replay, clip that" (voice), the crossed-arms X (gesture) and phone taps, as moments
    of kind `bookmark` (the user's own), id = the trigger id. The range is the clip's
    (the play the trigger resolved to) and `t` its play's end; a trigger that resolved to
    no play covers the `UNRESOLVED_S` before it. Voice and gesture are detected, so they
    keep source `heuristic` and the detector's confidence; `trigger` says which it was."""
    players = {p["id"]: p for p in game.get("players") or []}
    by_trigger = {c.get("trigger_id"): c for c in clips}
    out = []
    for tr in triggers:
        if "t" not in tr or not tr.get("id"):
            continue
        c = by_trigger.get(tr["id"])
        t = float(tr["t"])
        if c:
            a, b = float(c["t_start"]), float(c["t_end"])
            key = max(a, b - 1.0)  # courtcam pads a clip 1 s past its play
        else:
            a, b, key = max(0.0, t - UNRESOLVED_S), t, max(0.0, t - 1.0)
        kind_ = tr.get("type") or "tap"
        text = CLIP_WORDS.get(kind_, "Your clip")
        subject = players.get(tr.get("subject_player_id") or "")
        if subject and subject.get("name"):
            text = f"{text}, {subject['name']}"
        m = {
            "id": tr["id"], "t": round(key, 3), "t_start": round(a, 3), "t_end": round(b, 3),
            "kind": "bookmark", "label": text, "trigger": kind_,
            "clip_id": c["id"] if c else None,
            "source": "user" if kind_ == "tap" or tr.get("source") == "user" else "heuristic",
            "confidence": tr.get("confidence"), "confirmed": kind_ == "tap",
        }  # fmt: skip
        owner = players.get(tr.get("by_player_id") or "") or subject
        if owner:
            m["player"] = {
                k: owner[k] for k in ("id", "name", "color_hex") if owner.get(k) is not None
            }
        out.append(m)
    return out


NOTES_REL = "notes.json"  # = courtcam.playlog.NOTES_REL, written by `courtcam notes`
NOTE_S = 6.0  # a note covers this much before its time


def note_moments(notes: dict | None) -> list[dict]:
    """The uploader's own play log (D-90, docs/playlog.md) as moments of kind `bookmark`
    labelled "Your note", source `user`: what the person wrote, beside what the pipeline
    detected and never merged into it. An evaluation log is never shown."""
    if not notes or notes.get("use") != "notes":
        return []
    out = []
    for i, e in enumerate(notes.get("entries") or []):
        if "t" not in e:
            continue
        t = float(e["t"])
        did = {True: "made", False: "missed"}.get(e.get("made"), "")
        what = " ".join(x for x in (e.get("player"), did, (e.get("type") or "").replace("_", " "))
                        if x and x != "note")  # fmt: skip
        text = e.get("note") or what or "note"
        out.append({
            "id": f"note{i + 1}", "t": round(t, 3), "t_start": round(max(0.0, t - NOTE_S), 3),
            "t_end": round(t + 2.0, 3), "kind": "bookmark", "label": f"Your note: {text}",
            "trigger": "note", "clip_id": None, "source": "user", "confidence": None,
            "confirmed": True,
        })  # fmt: skip
    return out


def all_moments(events: list[dict], game: dict, triggers: list[dict] | None = None,
                clips: list[dict] | None = None, notes: dict | None = None) -> list[dict]:  # fmt: skip
    """Detected moments, the user's clips and the user's notes together, sorted by time."""
    out = moments(events, game) + clip_moments(triggers or [], clips or [], game)
    out += note_moments(notes)
    out.sort(key=lambda m: (m["t"], m["id"]))
    return out


def hero_time(events: list[dict], game: dict, hype: dict | None, duration: float):
    """(t, why): the frame the library shows for this game."""
    live = {m["id"]: m for m in moments(events, game)}
    by_id = {e["id"]: e for e in events if e.get("id") in live}
    cands = (hype or {}).get("candidates") or []
    if cands:  # best first (replay_render.hype)
        c = cands[0]
        inside = [by_id[i] for i, m in live.items() if m["kind"] == "score"
                  and c.get("t_start", c["t"]) <= m["t"] <= c.get("t_end", c["t"])]  # fmt: skip
        if inside:
            return float(max(inside, key=_rank)["t_key"]), "hype"
        return float(c["t"]), "hype"
    if by_id:
        return float(max(by_id.values(), key=_rank)["t_key"]), "event"
    return max(0.0, duration / 2.0), "middle"


# --------------------------------------------------------------------------- frames


def _fit(frame, size: tuple[int, int]):
    """Scale `frame` into `size`, letterboxed (black bars) so every image is 16:9."""
    import cv2
    import numpy as np

    w, h = size
    fh, fw = frame.shape[:2]
    s = min(w / fw, h / fh)
    nw, nh = max(1, round(fw * s)), max(1, round(fh * s))
    out = np.zeros((h, w, 3), np.uint8)
    x, y = (w - nw) // 2, (h - nh) // 2
    out[y : y + nh, x : x + nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    return out


def grab_frames(video: Path, shots: list[tuple[float, Path, tuple[int, int]]]) -> list[Path]:
    """Write the frame at each time `t` to its path at its size, in one decoder: in time
    order, stepping forward when the next time is close and seeking when it is not.
    Returns the paths written (a time past the end is clamped to the last frame)."""
    import cv2

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    last = max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) - 1)
    pos, written = -1, []
    try:
        for t, dst, size in sorted(shots, key=lambda s: s[0]):
            target = min(last, max(0, round(t * fps)))
            if pos < 0 or target < pos or target - pos > 4 * fps:  # ponytail: 4 s step-or-seek
                cap.set(cv2.CAP_PROP_POS_FRAMES, target)
                pos = target
            while pos < target and cap.grab():
                pos += 1
            ok, frame = cap.read()
            pos += 1
            if not ok:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(dst), _fit(frame, size), [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
            written.append(dst)
    finally:
        cap.release()
    return written


def write_storyboard(video: Path, game_dir: Path, threads: int = 6) -> dict:
    """storyboard/NNNN.jpg sheets + manifest.json (written last). Frame i of the video
    (time i * interval_s) is sheet i // (cols * rows), cell i % (cols * rows), row-major."""
    import cv2
    import numpy as np

    out = Path(game_dir) / STORYBOARD_DIR
    out.mkdir(parents=True, exist_ok=True)
    vf = (f"fps=1/{INTERVAL_S},scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=decrease,"
          f"pad={TILE_W}:{TILE_H}:(ow-iw)/2:(oh-ih)/2")  # fmt: skip
    cmd = ["ffmpeg", "-v", "error", "-threads", str(threads), "-i", str(video), "-an",
           "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]  # fmt: skip
    frame_bytes = TILE_W * TILE_H * 3
    per = COLS * ROWS
    sheets: list[str] = []
    count = 0
    sheet = np.zeros((ROWS * TILE_H, COLS * TILE_W, 3), np.uint8)

    def flush(n: int) -> None:
        rows = math.ceil(n / COLS)  # a short last sheet keeps only the rows it uses
        rel = f"{STORYBOARD_DIR}/{len(sheets):04d}.jpg"
        cv2.imwrite(
            str(Path(game_dir) / rel), sheet[: rows * TILE_H], [cv2.IMWRITE_JPEG_QUALITY, 70]
        )
        sheets.append(rel)
        sheet[:] = 0

    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        assert proc.stdout is not None
        while len(buf := proc.stdout.read(frame_bytes)) == frame_bytes:
            cell = count % per
            r, c = divmod(cell, COLS)
            sheet[r * TILE_H : (r + 1) * TILE_H, c * TILE_W : (c + 1) * TILE_W] = np.frombuffer(
                buf, np.uint8
            ).reshape(TILE_H, TILE_W, 3)
            count += 1
            if count % per == 0:
                flush(per)
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg storyboard failed: {err.strip()[-400:]}")
    if count % per:
        flush(count % per)
    manifest = {
        "schema": "replay.storyboard.v1",
        "interval_s": INTERVAL_S,
        "width": TILE_W,
        "height": TILE_H,
        "cols": COLS,
        "rows": ROWS,
        "count": count,
        "sheets": sheets,  # game-relative; the API's /storyboard route makes them URLs
    }
    (Path(game_dir) / STORYBOARD_REL).write_text(json.dumps(manifest, indent=1))
    return manifest


def _read(path: Path, key: str | None = None):
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc.get(key, []) if key else doc


def write_moments(game_dir: Path, video: Path | None = None, game: dict | None = None) -> dict:
    """moments.json + moments/<id>.jpg + media/hero.jpg for a processed game dir
    (`game` defaults to its game.json)."""
    gd = Path(game_dir)
    video = Path(video) if video else gd / WIDE_REL
    game = game if game is not None else _read(gd / "game.json") or {}
    events = _read(gd / "events.json", "events") or []
    rows = all_moments(events, game, _read(gd / "triggers.json", "triggers"),
                       _read(gd / "clips.json", "clips"), _read(gd / NOTES_REL))  # fmt: skip
    duration = float((game.get("video") or {}).get("duration_s") or 0.0)
    t_hero, why = hero_time(events, game, _read(gd / "hype.json"), duration)
    (gd / THUMB_DIR).mkdir(parents=True, exist_ok=True)
    shots = [(m["t"], gd / THUMB_DIR / f"{m['id']}.jpg", THUMB) for m in rows]
    shots.append((t_hero, gd / HERO_REL, HERO))
    written = set(grab_frames(video, shots))
    if gd / HERO_REL not in written:
        raise RuntimeError(f"no hero frame at {t_hero:.1f} s in {video}")
    doc = {
        "schema": SCHEMA,
        "hero": {"t": round(t_hero, 3), "from": why, "path": HERO_REL},
        "moments": [
            {**m, "thumb": f"{THUMB_DIR}/{m['id']}.jpg"}
            if gd / THUMB_DIR / f"{m['id']}.jpg" in written
            else m
            for m in rows
        ],
    }
    (gd / REL).write_text(json.dumps(doc, indent=1))
    return doc
