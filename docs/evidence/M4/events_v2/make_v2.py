"""Events v2 evidence: sum eval_synth.py outputs per run and write metrics_events_v2.json plus
the "Events v2" section of ../README.md (synthetic only).

usage: make_v2.py <eval_dir> <m4_dir>
  <eval_dir>/<clip>_<tag>.eval.json from ../eval/eval_synth.py (see RUNS for the tags and how
  each run was made); <m4_dir> = docs/evidence/M4 (metrics.json is read, README.md and
  metrics_events_v2.json are written).
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

EVAL, M4 = Path(sys.argv[1]), Path(sys.argv[2])
ITEMS = ("shot", "shot_half_court", "possession_change", "play", "contact", "rally", "point",
         "attack")  # fmt: skip
# tag -> (label, how it was made)
RUNS = {
    "head_gt": ("GT poses, before (HEAD 005cf87)", "bisect.sh _old/head _m/synth head_gt synthetic auto"),
    "v3_gt": ("GT poses, after (events v2)", "bisect.sh _old/v2 ... v2_gt synthetic auto, then rekeep.sh _old/v3 (events stage) on v2_gt"),
    "head_yolo": ("YOLO detect + pose, before (HEAD 005cf87)", "bisect.sh _old/head _m/synth head_yolo yolo yolo"),
    "v3_yolo": ("YOLO detect + pose, after (events v2)", "bisect.sh _old/v2 ... v2_yolo yolo yolo, then rekeep.sh _old/v3 (events stage) on v2_yolo"),
    "v3_gt_rally_scoring": ("GT poses, after, pickleball rally.side_out=false", "rekeep.sh _old/v3 on v2_gt, pickleball clips, override rally.side_out=false"),
    "v3_yolo_rally_scoring": ("YOLO, after, pickleball rally.side_out=false", "rekeep.sh _old/v3 on v2_yolo, pickleball clips, override rally.side_out=false"),
    "v3_gt_no1t": ("GT poses, after, rally.one_touch=false", "rekeep.sh _old/v3 on v2_gt, badminton + pickleball clips, override rally.one_touch=false"),
    "v3_yolo_no1t": ("YOLO, after, rally.one_touch=false", "rekeep.sh _old/v3 on v2_yolo, badminton + pickleball clips, override rally.one_touch=false"),
}  # fmt: skip
# the same badminton + pickleball clips cut out of the main "after" runs, for the one_touch rows
NET = ("badminton_doubles_s7", "badminton_doubles_s11", "pickleball_doubles_s7",
       "pickleball_doubles_s11")  # fmt: skip
PICKLE = NET[2:]


def total(tag: str, only: tuple[str, ...] = ()) -> dict:
    tot: dict = defaultdict(lambda: defaultdict(int))
    clips = []
    for p in sorted(EVAL.glob(f"*_{tag}.eval.json")):
        r = json.loads(p.read_text())
        if only and r["clip"] not in only:
            continue
        clips.append(r["clip"])
        for k in ITEMS:
            v = r.get(k)
            if not isinstance(v, dict):
                continue
            for kk, vv in v.items():
                if isinstance(vv, int) and not isinstance(vv, bool):
                    tot[k][kk] += vv
        if "basketball_half" in r["clip"] and isinstance(r.get("shot"), dict):
            for kk in ("tp", "fp", "fn"):
                tot["shot_half_court"][kk] += r["shot"][kk]
    for v in tot.values():
        tp, fp, fn = v["tp"], v["fp"], v["fn"]
        v["precision"] = round(tp / (tp + fp), 3) if tp + fp else None
        v["recall"] = round(tp / (tp + fn), 3) if tp + fn else None
    return {"clips": clips, **{k: dict(tot[k]) for k in ITEMS if k in tot}}


runs = {tag: total(tag) for tag in RUNS if any(EVAL.glob(f"*_{tag}.eval.json"))}
doc = {
    "synthetic": True,
    "milestone": "M4 events v2",
    "date": "2026-10-06",
    "host": "hfbox (AMD RX 9070 XT, ROCm), shared venv /workspace/wt/replay-env/venv",
    "data": "synthetic only: the 9 clips of metrics.json, regenerated today by ../eval/run_metrics.sh gen (seeds 7, 11)",
    "harness": "../eval/run1.py + ../eval/eval_synth.py (unchanged); run_trig.py (whisper voice) not run: no M4 row needs it",
    "code": {"before": "HEAD 005cf87 (git archive)", "after": "005cf87 + events.py, plays.py, profiles.py, sports/basketball.yaml, sports/pickleball.yaml, sports/badminton.yaml of this change"},
    "runs": {tag: {"label": RUNS[tag][0], "how": RUNS[tag][1], **body} for tag, body in runs.items()},
}  # fmt: skip
(M4 / "metrics_events_v2.json").write_text(json.dumps(doc, indent=1) + "\n")


def pr(run: dict, k: str) -> str:
    v = run.get(k)
    if not v:
        return "-"
    p, r = v["precision"], v["recall"]
    return f"P {p:.2f} / R {r:.2f} ({v['tp']} TP)" if p is not None and r is not None else "-"


def ratio(run: dict, k: str, a: str, b: str) -> str:
    v = run.get(k)
    return f"{v[a]}/{v[b]}" if v and b in v else "-"


rows = [
    ("shots (27)", lambda r: pr(r, "shot")),
    ("shots, half court (20)", lambda r: pr(r, "shot_half_court")),
    ("2 vs 3 points right / shots found", lambda r: ratio(r, "shot", "points_ok", "tp")),
    ("possession change", lambda r: pr(r, "possession_change")),
    ("possession cause right", lambda r: ratio(r, "possession_change", "cause_ok", "tp")),
    ("plays", lambda r: pr(r, "play")),
    ("contacts", lambda r: pr(r, "contact")),
    ("contact side right / found", lambda r: ratio(r, "contact", "side_ok", "tp")),
    ("contact hitter right / found", lambda r: ratio(r, "contact", "hitter_ok", "tp")),
    ("rallies", lambda r: pr(r, "rally")),
    ("points", lambda r: pr(r, "point")),
    ("point `winner_side` right / known", lambda r: ratio(r, "point", "winner_ok", "winner_known")),
    ("volleyball attack", lambda r: pr(r, "attack")),
]
main = [t for t in ("head_gt", "v3_gt", "head_yolo", "v3_yolo") if t in runs]
table = ["| item | " + " | ".join(RUNS[t][0] for t in main) + " |",
         "|---|" + "---|" * len(main)]  # fmt: skip
table += [f"| {name} | " + " | ".join(f(runs[t]) for t in main) + " |" for name, f in rows]


def pair_lines(off_tags: tuple[str, str], clips: tuple[str, ...], k: str, a: str, b: str):
    """One line per pose branch: the main "after" run cut to `clips` vs the override run."""
    out = []
    for main_tag, off in zip(("v3_gt", "v3_yolo"), off_tags, strict=True):
        if main_tag in runs and off in runs:
            on_run = total(main_tag, clips)
            out.append(
                f"- {RUNS[main_tag][0].split(',')[0]}, {', '.join(clips)}: {a} / {b} "
                f"{ratio(on_run, k, a, b)} as shipped vs {ratio(runs[off], k, a, b)} with "
                f"`{RUNS[off][0].split(', ')[-1]}`"
            )
    return out


side_lines = pair_lines(("v3_gt_rally_scoring", "v3_yolo_rally_scoring"), PICKLE, "point",
                        "winner_ok", "winner_known")  # fmt: skip
touch_lines = pair_lines(("v3_gt_no1t", "v3_yolo_no1t"), NET, "contact", "side_ok", "tp")
touch_lines += pair_lines(("v3_gt_no1t", "v3_yolo_no1t"), NET, "contact", "hitter_ok", "tp")
SECTION = "\n".join([
    "<!-- events-v2:start (generated by events_v2/make_v2.py; do not edit by hand) -->",
    "## Events v2 (2026-10-06)",
    "",
    "**Synthetic data only.** Same 9 clips and seeds, same `eval/eval_synth.py`, run today on",
    "hfbox; numbers in `metrics_events_v2.json`, scripts in `events_v2/`. \"Before\" is HEAD",
    "005cf87 extracted with `git archive`; \"after\" is 005cf87 plus this change only.",
    "",
    *table,
    "",
    "### What the M4 regression was",
    "",
    "- **GT-pose shots 23 → 18 of 27:** the accuracy pass (35e7909) lowered the release arm",
    "  line to 0.2 torso below the shoulders (`shot.release_up_min: -0.2`). That lengthens",
    "  every measured release: a synthetic jump shot is 0.83-0.87 s above the nose but",
    "  0.90-0.93 s above the new line, past `release_max_s: 0.9`, so 5 releases were thrown",
    "  out as \"held\". Bisected: old events code (60f140e) on today's clips gives 23; HEAD",
    "  gives 18; HEAD with `release_up_min: null` gives 23; switching off the camera hoop",
    "  (17) or the MAD floor (18, 4 false) does not bring them back. The clips are not the",
    "  cause (the M4-era clips give the same counts with either code). Fix:",
    "  `shot.release_max_s: 1.0` in basketball.yaml (1.0, 1.1, 1.2 and 1.5 all give 23 GT and",
    "  21 YOLO). Real Kennesaw 240 s (local) stays at 3 shots, all real.",
    "- **YOLO rallies P 0.97 / R 0.88 at M4:** not a regression in code since M4. The M4",
    "  YOLO run kept on the box (05:42 UTC, before the M4 commit 4c6c02a at 06:36 UTC) was",
    "  made with `rally.audio_fusion` on; the M4 commit shipped it off for badminton and",
    "  pickleball (D-51: real shuttle hits gave P/R 0.36 fused). Re-running",
    "  today's events stage on that run's stored outputs gives P 0.75 / R 0.69 with both the",
    "  M4 commit's code and HEAD, and P 0.88 / R 0.81 (exactly the stored run) with fusion",
    "  on. GT-pose rallies were P 0.73 / R 0.67 at M4 too.",
    "- **Fix for rallies without fusion:** players stop running before the last shot lands,",
    "  so a motion rally ended ~1.2 s early. A strong onset within `onset_pad_s` after the",
    "  motion end now extends the rally past it (`rally.audio_extend_end`, never shrinks or",
    "  splits a rally). Real badminton 240 s (14 hand-labelled rallies, local footage):",
    "  12/14 at P 1.00 before and after; full fusion there is 5/14. The cost: onsets after",
    "  the last hit (the landing) now count as contacts, so contact precision drops (table).",
    "",
    "### Pickleball side-out scoring (doubles)",
    "",
    "`rally.side_out: true` in pickleball.yaml: `events.assign_winners` follows USA Pickleball",
    "Official Rulebook (2025) 4.B.6 (the game's starting server serves alone, as \"Second",
    "Server\"; after a side out the First Server, then the Second Server) and Section 1 (only",
    "the serving side scores). The same side serving next with the partner serving means the",
    "first server lost the rally; a point's `points` is 0 when the receivers won, and",
    "`plays.score_timeline` adds `points`. The synthetic generator uses rally scoring (the",
    "rally winner always serves next, rotating servers), so on synthetic pickleball the",
    "side-out rule misreads a winning team's server rotation as a lost rally. The rule",
    "itself is checked by `tests/test_plays.py::test_side_out_doubles_second_server`.",
    "",
    *side_lines,
    "",
    "### Contact sides (open item: `side_ok` near chance)",
    "",
    "`rally.one_touch: true` (badminton, pickleball): contact sides alternate through a",
    "rally, anchored on the side most per-contact wrist-speed guesses agree with; the hitter",
    "is then the fastest wrists on that side. Volleyball (up to 3 touches a side) keeps the",
    "per-contact guess. Not measured on real footage (no contact labels); a real bounce",
    "loud enough to pass `contact_min_strength` would shift the parity for the rest of the",
    "rally.",
    "",
    *touch_lines,
    "",
    "Not attempted: volleyball attack (P 0.30 GT / 0.10 YOLO, unchanged).",
    "<!-- events-v2:end -->",
])  # fmt: skip
readme = (M4 / "README.md").read_text()
start, end = "<!-- events-v2:start", "<!-- events-v2:end -->"
if start in readme:
    readme = readme[: readme.index(start)] + SECTION + readme[readme.index(end) + len(end) :]
else:
    readme = readme.rstrip("\n") + "\n\n" + SECTION
(M4 / "README.md").write_text(readme.rstrip("\n") + "\n")
