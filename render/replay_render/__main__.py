"""CLI: python -m replay_render direct|render|stills|jitter <game_dir> ... (render/README.md)."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _size(text: str) -> tuple[int, int]:
    w, h = (int(v) for v in text.lower().split("x"))
    return w, h


def cmd_direct(a) -> int:
    from .director import direct, validate
    from .gamedata import load_game

    doc = direct(load_game(Path(a.game_dir)))
    validate(doc)
    out = Path(a.out) if a.out else Path(a.game_dir) / "cuts.json"
    out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    kinds: dict[str, int] = {}
    for c in doc["cuts"]:
        k = c["camera"].split(":")[0] if c["kind"] == "live" else "replay"
        kinds[k] = kinds.get(k, 0) + 1
    print(f"{out}: {len(doc['cuts'])} cuts {kinds}, provisional={doc['provisional']}")
    return 0


def cmd_render(a) -> int:
    from .compositor import render

    info = render(
        Path(a.game_dir),
        Path(a.out),
        size=_size(a.size),
        t0=a.t0,
        t1=a.t1,
        crf=a.crf,
        narration=Path(a.narration) if a.narration else None,
        label=a.label,
        audio_bitrate=a.abr,
        progress=lambda f: print(f"\rrender {f:5.1%}", end="", file=sys.stderr, flush=True),
    )
    print(file=sys.stderr)
    print(json.dumps(info))
    return 0


def cmd_stills(a) -> int:
    """PNG stills of a rendition at the moments that show each graphic: a lower third,
    the middle and late part of each replay (telestrator), and a plain live frame."""
    doc = json.loads((Path(a.game_dir) / "cuts.json").read_text())
    t0, t1 = a.t0, a.t1 if a.t1 is not None else doc["duration_s"]
    picks: list[tuple[str, float]] = []
    for i, l3 in enumerate(doc["graphics"]["lower_thirds"]):
        if t0 <= l3["t_start"] + 1.0 < t1:
            picks.append((f"lower_third_{i}", l3["t_start"] + 1.0))
    for i, c in enumerate(c for c in doc["cuts"] if c["kind"] == "replay"):
        if t0 <= c["t_start"] and c["t_end"] <= t1:
            d = c["t_end"] - c["t_start"]
            picks += [(f"replay_{i}_mid", c["t_start"] + 0.45 * d)]
            picks += [(f"replay_{i}_late", c["t_start"] + 0.8 * d)]
            picks += [(f"sting_{i}", c["t_start"] - 0.02)]
    live = [c for c in doc["cuts"] if c["kind"] == "live" and c["t_start"] >= t0]
    for name in ("wide", "tight", "follow"):
        hit = [c for c in live if c["camera"].split(":")[0] == name and c["t_end"] <= t1]
        if hit:
            picks.append((f"live_{name}", (hit[0]["t_start"] + hit[0]["t_end"]) / 2))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    for name, t in picks:
        dest = out / f"{name}.png"
        subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", f"{t - t0:.3f}", "-i", a.video,
                        "-frames:v", "1", str(dest)], check=True)  # fmt: skip
        print(f"{dest} (t={t:.2f})")
    return 0


def cmd_truth(a) -> int:
    from .truth import write_truth_game

    print(json.dumps(write_truth_game(Path(a.game_dir), Path(a.truth_dir), Path(a.out))))
    return 0


def cmd_jitter(a) -> int:
    from .jitter import report

    print(json.dumps(report(Path(a.game_dir), Path(a.out), t0=a.t0, t1=a.t1), indent=1))
    return 0


def _progress(f: float) -> None:
    print(f"\rrender {f:5.1%}", end="", file=sys.stderr, flush=True)


def cmd_hype(a) -> int:
    from .gamedata import load_game
    from .hype import REL, hype_series

    doc = hype_series(load_game(Path(a.game_dir)))
    out = Path(a.out) if a.out else Path(a.game_dir) / REL
    out.write_text(json.dumps(doc), encoding="utf-8")
    top = [(c["t"], c["score"], c["reasons"]) for c in doc["candidates"][:5]]
    print(f"{out}: {len(doc['values'])} values, sources {doc['sources']}, top {top}")
    return 0


def cmd_condensed(a) -> int:
    from .condensed import render_condensed

    doc = render_condensed(Path(a.game_dir), Path(a.out) if a.out else None,
                           size=_size(a.size), crf=a.crf, label=a.label, progress=_progress)  # fmt: skip
    print(file=sys.stderr)
    keep = ("n", "game_s", "rally_s", "condensed_s", "longest", "render")
    print(json.dumps({k: doc[k] for k in keep}))
    return 0


def cmd_vertical(a) -> int:
    from .gamedata import load_game
    from .vertical import export, resolve

    game = load_game(Path(a.game_dir))
    spec = resolve(game, clip_id=a.clip, play_id=a.play, event_id=a.event, t_start=a.t0,
                   t_end=a.t1, player_id=a.player)  # fmt: skip
    info = export(Path(a.game_dir), spec, Path(a.out), size=_size(a.size), crf=a.crf,
                  label=a.label, progress=_progress, game=game)  # fmt: skip
    print(file=sys.stderr)
    print(json.dumps(info))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m replay_render")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("direct", help="game dir -> cuts.json")
    d.add_argument("game_dir")
    d.add_argument("--out")
    r = sub.add_parser("render", help="cuts.json + source -> broadcast MP4")
    r.add_argument("game_dir")
    r.add_argument("--out", required=True)
    r.add_argument("--size", default="1920x1080")
    r.add_argument("--t0", type=float, default=0.0)
    r.add_argument("--t1", type=float)
    r.add_argument("--crf", type=int, default=20)
    r.add_argument("--abr", default="128k", help="AAC bitrate")
    r.add_argument("--narration", help="WAV on the source clock; game audio ducks under it")
    r.add_argument("--label", help='provenance label drawn bottom right, e.g. "SYNTHETIC"')
    t = sub.add_parser("truth-game", help="synthetic only: copy a game with ground-truth events")
    t.add_argument("game_dir")
    t.add_argument("truth_dir", help="the generator's output dir (ground_truth.json, events.json)")
    t.add_argument("--out", required=True)
    s = sub.add_parser("stills", help="PNG stills of each graphic from a rendition")
    s.add_argument("game_dir")
    s.add_argument("video")
    s.add_argument("--out", required=True)
    s.add_argument("--t0", type=float, default=0.0, help="the rendition's --t0")
    s.add_argument("--t1", type=float)
    j = sub.add_parser("jitter", help="camera-path jitter metrics + plots")
    j.add_argument("game_dir")
    j.add_argument("--out", required=True)
    j.add_argument("--t0", type=float, default=0.0)
    j.add_argument("--t1", type=float)
    h = sub.add_parser("hype", help="hype meter series + highlight candidates -> hype.json")
    h.add_argument("game_dir")
    h.add_argument("--out")
    c = sub.add_parser("condensed", help="net sports: rallies only -> condensed MP4 + json")
    c.add_argument("game_dir")
    c.add_argument("--out", help="default <game>/renditions/condensed.mp4")
    c.add_argument("--size", default="1280x720")
    c.add_argument("--crf", type=int, default=26)
    c.add_argument("--label")
    v = sub.add_parser("vertical", help="9:16 share export of a clip / play / event / window")
    v.add_argument("game_dir")
    v.add_argument("--out", required=True)
    v.add_argument("--clip")
    v.add_argument("--play")
    v.add_argument("--event")
    v.add_argument("--t0", type=float)
    v.add_argument("--t1", type=float)
    v.add_argument("--player")
    v.add_argument("--size", default="720x1280")
    v.add_argument("--crf", type=int, default=23)
    v.add_argument("--label")
    a = p.parse_args(argv)
    return {"direct": cmd_direct, "render": cmd_render, "stills": cmd_stills,
            "jitter": cmd_jitter, "truth-game": cmd_truth, "hype": cmd_hype,
            "condensed": cmd_condensed, "vertical": cmd_vertical}[a.cmd](a)  # fmt: skip


if __name__ == "__main__":
    raise SystemExit(main())
