"""Profiles provider (vision §21): players across games. SQLite now, DynamoDB later
(`aws.DynamoProfiles`).

A profile row holds only what a person typed or opted into: name, photo, sports,
positions, user stat corrections (`stats_user`), which fields they edited, and the
face / voice enrollment flags. Links `(game_id, player_id) -> profile_id` live in their own
table whose primary key makes "one game player belongs to at most one profile" a
database constraint. Declined link suggestions live in `declines` (added later with
CREATE IF NOT EXISTS, so older databases gain it on open) and cascade with the profile. Auto stats are not stored: the routes aggregate them from the
linked games on read (profiles/career.py), the way `stats.py` derives a game's box score.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Protocol

SCHEMA = "replay.profile.v1"
FIELDS = ("name", "photo_url", "sports", "positions", "stats_user", "user_edited_fields",
          "face_enrolled", "voice_enrolled")  # fmt: skip


class LinkConflict(ValueError):
    """The game player is already linked to another profile."""


class Profiles(Protocol):
    def create(self, doc: dict) -> dict: ...
    def get(self, profile_id: str) -> dict | None: ...
    def list(self) -> list[dict]: ...
    def save(self, doc: dict) -> None: ...
    def delete(self, profile_id: str) -> bool: ...
    def link(self, profile_id: str, game_id: str, player_id: str) -> None: ...
    def unlink(self, profile_id: str, game_id: str, player_id: str) -> bool: ...
    def owner(self, game_id: str, player_id: str) -> str | None: ...
    def decline(self, profile_id: str, game_id: str, player_id: str) -> None: ...
    def declined(self, profile_id: str) -> set[tuple[str, str]]: ...


def blank(name: str) -> dict:
    return {
        "name": name,
        "photo_url": None,
        "sports": None,  # None = derived from the linked games
        "positions": [],
        "stats_user": {},  # {sport: {stat: value}}; user values win over auto ones
        "user_edited_fields": [],
        "face_enrolled": False,
        "voice_enrolled": False,
    }


class LocalProfiles:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    profile_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, doc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS links (
                    game_id TEXT NOT NULL, player_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
                    PRIMARY KEY (game_id, player_id));
                CREATE INDEX IF NOT EXISTS links_profile ON links (profile_id);
                CREATE TABLE IF NOT EXISTS declines (
                    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
                    game_id TEXT NOT NULL, player_id TEXT NOT NULL,
                    PRIMARY KEY (profile_id, game_id, player_id));
                """
            )

    def _db(self):
        # one connection per call: FastAPI runs sync routes on a thread pool
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA foreign_keys = ON")
        return _Tx(db)

    def _linked(self, db, profile_id: str) -> list[dict]:
        rows = db.execute(
            "SELECT game_id, player_id FROM links WHERE profile_id = ? ORDER BY game_id, player_id",
            (profile_id,),
        )
        return [{"game_id": g, "player_id": p} for g, p in rows]

    def _out(self, db, profile_id: str, doc: str) -> dict:
        d = json.loads(doc)
        return {"schema": SCHEMA, "profile_id": profile_id, **d,
                "linked": self._linked(db, profile_id)}  # fmt: skip

    def create(self, doc: dict) -> dict:
        pid = "pr_" + secrets.token_hex(6)
        body = {k: doc[k] for k in FIELDS if k in doc}
        with self._db() as db:
            seq = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM profiles").fetchone()[0]
            db.execute("INSERT INTO profiles VALUES (?, ?, ?)", (pid, seq, json.dumps(body)))
            return self._out(db, pid, json.dumps(body))

    def get(self, profile_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute(
                "SELECT doc FROM profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
            return self._out(db, profile_id, row[0]) if row else None

    def list(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT profile_id, doc FROM profiles ORDER BY seq").fetchall()
            return [self._out(db, pid, doc) for pid, doc in rows]

    def save(self, doc: dict) -> None:
        body = {k: doc[k] for k in FIELDS if k in doc}
        with self._db() as db:
            cur = db.execute(
                "UPDATE profiles SET doc = ? WHERE profile_id = ?",
                (json.dumps(body), doc["profile_id"]),
            )
            if cur.rowcount == 0:
                raise KeyError(doc["profile_id"])

    def delete(self, profile_id: str) -> bool:
        with self._db() as db:
            return (
                db.execute("DELETE FROM profiles WHERE profile_id = ?", (profile_id,)).rowcount > 0
            )

    def link(self, profile_id: str, game_id: str, player_id: str) -> None:
        with self._db() as db:
            try:
                db.execute("INSERT INTO links VALUES (?, ?, ?)", (game_id, player_id, profile_id))
            except sqlite3.IntegrityError as exc:
                if self._owner(db, game_id, player_id) == profile_id:
                    return  # already linked here: idempotent
                raise LinkConflict(f"{game_id}/{player_id} is linked to another profile") from exc

    def unlink(self, profile_id: str, game_id: str, player_id: str) -> bool:
        with self._db() as db:
            cur = db.execute(
                "DELETE FROM links WHERE profile_id = ? AND game_id = ? AND player_id = ?",
                (profile_id, game_id, player_id),
            )
            return cur.rowcount > 0

    def _owner(self, db, game_id: str, player_id: str) -> str | None:
        row = db.execute(
            "SELECT profile_id FROM links WHERE game_id = ? AND player_id = ?", (game_id, player_id)
        ).fetchone()
        return row[0] if row else None

    def owner(self, game_id: str, player_id: str) -> str | None:
        with self._db() as db:
            return self._owner(db, game_id, player_id)

    def decline(self, profile_id: str, game_id: str, player_id: str) -> None:
        with self._db() as db:
            db.execute(
                "INSERT OR IGNORE INTO declines VALUES (?, ?, ?)", (profile_id, game_id, player_id)
            )

    def declined(self, profile_id: str) -> set[tuple[str, str]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT game_id, player_id FROM declines WHERE profile_id = ?", (profile_id,)
            )
            return {(g, p) for g, p in rows}


class _Tx:
    """`with` = one transaction (commit on success, rollback on error), then close."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        return self.db

    def __exit__(self, *exc) -> None:
        with closing(self.db):
            if exc[0] is None:
                self.db.commit()
            else:
                self.db.rollback()
