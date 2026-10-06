"""Game index provider.

D-note: `game.json` on disk is the source of truth; the index just enumerates it.
A SQLite mirror would buy nothing at Phase 1 scale (tens of games, one process) and
would be a second truth to keep in sync. Phase 2 swaps this for DynamoDB.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Protocol

from .storage import LocalStorage

GAME_JSON = "game.json"


class Index(Protocol):
    def new_id(self) -> str: ...
    def create(self, title: str, sport: str) -> dict: ...
    def load(self, game_id: str) -> dict | None: ...
    def save(self, game: dict) -> None: ...
    def list(self) -> list[dict]: ...


class LocalIndex:
    def __init__(self, storage: LocalStorage):
        self.storage = storage

    def new_id(self) -> str:
        return "g_" + secrets.token_hex(6)

    def create(self, title: str, sport: str) -> dict:
        game = {
            "schema": "replay.game.v1",
            "id": self.new_id(),
            "title": title,
            "recorded_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
            "status": "created",
            "stages": {k: "pending" for k in ("ingest", "detect", "track", "render", "label")},
            "video": {"duration_s": 0.0, "fps": 0, "width": 0, "height": 0},
            "sport": sport,
            "court": None,
            "renditions": {"wide": None, "players": {}},
            "players": [],
            "teams": [],
            "tracks": None,
            "croppaths": None,
            "events_url": "events.json",
        }
        self.storage.game_dir(game["id"]).mkdir(parents=True, exist_ok=True)
        self.save(game)
        return game

    def load(self, game_id: str) -> dict | None:
        # game ids are generated; refuse anything that could walk the tree
        if not game_id.replace("_", "").isalnum():
            return None
        p = self.storage.path(game_id, GAME_JSON)
        if not p.is_file():
            return None
        return self.storage.read_json(game_id, GAME_JSON)

    def save(self, game: dict) -> None:
        self.storage.write_json(game["id"], GAME_JSON, game)

    def list(self) -> list[dict]:
        games = []
        for d in sorted(self.storage.games_dir.glob("*/" + GAME_JSON)):
            try:
                games.append(self.storage.read_json(d.parent.name, GAME_JSON))
            except (OSError, ValueError):
                continue
        # worker-made games carry `recorded_at: null`: undated sorts last
        games.sort(key=lambda g: g.get("recorded_at") or "", reverse=True)
        return games
