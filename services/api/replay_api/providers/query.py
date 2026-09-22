"""Query engine provider — deterministic rule parser (plan §4.7, decision 5).

Grammar: [player] + [event vocab from the sport profile] + [time filter].
Unknown text returns no match; the optional LLM layer (Phase 2) plugs in there.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Protocol

PAD_S = 1.5

# Basketball vocabulary; a sport profile may override via `query_vocab`.
# Longest phrase wins, so "all shots"/"top plays" must be able to beat "shots".
DEFAULT_VOCAB: dict[str, dict[str, Any]] = {
    "top plays": {
        "type": "shot",
        "made": True,
        "sort": "confidence_desc",
        "limit": 10,
        "label": "top plays",
    },
    "all shots": {"type": "shot", "label": "all shots"},
    "shots": {"type": "shot", "label": "all shots"},
    "shot": {"type": "shot", "label": "all shots"},
    "makes": {"type": "shot", "made": True, "label": "made shots"},
    "made": {"type": "shot", "made": True, "label": "made shots"},
    "buckets": {"type": "shot", "made": True, "label": "made shots"},
    "misses": {"type": "shot", "made": False, "label": "missed shots"},
    "missed": {"type": "shot", "made": False, "label": "missed shots"},
    "bookmarks": {"type": "bookmark", "label": "bookmarks"},
    "bookmark": {"type": "bookmark", "label": "bookmarks"},
    "rallies": {"type": "rally", "label": "rallies"},
    "longest rallies": {
        "type": "rally",
        "sort": "duration_desc",
        "limit": 10,
        "label": "longest rallies",
    },
}

_LAST_N = re.compile(r"last (\d+) (?:minutes|minute|mins|min)")


class QueryEngine(Protocol):
    def query(self, text: str, game: dict, events: list[dict]) -> dict: ...


def _normalize(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "


def _match_vocab(norm: str, vocab: dict[str, dict]) -> tuple[dict | None, str, str]:
    """Longest phrase wins, so "all shots" beats "shots"."""
    for phrase in sorted(vocab, key=len, reverse=True):
        if f" {phrase} " in norm:
            return vocab[phrase], phrase, norm.replace(f" {phrase} ", " ")
    return None, "", norm


def _match_player(norm: str, players: list[dict]) -> dict | None:
    tokens = [t for t in norm.split() if len(t) > 2]
    best, best_score = None, 0.0
    for p in players:
        for part in (p.get("name") or "").lower().split():
            if len(part) < 3:
                continue
            for tok in tokens:
                score = difflib.SequenceMatcher(None, tok, part).ratio()
                if score > best_score:
                    best, best_score = p, score
    return best if best_score >= 0.8 else None


def _match_time(norm: str, duration_s: float) -> tuple[tuple[float, float] | None, str]:
    half = duration_s / 2.0
    if " second half " in norm or " 2nd half " in norm:
        return (half, duration_s), "2nd half"
    if " first half " in norm or " 1st half " in norm:
        return (0.0, half), "1st half"
    m = _LAST_N.search(norm)
    if m:
        n = int(m.group(1))
        return (max(0.0, duration_s - n * 60.0), duration_s), f"last {n} min"
    return None, ""


def _cap(t: float, duration: float) -> float:
    return min(t, duration) if duration else t


def _clip_label(ev: dict, name_by_id: dict[str, str]) -> str:
    who = name_by_id.get(ev.get("player_id") or "", "")
    if ev.get("type") == "shot":
        what = "made" if ev.get("made") else "missed"
        return f"{who} {what}".strip()
    return f"{who} {ev.get('type', 'clip')}".strip()


class RuleQueryEngine:
    name = "rules"

    def __init__(self, vocab: dict[str, dict] | None = None):
        self.vocab = vocab or DEFAULT_VOCAB

    def query(self, text: str, game: dict, events: list[dict]) -> dict:
        duration = float((game.get("video") or {}).get("duration_s") or 0.0)
        players = game.get("players") or []
        norm = _normalize(text)

        filt, phrase, rest = _match_vocab(norm, self.vocab)
        player = _match_player(rest, players)
        window, time_label = _match_time(rest, duration)

        if filt is None and player is None:
            return {"interpretation": "No match", "clips": []}
        if filt is None:  # "Marcus" alone -> that player's shots (H1)
            filt, phrase = {"type": "shot", "label": "all shots"}, "all shots"

        picked = [e for e in events if e.get("type") == filt["type"]]
        if "made" in filt:
            picked = [e for e in picked if bool(e.get("made")) is filt["made"]]
        if player is not None:
            picked = [e for e in picked if e.get("player_id") == player["id"]]
        if window:
            lo, hi = window
            picked = [e for e in picked if lo <= float(e.get("t_key", e.get("t_start", 0))) <= hi]

        if filt.get("sort") == "confidence_desc":
            picked.sort(key=lambda e: e.get("confidence") or 0, reverse=True)
        elif filt.get("sort") == "duration_desc":
            picked.sort(key=lambda e: e.get("t_end", 0) - e.get("t_start", 0), reverse=True)
        if filt.get("limit"):
            picked = picked[: filt["limit"]]

        name_by_id = {p["id"]: p.get("name") or p["id"] for p in players}
        clips = [
            {
                "t_start": max(0.0, round(float(e["t_start"]) - PAD_S, 3)),
                "t_end": round(_cap(float(e["t_end"]) + PAD_S, duration), 3),
                "event_id": e["id"],
                "label": _clip_label(e, name_by_id),
            }
            for e in picked
        ]
        clips = _merge_overlaps(clips)

        parts = [
            p
            for p in (
                player.get("name") if player else None,
                filt.get("label") or phrase,
                time_label,
            )
            if p
        ]
        return {"interpretation": " — ".join(parts) or "No match", "clips": clips}


def _merge_overlaps(clips: list[dict]) -> list[dict]:
    out: list[dict] = []
    for clip in sorted(clips, key=lambda c: c["t_start"]):
        if out and clip["t_start"] <= out[-1]["t_end"]:
            out[-1]["t_end"] = max(out[-1]["t_end"], clip["t_end"])
        else:
            out.append(dict(clip))
    return out


def merged_vocab(profile_vocab: dict[str, dict] | None) -> dict[str, dict]:
    """A sport profile (§4.9) carries only its own words; the shared grammar keeps the
    rest, and a profile entry wins field by field."""
    out = dict(DEFAULT_VOCAB)
    for phrase, filt in (profile_vocab or {}).items():
        out[phrase] = {**DEFAULT_VOCAB.get(phrase, {}), **filt}
    return out


def get_query_engine(name: str, vocab: dict[str, dict] | None = None) -> QueryEngine:
    if name != "rules":
        raise ValueError(f"query engine {name!r} is not available in Phase 1")
    return RuleQueryEngine(vocab)
