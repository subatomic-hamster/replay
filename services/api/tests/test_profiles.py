"""M10: profile store, cross-game links, stats aggregation with user overrides, the card,
the career reel and the face-enrollment privacy invariants."""

from __future__ import annotations

import json
import shutil

import pytest
from replay_api.profiles import faces as F
from replay_api.providers import NotConfiguredError
from replay_api.providers.face import LocalFace
from replay_api.providers.profiles import LinkConflict, LocalProfiles, blank

from .conftest import ready_game

# --- store -------------------------------------------------------------------------------


def test_store_roundtrip_links_are_a_db_constraint(tmp_path):
    s = LocalProfiles(tmp_path / "p.sqlite")
    a, b = s.create(blank("Ana")), s.create(blank("Bo"))
    assert [p["name"] for p in s.list()] == ["Ana", "Bo"]
    s.link(a["profile_id"], "g_1", "p1")
    s.link(a["profile_id"], "g_1", "p1")  # idempotent
    with pytest.raises(LinkConflict):
        s.link(b["profile_id"], "g_1", "p1")  # one game player, one profile
    assert s.owner("g_1", "p1") == a["profile_id"]
    assert s.get(a["profile_id"])["linked"] == [{"game_id": "g_1", "player_id": "p1"}]
    doc = s.get(a["profile_id"])
    doc["positions"] = ["guard"]
    s.save(doc)
    assert LocalProfiles(tmp_path / "p.sqlite").get(a["profile_id"])["positions"] == ["guard"]
    assert s.delete(a["profile_id"])
    assert s.owner("g_1", "p1") is None  # links cascade
    assert s.get(a["profile_id"]) is None


# --- linking + stats -----------------------------------------------------------------------


@pytest.fixture
def two_games(client):
    return [ready_game(client, client.app_settings, t) for t in ("Game one", "Game two")]


def _profile(client, name="Jo", **kw):
    r = client.post("/profiles", json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()["profile_id"]


def test_link_names_roster_and_rename_propagates(client, two_games):
    g1, g2 = two_games
    pid = _profile(client, "Jo")
    for g in two_games:
        r = client.post(f"/profiles/{pid}/links", json={"game_id": g, "player_id": "p1"})
        assert r.status_code == 200, r.text
    for g in two_games:
        p1 = next(p for p in client.get(f"/games/{g}").json()["players"] if p["id"] == "p1")
        assert (p1["name"], p1["profile_id"], p1["tagged"]) == ("Jo", pid, True)
    client.patch(f"/profiles/{pid}", json={"name": "Joanna"})
    p1 = next(p for p in client.get(f"/games/{g2}").json()["players"] if p["id"] == "p1")
    assert p1["name"] == "Joanna"
    other = _profile(client, "Other")
    r = client.post(f"/profiles/{other}/links", json={"game_id": g1, "player_id": "p1"})
    assert r.status_code == 409
    r = client.delete(f"/profiles/{pid}/links/{g1}/p1")
    assert r.json()["linked"] == [{"game_id": g2, "player_id": "p1"}]
    p1 = next(p for p in client.get(f"/games/{g1}").json()["players"] if p["id"] == "p1")
    assert "profile_id" not in p1
    assert client.post(f"/profiles/{pid}/links", json={"game_id": g1, "player_id": "nope"}).status_code == 404  # fmt: skip


def test_suggestions_by_name_only_without_enrollment(client, two_games):
    pid = _profile(client, "alex")  # fixture p2 is "Alex"
    sug = client.get(f"/profiles/{pid}/suggestions").json()["suggestions"]
    assert {(s["game_id"], s["player_id"]) for s in sug} == {(g, "p2") for g in two_games}
    assert all(r["kind"] == "same_name" for s in sug for r in s["reasons"])
    client.post(f"/profiles/{pid}/links", json={"game_id": two_games[0], "player_id": "p2"})
    sug = client.get(f"/profiles/{pid}/suggestions").json()["suggestions"]
    assert [s["game_id"] for s in sug] == [two_games[1]]  # linked players drop out


def test_stats_aggregate_across_games_and_user_values_win(client, two_games):
    pid = _profile(client)
    rows = []
    for g in two_games:
        client.post(f"/profiles/{pid}/links", json={"game_id": g, "player_id": "p1"})
        rows.append(next(r for r in client.get(f"/games/{g}/stats").json()["box_score"]
                         if r["player_id"] == "p1"))  # fmt: skip
    bb = client.get(f"/profiles/{pid}").json()["stats_by_sport"]["basketball"]
    assert bb["stats"]["games"] == 2
    assert bb["stats"]["points"] == sum(r["points"] for r in rows) > 0
    assert bb["stats"]["shots_attempted"] == sum(r["attempts"] for r in rows)
    assert bb["stats"]["shots_made"] == sum(r["makes"] for r in rows)
    assert [g["game_id"] for g in bb["games"]] == sorted(two_games)
    assert bb["edited"] == []

    body = client.patch(f"/profiles/{pid}", json={"stats": {"basketball": {"points": 31}}}).json()
    bb = body["stats_by_sport"]["basketball"]
    assert bb["stats"]["points"] == 31 and bb["auto"]["points"] == sum(r["points"] for r in rows)
    assert bb["edited"] == ["points"]
    assert "stats_by_sport.basketball.points" in body["user_edited_fields"]
    card = client.get(f"/profiles/{pid}/card").json()
    assert next(t for t in card["stats"] if t["key"] == "points") == {
        "key": "points", "label": "PTS", "value": 31, "edited": True}  # fmt: skip
    body = client.patch(f"/profiles/{pid}", json={"stats": {"basketball": {"points": None}}}).json()
    assert body["stats_by_sport"]["basketball"]["edited"] == []
    assert body["user_edited_fields"] == []


def test_missing_game_is_reported_not_fatal(client, two_games):
    pid = _profile(client)
    for g in two_games:
        client.post(f"/profiles/{pid}/links", json={"game_id": g, "player_id": "p1"})
    shutil.rmtree(client.app_settings.games_dir / two_games[1])
    body = client.get(f"/profiles/{pid}").json()
    assert body["missing_links"] == [{"game_id": two_games[1], "player_id": "p1",
                                      "missing": "game"}]  # fmt: skip
    assert body["stats_by_sport"]["basketball"]["stats"]["games"] == 1


# --- card + reel ---------------------------------------------------------------------------


def test_card_json_is_deterministic_and_grounded(client, two_games):
    pid = _profile(client, "Jo")
    for g in two_games:
        client.post(f"/profiles/{pid}/links", json={"game_id": g, "player_id": "p1"})
    a = client.get(f"/profiles/{pid}/card").json()
    b = client.get(f"/profiles/{pid}/card").json()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["schema"] == "replay.card.v1" and a["sport"] == "basketball" and a["games"] == 2
    assert a["title_source"] == "template" and a["grounding"]["template_ok"]
    assert a["title"].startswith("Jo the scorer: ")
    assert a["best_moment"]["game_id"] == min(two_games)  # ties go to the earlier game
    reel = client.get(f"/profiles/{pid}/reel").json()
    keys = [(i["game_id"], i["t_start"]) for i in reel["items"]]
    assert keys == sorted(keys) and len({k[0] for k in keys}) == 2


def test_card_title_falls_back_when_a_claim_is_ungrounded(client, two_games):
    pid = _profile(client, "Jo")
    client.post(f"/profiles/{pid}/links", json={"game_id": two_games[0], "player_id": "p1"})
    # a user-entered 3-pt total the events cannot vouch for: no "three-pointers" title
    client.patch(f"/profiles/{pid}", json={"stats": {"basketball": {"threes_made": 5}}})
    card = client.get(f"/profiles/{pid}/card").json()
    assert "three" not in card["title"] and card["grounding"]["template_ok"]
    assert card["grounding"]["tried"][0]["ok"] is False


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_card_png_renders(client, two_games):
    pid = _profile(client, "Jo")
    client.post(f"/profiles/{pid}/links", json={"game_id": two_games[0], "player_id": "p1"})
    assert client.post(f"/profiles/{pid}/card").json()["rendered"]
    r = client.get(f"/media/profiles/{pid}/card.png")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"


# --- face privacy invariants ---------------------------------------------------------------


class FakeFace(LocalFace):
    """LocalFace with the model replaced: an "image" is a list of unit vectors (faces)."""

    def __init__(self, store_dir):
        super().__init__(store_dir=store_dir)
        self.detect_calls = 0

    @staticmethod
    def _read(image):
        return json.loads(image.read_text()) if hasattr(image, "read_text") else image

    def detect(self, img):
        self.detect_calls += 1
        return [{"box": [0, 0, 40, 40], "score": 0.9, "e": e} for e in img]


def _img(tmp_path, name, *vecs):
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps([list(v) for v in vecs]))
    return p


def test_identify_compares_only_enrolled_and_forget_purges(tmp_path):
    face = FakeFace(tmp_path / "store")
    stranger = _img(tmp_path, "s", (1, 0, 0))
    assert face.identify(stranger) == [] and face.detect_calls == 0  # nobody enrolled
    face.enroll("pr_a", [_img(tmp_path, "a", (0, 1, 0))])
    assert face.identify(stranger) == []  # an unenrolled face never matches
    hit = face.identify(_img(tmp_path, "a2", (0, 1, 0), (1, 0, 0)))
    assert [h["profile_id"] for h in hit] == ["pr_a"]
    assert [p.name for p in (tmp_path / "store").iterdir()] == ["pr_a.json"]  # nothing else
    face.forget("pr_a")
    assert face.identify(_img(tmp_path, "a3", (0, 1, 0))) == []
    assert list((tmp_path / "store").iterdir()) == []


def test_face_unconfigured_is_opt_in():
    with pytest.raises(NotConfiguredError, match="face"):
        LocalFace().enrolled()


def test_enroll_route_needs_consent_and_delete_purges(client, tmp_path, two_games):
    face = FakeFace(tmp_path / "store")
    client.app.state.face = face
    pid = _profile(client, "Jo")
    photo = ("photos", ("me.json", json.dumps([[0, 1, 0]]), "application/json"))
    r = client.post(f"/profiles/{pid}/face", data={"consent": "false"}, files=[photo])
    assert r.status_code == 400 and not (tmp_path / "store").exists()
    r = client.post(f"/profiles/{pid}/face", data={"consent": "true"}, files=[photo])
    assert r.status_code == 200, r.text
    assert r.json()["face_enrolled"] and (tmp_path / "store" / f"{pid}.json").is_file()

    # a game's faces.json suggests only enrolled profiles; others never see face reasons
    g = two_games[0]
    doc = {"schema": F.SCHEMA, "matches": [{"player_id": "p1", "profile_id": pid,
                                            "similarity": 0.7, "votes": 3}]}  # fmt: skip
    (client.app_settings.games_dir / g / F.REL).write_text(json.dumps(doc))
    sug = client.get(f"/profiles/{pid}/suggestions").json()["suggestions"]
    assert {"kind": "face", "similarity": 0.7, "votes": 3} in sug[0]["reasons"]
    other = _profile(client, "Zed")
    assert client.get(f"/profiles/{other}/suggestions").json()["suggestions"] == []

    r = client.delete(f"/profiles/{pid}/face")
    assert r.json()["face_enrolled"] is False
    assert not (tmp_path / "store" / f"{pid}.json").exists()
    assert json.loads((client.app_settings.games_dir / g / F.REL).read_text())["matches"] == []

    client.post(f"/profiles/{pid}/face", data={"consent": "true"}, files=[photo])
    assert client.delete(f"/profiles/{pid}").status_code == 204
    assert list((tmp_path / "store").iterdir()) == []  # deleting the profile purges too


def test_matcher_needs_a_majority_of_usable_samples():
    assert F.decide(["pr_a", "pr_a", "pr_b"], 4) == ("pr_a", 2)
    assert F.decide(["pr_a", "pr_a"], 5) is None  # 2 of 5 faces: a stray match, not a person
    assert F.decide(["pr_a"], 1) is None  # one vote is never enough
    assert F.decide([], 3) is None


def test_game_matcher_skips_video_without_enrollment(client, tmp_path, two_games):
    face = FakeFace(tmp_path / "store")
    doc = F.match_game(client.app_settings.games_dir / two_games[0], face)
    assert doc["skipped"] == "no enrolled profiles" and doc["matches"] == []
    assert face.detect_calls == 0 and doc["samples"] == 0
