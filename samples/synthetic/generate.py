#!/usr/bin/env python
"""Synthetic fixtures (plan §7.4, M1).

    python samples/synthetic/generate.py --goldens      # rewrite every golden below
    python samples/synthetic/generate.py --out DIR ...  # same as `courtcam synth ...`

A golden is `samples/synthetic/<sport>/<variant>/`: `golden.json` (the compact digest
`courtcam/tests/test_synth_golden.py` regenerates and compares within tolerance),
`keyframe.png`, and the contract files (`events.json`, `plays.json`, `triggers.json`,
`calibration.json`, `landmarks.json`). The full clip and per-frame ground truth are not
committed: `golden.json["regenerate"]` is the command that rebuilds them bit-for-bit
from the seed.

`basketball_half/` is the frozen pre-M1 fixture (stick figures, `courtcam.synth.v1`);
the pipeline and autocalib tests read it as data, nothing regenerates it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDENS = [
    ("basketball", "half"),
    ("basketball", "full"),
    ("pickleball", "doubles"),
    ("badminton", "doubles"),
    ("volleyball", "indoor"),
]
DURATION_S = 40.0
SEED = 7


def write_goldens() -> None:
    import cv2
    from courtcam.synth import build_scene, golden_digest, write_truth

    for sport, variant in GOLDENS:
        out = HERE / sport / variant
        out.mkdir(parents=True, exist_ok=True)
        scene = build_scene(sport, variant, duration_s=DURATION_S, seed=SEED)
        doc, keyframe = golden_digest(scene, HERE / "voice")
        write_truth(scene, out, None, doc["voice"])
        (out / "golden.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        cv2.imwrite(str(out / "keyframe.png"), keyframe)
        kinds = sorted({t["type"] for t in scene.triggers})
        print(f"{out.relative_to(HERE)}: {len(scene.plays)} plays, triggers {kinds}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--goldens"]:
        write_goldens()
    else:
        from courtcam.cli import app

        sys.argv = [sys.argv[0], "synth", *sys.argv[1:]]
        app()
