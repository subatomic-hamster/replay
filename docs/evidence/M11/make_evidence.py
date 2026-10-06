"""Regenerate the M11 evidence from processed game dirs (run on the box).

    d=/workspace/wt/replay-<you>; export PYTHONPATH=$d/courtcam:$d/services/api:$d/render
    python docs/evidence/M11/make_evidence.py <out_dir> <slug>=<game_dir>[:<synth_dir>] ... \
        [--label SYNTHETIC]

Per game: <slug>_box_score.json + <slug>_shot_chart.png (shots), <slug>_review_queue.json,
<slug>_hype.json + <slug>_hype.png, <slug>_rallies.json + <slug>_condensed.mp4 (rallies),
<slug>_vertical.mp4 + <slug>_vertical.png (a still). `:<synth_dir>` (the generator's
output) adds hype precision / recall against the ground-truth makes (basketball) or
points (net sports). Timings and metrics go to <out_dir>/metrics.json.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from replay_api import pipeline_adapter as adapter
from replay_api import stats as stats_mod
from replay_render import condensed, hype, review, vertical
from replay_render.gamedata import _list, load_game, read_json


def _frames(gd: Path):
    for chunk in sorted((gd / "tracks").glob("*.json")):
        yield from json.loads(chunk.read_text())["frames"]


def _dump(path: Path, doc) -> None:
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")


def hype_png(doc: dict, moments: list[float], out: Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = [i / doc["rate_hz"] for i in range(len(doc["values"]))]
    fig, ax = plt.subplots(figsize=(12, 3.2), dpi=100)
    for k, col in (("audio", "#1F6FEB"), ("arms_up", "#2DA44E"), ("speed", "#8B949E")):
        ax.plot(t, doc["components"][k], color=col, lw=0.8, alpha=0.7, label=k)
    ax.fill_between(t, doc["values"], color="#FFB800", alpha=0.35, lw=0)
    ax.plot(t, doc["values"], color="#B07D00", lw=1.6, label="hype")
    for m in moments:
        ax.axvline(m, color="#E5484D", lw=1, ls="--")
    for c in doc["candidates"]:
        ax.plot(c["t"], c["score"], "v", color="#0E1116", ms=7)
    ax.set_xlim(0, t[-1] if t else 1)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("game time (s)")
    ax.set_title(title + ("   (red dashes: ground-truth moments)" if moments else ""), fontsize=10)
    ax.legend(loc="upper right", fontsize=8, ncol=4)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def moments(gd: Path, synth: Path | None) -> list[float]:
    """Ground truth that should cheer: made shots (basketball) or points (net sports)."""
    if synth is None:
        return []
    evs = _list(read_json(synth / "events.json"), "events")
    made = [e["t_key"] for e in evs if e.get("type") == "shot" and e.get("made") is True]
    return made or [e["t_key"] for e in evs if e.get("type") == "point"]


def hype_pr(cands: list[dict], truth: list[float], before=1.0, after=6.0) -> dict:
    """A candidate is right if it peaks within [-1, +6] s of a ground-truth moment."""
    hit = [c for c in cands if any(m - before <= c["t"] <= m + after for m in truth)]
    found = [m for m in truth if any(m - before <= c["t"] <= m + after for c in cands)]
    return {
        "candidates": len(cands),
        "moments": len(truth),
        "precision": round(len(hit) / len(cands), 3) if cands else None,
        "recall": round(len(found) / len(truth), 3) if truth else None,
    }


def still(video: Path, t: float, out: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                    "-frames:v", "1", str(out)], check=True)  # fmt: skip


def one(out: Path, slug: str, gd: Path, synth: Path | None, label: str | None) -> dict:
    game = load_game(gd)
    gjson = read_json(gd / "game.json")
    gjson.setdefault("id", gd.name)
    events = [e for e in game.events if not e.get("dismissed")]
    m: dict = {"game": gd.name, "sport": game.sport, "duration_s": game.duration}
    variant = (gjson.get("court") or {}).get("variant")

    t = time.time()
    st = stats_mod.compute(gjson, events, _frames(gd), adapter.get_profile(game.sport, variant))
    m["stats_s"] = round(time.time() - t, 2)
    _dump(out / f"{slug}_box_score.json", {k: v for k, v in st.items() if k != "heatmap"})
    _dump(out / f"{slug}_review_queue.json",
          stats_mod.review_queue(gjson, events, _frames(gd)))  # fmt: skip
    if st["shots"]:
        review.shot_chart_png(st, game.sport, variant, out / f"{slug}_shot_chart.png",
                              team_colors=game.team_colors(), label=label)  # fmt: skip

    t = time.time()
    hd = hype.hype_series(game)
    m["hype_s"] = round(time.time() - t, 2)
    _dump(out / f"{slug}_hype.json", hd)
    truth = moments(gd, synth)
    hype_png(hd, truth, out / f"{slug}_hype.png", f"{slug}: hype meter ({label or 'real'})")
    if synth is not None:
        m["hype_vs_truth"] = hype_pr(hd["candidates"], truth)

    if any(e.get("type") == "rally" for e in events):
        doc = condensed.render_condensed(gd, out / f"{slug}_condensed.mp4", size=(854, 480),
                                         crf=30, label=label)  # fmt: skip
        _dump(out / f"{slug}_rallies.json", {k: v for k, v in doc.items() if k != "render"})
        m["condensed"] = {k: doc[k] for k in ("n", "game_s", "rally_s", "condensed_s")}
        m["condensed"]["render"] = doc["render"]
        (gd / condensed.DOC_REL).unlink(missing_ok=True)  # keep the game dir as it was

    # vertical: the first play with a made shot, else the best hype candidate's play,
    # else the first made shot / rally event
    made = {e["id"] for e in events if e.get("made") is True}
    plays = {p["id"]: p for p in game.plays}
    with_make = [p for p in game.plays if made & set(p.get("event_ids") or ())]
    cands = [c for c in hd["candidates"] if c["play_id"] in plays]
    if with_make:
        ref = {"play_id": with_make[0]["id"]}
    elif made:
        ref = {"event_id": min(made)}
    else:
        ref = {"play_id": cands[0]["play_id"]} if cands else None
    if ref is None:
        ev = next((e for e in events if e.get("type") == "shot" and e.get("made")), None)
        ev = ev or next((e for e in events if e.get("type") in ("rally", "shot")), None)
        ref = {"event_id": ev["id"]} if ev else {"t_start": 0.0, "t_end": 8.0}
    spec = vertical.resolve(game, **ref)
    info = vertical.export(gd, spec, out / f"{slug}_vertical.mp4", size=(540, 960), crf=28,
                           label=label, game=game)  # fmt: skip
    still(
        out / f"{slug}_vertical.mp4",
        min(2.5, info["render"]["seconds"] / 2),
        out / f"{slug}_vertical.png",
    )
    m["vertical"] = {k: info[k] for k in ("t_start", "t_end", "player_id", "caption", "ref")}
    m["vertical"]["render"] = info["render"]
    return m


def main(argv: list[str]) -> int:
    label = None
    if "--label" in argv:
        i = argv.index("--label")
        label = argv[i + 1]
        argv = argv[:i] + argv[i + 2 :]
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    metrics = {}
    for arg in argv[1:]:
        slug, _, paths = arg.partition("=")
        gd, _, synth = paths.partition(":")
        metrics[slug] = one(out, slug, Path(gd), Path(synth) if synth else None, label)
        print(slug, json.dumps(metrics[slug]), flush=True)
    _dump(out / "metrics.json", metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
