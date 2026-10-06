"""M10 stage `face_match` (opt-in, not in the default DAG): `faces.json`, suggestions that
a game's tracked players are face-ENROLLED profiles (replay_api.profiles.faces).

Gated on enrollment: config `face_dir` names the enrollment store (else REPLAY_FACE_DIR);
with no store, no models, or no enrolled profile the stage writes a `skipped` doc without
opening the video. The store is a cache input, so enrolling or deleting a profile re-runs
it. CPU only (OpenCV DNN YuNet + SFace).

    python -m replay_worker run <game_dir> --stages face_match --set face_dir=/path/to/store
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from courtcam import pipeline as P

from ..dag import Ctx, Stage


def _code_hash() -> str:
    spec = importlib.util.find_spec("replay_api")
    root = (
        Path(spec.origin).parent
        if spec and spec.origin
        else Path(__file__).resolve().parents[3] / "api" / "replay_api"
    )
    h = hashlib.sha256(Path(__file__).read_bytes())
    for f in (root / "profiles" / "faces.py", root / "providers" / "face.py"):
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


VERSION = _code_hash()
OUT = "faces.json"


def run_face_match(ctx: Ctx, item: str | None) -> None:
    from replay_api.profiles import faces as F
    from replay_api.providers import NotConfiguredError
    from replay_api.providers.face import LocalFace

    face = LocalFace(store_dir=ctx.cfg.get("face_dir"))
    try:
        doc = F.match_game(ctx.game_dir, face)
    except NotConfiguredError as exc:
        doc = {"schema": F.SCHEMA, "matches": [], "skipped": str(exc)}
    (ctx.game_dir / OUT).write_text(json.dumps(doc, indent=1), encoding="utf-8")


STAGES = [
    Stage(
        "face_match",
        VERSION,
        run_face_match,
        inputs=("game.json", "tracks", P.WIDE_REL, "{face_dir}"),
        outputs=(OUT,),
        params=("face_dir",),
        after=("game",),
        default=False,
    ),
]
