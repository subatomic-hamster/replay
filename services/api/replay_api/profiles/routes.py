"""M10 endpoints (additive): profiles, cross-game links, player cards, career reel and
opt-in face enrollment.

    GET    /profiles                                   all profiles (no stats)
    POST   /profiles {name, photo_url?, sports?, positions?}
    GET    /profiles/{id}                              + linked (missing flagged), stats_by_sport
    PATCH  /profiles/{id} {name?, photo_url?, sports?, positions?, stats?: {sport: {k: v|null}}}
    DELETE /profiles/{id}                              also purges face enrollment, unlinks
    POST   /profiles/{id}/links {game_id, player_id}   names that roster player after the profile
    DELETE /profiles/{id}/links/{game_id}/{player_id}
    GET    /profiles/{id}/suggestions                  same-name roster players (+ face matches
                                                       from faces.json, enrolled profiles only)
    GET    /profiles/{id}/card[?llm=true]              card JSON
    POST   /profiles/{id}/card[?llm=true]              + renders card.png / thumb.jpg
    GET    /profiles/{id}/reel                         career reel manifest
    PUT    /profiles/{id}/photo                        raw image bytes -> photo.jpg
    POST   /profiles/{id}/face (multipart: consent=true, photos)   opt-in enrollment
    DELETE /profiles/{id}/face                         purge the embedding
    POST   /games/{game_id}/faces/match                faces.json (202 job)
    GET    /media/profiles/{id}/{photo.jpg|card.png|thumb.jpg}   (open, like /media/games)

Linking writes the profile's name and `profile_id` onto the game's roster player, and a
rename re-applies it to every linked game, so commentary, advice and the TV read the name
from game.json as before. Unlinking drops `profile_id` and keeps the name.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import edits, providers
from ..providers import NotConfiguredError
from ..providers.profiles import LinkConflict, blank
from . import card as K
from . import career
from . import faces as F

router = APIRouter()
PID = re.compile(r"^pr_[0-9a-f]{12}$")
MEDIA = {"photo.jpg": "image/jpeg", "card.png": "image/png", "thumb.jpg": "image/jpeg"}
MAX_PHOTO_BYTES = 8 << 20
Stat = float | int | None


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    photo_url: str | None = Field(default=None, max_length=500)
    sports: list[str] | None = None
    positions: list[str] = Field(default_factory=list, max_length=8)


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    photo_url: str | None = Field(default=None, max_length=500)
    sports: list[str] | None = None
    positions: list[str] | None = Field(default=None, max_length=8)
    # {sport: {stat: value}}; null removes a correction (the auto value shows again)
    stats: dict[str, dict[str, Stat]] | None = None


class LinkIn(BaseModel):
    game_id: str
    player_id: str


def store(request: Request):
    st = request.app.state
    if getattr(st, "profiles", None) is None:
        st.profiles = providers.create("profiles", path=st.settings.data_dir / "profiles.sqlite")
    return st.profiles


def _dir(request: Request, pid: str) -> Path:
    return request.app.state.settings.data_dir / "profiles" / pid


def _doc(request: Request, pid: str) -> dict:
    doc = store(request).get(pid) if PID.match(pid) else None
    if doc is None:
        raise HTTPException(404, f"profile {pid} not found")
    return doc


def _linked(request: Request, doc: dict):
    st = request.app.state
    return career.load_links(doc["linked"], st.storage.game_dir)


def _full(request: Request, doc: dict) -> dict:
    linked, missing = _linked(request, doc)
    stats = career.stats_by_sport(linked, doc.get("stats_user") or {})
    out = {k: v for k, v in doc.items() if k != "stats_user"}
    out["sports"] = doc.get("sports") or sorted({lk.sport for lk in linked})
    out["stats_by_sport"] = stats
    out["user_edited_fields"] = career.edited_fields(doc)
    out["missing_links"] = missing
    return out


def _set_roster(request: Request, game_id: str, player_id: str, name: str | None,
                profile_id: str | None) -> None:  # fmt: skip
    index = request.app.state.index
    game = index.load(game_id)
    player = next((p for p in (game or {}).get("players") or [] if p["id"] == player_id), None)
    if player is None:
        return
    fields = (
        {"profile_id": None}  # unlink keeps the name
        if profile_id is None
        else {"name": name, "tagged": True, "profile_id": profile_id}
    )
    gd = request.app.state.storage.game_dir(game_id)
    index.save(edits.apply_game(game, edits.patch(gd, "game.json", player_id, fields)))  # D-61


@router.get("/profiles")
def list_profiles(request: Request):
    return {"profiles": [{k: v for k, v in d.items() if k != "stats_user"}
                         for d in store(request).list()]}  # fmt: skip


@router.post("/profiles", status_code=201)
def create_profile(request: Request, body: ProfileIn):
    doc = blank(body.name)
    doc.update(photo_url=body.photo_url, positions=body.positions)
    if body.sports is not None:
        doc.update(sports=body.sports, user_edited_fields=["sports"])
    return _full(request, store(request).create(doc))


@router.get("/profiles/{pid}")
def get_profile(request: Request, pid: str):
    return _full(request, _doc(request, pid))


@router.patch("/profiles/{pid}")
def patch_profile(request: Request, pid: str, body: ProfilePatch):
    doc = _doc(request, pid)
    sent = body.model_fields_set
    edited = set(doc.get("user_edited_fields") or [])
    for f in ("name", "photo_url", "sports", "positions"):
        if f in sent:
            doc[f] = getattr(body, f) if f != "positions" else (body.positions or [])
            edited.add(f)
    if "sports" in sent and body.sports is None:
        edited.discard("sports")  # back to the linked games' sports
    for sport, vals in (body.stats or {}).items():
        mine = doc.setdefault("stats_user", {}).setdefault(sport, {})
        for k, v in vals.items():
            if v is None:
                mine.pop(k, None)
            else:
                mine[k] = v
        if not mine:
            doc["stats_user"].pop(sport)
    doc["user_edited_fields"] = sorted(edited)
    store(request).save(doc)
    if "name" in sent:
        for ln in doc["linked"]:
            _set_roster(request, ln["game_id"], ln["player_id"], body.name, pid)
    return _full(request, doc)


@router.delete("/profiles/{pid}", status_code=204)
def delete_profile(request: Request, pid: str):
    doc = _doc(request, pid)
    _forget_face(request, pid)
    _drop_face_matches(request, pid)
    for ln in doc["linked"]:
        _set_roster(request, ln["game_id"], ln["player_id"], None, None)
    store(request).delete(pid)
    shutil.rmtree(_dir(request, pid), ignore_errors=True)


@router.post("/profiles/{pid}/links")
def link(request: Request, pid: str, body: LinkIn):
    doc = _doc(request, pid)
    game = request.app.state.index.load(body.game_id)
    if game is None:
        raise HTTPException(404, f"game {body.game_id} not found")
    if body.player_id not in {p["id"] for p in game.get("players") or []}:
        raise HTTPException(404, f"player {body.player_id} not found")
    try:
        store(request).link(pid, body.game_id, body.player_id)
    except LinkConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    _set_roster(request, body.game_id, body.player_id, doc["name"], pid)
    return _full(request, _doc(request, pid))


@router.delete("/profiles/{pid}/links/{game_id}/{player_id}")
def unlink(request: Request, pid: str, game_id: str, player_id: str):
    _doc(request, pid)
    if not store(request).unlink(pid, game_id, player_id):
        raise HTTPException(404, "no such link")
    _set_roster(request, game_id, player_id, None, None)
    return _full(request, _doc(request, pid))


def _norm(name: str | None) -> str:
    return " ".join((name or "").lower().split())


@router.get("/profiles/{pid}/suggestions")
def suggestions(request: Request, pid: str):
    """Unlinked roster players that may be this person. Non-biometric: same name tag.
    Face: only when this profile opted in, from faces.json (enrolled matches only)."""
    doc = _doc(request, pid)
    st, profiles = request.app.state, store(request)
    out = []
    for game in st.index.list():
        faces = {}
        if doc.get("face_enrolled"):
            p = st.storage.path(game["id"], F.REL)
            if p.is_file():
                faces = {m["player_id"]: m for m in json.loads(p.read_text())["matches"]
                         if m["profile_id"] == pid}  # fmt: skip
        for player in game.get("players") or []:
            if profiles.owner(game["id"], player["id"]) is not None:
                continue
            reasons = []
            if _norm(player.get("name")) and _norm(player.get("name")) == _norm(doc["name"]):
                reasons.append({"kind": "same_name"})
            if player["id"] in faces:
                m = faces[player["id"]]
                reasons.append({"kind": "face", "similarity": m["similarity"], "votes": m["votes"]})
            if reasons:
                out.append({"game_id": game["id"], "game_title": game.get("title"),
                            "player_id": player["id"], "reasons": reasons})  # fmt: skip
    return {"profile_id": pid, "suggestions": out}


def _card(request: Request, pid: str, llm: bool) -> tuple[dict, list]:
    doc = _doc(request, pid)
    linked, _ = _linked(request, doc)
    stats = career.stats_by_sport(linked, doc.get("stats_user") or {})
    model = request.app.state.llm if llm else None
    return K.build(doc, linked, stats, llm=model), linked


@router.get("/profiles/{pid}/card")
def get_card(request: Request, pid: str, llm: bool = False):
    card, _ = _card(request, pid, llm)
    card["rendered"] = (_dir(request, pid) / "card.png").is_file()
    return card


@router.post("/profiles/{pid}/card")
def render_card(request: Request, pid: str, llm: bool = False):
    card, linked = _card(request, pid, llm)
    d = _dir(request, pid)
    thumb = None
    best = card["best_moment"]
    if best:
        lk = next(lk for lk in linked if lk.game_id == best["game_id"])
        thumb = K.thumbnail(lk.dir, lk.game, best)
        if thumb is not None:
            d.mkdir(parents=True, exist_ok=True)
            thumb.save(d / "thumb.jpg", quality=90)
    K.render_png(card, thumb, d / "card.png")
    (d / "card.json").write_text(json.dumps(card, indent=1))
    return {**card, "rendered": True}


@router.get("/profiles/{pid}/reel")
def career_reel(request: Request, pid: str):
    doc = _doc(request, pid)
    linked, _ = _linked(request, doc)
    reel = career.reel(pid, linked, career.moments(linked))
    st, base = request.app.state, str(request.base_url)
    for it in reel["items"]:
        rel = it.pop("media_rel")
        it["url"] = st.storage.url(it["game_id"], rel, base) if rel else None
    return reel


@router.put("/profiles/{pid}/photo")
async def put_photo(request: Request, pid: str):
    doc = _doc(request, pid)
    data = await request.body()
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413 if data else 400, "send one image up to 8 MB")
    from io import BytesIO

    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(BytesIO(data)).convert("RGB")
    except UnidentifiedImageError as exc:
        raise HTTPException(415, "not an image") from exc
    d = _dir(request, pid)
    d.mkdir(parents=True, exist_ok=True)
    img.thumbnail((1080, 1080))
    img.save(d / "photo.jpg", quality=90)  # re-encoded: no EXIF / location kept
    doc["photo_url"] = f"/media/profiles/{pid}/photo.jpg"
    doc["user_edited_fields"] = sorted({*doc.get("user_edited_fields", []), "photo_url"})
    store(request).save(doc)
    return _full(request, doc)


@router.get("/media/profiles/{pid}/{name}")
def profile_media(request: Request, pid: str, name: str):
    if not PID.match(pid) or name not in MEDIA:
        raise HTTPException(404, "not found")
    p = _dir(request, pid) / name
    if not p.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(p, media_type=MEDIA[name])


# --- opt-in face enrollment --------------------------------------------------------------


def _face(request: Request):
    return request.app.state.face


def _forget_face(request: Request, pid: str) -> None:
    try:
        _face(request).forget(pid)
    except NotConfiguredError:
        pass  # nothing could have been enrolled without the store


@router.post("/profiles/{pid}/face")
async def enroll_face(
    request: Request,
    pid: str,
    # B008: a call in a default is how FastAPI declares form fields
    consent: bool = Form(False),
    photos: list[UploadFile] = File(...),  # noqa: B008
):
    """Consent is explicit and per request; the photos are the person's own. They are
    embedded and deleted; only the mean embedding is stored, for this profile only."""
    doc = _doc(request, pid)
    if not consent:
        raise HTTPException(400, "face enrollment needs consent=true from the person enrolled")
    if not 1 <= len(photos) <= 10:
        raise HTTPException(400, "send 1 to 10 photos")
    with tempfile.TemporaryDirectory(prefix="replay-face-") as tmp:
        paths = []
        for i, up in enumerate(photos):
            data = await up.read()
            if len(data) > MAX_PHOTO_BYTES:
                raise HTTPException(413, "photo over 8 MB")
            p = Path(tmp) / f"{i}.img"
            p.write_bytes(data)
            paths.append(p)
        try:
            res = _face(request).enroll(pid, paths)
        except NotConfiguredError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    doc["face_enrolled"] = True
    store(request).save(doc)
    return {**_full(request, doc), "enrollment": res}


@router.delete("/profiles/{pid}/face")
def delete_face(request: Request, pid: str):
    doc = _doc(request, pid)
    _forget_face(request, pid)
    doc["face_enrolled"] = False
    store(request).save(doc)
    _drop_face_matches(request, pid)
    return _full(request, doc)


def _drop_face_matches(request: Request, pid: str) -> None:
    """Face-based suggestions for this profile disappear with its enrollment."""
    st = request.app.state
    for game in st.index.list():
        p = st.storage.path(game["id"], F.REL)
        if p.is_file():
            fd = json.loads(p.read_text())
            keep = [m for m in fd["matches"] if m["profile_id"] != pid]
            if len(keep) != len(fd["matches"]):
                fd["matches"] = keep
                st.storage.write_json(game["id"], F.REL, fd)


@router.post("/games/{game_id}/faces/match", status_code=202)
def face_match(request: Request, game_id: str):
    st = request.app.state
    if st.index.load(game_id) is None:
        raise HTTPException(404, f"game {game_id} not found")
    face = _face(request)
    try:
        face.enrolled()
    except NotConfiguredError as exc:
        raise HTTPException(503, str(exc)) from exc

    def task(job_id: str) -> None:
        doc = F.match_game(st.storage.game_dir(game_id), face)
        st.storage.write_json(game_id, F.REL, doc)

    job = st.jobs.submit("face_match", game_id, task)
    return {"job_id": job["id"], "status": job["status"]}
