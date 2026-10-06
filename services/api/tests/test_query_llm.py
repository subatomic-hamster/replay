"""Free text -> LLM structured filter -> deterministic validator (vision 22). Fake LLM."""

from __future__ import annotations

import json

from replay_api.providers import NotConfiguredError
from replay_api.providers.query import (
    LLMQueryEngine,
    filter_schema,
    get_query_engine,
    validate_filter,
)

from .test_query import EVENTS, GAME


class FakeLLM:
    def __init__(self, reply: dict | Exception):
        self.reply = reply
        self.prompts: list[dict] = []

    def complete(self, prompt, *, system=None, json_schema=None, max_tokens=512):
        self.prompts.append({"prompt": json.loads(prompt), "schema": json_schema})
        if isinstance(self.reply, Exception):
            raise self.reply
        return json.dumps(self.reply)


EVERYTHING = {"event_type": "shot", "result": "made", "player": "Marcus", "half": "second",
              "longest": True}  # fmt: skip


def test_rules_answer_first_llm_never_called():
    llm = FakeLLM(EVERYTHING)
    out = LLMQueryEngine(llm=llm).query("Marcus makes", GAME, EVENTS)
    assert out["interpretation"] == "Marcus — made shots" and not llm.prompts


def test_llm_filter_keeps_only_what_the_text_grounds():
    llm = FakeLLM(EVERYTHING)
    out = LLMQueryEngine(llm=llm).query("did Mark ever score", GAME, EVENTS)
    assert out["source"] == "llm"
    assert out["interpretation"] == "Marcus — made shots"
    assert [c["event_id"] for c in out["clips"]] == ["e_0001"]
    assert sorted(out["dropped"]) == ["half=second", "longest"]
    schema = llm.prompts[0]["schema"]
    assert set(schema["properties"]) == {
        "event_type", "result", "shot_value", "player", "half", "longest"}  # fmt: skip
    assert "Marcus" in schema["properties"]["player"]["enum"]


def test_hallucinated_filter_is_dropped_entirely():
    llm = FakeLLM({"event_type": "shot", "result": "made", "player": "Alex", "half": "any",
                   "longest": False})  # fmt: skip
    out = LLMQueryEngine(llm=llm).query("show the crowd going wild", GAME, EVENTS)
    assert out["clips"] == [] and out["dropped"] == ["everything"]


def test_player_only_rule_match_still_asks_the_llm_for_the_event():
    game = {**GAME, "video": {"duration_s": 20.0}}
    events = EVENTS + [
        {"id": "s1", "type": "possession_change", "cause": "steal", "player_id": "p1",
         "t_start": 3.0, "t_key": 3.0, "t_end": 3.5},
        {"id": "s2", "type": "possession_change", "cause": "inbound", "player_id": "p1",
         "t_start": 9.0, "t_key": 9.0, "t_end": 9.5},
    ]  # fmt: skip
    llm = FakeLLM({"event_type": "steal", "result": "made", "shot_value": "three",
                   "player": "Marcus", "half": "any", "longest": False})  # fmt: skip
    out = LLMQueryEngine(llm=llm).query("every time Marcus stole the ball", game, events)
    assert out["source"] == "llm" and out["event_ids"] == ["s1"]
    assert out["interpretation"] == "Marcus — steals"
    assert sorted(out["dropped"]) == ["result=made", "shot_value=three"]
    assert "steal" in llm.prompts[0]["prompt"]["event_types"]


def test_made_only_for_shots():
    v = validate_filter({"event_type": "bookmark", "result": "made", "player": "none",
                         "half": "any", "longest": False},
                        "my saved bookmarks that were made", GAME, ["bookmark", "shot"])  # fmt: skip
    assert v["filt"] == {"type": "bookmark"} and v["dropped"] == ["result=made"]


def test_unconfigured_llm_falls_back_to_rules():
    out = LLMQueryEngine(llm=FakeLLM(NotConfiguredError("llm"))).query("zzz", GAME, EVENTS)
    assert out == {"interpretation": "No match", "clips": []}
    out = LLMQueryEngine(llm=FakeLLM(OSError("refused"))).query("zzz", GAME, EVENTS)
    assert out["clips"] == [] and "refused" in out["llm_error"]


def test_engine_selection():
    assert get_query_engine("rules").name == "rules"
    assert get_query_engine("llm", llm=FakeLLM({})).name == "llm"
    assert "time" not in json.dumps(filter_schema(["shot"], ["A"]))
