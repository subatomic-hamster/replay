"""Re-run only the identity stage of a finished run with another jersey-cut rule (synthetic only).
usage: ident_cover.py <src_out> <dst_out> <max_cover> [ship|weight|drop]
dst gets a copy of src's _work/ (court.json is the identity input), game.json and a symlink
to src's media/wide.mp4; `courtcam eval --out <dst_out>` then scores it.

  max_cover 1.0      : no sample counts as covered = D-70 (81e1e99) behaviour
  ship (default)     : a changed run that is mostly covered is no change (shipped, v3)
  weight             : a run's length counts only its clear samples (variant B, not shipped)
  drop               : covered samples are dropped before the cut (variant A, not shipped)
"""

import json
import shutil
import sys
from pathlib import Path

import numpy as np
from courtcam.profiles import load_profile

from courtcam import identity as I
from courtcam import pipeline as P

src, dst, cover = Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3])
variant = sys.argv[4] if len(sys.argv) > 4 else "ship"
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(src / "_work", dst / "_work")
shutil.copy(src / "game.json", dst / "game.json")
(dst / "media").mkdir()
(dst / "media" / "wide.mp4").symlink_to((src / "media" / "wide.mp4").resolve())
I.JERSEY_MAX_COVER = cover

if variant == "weight":
    runs = I._runs

    def _runs_weight(labels, min_len, weight=None):
        if weight is None:
            return runs(labels, min_len)
        # same merge rule, but a run's length is its count of clear samples
        cum = np.concatenate([[0], np.cumsum(weight)])
        out: list[list[int]] = []
        for i, x in enumerate(labels.tolist()):
            if out and out[-1][2] == x:
                out[-1][1] = i + 1
            else:
                out.append([i, i + 1, x])
        merged: list[list[int]] = []
        for r in out:
            short = lambda q: cum[q[1]] - cum[q[0]] < min_len
            if merged and (short(r) or merged[-1][2] == r[2]):
                merged[-1][1] = r[1]
            elif merged and short(merged[-1]):
                merged[-1] = [merged[-1][0], r[1], r[2]]
            else:
                merged.append(list(r))
        return [tuple(r) for r in merged]

    I._runs = _runs_weight
elif variant == "drop":
    split = I.split_switches
    I.split_switches = lambda tracks, lab, teams, clear=None: split(tracks, clear, teams)

game = json.loads((src / "game.json").read_text())
P.stage_identity(
    dst,
    load_profile(game["sport"]),
    game["court"]["variant"],
    force=True,
    progress=lambda s, f: None,
)
