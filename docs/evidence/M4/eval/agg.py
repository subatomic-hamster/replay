"""Sum per-clip eval_synth.py / courtcam eval outputs into one JSON (synthetic only).

usage: agg.py <out_dir>  -> prints {"runs": {tag: {item: totals}}, "per_clip": ..., "mot": ...}
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

out = Path(sys.argv[1])
SKIP = {"clip", "sport", "pid_mapped", "counts", "resolve_rule_on_gt", "tap"}
runs, per_clip = {}, defaultdict(dict)
for tag in ("gt", "yolo", "vit"):
    tot: dict = defaultdict(lambda: defaultdict(int))
    for p in sorted(out.glob(f"*_{tag}.eval.json")):
        r = json.loads(p.read_text())
        per_clip[r["clip"]][tag] = {k: v for k, v in r.items() if k not in ("clip", "sport")}
        for k, v in r.items():
            if k in SKIP or not isinstance(v, dict):
                continue
            for kk, vv in v.items():
                if isinstance(vv, int) and not isinstance(vv, bool):
                    tot[k][kk] += vv
            if k == "shot" and "basketball_half" in r["clip"]:
                for kk in ("tp", "fp", "fn"):
                    tot["shot_half_court"][kk] += v[kk]
        tot["tap"]["n"] += r["tap"]["n"]
        tot["tap"]["clip_ok"] += r["tap"]["clip_ok"]
        a, b = (int(x) for x in r["resolve_rule_on_gt"].split("/"))
        tot["resolve_rule_on_gt"]["ok"] += a
        tot["resolve_rule_on_gt"]["n"] += b
        if r.get("voice"):
            tot["voice_clips_all_heard"]["n"] += 1
            tot["voice_clips_all_heard"]["ok"] += int(r["voice"]["fn"] == 0)
    for v in tot.values():
        if "tp" in v:
            tp, fp, fn = v["tp"], v["fp"], v["fn"]
            v["precision"] = round(tp / (tp + fp), 3) if tp + fp else None
            v["recall"] = round(tp / (tp + fn), 3) if tp + fn else None
    runs[tag] = {k: dict(v) for k, v in tot.items()}
mot = {}
for p in sorted(out.glob("*.mot.json")):
    r = json.loads(p.read_text())
    keep = ("mota", "idf1", "id_switches", "precision", "recall", "gt_ids", "pred_ids")
    mot[p.name.removesuffix(".mot.json")] = {
        "players": {k: r["players"][k] for k in keep}
        | {"court_err_m": r["players"]["court_err_m"]},
        "detections": {k: r["detections"][k] for k in keep},
    }
print(
    json.dumps({"synthetic": True, "runs": runs, "mot": mot, "per_clip": per_clip}, indent=1)
)  # ttsr-ignore: py/no-print (CLI)
