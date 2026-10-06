"""CLI: `python -m replay_worker run|status|perf|dag`. See services/worker/README.md."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "6")  # box rule: <= 6 threads; set before numpy loads

from . import dag, perf
from .cache import Cache

API_SOURCE = "source.mp4"  # services/api's SOURCE_REL


def _csv(text: str | None) -> list[str]:
    return [s.strip() for s in (text or "").split(",") if s.strip()]


def build_cfg(args: argparse.Namespace) -> tuple[Path, dict]:
    """(game_dir, cfg) from a video file or an existing game dir (API layout)."""
    target = Path(args.target)
    game: dict = {}
    if target.is_dir():
        game_dir = target
        if (target / "game.json").is_file():
            game = json.loads((target / "game.json").read_text())
        source = Path(args.source) if args.source else target / API_SOURCE
    else:
        source = target
        gid = args.game_id or "g_" + re.sub(r"[^a-z0-9]+", "_", target.stem.lower()).strip("_")
        game_dir = Path(args.out) if args.out else Path("data/games") / gid
    court = game.get("court") or {}
    cfg = {
        "source": str(source),
        "sport": args.sport or game.get("sport") or "basketball",
        "variant": args.variant or court.get("variant"),
        "landmarks_px": court.get("landmarks_px") or None,
        "detector": args.detector,
        "ground_truth": args.ground_truth,
        "backend": args.backend,
        "model": args.model,
        "stride": args.stride,
        "max_frames": args.max_frames,
        "title": args.title or game.get("title"),
        "game_id": args.game_id or game.get("id") or (None if target.is_dir() else game_dir.name),
        "recorded_at": game.get("recorded_at"),
    }
    # the same sibling-file conventions as `courtcam run`
    landmarks = Path(args.landmarks) if args.landmarks else source.parent / "landmarks.json"
    if args.landmarks or (not cfg["landmarks_px"] and landmarks.is_file()):
        from courtcam.pipeline import load_landmarks

        marks, variant = load_landmarks(landmarks)
        cfg["landmarks_px"] = {k: [v[0], v[1]] for k, v in marks.items()}
        cfg["variant"] = cfg["variant"] or variant
    if cfg["detector"] == "synthetic" and not cfg["ground_truth"]:
        guess = source.parent / "ground_truth.json"
        cfg["ground_truth"] = str(guess) if guess.is_file() else None
    return game_dir, cfg


def cmd_run(args: argparse.Namespace) -> int:
    game_dir, cfg = build_cfg(args)
    cache = Cache(Path(args.cache)) if args.cache else Cache()
    print(f"game_dir={game_dir} cache={cache.root}", flush=True)
    try:
        records = dag.run(
            game_dir,
            cfg,
            stages=_csv(args.stages) or None,
            force=_csv(args.force),
            cache=cache,
            cpu_workers=args.cpu_workers,
            progress=None,
        )
    except dag.StageFailed as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    for r in records:
        task = r["stage"] + (f"[{r['item']}]" if r["item"] else "")
        print(f"{task:<16} {r['resource']:<4} {r['cache']:<5} {r['wall_s']:>8.2f}s")
    hits = sum(r["cache"] == "hit" for r in records)
    misses = sum(r["cache"] == "miss" for r in records)
    print(f"{len(records)} tasks: {misses} miss, {hits} hit; log {game_dir / dag.LOG_REL}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from .stages import load_registry

    game_dir = Path(args.game_dir)
    last = {r["stage"]: r for r in perf.read_log(game_dir)}
    for name, stage in load_registry().items():
        outs = all((game_dir / o).exists() for o in stage.outputs if "{item}" not in o)
        r = last.get(name)
        seen = (
            f"{r['status']} {r.get('cache', '-')} {r['wall_s']:.2f}s run {r['run']}" if r else "-"
        )
        print(f"{name:<10} outputs={'yes' if outs else 'no ':<3}  last: {seen}")
    return 0


def cmd_perf(args: argparse.Namespace) -> int:
    text = perf.render([Path(g) for g in args.game_dirs])
    if args.write:
        Path(args.write).write_text(text)
        print(f"wrote {args.write}")
    else:
        print(text)
    return 0


def cmd_dag(args: argparse.Namespace) -> int:
    """The DAG shape (no versions — they change with every courtcam edit), for infra/."""
    from .stages import load_registry

    out = [
        {
            "name": s.name,
            "after": list(s.after),
            "resource": dag._resource(s, {"detector": "yolo"}),
            "fanout": s.fanout is not None,
            "cached": s.cache,
            "default": s.default,
        }
        for s in load_registry().values()
    ]
    print(json.dumps(out, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m replay_worker")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the DAG for one game")
    r.add_argument("target", help="a source video, or a game dir (API layout)")
    r.add_argument("--out", help="game dir for a video target (default data/games/<game id>)")
    r.add_argument("--source", help="source video for a game-dir target")
    r.add_argument("--stages", help="comma-separated targets; their upstream runs too")
    r.add_argument("--force", help="comma-separated stages to recompute despite the cache")
    r.add_argument("--sport")
    r.add_argument("--variant")
    r.add_argument("--landmarks", help="landmarks.json / calib.json (default: sibling file)")
    r.add_argument("--detector", default="yolo", help="yolo | synthetic")
    r.add_argument("--ground-truth")
    r.add_argument("--backend", default="pt")
    r.add_argument("--model")
    r.add_argument("--stride", type=int)
    r.add_argument("--max-frames", type=int)
    r.add_argument("--title")
    r.add_argument("--game-id")
    r.add_argument("--cache", help="cache root (default $REPLAY_CACHE_DIR or the box cache)")
    r.add_argument("--cpu-workers", type=int)
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("status", help="last result per stage for a game dir")
    s.add_argument("game_dir")
    s.set_defaults(fn=cmd_status)

    f = sub.add_parser("perf", help="render perf tables from game logs")
    f.add_argument("game_dirs", nargs="+")
    f.add_argument("--write", help="write markdown here (e.g. docs/perf.md)")
    f.set_defaults(fn=cmd_perf)

    d = sub.add_parser("dag", help="print the DAG shape as JSON (infra/dag.json)")
    d.set_defaults(fn=cmd_dag)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
