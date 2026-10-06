"""Write the 9:16 export spec for a game's top highlight, exactly as
`POST /games/{id}/exports/vertical {play_id}` would, so the worker's `vertical` stage
renders it and the API later finds it done. Used by scripts/box-demo.sh.

    python scripts/demo_vertical_spec.py <game dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from replay_render import gamedata, vertical
from replay_render.virtual.replays import read_highlights


def main(game_dir: Path) -> str:
    game = gamedata.load_game(game_dir)
    plays = [p["id"] for p in game.plays]
    tops = [h["play_id"] for h in read_highlights(game_dir)["plays"] if h["play_id"] in plays]
    if not (tops or plays):
        raise SystemExit(f"{game_dir}: no plays to export")
    spec = vertical.resolve(game, play_id=(tops or plays)[0])
    vid = vertical.spec_id(spec)
    path = game_dir / vertical.DIR / f"{vid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**spec, "id": vid, "size": list(vertical.SIZE)}), encoding="utf-8")
    print(f"vertical spec {vid}: {spec['ref']} {spec['t_start']}-{spec['t_end']} s")
    return vid


if __name__ == "__main__":
    main(Path(sys.argv[1]))
