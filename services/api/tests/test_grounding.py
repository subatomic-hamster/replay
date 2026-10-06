"""Grounding check (vision "Grounding"): adversarial paraphrases are rejected, grounded
ones pass, and every template line over every synthetic play passes (the guaranteed
path must be 100 %)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from replay_api.narrate import commentary as C
from replay_api.narrate import grounding as G

SYNTH = Path(__file__).resolve().parents[3] / "samples" / "synthetic"
NAMES = ["Alex", "Sam", "Jordan", "Riley", "Casey", "Morgan", "Taylor", "Jamie", "Avery",
         "Quinn", "Drew", "Blake"]  # fmt: skip

GAME = {
    "id": "g_test",
    "sport": "basketball",
    "players": [
        {"id": "p1", "name": "Alex", "team": 0},
        {"id": "p3", "name": "Jordan", "team": 0},
        {"id": "p5", "name": "Casey", "team": 0},
        {"id": "p7", "name": "Morgan", "team": 1},
        {"id": "p10", "name": "Quinn", "team": 1},
    ],
    "teams": [{"id": 0}, {"id": 1}],
}
POSSESSION = [
    {"id": "e1", "type": "possession_change", "cause": "inbound", "player_id": "p3", "team": 0},
    {"id": "e2", "type": "pass", "player_id": "p3", "receiver_id": "p5", "team": 0},
    {"id": "e3", "type": "shot", "made": True, "points": 2, "player_id": "p5", "team": 0},
]
FACTS = G.build_facts(
    GAME, POSSESSION, participants=[{"player_id": "p1", "role": "inbounder"}], score=[2, 0]
)

NET_GAME = {
    "id": "g_net",
    "sport": "badminton",
    "players": [
        {"id": "p1", "name": "Alex", "team": 0},
        {"id": "p2", "name": "Sam", "team": 0},
        {"id": "p4", "name": "Riley", "team": 1},
    ],
}
RALLY = [
    {"id": "e1", "type": "serve", "player_id": "p1", "team": 0},
    {"id": "e2", "type": "rally", "contacts": 8, "winner_side": 0},
    {"id": "e3", "type": "point", "winner_side": 0, "cause": "net", "player_id": "p4", "team": 1},
]
NET_FACTS = G.build_facts(
    NET_GAME, RALLY, participants=[{"player_id": p, "role": "hitter"} for p in ("p1", "p4")]
)


@pytest.mark.parametrize(
    "text, kind",
    [
        ("LeBron scores two.", "unknown_name"),
        ("Quinn scores two.", "absent_player"),
        ("Casey knocks down the three!", "absent_shot_value"),
        ("Casey drains a three-pointer from way out.", "absent_shot_value"),
        ("Casey misses the shot.", "absent_action"),
        ("Jordan scores two.", "wrong_actor"),
        ("Casey finds Jordan.", "wrong_direction"),
        ("Casey with the steal!", "absent_action"),
        ("Casey scores 4.", "absent_number"),
        ("Casey scores twenty-two.", "absent_number"),
        ("Casey scores two with 5 seconds left.", "absent_number"),
        ("Casey throws down a dunk!", "invented_fact"),
        ("Casey scores two on the fast break.", "invented_fact"),
        ("Casey hits the layup.", "invented_fact"),
        ("Casey's form on that jumper is perfect.", "invented_fact"),  # no biomechanics
        ("He scores two.", "invented_attribute"),
        ("Jordan finds Casey and she scores.", "invented_attribute"),
        ("Team B leads 2 to 0.", "absent_score_state"),
        ("It's tied at 2.", "absent_score_state"),
        ("Casey scores two in the 3rd quarter.", "absent_number"),
        ("Player 9 scores two.", "absent_number"),
        ("Team B brings it in.", "wrong_actor"),  # Jordan (Team A) inbounded
        ("Casey wins it for Team A.", "absent_action"),  # nothing was won
        ("Casey grabs the offensive rebound.", "absent_action"),
        ("", "empty"),
    ],
)
def test_adversarial_lines_are_rejected(text, kind):
    rep = G.check(text, FACTS)
    assert not rep["ok"]
    assert kind in {v["kind"] for v in rep["violations"]}, rep


@pytest.mark.parametrize(
    "text",
    [
        "Jordan brings it in, finds Casey, and Casey scores two!",
        "Casey puts it in for two.",
        "Team A leads 2 to 0.",
        "Alex inbounds to Jordan.",  # plays.json names Alex the inbounder
        "What a pass from Jordan to Casey!",
        "That puts it at 2 to 0.",
        "Stay sharp, Casey — you're hitting them.",  # coaching tone, no new fact
    ],
)
def test_grounded_paraphrases_pass(text):
    rep = G.check(text, FACTS)
    assert rep["ok"], rep["violations"]


@pytest.mark.parametrize(
    "text, ok",
    [
        ("Riley hits the net. Point to Team A.", True),
        ("That rally ran 8 touches.", True),
        ("Alex serves.", True),
        ("Riley wins the point.", False),  # Riley's side lost it
        ("Point to Team B.", False),
        ("Alex serves an ace!", False),
        ("That rally ran 9 touches.", False),
        ("Sam smashes it home.", False),  # stroke types are not in the events
    ],
)
def test_net_sport_claims(text, ok):
    assert G.check(text, NET_FACTS)["ok"] is ok


def test_label_digits_are_not_numbers():
    game = {"players": [{"id": "p5", "name": None, "team": 0}]}
    facts = G.build_facts(game, [{"id": "e", "type": "shot", "made": True, "player_id": "p5"}])
    assert G.check("Player 5 scores!", facts)["ok"]
    assert not G.check("Player 5 scores 5!", facts)["ok"]


def _synthetic_games():
    for ev_path in sorted(SYNTH.glob("*/*/events.json")):
        plays_path = ev_path.with_name("plays.json")
        if plays_path.is_file():
            yield ev_path.parent.relative_to(SYNTH).as_posix(), ev_path, plays_path


def _game(events: list[dict], sport: str, named: bool) -> dict:
    pids = sorted({e[k] for e in events for k in ("player_id", "receiver_id") if e.get(k)},
                  key=lambda p: int(p[1:]))  # fmt: skip
    team = {e["player_id"]: e.get("team") for e in events if e.get("player_id")}
    return {
        "id": "g_synth",
        "sport": sport,
        "players": [
            {
                "id": p,
                "name": NAMES[(int(p[1:]) - 1) % len(NAMES)] if named else None,
                "team": team.get(p),
            }
            for p in pids
        ],
    }


def _with_points(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """What the plays stage adds (synthetic test data): shot values and a running score."""
    out, score, s = [], [], [0, 0]
    for i, e in enumerate(sorted(events, key=lambda e: e["t_key"])):
        e = dict(e)
        if e["type"] == "shot":
            e["points"] = 3 if i % 2 else 2
            if e.get("made"):
                s[e["team"]] += e["points"]
                score.append({"t": e["t_key"], "scores": list(s), "event_id": e["id"]})
        if e["type"] == "point":
            s[e["winner_side"]] += 1
            score.append({"t": e["t_key"], "scores": list(s), "event_id": e["id"]})
        out.append(e)
    return out, score


@pytest.mark.parametrize("named", [True, False])
@pytest.mark.parametrize("scored", [True, False])
def test_templates_are_grounded_on_every_synthetic_play(named, scored):
    games = list(_synthetic_games())
    assert len(games) >= 5
    total = 0
    for name, ev_path, plays_path in games:
        doc = json.loads(ev_path.read_text())
        events, score = _with_points(doc["events"]) if scored else (doc["events"], [])
        plays = json.loads(plays_path.read_text())["plays"]
        script = C.game_script(_game(events, doc["sport"], named), events, plays, score)
        for s in script["plays"]:
            assert s["lines"], f"{name} {s['play_id']}: no lines"
            assert s["grounding"]["template_ok"], (name, s["play_id"], s["grounding"])
        total += len(script["plays"])
    assert total >= 15


class FakeLLM:
    def __init__(self, lines_for):
        self.lines_for = lines_for
        self.calls = 0

    def complete(self, prompt, *, system=None, json_schema=None, max_tokens=512):
        self.calls += 1
        n = json_schema["properties"]["lines"]["minItems"]
        return json.dumps({"lines": self.lines_for(json.loads(prompt), n)})


def test_llm_paraphrase_falls_back_to_template_when_ungrounded():
    plays = [{"id": "pl1", "t_start": 0, "t_end": 9, "event_ids": ["e1", "e2", "e3"]}]
    ev = [{**e, "t_key": float(i)} for i, e in enumerate(POSSESSION)]

    def invent(view, n):
        return ["Casey with a monster dunk!"] * n

    s = C.game_script(GAME, ev, plays, llm=FakeLLM(invent))["plays"][0]
    assert s["source"] == "template" and not s["llm"]["accepted"]
    assert {v["kind"] for v in s["llm"]["violations"]} >= {"invented_fact"}

    def faithful(view, n):
        return ["Jordan brings it in.", "Jordan feeds Casey.", "Casey puts it in for two!",
                "That puts it at 2 to 0."][:n]  # fmt: skip

    score = [{"t": 2.0, "scores": [2, 0], "event_id": "e3"}]
    s = C.game_script(GAME, ev, plays, score, llm=FakeLLM(faithful))["plays"][0]
    assert s["source"] == "llm" and s["llm"]["accepted"], s["llm"]
    assert s["template_lines"][2] == "Casey scores two."
    assert [ln["t"] for ln in s["lines"]] == sorted(ln["t"] for ln in s["lines"])


def test_events_without_plays_become_one_event_plays():
    ev = [{**e, "t_key": float(i), "t_start": float(i), "t_end": i + 1.0}
          for i, e in enumerate(POSSESSION)]  # fmt: skip
    script = C.game_script(GAME, ev, [])
    assert [s["play_id"] for s in script["plays"]] == ["ev_e3"]
    assert script["plays"][0]["derived_from"] == "event"
    assert script["plays"][0]["lines"][0]["text"] == "Casey scores two."
