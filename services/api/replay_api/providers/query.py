"""Query engine provider — deterministic rule parser (plan §4.7, decision 5).

Grammar: [player] + [event vocab from the sport profile] + [time filter].
Unknown text returns no match. `REPLAY_QUERY=llm` adds the LLM layer behind the rules:
only text the rules cannot parse reaches the LLM, which may only fill a structured filter
(`LLMQueryEngine`, `validate_filter`).
"""

from __future__ import annotations

import difflib
import json
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
        return self.execute(filt, phrase, player, window, time_label, game, events)

    def execute(
        self,
        filt: dict,
        phrase: str,
        player: dict | None,
        window: tuple[float, float] | None,
        time_label: str,
        game: dict,
        events: list[dict],
    ) -> dict:
        """A structured filter -> clips (shared by the rule and the LLM path)."""
        duration = float((game.get("video") or {}).get("duration_s") or 0.0)
        players = game.get("players") or []
        picked = [e for e in events if e.get("type") == filt["type"]]
        if "made" in filt:
            picked = [e for e in picked if bool(e.get("made")) is filt["made"]]
        if "points" in filt:  # LLM path only
            picked = [e for e in picked if e.get("points") == filt["points"]]
        if "cause" in filt:  # LLM path only: steal / rebound
            picked = [e for e in picked if filt["cause"] in (e.get("cause") or "")]
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
        return {
            "interpretation": " — ".join(parts) or "No match",
            "clips": clips,
            # additive: every selected event (merged clips keep only their first id)
            "event_ids": [e["id"] for e in picked],
        }


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


# --- LLM path (vision 22): free text -> structured filter only, then a deterministic
# validator. The schema has no time fields, so the model can never emit timestamps.

# a filter field survives only if the query text itself says so (D-39: schema-valid output
# can still be semantically wrong, e.g. `made: true` on a badminton query)
# event type -> (words the query must contain, what it is, for the prompt)
TYPES: dict[str, tuple[str, str]] = {
    "shot": (r"shot|shoot|basket|bucket|make|made|miss|three|jumper|scor|pointer",
             "a shot at the basket: baskets, buckets, threes, makes and misses"),
    "pass": (r"pass|assist|dish|feed", "a pass to a teammate"),
    "steal": (r"steal|stole|pickpocket|strip", "a steal (possession won from the other team)"),
    "rebound": (r"rebound|board", "a rebound"),
    "possession_change": (r"inbound|possession", "an inbound or any change of possession"),
    "turnover": (r"turnover|turn(?:ed|s)? (?:it )?over|giveaway|lost the ball|lose the ball",
                 "a turnover: the ball lost"),
    "rally": (r"rall(?:y|ies)|exchange", "a rally (net sports)"),
    "serve": (r"serv", "a serve (net sports)"),
    "point": (r"point", "a point won (net sports)"),
    "block": (r"block|reject|swat", "a block"),
    "contact": (r"contact|touch", "a racket or hand contact (net sports)"),
    "bookmark": (r"bookmark|saved|marked", "a moment the viewer bookmarked"),
    "hype": (r"hype|crowd|loud|cheer", "a loud crowd moment"),
}  # fmt: skip
# sub-types the LLM may pick: a possession change with that cause
SUBTYPES = {"steal": "steal", "rebound": "rebound"}
MADE_WORDS = re.compile(r"\b(?:makes?|made|scor\w*|buckets?|baskets?|hits?|sinks?|sank|drain\w*)\b")
MISS_WORDS = re.compile(r"\b(?:miss\w*|brick\w*|airball\w*)\b")
VALUE_WORDS = {3: re.compile(r"\b(?:three|3|threes|triples?|deep|downtown)\b"),
               2: re.compile(r"\b(?:two|2)[- ]?pointers?\b|\btwos\b")}  # fmt: skip
LLM_SYSTEM = (
    "Convert a viewer's request about one recorded game into a JSON filter. Fill a field "
    "only when the request clearly asks for it; otherwise use none / any / false. "
    "Never output times or numbers."
)


def filter_schema(types: list[str], names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "event_type": {"type": "string", "enum": [*types, "none"]},
            "result": {"type": "string", "enum": ["made", "missed", "any"]},
            "shot_value": {"type": "string", "enum": ["three", "two", "any"]},
            "player": {"type": "string", "enum": [*names, "none"]},
            "half": {"type": "string", "enum": ["first", "second", "any"]},
            "longest": {"type": "boolean"},
        },
        "required": ["event_type", "result", "shot_value", "player", "half", "longest"],
    }


def _grounded_player(name: str, norm: str, players: list[dict]) -> dict | None:
    """The roster entry for `name` if some query token resembles one of its parts."""
    p = next((p for p in players if p.get("name") == name), None)
    if p is None:
        return None
    parts = [x for x in name.lower().split() if len(x) >= 3]
    toks = [t for t in norm.split() if len(t) >= 3]
    ok = any(difflib.SequenceMatcher(None, t, x).ratio() >= 0.6 for t in toks for x in parts)
    return p if ok else None


def validate_filter(raw: dict, text: str, game: dict, types: list[str]) -> dict | None:
    """Keep only the fields of an LLM filter that the query text grounds. Returns
    `{filt, label, player, window, time_label, dropped}` or None when nothing survives."""
    norm = _normalize(text)
    players = game.get("players") or []
    duration = float((game.get("video") or {}).get("duration_s") or 0.0)
    dropped: list[str] = []
    et = raw.get("event_type")
    if et not in types or not re.search(TYPES.get(et, (r"(?!)",))[0], norm):
        if et not in (None, "none"):
            dropped.append(f"event_type={et}")
        et = None
    player = None
    if raw.get("player") not in (None, "none"):
        player = _grounded_player(raw["player"], norm, players)
        if player is None:
            dropped.append(f"player={raw['player']}")
    if et is None and player is None:
        return None
    et = et or "shot"  # a player alone means their shots, as in the rule path (H1)
    filt: dict[str, Any] = {"type": et}
    if et in SUBTYPES:
        filt = {"type": "possession_change", "cause": SUBTYPES[et]}
    value = {"three": 3, "two": 2}.get(raw.get("shot_value"))
    if value:
        if et == "shot" and VALUE_WORDS[value].search(norm):
            filt["points"] = value
        else:
            dropped.append(f"shot_value={raw['shot_value']}")
    result = raw.get("result")
    if result in ("made", "missed"):
        words = MADE_WORDS if result == "made" else MISS_WORDS
        if et == "shot" and words.search(norm):
            filt["made"] = result == "made"
        else:
            dropped.append(f"result={result}")
    if raw.get("longest"):
        if " long" in norm:
            filt.update(sort="duration_desc", limit=10)
        else:
            dropped.append("longest")
    window, time_label = None, ""
    half = raw.get("half")
    if half in ("first", "second"):
        said = {"first": (" first half ", " 1st half "), "second": (" second half ", " 2nd half ")}
        if any(s in norm for s in said[half]) and duration:
            mid = duration / 2
            window = (0.0, mid) if half == "first" else (mid, duration)
            time_label = "1st half" if half == "first" else "2nd half"
        else:
            dropped.append(f"half={half}")
    what = {True: "made ", False: "missed "}.get(filt.get("made"), "")
    what += {3: "three-point ", 2: "two-point "}.get(filt.get("points"), "")
    noun = et.replace("_", " ")
    label = (
        ("longest " if "sort" in filt else "") + what + noun + ("es" if noun.endswith("s") else "s")
    )
    return {"filt": filt, "label": label, "player": player, "window": window,
            "time_label": time_label, "dropped": dropped}  # fmt: skip


class LLMQueryEngine(RuleQueryEngine):
    """Rules first: a query whose event words the rule vocabulary knows is answered by the
    rules alone. The rest (no match, or only a player name next to words the rules do not
    know, like "every time Quinn stole the ball") goes to the LLM, whose filter is then
    validated against the query text, the roster and the sport's event types; if nothing
    survives validation the rule answer stands."""

    name = "llm"

    def __init__(self, vocab: dict[str, dict] | None = None, llm: Any = None):
        super().__init__(vocab)
        self.llm = llm

    def query(self, text: str, game: dict, events: list[dict]) -> dict:
        out = super().query(text, game, events)
        if self.llm is None or _match_vocab(_normalize(text), self.vocab)[0] is not None:
            return out
        from . import NotConfiguredError

        types = {e.get("type") for e in events if e.get("type")}
        types |= {f["type"] for f in self.vocab.values()}
        if "possession_change" in types:
            types |= set(SUBTYPES)
        types = sorted(t for t in types if t in TYPES)
        names = sorted({p["name"] for p in game.get("players") or [] if p.get("name")})
        prompt = json.dumps({"request": text, "sport": game.get("sport"), "players": names,
                             "event_types": {t: TYPES[t][1] for t in types}})  # fmt: skip
        try:
            raw = json.loads(self.llm.complete(prompt, system=LLM_SYSTEM,
                                               json_schema=filter_schema(types, names),
                                               max_tokens=120))  # fmt: skip
        except NotConfiguredError:
            return out
        except (OSError, ValueError) as exc:  # server down / bad JSON: the rule answer stands
            return {**out, "llm_error": f"{type(exc).__name__}: {exc}"}
        v = validate_filter(raw, text, game, types)
        if v is None:  # nothing the text grounds: the rule answer stands
            return {**out, "llm_filter": raw, "dropped": ["everything"]}
        res = self.execute(v["filt"], v["label"], v["player"], v["window"], v["time_label"],
                           game, events)  # fmt: skip
        return {**res, "source": "llm", "llm_filter": raw, "dropped": v["dropped"]}


def get_query_engine(
    name: str, vocab: dict[str, dict] | None = None, llm: Any = None
) -> QueryEngine:
    if name == "rules":
        return RuleQueryEngine(vocab)
    if name == "llm":
        if llm is None:
            from . import create

            llm = create("llm")
        return LLMQueryEngine(vocab, llm)
    raise ValueError(f"query engine {name!r} is not available (rules | llm)")
