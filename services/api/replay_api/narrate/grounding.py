"""Grounding: generated text may only state facts present in the structured input.

`build_facts` turns a slice of the game's JSON (roster, events, score) into the facts a
text is allowed to state; `check` extracts every claim it can recognise from a text and
rejects it when a claim is absent from those facts:

- names: every roster name in the text must be one of the players this text may name;
  any other capitalised word must be ordinary English from `COMMON` (an invented
  "LeBron" fails)
- numbers: digits, number words and ordinals must be numbers in the facts (points,
  rally lengths, the score, the stats an advice line cites); timestamps never are
- actions: verbs are mapped to classes (score, miss, pass, steal, ...); a class must
  occur in the events, and when the sentence names players one of them must be an actor
  of that class (pass and steal also check direction: "B finds A" when A passed to B)
- shot values: "three-pointer", "from deep", "two points" must match a shot with those
  `points` (and made/missed as the sentence says)
- score claims: "leads" / "tied" must match the score after the play
- team claims: a team named next to an action must have an actor of that action
  ("Team B brings it in"); "offensive" / "defensive" must match the rebound's cause
- invented facts: shot types and situations the events never carry (dunk, layup, foul,
  buzzer-beater, fast break, stroke types, court zones, body mechanics) and gendered
  pronouns (the roster has no gender)

The check is deliberately conservative: a false rejection only costs the LLM paraphrase
(the template is used instead); a false acceptance would put an invented fact on air.
ponytail: English-only lexicon; a new sport's verbs need entries here.
"""

from __future__ import annotations

import re
from typing import Any

# --- labels -----------------------------------------------------------------------------


def player_label(p: dict) -> str:
    name = (p.get("name") or "").strip()
    return name or id_label(p["id"])


def id_label(pid: str) -> str:
    m = re.fullmatch(r"p_?0*(\d+)", pid)
    return f"Player {m.group(1)}" if m else pid


def team_labels(game: dict) -> dict[int, str]:
    teams = game.get("teams") or [{"id": 0}, {"id": 1}]
    return {int(t["id"]): (t.get("name") or f"Team {'AB'[int(t['id']) % 2]}") for t in teams}


def roster(game: dict) -> dict[str, str]:
    return {p["id"]: player_label(p) for p in game.get("players") or []}


# --- facts ------------------------------------------------------------------------------

# a play participant's role vouches for the matching action class
ROLE_CLASS = {
    "inbounder": "inbound",
    "stealer": "steal",
    "shooter": "shot",
    "passer": "pass",
    "receiver": "pass",
    "server": "serve",
    "rebounder": "rebound",
    "turnover": "turnover",
    "blocker": "block",
}


def build_facts(
    game: dict,
    events: list[dict],
    *,
    participants: list[dict] = (),
    score: list[int] | None = None,
    numbers: tuple[int, ...] | list[int] = (),
    sport: str | None = None,
) -> dict[str, Any]:
    """The facts a text about `events` may state. JSON-serialisable (it is also the LLM's
    prompt and the stored grounding report). No timestamps or coordinates go in."""
    names = roster(game)
    team_of = {p["id"]: p.get("team") for p in game.get("players") or []}
    for e in events:  # the event's team wins over a missing roster team
        if e.get("player_id") and team_of.get(e["player_id"]) is None:
            team_of[e["player_id"]] = e.get("team")
    allowed = {e[k] for e in events for k in ("player_id", "receiver_id") if e.get(k)}
    allowed |= {p["player_id"] for p in participants if p.get("player_id")}
    for pid in allowed:
        names.setdefault(pid, id_label(pid))
    teams = team_labels(game)

    actions: dict[str, set[str]] = {}
    pairs: dict[str, set[tuple[str, str]]] = {"pass": set(), "steal": set()}
    values: list[dict] = []
    nums = {int(n) for n in numbers}
    point_winners: set[str] = set()

    def add(cls: str, *pids: str | None) -> None:
        actions.setdefault(cls, set()).update(p for p in pids if p)

    losers = set()
    for e in events:
        typ, a, b, cause = e.get("type"), e.get("player_id"), e.get("receiver_id"), e.get("cause")
        if typ == "shot":
            add("shot", a)
            if e.get("made") is True:
                add("score", a)
            elif e.get("made") is False:
                add("miss", a)
            if e.get("points"):
                values.append({"points": int(e["points"]), "made": e.get("made"), "player": a})
                nums.add(int(e["points"]))
        elif typ == "pass":
            add("pass", a, b)
            if a and b:
                pairs["pass"].add((a, b))
        elif typ == "possession_change":
            if cause == "steal":
                add("steal", a)
            elif cause == "inbound":
                add("inbound", a)
            elif cause and "rebound" in cause:
                add("rebound", a)
        elif typ == "turnover":
            add("turnover", a)
            if cause == "steal":
                add("steal")
                losers.add(a)
        elif typ in ("block", "serve", "contact"):
            add(typ, a)
        elif typ == "rally":
            add("rally")
            if isinstance(e.get("contacts"), int):
                nums.add(e["contacts"])
        elif typ == "point":
            w = e.get("winner_side")
            add("point", *[p for p in allowed if w is not None and team_of.get(p) == w])
            if w in teams:
                point_winners.add(teams[w])
            if cause in ("net", "out", "winner"):
                add(cause, a)
        elif typ == "hype":
            add("crowd")
    for p in participants:
        cls = ROLE_CLASS.get(p.get("role", ""))
        if cls and cls in actions:
            add(cls, p.get("player_id"))
    pairs["steal"] = {(s, lo) for s in actions.get("steal", ()) for lo in losers if lo and s != lo}

    leader, tied = None, False
    if score is not None:
        nums.update(int(s) for s in score)
        a0, a1 = score
        tied = a0 == a1
        leader = None if tied else teams.get(0 if a0 > a1 else 1)
    return {
        "sport": sport or game.get("sport"),
        "roster": names,
        "players": {pid: names[pid] for pid in sorted(allowed)},
        "teams": {str(k): v for k, v in teams.items()},
        "events": [_event_view(e, names) for e in events],
        "score": list(score) if score is not None else None,
        "leader": leader,
        "tied": tied,
        "numbers": sorted(nums),
        "actions": {k: sorted(v) for k, v in sorted(actions.items())},
        "pairs": {k: sorted(v) for k, v in pairs.items()},
        "shot_values": values,
        "point_winners": sorted(point_winners),
        "player_teams": {p: teams[team_of[p]] for p in sorted(allowed) if team_of.get(p) in teams},
        "rebound_causes": sorted(
            {e["cause"] for e in events if "rebound" in (e.get("cause") or "")}
        ),
    }


_EVENT_KEYS = ("type", "made", "points", "cause", "contacts", "winner_side", "team")


def _event_view(e: dict, names: dict[str, str]) -> dict:
    out = {k: e[k] for k in _EVENT_KEYS if e.get(k) is not None}
    for k, as_ in (("player_id", "player"), ("receiver_id", "receiver")):
        if e.get(k):
            out[as_] = names.get(e[k], id_label(e[k]))
    return out


# --- lexicon ----------------------------------------------------------------------------

ACTIONS: dict[str, str] = {
    "shot": r"shoots?|shot|shooting|fires?|fired|puts? (?:it )?up|attempts?|launch(?:es|ed)?"
    r"|pulls? up|lets? it fly|jumper|jump shot",
    "score": r"scores?|scored|scoring|knocks? (?:it )?down|knocked down|bur(?:y|ies|ied)"
    r"|drains?|drained|sinks?|sank|nails?|nailed|converts?|converted|cash(?:es)? in"
    r"|buckets?|it'?s good|connects?|finish(?:es|ed)?|makes? (?:it|the shot|the basket)",
    "miss": r"miss(?:es|ed)?|no good|rims? out|off the rim|clanks?|brick(?:s|ed)?"
    r"|comes? up (?:short|empty)|won'?t fall|doesn'?t fall|off target|falls? short",
    "pass": r"pass(?:es|ed|ing)?|finds?|found|feeds?|fed|dish(?:es|ed)?|swings? it"
    r"|kicks? it|assists?|hands? (?:it )?off|dumps? it",
    "steal": r"steals?|stole|stolen|picks? (?:it )?off|picked off|strips?|stripped"
    r"|swipes?|intercept\w*|pickpocket\w*",
    "turnover": r"turnovers?|turns? it over|turned it over|coughs? (?:it )?up|gives? it away"
    r"|giveaway|loses? (?:the ball|it|possession)",
    "rebound": r"rebounds?|rebounded|boards?|crash(?:es)? the glass|pulls? down",
    "inbound": r"inbounds?|inbounded|inbounding|brings? it in",
    "block": r"blocks?|blocked|rejects?|rejected|swats?|swatted|stuff(?:s|ed)?",
    "serve": r"serves?|served|serving|service",
    "rally": r"rally|rallies",
    "contact": r"contacts?",
    "point": r"wins?|won|takes the point|point (?:to|for|goes)",
    "net": r"(?:the|into the) net",
    "out": r"sends? it (?:out|long|wide)|out of bounds|lands? out|goes? out",
    "winner": r"winners?|puts? it away",
    "crowd": r"crowd|fans|stands",
}
_ACTION_RE = {k: re.compile(rf"\b(?:{v})\b") for k, v in ACTIONS.items()}
# classes whose team claims are checked elsewhere (point: the winning side) or carry none
TEAMLESS = {"point", "rally", "crowd"}

INVENTED = re.compile(
    r"\b(?:dunk\w*|slam\w*|jams?|lay-?ups?|lays? it (?:up|in)|alley[- ]?oops?|hook shot"
    r"|floaters?|fade-?aways?|bank shot|off the glass|free throws?|foul\w*|and[- ]one"
    r"|buzzer\w*|game[- ]winn\w*|go[- ]ahead|clutch|fast break|breakaway|transition"
    r"|timeouts?|quarters?|overtime|halftime|crossover|euro[- ]?step|no[- ]look|swish\w*"
    r"|nothing but net|careers?|seasons?|records?|streaks?|on fire|hot hand|mvp|coach\w*"
    r"|referee\w*|whistle|injur\w*|spikes?|kills?|digs?|smash\w*|dinks?|lobs?|drop shot"
    r"|volley\w*|aces?|faults?|paint|mid-?range|corner|elbow|baseline|wing|top of the key"
    r"|low post|knees?|wrists?|footwork|stance|form|follow[- ]through|balance|posture"
    r"|release|tall|veteran|rookie|dominat\w*|unstoppable|again|first time)\b"
)
GENDERED = re.compile(r"\b(?:he|him|his|himself|she|her|hers|herself|guy|girl|man|woman)\b")
# "for two" claims a shot value, "1 for 2" is a shooting line (not a claim)
THREE = re.compile(
    r"\b(?:three|3)[- ]?(?:pointers?|pt|points?|ball)\b|\b(?:from|(?<!\d )for|a|the) (?:three"
    r"|3|deep|downtown|long range)\b|\bbeyond the arc\b|\btriples?\b"
)
TWO = re.compile(
    r"\b(?:two|2)[- ]?(?:pointers?|points?)\b|\b(?:scores|(?<!\d )for|adds) (?:two|2)\b"
)
LEAD = re.compile(r"\b(?:leads?|leading|ahead|in front|up by)\b")
TIE = re.compile(r"\b(?:tie|tied|ties|level|all square|knotted)\b")

UNITS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen",
]  # fmt: skip
NUM_WORDS = {w: i for i, w in enumerate(UNITS)}
TENS = {w: 10 * (i + 2) for i, w in enumerate(["twenty", "thirty", "forty", "fifty", "sixty"])}
TENS |= {"seventy": 70}
TENS |= {"eighty": 80, "ninety": 90, "hundred": 100}
OTHER_NUMS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "once": 1}
OTHER_NUMS |= {"twice": 2, "double": 2, "triple": 3, "pair": 2, "couple": 2, "dozen": 12}

# capitalised words that are ordinary English, not names (sentence starts, interjections)
COMMON = set(
    [
        "the",
        "a",
        "an",
        "and",
        "but",
        "or",
        "so",
        "then",
        "now",
        "what",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "it's",
        "there",
        "here",
        "with",
        "from",
        "off",
        "on",
        "in",
        "into",
        "to",
        "for",
        "of",
        "by",
        "after",
        "before",
        "as",
        "at",
        "no",
        "not",
        "yes",
        "oh",
        "wow",
        "nice",
        "great",
        "good",
        "big",
        "huge",
        "beautiful",
        "smooth",
        "easy",
        "quick",
        "another",
        "over",
        "up",
        "down",
        "out",
        "back",
        "just",
        "still",
        "and",
        "both",
        "all",
        "every",
        "each",
        "score",
        "rally",
        "point",
        "team",
        "player",
        "players",
        "possession",
        "ball",
        "shot",
        "pass",
        "steal",
        "turnover",
        "serve",
        "look",
        "watch",
        "replay",
        "play",
        "here's",
        "what's",
        "that's",
        "there's",
        "let's",
        "who",
        "will",
        "can",
        "nobody",
        "everyone",
        "inside",
        "side",
        "their",
        "they",
        "them",
        "we",
        "our",
        "you",
        "your",
        "i",
        "my",
        "me",
        "well",
        "yes",
        "ok",
        "okay",
        "right",
        "sure",
        "meanwhile",
        "next",
        "later",
        "early",
        "what",
        "a",
        "how",
        "why",
        "where",
        "when",
        "since",
        "while",
        "if",
        "once",
        "he",
        "she",
        "best",
        "most",
        "more",
        "less",
        "fewer",
        "only",
        "also",
        "too",
        "very",
        "really",
        "quite",
        "much",
        "many",
        "few",
        "some",
        "any",
        "none",
        "made",
        "makes",
        "missed",
        "misses",
        "shooting",
        "passing",
        "scoring",
        "serving",
        "efficient",
        "efficiency",
        "covered",
        "distance",
        "rebound",
        "rebounds",
        "steals",
        "turnovers",
        "serves",
        "points",
        "rallies",
        "shots",
        "passes",
        "assists",
        "blocks",
        "inbound",
        "inbounds",
        "contacts",
        "touches",
        "total",
        "overall",
        "strong",
        "solid",
        "keep",
        "try",
        "focus",
        "consider",
        "work",
        "worth",
        "plenty",
        "listen",
    ]
    # coaching imperatives and contractions that open advice sentences
    + [
        "stay",
        "cover",
        "move",
        "get",
        "take",
        "use",
        "push",
        "aim",
        "practice",
        "watch",
        "hold",
        "look",
        "find",
        "build",
        "trust",
        "attack",
        "defend",
        "drive",
        "shoot",
        "pass",
        "finish",
        "crash",
        "box",
        "hunt",
        "go",
        "let",
        "make",
        "you're",
        "you've",
        "you'll",
        "we're",
        "let's",
        "well",
    ]
)

_TOKEN = re.compile(r"[A-Za-z][A-Za-z'’]*")
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _sentences(text: str) -> list[str]:
    text = text.replace("’", "'").replace("—", ", ").replace("–", "-")
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _variants(label: str) -> list[str]:
    parts = label.split()
    out = [label]
    if len(parts) > 1 and parts[0] not in ("Player", "Team") and len(parts[0]) >= 3:
        out.append(parts[0])  # "Marcus" for "Marcus Smart"
    return out


def _find(sentence: str, labels: dict[str, str]) -> tuple[list[str], str]:
    """Keys whose label occurs (ordered by first occurrence) and the sentence with every
    occurrence blanked, so label digits ("Player 5") never count as stated numbers."""
    hits: list[tuple[int, str]] = []
    out = sentence
    for key, label in sorted(labels.items(), key=lambda kv: -len(kv[1])):
        for var in _variants(label):
            pat = re.compile(rf"(?<![\w]){re.escape(var)}(?![\w])")
            m = pat.search(out)
            if m:
                hits.append((m.start(), key))
                out = pat.sub(" _ ", out)
                break
    return [k for _, k in sorted(hits)], out


def numbers_in(text: str) -> list[float]:
    low = text.lower()
    found: list[float] = [float(n) for n in _NUM.findall(low)]
    toks = re.findall(r"[a-z]+", low)
    i = 0
    while i < len(toks):
        w = toks[i]
        if w in TENS:
            val = TENS[w]
            if i + 1 < len(toks) and toks[i + 1] in NUM_WORDS and 0 < NUM_WORDS[toks[i + 1]] < 10:
                val += NUM_WORDS[toks[i + 1]]
                i += 1
            found.append(float(val))
        elif w in NUM_WORDS:
            found.append(float(NUM_WORDS[w]))
        elif w in OTHER_NUMS:
            found.append(float(OTHER_NUMS[w]))
        i += 1
    return found


def classes_in(sentence_lower: str) -> list[str]:
    return [c for c, rx in _ACTION_RE.items() if rx.search(sentence_lower)]


# --- the check --------------------------------------------------------------------------


def check(text: str, facts: dict) -> dict:
    """`{"ok": bool, "violations": [{"kind", "detail", "sentence"}]}` for `text`."""
    roster_ = facts["roster"]
    allowed = facts["players"]
    teams = {v: v for v in facts["teams"].values()}
    actions = {k: set(v) for k, v in facts["actions"].items()}
    pairs = {k: {tuple(p) for p in v} for k, v in facts["pairs"].items()}
    numbers = {float(n) for n in facts["numbers"]}
    name_tokens = {t for lab in list(roster_.values()) + list(teams) for t in lab.split()}
    out: list[dict] = []

    def bad(kind: str, detail: str, sentence: str) -> None:
        out.append({"kind": kind, "detail": detail, "sentence": sentence})

    if not text.strip():
        bad("empty", "no text", "")
    for sent in _sentences(text):
        names, rest = _find(sent, roster_)
        team_hits, rest = _find(rest, teams)
        low = rest.lower()
        for pid in names:
            if pid not in allowed:
                bad("absent_player", roster_[pid], sent)
        for tok in _TOKEN.findall(rest):
            if tok[0].isupper() and tok not in name_tokens:
                word = re.sub(r"'s?$", "", tok.lower())
                known = COMMON.union(NUM_WORDS, TENS, OTHER_NUMS)
                if word not in known and not classes_in(word):
                    bad("unknown_name", tok, sent)
        for n in numbers_in(rest):
            if n not in numbers:
                bad("absent_number", f"{n:g}", sent)
        for m in INVENTED.finditer(low):
            bad("invented_fact", m.group(0), sent)
        for m in GENDERED.finditer(low):
            bad("invented_attribute", m.group(0), sent)
        found = classes_in(low)
        for cls in found:
            if cls not in actions:
                bad("absent_action", cls, sent)
            elif names and actions[cls] and not set(names) & actions[cls]:
                who = ", ".join(roster_[p] for p in names)
                bad("wrong_actor", f"{cls} by {who}", sent)
            elif cls in pairs and len(names) >= 2:
                fwd, rev = (names[0], names[1]), (names[1], names[0])
                if fwd not in pairs[cls] and rev in pairs[cls]:
                    bad("wrong_direction", f"{cls} {roster_[fwd[0]]} -> {roster_[fwd[1]]}", sent)
            actor_teams = {facts["player_teams"].get(p) for p in actions.get(cls, ())}
            if (
                cls not in TEAMLESS
                and team_hits
                and actor_teams
                and not actor_teams & set(team_hits)
            ):
                bad("wrong_actor", f"{cls} by {', '.join(team_hits)}", sent)
        for side in ("offensive", "defensive"):
            if re.search(rf"\b{side}\b", low) and f"{side}_rebound" not in facts["rebound_causes"]:
                bad("absent_action", f"{side} rebound", sent)
        for rx, value in ((THREE, 3), (TWO, 2)):
            if not rx.search(low):
                continue
            cands = [v for v in facts["shot_values"] if v["points"] == value]
            if names:
                cands = [v for v in cands if v["player"] in names]
            if "score" in found:
                cands = [v for v in cands if v["made"] is True]
            if "miss" in found:
                cands = [v for v in cands if v["made"] is False]
            if not cands:
                bad("absent_shot_value", f"{value}-point shot", sent)
        if LEAD.search(low):
            if not facts.get("leader"):
                bad("absent_score_state", "lead", sent)
            elif team_hits and facts["leader"] not in team_hits:
                bad("absent_score_state", f"lead by {', '.join(team_hits)}", sent)
        if TIE.search(low) and not facts.get("tied"):
            bad("absent_score_state", "tie", sent)
        if "point" in found and team_hits and not set(team_hits) & set(facts["point_winners"]):
            bad("wrong_actor", f"point to {', '.join(team_hits)}", sent)
    return {"ok": not out, "violations": out}
