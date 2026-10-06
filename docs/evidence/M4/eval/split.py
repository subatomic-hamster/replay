"""Split agg.py output into the per-milestone metrics.json files (synthetic only).

usage: split.py <agg.json> <dest_dir> <meta.json>  -> writes <dest_dir>/{M1,M4,M5}.metrics.json
meta.json carries the run's date / code state / commands, copied verbatim into each file.
"""

import json
import sys
from pathlib import Path

agg = json.loads(Path(sys.argv[1]).read_text())
dest, meta = Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text())
runs, mot = agg["runs"], agg["mot"]
S7 = ("basketball_half_s7", "basketball_full_s7", "pickleball_doubles_s7",
      "badminton_doubles_s7", "volleyball_indoor_s7")  # fmt: skip


def pick(tag, *items):
    return {k: runs[tag][k] for k in items if k in runs.get(tag, {})}


out = {
    "M1": {
        "players_mot_yolo": {c: mot[f"{c}_yolo"]["players"] for c in S7},
        "players_mot_gt_detector": {c: mot[f"{c}_gt"]["players"] for c in S7},
        "detections_mot_yolo": {c: mot[f"{c}_yolo"]["detections"] for c in S7},
        "voice_asr_whisper_small_gt_run": pick("gt", "voice", "voice_clips_all_heard"),
        "voice_asr_whisper_small_yolo_run": pick("yolo", "voice", "voice_clips_all_heard"),
    },
    "M4": {
        "synthetic_detector_gt_poses": pick(
            "gt", "shot", "shot_half_court", "possession_change", "play", "contact", "rally",
            "point", "attack"),
        "yolo_detect_yolo_pose": pick(
            "yolo", "shot", "shot_half_court", "possession_change", "play", "contact", "rally",
            "point", "attack"),
        "accuracy_pass_vitpose": pick(
            "vit", "shot", "shot_half_court", "possession_change", "point"),
    },
    "M5": {
        "synthetic_detector_gt_poses": pick("gt", "gesture", "voice", "tap", "resolve_rule_on_gt"),
        "yolo_detect_yolo_pose": pick("yolo", "gesture", "voice", "tap"),
        "accuracy_pass_vitpose": pick("vit", "gesture"),
    },
}  # fmt: skip
for m, body in out.items():
    doc = {"synthetic": True, "milestone": m, **meta, "metrics": body}
    (dest / f"{m}.metrics.json").write_text(json.dumps(doc, indent=1) + "\n")
