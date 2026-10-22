"""Storage provider: where a game's bytes live and how they become URLs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    def game_dir(self, game_id: str) -> Path: ...
    def path(self, game_id: str, rel: str) -> Path: ...
    def read_json(self, game_id: str, rel: str) -> dict: ...
    def write_json(self, game_id: str, rel: str, data: dict) -> None: ...
    def url(self, game_id: str, rel: str, base: str) -> str: ...


class LocalStorage:
    """`data/games/{game_id}/...` on disk, served by the API under `/media/games/...`."""

    def __init__(self, games_dir: Path):
        self.games_dir = Path(games_dir)
        self.games_dir.mkdir(parents=True, exist_ok=True)

    def game_dir(self, game_id: str) -> Path:
        return self.games_dir / game_id

    def path(self, game_id: str, rel: str) -> Path:
        return self.game_dir(game_id) / rel

    def game_dir_with(self, game_id: str, *rels: str) -> Path:
        """The game folder with only `rels` (files or folders) current. The cloud mirror
        pulls just those (one LIST and the changed GETs each), where `game_dir` pulls the
        whole game, every image included: ~17 s on a fresh Lambda instance (D-86)."""
        for rel in rels:
            self.path(game_id, rel)
        return self.games_dir / game_id

    def resolve_inside(self, game_id: str, rel: str) -> Path | None:
        """Resolved path under the game dir, or None if it escapes it (traversal guard)."""
        root = self.game_dir(game_id).resolve()
        try:
            target = (root / rel).resolve()
        except OSError:
            return None
        return target if target == root or root in target.parents else None

    def read_json(self, game_id: str, rel: str) -> dict:
        return json.loads(self.path(game_id, rel).read_text())

    def write_json(self, game_id: str, rel: str, data: dict) -> None:
        p = self.path(game_id, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(p)

    def url(self, game_id: str, rel: str, base: str) -> str:
        return f"{base.rstrip('/')}/media/games/{game_id}/{rel.lstrip('/')}"
