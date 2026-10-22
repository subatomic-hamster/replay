"""Per-game tokens for phone pages (D-80, docs/aws-migration.md "Auth").

Two kinds, signed with the same secret, valid 24 h, never interchangeable:

- upload: base64url(game_id "." exp "." HMAC-SHA256(secret, game_id "." exp)), header
  X-Replay-Upload-Token, for the QR upload page (`_GAME_ROUTE`).
- phone: base64url("phone." game_id "." exp "." HMAC(secret, "phone." game_id "." exp)),
  header X-Replay-Phone-Token, for the "do it on your phone" pages (`PHONE_ROUTES`).

Each stands in for X-Replay-Key only on its own routes for *that* game.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time

TTL_S = 24 * 3600
UPLOAD, PHONE = "upload", "phone"
_PREFIX = {UPLOAD: "", PHONE: "phone."}

# The upload page's routes. Bare game and its jobs: GET only; the rest are its own writes.
_GAME_ROUTE = re.compile(
    r"^/games/(g_[0-9a-f]+)"
    r"(/jobs|/upload|/upload/multipart|/upload/parts|/upload/complete|/upload/abort"
    r"|/calibration|/calibration/auto|/process)?$"
)

# The phone pages' routes (clip, tag, review, search). `{g}` must be the token's own game.
# POST /profiles/{pid}/links names its game in the body: the route checks it against
# `phone_game(request)`. Not here, on purpose: uploads, calibration, process, delete,
# /games list, phone-link, profile photo/face/card, /worker, /sessions.
PHONE_ROUTES = (
    ("GET", "/sports"),
    ("GET", "/profiles"),  # pick who to tag
    ("POST", "/profiles"),  # tag someone new (name only)
    ("POST", "/profiles/{id}/links"),
    ("DELETE", "/profiles/{id}/links/{g}/{id}"),
    ("GET", "/games/{g}"),
    ("GET", "/games/{g}/moments"),
    ("GET", "/games/{g}/storyboard"),
    ("GET", "/games/{g}/plays"),
    ("GET", "/games/{g}/triggers"),
    ("GET", "/games/{g}/clips"),
    ("GET", "/games/{g}/score"),
    ("GET", "/games/{g}/stats"),
    ("GET", "/games/{g}/renditions"),
    ("GET", "/games/{g}/review/queue"),
    ("GET", "/games/{g}/exports/vertical"),
    ("GET", "/games/{g}/exports/vertical/{id}"),
    ("GET", "/games/{g}/exports/reel"),
    ("GET", "/games/{g}/exports/reel/{id}"),
    ("POST", "/games/{g}/exports/reel"),  # the highlight reel (16:9 or 9:16)
    ("POST", "/games/{g}/triggers"),  # make a clip at t
    ("PATCH", "/games/{g}/clips/{id}"),  # trim
    ("POST", "/games/{g}/exports/vertical"),  # aspect: the 9:16 share render
    ("PATCH", "/games/{g}/players/{id}"),  # name / merge (tag, review answers)
    ("PATCH", "/games/{g}/events/{id}"),  # review answers
    ("POST", "/games/{g}/search"),
    ("POST", "/games/{g}/query"),  # search's fallback without embeddings
)
_PHONE_RES = tuple(
    (
        method,
        re.compile("^" + p.replace("{g}", r"(?P<g>g_[0-9a-f]+)").replace("{id}", "[^/]+") + "$"),
    )
    for method, p in PHONE_ROUTES
)


def same(given: str | None, expected: str | None) -> bool:
    """Constant-time key compare; an unset expected key never matches."""
    return bool(given and expected) and hmac.compare_digest(given.encode(), expected.encode())


def _mac(secret: str, body: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def make_token(secret: str, game_id: str, now: float | None = None, kind: str = UPLOAD) -> str:
    exp = int((now if now is not None else time.time()) + TTL_S)
    body = f"{_PREFIX[kind]}{game_id}.{exp}"
    raw = f"{body}.{_mac(secret, body)}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def token_game(
    secret: str, token: str | None, now: float | None = None, kind: str = UPLOAD
) -> str | None:
    """The game a valid, unexpired token of `kind` was issued for, else None."""
    if not token or not secret:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        head, exp, mac = raw.rsplit(".", 2)
        expired = int(exp) < (now if now is not None else time.time())
    except ValueError:  # bad base64 / utf-8 / shape / exp
        return None
    if expired or not hmac.compare_digest(mac, _mac(secret, f"{head}.{exp}")):
        return None
    prefix = _PREFIX[kind]
    game_id = head[len(prefix) :]
    # the kind is part of the signed body: a phone token never reads as an upload one
    if not head.startswith(prefix) or not game_id or "." in game_id:
        return None
    return game_id


def token_allows(secret: str, token: str | None, method: str, path: str) -> bool:
    """Whether upload `token` opens `method path`: one of its own game's upload-page
    routes, or the sport catalog the calibration screen reads."""
    game_id = token_game(secret, token)
    if game_id is None:
        return False
    if path == "/sports":
        return method == "GET"
    m = _GAME_ROUTE.match(path)
    if not m or m.group(1) != game_id:
        return False
    return method == "GET" if m.group(2) in (None, "/jobs") else True


def phone_allows(secret: str, token: str | None, method: str, path: str) -> str | None:
    """The token's game when phone `token` opens `method path` (a PHONE_ROUTES entry, on
    its own game where the path names one), else None."""
    game_id = token_game(secret, token, kind=PHONE)
    if game_id is None:
        return None
    for m, rx in _PHONE_RES:
        hit = rx.match(path) if m == method else None
        if hit and hit.groupdict().get("g", game_id) == game_id:
            return game_id
    return None


PHONE_SCOPE_KEY = "replay.phone_game"


def phone_game(request) -> str | None:
    """Set by the auth middleware when this request got in on a phone token (not the key):
    routes whose game is in the body check it against this."""
    return request.scope.get(PHONE_SCOPE_KEY)
