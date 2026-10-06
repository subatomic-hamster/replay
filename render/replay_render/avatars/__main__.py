"""Tier C command line (on the box; wrap MotionBERT runs in `flock <gpu lock> timeout N`).

python -m replay_render.avatars scene  <game> <play> [--method auto|motionbert|analytic]
                                       [--kp auto|gt|yolo|poses] [--ground-truth gt.json]
python -m replay_render.avatars render <game> <play> <angle> [--out x.mp4] [--size 1280x720]
python -m replay_render.avatars eval   <game> <play> --ground-truth gt.json --out dir
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import evaluate, render, scene


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m replay_render.avatars")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scene")
    s.add_argument("game_dir", type=Path)
    s.add_argument("play_id")
    s.add_argument("--method", default="auto")
    s.add_argument("--kp", default="auto")
    s.add_argument("--ground-truth", type=Path)
    s.add_argument("--video", type=Path)
    r = sub.add_parser("render")
    r.add_argument("game_dir", type=Path)
    r.add_argument("play_id")
    r.add_argument("angle")
    r.add_argument("--out", type=Path)
    r.add_argument("--size", default="1280x720")
    e = sub.add_parser("eval")
    e.add_argument("game_dir", type=Path)
    e.add_argument("play_id")
    e.add_argument("--ground-truth", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--methods", default="motionbert,analytic")
    a = ap.parse_args()
    video = lambda: a.video or a.game_dir / "media" / "wide.mp4"
    if a.cmd == "scene":
        doc = scene.build(a.game_dir, a.play_id, video(), method=a.method, kp_source=a.kp,
                          ground_truth=a.ground_truth)  # fmt: skip
        path = scene.write(a.game_dir, a.play_id, doc)
        print(json.dumps({"scene": str(path), "method": doc["method"], **doc["quality"]}))
    elif a.cmd == "render":
        w, h = (int(v) for v in a.size.lower().split("x"))
        out = a.out or a.game_dir / "replays" / a.play_id / f"tierc_{a.angle}.mp4"
        print(json.dumps(render.render_angle(scene.read(a.game_dir, a.play_id), a.angle, out,
                                             size=(w, h))))  # fmt: skip
    else:
        res = evaluate.run(a.game_dir, a.play_id, a.game_dir / "media" / "wide.mp4",
                           a.ground_truth, a.out, a.methods.split(","))  # fmt: skip
        print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
