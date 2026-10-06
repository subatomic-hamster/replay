"""Play-by-play commentary from structured JSON only (vision item 9).

Per play: one line per event that has something to say, from deterministic templates
(the guaranteed path — every template line passes `grounding.check`, tested over every
synthetic play). With an LLM, the lines are paraphrased under a JSON schema and the
paraphrase is used only if every line passes the same check; otherwise the template
stays. Timing comes from the events, never from the model: each line keeps its event's
time, and `narrate` lays the spoken lines on the game clock without overlaps.

Without plays.json (no plays stage yet), every shot / point / block / turnover becomes
its own one-event play (`"derived_from": "event"`).
"""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

import numpy as np

from . import grounding as G

SCHEMA = "replay.commentary.v1"
SOLO_TYPES = ("shot", "point", "block", "turnover")

SYSTEM = (
    "You are a sports play-by-play commentator. You get FACTS (JSON) about one play and "
    "LINES, a draft commentary with one line per moment. Rewrite each line to sound like "
    "live TV commentary, same order, same count. Use only what FACTS states: the same "
    "player names and team names, no other names, no numbers that are not in FACTS, no "
    "shot types, fouls, dunks, layups, distances, court areas or game situations that are "
    "not in FACTS. Never use he, she, his or her: repeat the name. At most 14 words a line."
)


def _schema(n: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "minItems": n,
                "maxItems": n,
                "items": {"type": "string", "maxLength": 140},
            }
        },
        "required": ["lines"],
    }


def _read(path: Path, key: str) -> list:
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, list) else doc.get(key) or []


def load_docs(game_dir: Path) -> tuple[dict, list[dict], list[dict], list[dict]]:
    """(game, live events, plays, score entries) from a game dir; optional files may be
    missing. Dismissed events (D-11) are dropped."""
    gd = Path(game_dir)
    game = json.loads((gd / "game.json").read_text(encoding="utf-8"))
    events = [e for e in _read(gd / "events.json", "events") if not e.get("dismissed")]
    return game, events, _read(gd / "plays.json", "plays"), _read(gd / "score.json", "score")


def score_index(score_entries: list[dict]) -> dict[str, list[int]]:
    return {s["event_id"]: list(s["scores"]) for s in score_entries if s.get("event_id")}


def game_plays(plays: list[dict], events: list[dict]) -> list[dict]:
    if plays:
        return plays
    return [
        {
            "id": f"ev_{e['id']}",
            "t_start": e.get("t_start", e.get("t_key", 0.0)),
            "t_end": e.get("t_end", e.get("t_key", 0.0)),
            "event_ids": [e["id"]],
            "participants": [],
            "derived_from": "event",
        }
        for e in events
        if e.get("type") in SOLO_TYPES
    ]


def _template_lines(evs: list[dict], names: dict, teams: dict, score: dict) -> list[dict]:
    def name(pid: str | None) -> str | None:
        return names.get(pid) if pid else None

    stolen_from = {
        e.get("t_key"): name(e.get("player_id"))
        for e in evs
        if e.get("type") == "turnover" and e.get("cause") == "steal"
    }
    has_steal = any(e.get("type") == "possession_change" and e.get("cause") == "steal" for e in evs)
    lines: list[dict] = []

    def say(e: dict, text: str | None, t: float | None = None) -> None:
        if text:
            lines.append({"t": round(float(t if t is not None else e.get("t_key", 0)), 3),
                          "event_ids": [e["id"]], "text": text})  # fmt: skip

    for e in evs:
        typ, cause = e.get("type"), e.get("cause")
        a, b = name(e.get("player_id")), name(e.get("receiver_id"))
        pts = e.get("points")
        text = None
        if typ == "possession_change" and a:
            if cause == "steal":
                loser = stolen_from.get(e.get("t_key"))
                text = f"{a} steals it from {loser}!" if loser else f"{a} with the steal!"
            elif cause == "inbound":
                text = f"{a} brings it in."
            elif cause and "rebound" in cause:
                text = f"{a} pulls down the rebound."
        elif typ == "pass" and a:
            text = f"{a} finds {b}." if b else f"{a} passes."
        elif typ == "shot" and a:
            if e.get("made") is True:
                text = {3: f"{a} knocks down the three!", 2: f"{a} scores two."}.get(
                    pts, f"{a} scores!"
                )
            elif e.get("made") is False:
                text = f"{a} misses from three." if pts == 3 else f"{a} shoots, no good."
            else:
                text = f"{a} puts up a shot."
        elif typ == "turnover" and a and not (cause == "steal" and has_steal):
            text = f"Turnover by {a}."
        elif typ == "block" and a:
            text = f"{a} with the block!"
        elif typ == "serve" and a:
            text = f"{a} serves."
        elif typ == "rally" and isinstance(e.get("contacts"), int):
            n = e["contacts"]
            text = f"That rally ran {n} {'touch' if n == 1 else 'touches'}."
            say(e, text, e.get("t_end"))
            continue
        elif typ == "point" and e.get("winner_side") in teams:
            won = f"Point to {teams[e['winner_side']]}."
            how = {"net": "hits the net.", "out": "sends it out.", "winner": "with the winner!"}
            text = f"{a} {how[cause]} {won}" if a and cause in how else won
        elif typ == "hype":
            text = "Listen to that crowd!"
        say(e, text)
        if e["id"] in score:
            s0, s1 = score[e["id"]]
            say(e, f"That puts it at {s0} to {s1}.", e.get("t_end"))
    lines.sort(key=lambda ln: ln["t"])
    return lines


def play_facts(game: dict, play: dict, events_by_id: dict, score: dict) -> tuple[dict, list]:
    evs = [events_by_id[i] for i in play.get("event_ids", []) if i in events_by_id]
    evs.sort(key=lambda e: float(e.get("t_key", e.get("t_start", 0))))
    scores = [score[e["id"]] for e in evs if e["id"] in score]
    facts = G.build_facts(
        game,
        evs,
        participants=play.get("participants") or [],
        score=scores[-1] if scores else None,
        numbers=[n for s in scores for n in s],
        sport=play.get("sport") or game.get("sport"),
    )
    return facts, evs


def _llm_view(facts: dict) -> dict:
    keys = ("sport", "teams", "events", "score", "leader", "tied")
    return {k: facts[k] for k in keys if facts.get(k) not in (None, False)}


def paraphrase(
    llm: Any, facts: dict, lines: list[str], system: str = SYSTEM, view: dict | None = None
) -> dict:
    """One LLM attempt (temperature 0, fixed seed in the provider): accepted only when every
    line passes the grounding check. `{"lines": [...] | None, "raw", "checks", "error"}`."""
    prompt = json.dumps({"FACTS": view or _llm_view(facts), "LINES": lines})
    try:
        raw = llm.complete(prompt, system=system, json_schema=_schema(len(lines)), max_tokens=400)
        texts = json.loads(raw)["lines"]
    # NotConfiguredError (a RuntimeError), HTTP / socket (OSError), bad JSON: template stays
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
        return {"lines": None, "raw": None, "checks": [], "error": f"{type(exc).__name__}: {exc}"}
    if len(texts) != len(lines):
        return {"lines": None, "raw": texts, "checks": [], "error": "line count changed"}
    checks = [G.check(t, facts) for t in texts]
    ok = all(c["ok"] for c in checks)
    return {"lines": texts if ok else None, "raw": texts, "checks": checks, "error": None}


def llm_report(attempt: dict) -> dict:
    return {
        "accepted": attempt["lines"] is not None,
        "error": attempt["error"],
        "raw": attempt["raw"],
        "violations": [v for c in attempt["checks"] for v in c["violations"]],
    }


def script_for_play(
    game: dict, play: dict, events_by_id: dict, score: dict, llm: Any = None
) -> dict:
    facts, evs = play_facts(game, play, events_by_id, score)
    lines = _template_lines(evs, facts["roster"], {int(k): v for k, v in facts["teams"].items()},
                            score)  # fmt: skip
    checks = [G.check(ln["text"], facts) for ln in lines]
    out = {
        "play_id": play["id"],
        "t_start": play.get("t_start"),
        "t_end": play.get("t_end"),
        "source": "template",
        "lines": lines,
        "grounding": {
            "template_ok": all(c["ok"] for c in checks),
            "violations": [v for c in checks for v in c["violations"]],
        },
        "facts": facts,
    }
    if play.get("derived_from"):
        out["derived_from"] = play["derived_from"]
    if llm is not None and lines:
        attempt = paraphrase(llm, facts, [ln["text"] for ln in lines])
        out["llm"] = llm_report(attempt)
        if attempt["lines"] is not None:
            out["source"] = "llm"
            out["template_lines"] = [ln["text"] for ln in lines]
            out["lines"] = [{**ln, "text": t} for ln, t in zip(lines, attempt["lines"])]
    return out


def game_script(
    game: dict,
    events: list[dict],
    plays: list[dict],
    score_entries: list[dict] = (),
    llm: Any = None,
    only: str | None = None,
) -> dict:
    by_id = {e["id"]: e for e in events}
    score = score_index(list(score_entries))
    scripts = [
        script_for_play(game, p, by_id, score, llm)
        for p in game_plays(plays, events)
        if only is None or p["id"] == only
    ]
    tried = [s for s in scripts if "llm" in s]
    return {
        "schema": SCHEMA,
        "game_id": game.get("id"),
        "sport": game.get("sport"),
        "plays": scripts,
        "summary": {
            "plays": len(scripts),
            "lines": sum(len(s["lines"]) for s in scripts),
            "template_grounded": sum(s["grounding"]["template_ok"] for s in scripts),
            "llm_attempted": len(tried),
            "llm_accepted": sum(s["llm"]["accepted"] for s in tried),
        },
    }


# --- audio ------------------------------------------------------------------------------


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        a = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768
    return (a.reshape(-1, ch).mean(axis=1) if ch > 1 else a), sr


def write_wav(path: Path, a: np.ndarray, sr: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def narrate(
    script: dict,
    tts: Any,
    out_dir: Path,
    *,
    duration_s: float | None = None,
    voice: str | None = None,
    gap_s: float = 0.2,
) -> dict:
    """Speak every line, lay the clips on the game clock (a line starts at its event time,
    or right after the previous line if that is still talking) and write
    `<out_dir>/narration.wav` (whole game, for the broadcast mixer) plus
    `<out_dir>/<play_id>.wav` (play-relative, for replays). Adds `audio_t` / `audio_s`
    to each line. Returns timing info."""
    out_dir = Path(out_dir)
    clips_dir = out_dir / "lines"
    jobs = [
        (ln["text"], clips_dir / f"{s['play_id']}_{i:02d}.wav")
        for s in script["plays"]
        for i, ln in enumerate(s["lines"])
    ]
    if hasattr(tts, "synthesize_many"):
        tts.synthesize_many(jobs, voice=voice)
    else:
        for text, path in jobs:
            tts.synthesize(text, path, voice=voice)
    all_lines = [ln for s in script["plays"] for ln in s["lines"]]  # same order as jobs
    by_line = {id(ln): _read_wav(p) for ln, (_, p) in zip(all_lines, jobs)}
    placed: list[tuple[float, np.ndarray]] = []
    sr = 24000
    cursor = 0.0
    for ln in sorted(all_lines, key=lambda ln: ln["t"]):
        a, sr = by_line[id(ln)]
        start = max(float(ln["t"]), cursor)
        ln["audio_t"], ln["audio_s"] = round(start, 3), round(len(a) / sr, 3)
        placed.append((start, a))
        cursor = start + len(a) / sr + gap_s
    total = max(cursor, duration_s or 0.0)
    track = np.zeros(int(total * sr) + 1, np.float32)
    for start, a in placed:
        i = int(start * sr)
        track[i : i + len(a)] += a[: len(track) - i]
    write_wav(out_dir / "narration.wav", track, sr)
    for s in script["plays"]:
        if not s["lines"]:
            continue
        t0 = float(s.get("t_start") or 0.0)
        end = max(ln["audio_t"] + ln["audio_s"] for ln in s["lines"])
        i0, i1 = int(max(t0, 0) * sr), int(end * sr) + 1
        write_wav(out_dir / f"{s['play_id']}.wav", track[i0:i1], sr)
        s["audio"] = f"{s['play_id']}.wav"
    script["narration"] = {"file": "narration.wav", "sr": sr, "duration_s": round(total, 3)}
    return {"lines": len(jobs), "speech_s": round(sum(len(a) for _, a in placed) / sr, 3)}
