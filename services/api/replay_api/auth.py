"""Per-game upload tokens for the phone's QR page (D-80, docs/aws-migration.md "Auth").

token = base64url(game_id "." exp "." hex HMAC-SHA256(secret, game_id "." exp)), valid
24 h. It stands in for X-Replay-Key only on the routes the phone needs for *that* game.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time

TTL_S = 24 * 3600

# The phone page's routes. Bare game and its jobs: GET only; the rest are its own writes.
_GAME_ROUTE = re.compile(
    r"^/games/(g_[0-9a-f]+)"
    r"(/jobs|/upload|/upload/multipart|/upload/complete|/upload/abort"
    r"|/calibration|/calibration/auto|/process)?$"
)


def same(given: str | None, expected: str | None) -> bool:
    """Constant-time key compare; an unset expected key never matches."""
    return bool(given and expected) and hmac.compare_digest(given.encode(), expected.encode())


def _mac(secret: str, body: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def make_token(secret: str, game_id: str, now: float | None = None) -> str:
    body = f"{game_id}.{int((now if now is not None else time.time()) + TTL_S)}"
    raw = f"{body}.{_mac(secret, body)}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def token_game(secret: str, token: str | None, now: float | None = None) -> str | None:
    """The game a valid, unexpired token was issued for, else None."""
    if not token or not secret:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        game_id, exp, mac = raw.rsplit(".", 2)
        expired = int(exp) < (now if now is not None else time.time())
    except ValueError:  # bad base64 / utf-8 / shape / exp
        return None
    if expired or not hmac.compare_digest(mac, _mac(secret, f"{game_id}.{exp}")):
        return None
    return game_id


def token_allows(secret: str, token: str | None, method: str, path: str) -> bool:
    """Whether `token` opens `method path`: one of its own game's phone routes, or the
    sport catalog the calibration screen reads."""
    game_id = token_game(secret, token)
    if game_id is None:
        return False
    if path == "/sports":
        return method == "GET"
    m = _GAME_ROUTE.match(path)
    if not m or m.group(1) != game_id:
        return False
    return method == "GET" if m.group(2) in (None, "/jobs") else True
