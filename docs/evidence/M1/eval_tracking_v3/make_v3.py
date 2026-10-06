"""Write metrics_tracking_v3.json (synthetic only).
usage: make_v3.py <before_out> <after_out> <sweep_dir>
  before_out / after_out: run_metrics.sh output dirs (gt, yolo, mot steps) at 81e1e99 and
  with the v3 identity.py; summed with ../../M4/eval/agg.py (copied to _m/agg.py).
  sweep_dir: <clip>_<det>_<variant>_c<cover>.mot.json from sweep.sh (identity-only reruns).
"""

import json
import subprocess
import sys
from pathlib import Path

before, after, sweep = (Path(a) for a in sys.argv[1:4])


def agg(d: Path) -> dict:
    out = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("agg.py")), str(d)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(out.stdout)


def mot_row(m: dict) -> dict:
    p = m["players"]
    return {
        k: round(p[k], 4) if isinstance(p[k], float) else p[k]
        for k in ("mota", "idf1", "id_switches")
    }


b, a = agg(before), agg(after)
variants: dict = {}
for p in sorted(sweep.glob("*.mot.json")):
    clip_det, var, cover = p.name.removesuffix(".mot.json").rsplit("_", 2)
    variants.setdefault(f"{var}_{cover}", {})[clip_det] = mot_row(json.loads(p.read_text()))

print(  # ttsr-ignore: py/no-print (CLI output)
    json.dumps(
        {
            "synthetic": True,
            "base": "81e1e99 (identity v2, D-70)",
            "mot_players": {
                k: {"before": mot_row(b["mot"][k]), "after": mot_row(a["mot"][k])}
                for k in sorted(set(b["mot"]) & set(a["mot"]))
            },
            "variants_identity_only": variants,
            "before": {"runs": b["runs"], "mot": b["mot"]},
            "after": {"runs": a["runs"], "mot": a["mot"]},
        },
        indent=1,
    )
)
