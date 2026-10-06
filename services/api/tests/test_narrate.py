"""M7: narration audio layout, advice, and the commentary / advice / search endpoints
(fake TTS, LLM and embeddings: no model, no GPU)."""

from __future__ import annotations

import itertools
import json
import math
import wave
from pathlib import Path

import numpy as np
from replay_api.narrate import advice as A
from replay_api.narrate import commentary as C
from replay_api.narrate import search as S

from .conftest import ready_game

SR = 24000


class FakeTTS:
    """0.05 s of tone per word, so the layout is predictable."""

    def __init__(self):
        self.calls = 0

    def synthesize_many(self, items, *, voice=None):
        self.calls += 1
        for text, path in items:
            n = int(0.05 * len(text.split()) * SR)
            a = (0.1 * np.sin(np.arange(n) * 2 * math.pi * 220 / SR) * 32767).astype("<i2")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SR)
                w.writeframes(a.tobytes())
        return {"items": len(items)}


GAME = {
    "id": "g_t",
    "sport": "basketball",
    "video": {"duration_s": 20.0},
    "players": [{"id": "p1", "name": "Marcus", "team": 0}, {"id": "p2", "name": "Alex", "team": 1}],
}
EVENTS = [
    {"id": "e1", "type": "pass", "t_key": 1.0, "player_id": "p1", "receiver_id": "p2"},
    {"id": "e2", "type": "shot", "t_key": 1.1, "t_end": 2.0, "made": True, "points": 3,
     "player_id": "p2", "team": 1},
]  # fmt: skip
PLAYS = [{"id": "pl1", "t_start": 0.5, "t_end": 3.0, "event_ids": ["e1", "e2"]}]
SCORE = [{"t": 2.0, "scores": [0, 3], "event_id": "e2"}]


def test_narration_lines_follow_events_without_overlap(tmp_path):
    script = C.game_script(GAME, EVENTS, PLAYS, SCORE)
    texts = [ln["text"] for ln in script["plays"][0]["lines"]]
    assert texts == ["Marcus finds Alex.", "Alex knocks down the three!", "That puts it at 0 to 3."]
    info = C.narrate(script, FakeTTS(), tmp_path, duration_s=20.0)
    lines = script["plays"][0]["lines"]
    assert info["lines"] == 3
    for a, b in itertools.pairwise(lines):
        assert b["audio_t"] >= a["audio_t"] + a["audio_s"]  # never talks over itself
    assert all(ln["audio_t"] >= ln["t"] for ln in lines)  # never ahead of the play
    assert lines[0]["audio_t"] == 1.0
    with wave.open(str(tmp_path / "narration.wav")) as w:
        assert abs(w.getnframes() / w.getframerate() - 20.0) < 0.01
    assert (tmp_path / "pl1.wav").is_file() and script["plays"][0]["audio"] == "pl1.wav"


def test_advice_is_grounded_and_compares_shot_values():
    shots = [(2, True), (2, True), (2, True), (2, False), (3, False), (3, False), (3, True)]
    events = [{"id": f"s{i}", "type": "shot", "made": m, "points": v, "player_id": "p1",
               "team": 0} for i, (v, m) in enumerate(shots)]  # fmt: skip
    events += [{"id": "t1", "type": "turnover", "player_id": "p1", "team": 0}]
    stats = {"box_score": [
        {"player_id": "p1", "team": 0, "samples": 100, "distance_m": 812.4},
        {"player_id": "p3", "team": 0, "samples": 100, "distance_m": 700.0},
    ]}  # fmt: skip
    out = A.player_advice(GAME, events, [], stats, "p1")
    assert out["grounding"]["template_ok"], out["grounding"]
    assert out["lines"] == [
        "Marcus shot 4 for 7 (57%).",
        "Inside the arc: 3 for 4.",
        "From three: 1 for 3.",
        (
            "Marcus is more efficient inside the arc (75% against 33% from three): worth looking"
            " for more of those shots."
        ),
        "Marcus had 1 turnovers.",
        "Marcus covered 812 metres; the team average was 756 metres.",
    ]


def test_advice_llm_paraphrase_must_stay_grounded():
    events = [{"id": "s1", "type": "shot", "made": True, "points": 2, "player_id": "p1"}]

    class LLM:
        def __init__(self, line):
            self.line = line

        def complete(self, prompt, *, system=None, json_schema=None, max_tokens=512):
            n = json_schema["properties"]["lines"]["minItems"]
            return json.dumps({"lines": [self.line] * n})

    bad = A.player_advice(GAME, events, [], {}, "p1", llm=LLM("Marcus should bend the knees."))
    assert bad["source"] == "template" and not bad["llm"]["accepted"]
    good = A.player_advice(GAME, events, [], {}, "p1", llm=LLM("Marcus went 1 for 1, 100%!"))
    assert good["source"] == "llm" and good["lines"] == ["Marcus went 1 for 1, 100%!"] * 2


def test_net_sport_advice_counts_rallies():
    game = {"id": "g", "sport": "pickleball",
            "players": [{"id": "p1", "name": "Sam", "team": 0}, {"id": "p2", "name": "Jo", "team": 1}]}  # fmt: skip
    events = [
        {"id": "a", "type": "serve", "player_id": "p1", "team": 0},
        {"id": "b", "type": "rally", "contacts": 5, "winner_side": 0},
        {"id": "c", "type": "point", "winner_side": 0, "cause": "winner", "player_id": "p1",
         "team": 0},
        {"id": "d", "type": "rally", "contacts": 3, "winner_side": 1},
        {"id": "e", "type": "point", "winner_side": 1, "cause": "net", "player_id": "p1", "team": 0},
    ]  # fmt: skip
    plays = [
        {"id": "r1", "grammar": "rally", "event_ids": ["a", "b", "c"],
         "participants": [{"player_id": "p1", "role": "server"}]},
        {"id": "r2", "grammar": "rally", "event_ids": ["d", "e"],
         "participants": [{"player_id": "p1", "role": "hitter"}]},
    ]  # fmt: skip
    out = A.player_advice(game, events, plays, {}, "p1")
    assert out["grounding"]["template_ok"], out["grounding"]
    assert "Sam's team took 1 of the 2 rallies Sam played." in out["lines"]
    assert "Sam ended rallies 1 with a winner, 1 into the net." in out["lines"]


# --- API -------------------------------------------------------------------------------


def test_commentary_endpoints_from_events(client, settings):
    gid = ready_game(client, settings)
    r = client.get(f"/games/{gid}/commentary")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["schema"] == "replay.commentary.v1" and doc["stored"] is False
    assert doc["summary"]["plays"] == 3 == doc["summary"]["template_grounded"]
    first = doc["plays"][0]
    assert first["lines"][0]["text"] == "Marcus scores!" and first["audio_url"] is None
    assert "facts" not in first
    one = client.get(f"/games/{gid}/plays/{first['play_id']}/commentary").json()
    assert one["facts"]["players"] == {"p1": "Marcus"}
    assert client.get(f"/games/{gid}/plays/nope/commentary").status_code == 404
    # llm=true without a configured LLM: the template stays, the error is reported
    client.app.state.llm.url = ""  # whatever REPLAY_LLM_URL the shell has
    doc = client.get(f"/games/{gid}/commentary?llm=true").json()
    assert all(s["source"] == "template" for s in doc["plays"])
    assert "NotConfiguredError" in doc["plays"][0]["llm"]["error"]


def test_stored_script_and_audio_urls(client, settings):
    gid = ready_game(client, settings)
    gd = settings.games_dir / gid
    _, events, plays, score = C.load_docs(gd)
    game = json.loads((gd / "game.json").read_text())
    script = C.game_script(game, events, plays, score)
    C.narrate(script, FakeTTS(), gd / "commentary", duration_s=20.0)
    (gd / "commentary" / "script.json").write_text(json.dumps(script))
    doc = client.get(f"/games/{gid}/commentary").json()
    assert doc["stored"] is True
    assert doc["narration_url"].endswith(f"/media/games/{gid}/commentary/narration.wav")
    assert doc["plays"][0]["audio_url"].endswith(".wav")
    assert client.get(doc["narration_url"]).status_code == 200


def test_advice_endpoint(client, settings):
    gid = ready_game(client, settings)
    r = client.get(f"/games/{gid}/players/p1/advice")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lines"][0] == "Marcus shot 1 for 2 (50%)."
    assert body["grounding"]["template_ok"]
    assert client.get(f"/games/{gid}/players/p9/advice").status_code == 404


class FakeEmb:
    """Bag-of-words text vectors; every image looks the same."""

    DIM = 32

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.DIM)
        for w in text.lower().split():
            v[sum(map(ord, w.strip(".!,"))) % self.DIM] += 1
        return (v / max(np.linalg.norm(v), 1e-9)).tolist()

    def embed_texts(self, texts):
        return [self._vec(t) for t in texts]

    def embed_images(self, paths):
        return [[1.0] + [0.0] * (self.DIM - 1) for _ in paths]


def _index(gd: Path, emb: FakeEmb) -> dict:
    game, events, plays, score = C.load_docs(gd)
    ps = C.game_plays(plays, events)
    texts = {p["id"]: S.play_text(game, p, events, score) for p in ps}
    (gd / "embeddings").mkdir(exist_ok=True)
    for p in ps:
        vec = np.asarray([emb.embed_images(["x"])[0], emb.embed_texts([texts[p["id"]]])[0]])
        np.save(gd / "embeddings" / f"{S.safe_id(p['id'])}.npy", vec.astype(np.float32))
    return S.write_index(gd, ps, texts, "fake")


def test_search_ranks_and_reranks_by_filter(client, settings):
    gid = ready_game(client, settings)
    assert client.post(f"/games/{gid}/search", json={"text": "x"}).status_code == 409
    emb = FakeEmb()
    idx = _index(settings.games_dir / gid, emb)
    assert len(idx["plays"]) == 3
    client.app.state.embeddings = emb
    r = client.post(f"/games/{gid}/search", json={"text": "Alex scores", "k": 3})
    assert r.status_code == 200, r.text
    res = r.json()["results"]
    assert res[0]["text"] == "basketball play. Alex scores!"
    # the structured filter (rules: Marcus's missed shots) wins over similarity
    r = client.post(f"/games/{gid}/search", json={"text": "Marcus misses", "k": 3}).json()
    assert r["interpretation"] == "Marcus — missed shots"
    assert r["results"][0]["filter_match"] and "Marcus shoots, no good." in r["results"][0]["text"]
    assert [x["filter_match"] for x in r["results"]] == [True, False, False]


def test_query_words_break_flat_similarity(tmp_path):
    texts = ["Sam brings it in.", "Alex with the steal! Alex scores two.", "Sam pulls down the rebound."]  # fmt: skip
    rows = []
    for i, t in enumerate(texts):
        np.save(tmp_path / f"{i}.npy", np.ones((2, 4), np.float32))  # SigLIP-flat cosines
        rows.append({"id": f"pl_{i}", "t_start": i, "t_end": i + 1, "text": t, "file": f"{i}.npy"})
    idx = {"plays": rows}
    q = [1.0, 1.0, 1.0, 1.0]
    assert S.rank(tmp_path, idx, q, query_text="a steal", k=1)[0]["play_id"] == "pl_1"
    assert S.rank(tmp_path, idx, q, query_text="rebounds", k=1)[0]["play_id"] == "pl_2"


def test_search_without_model_is_503(client, settings, monkeypatch):
    monkeypatch.delenv("REPLAY_MODEL_VENVS", raising=False)  # the box exports it
    gid = ready_game(client, settings)
    _index(settings.games_dir / gid, FakeEmb())
    r = client.post(f"/games/{gid}/search", json={"text": "anything"})
    assert r.status_code == 503 and "embeddings" in r.json()["detail"]
