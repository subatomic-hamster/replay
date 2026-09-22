"""`courtcam` command line (plan §4.4: every stage runnable from the CLI)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated, Any

import typer

from . import calibrate as calib_mod
from . import pipeline
from .profiles import available_sports, load_profile
from .schema import CropPath, read_json

app = typer.Typer(add_completion=False, help="Court-aware video pipeline for Replay.")


def _landmarks(value: str | None) -> dict[str, tuple[float, float]] | None:
    """`--landmarks` takes a path to a JSON file or an inline JSON object."""
    if not value:
        return None
    source: Any = Path(value)
    if not source.exists():
        source = json.loads(value)
    return pipeline.load_landmarks(source)[0]


def _frame_size(path: Path) -> tuple[int, int]:
    """(width, height) of an image, without pulling cv2 into the CLI's import path."""
    import cv2

    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(f"could not read an image from {path}")
    return img.shape[1], img.shape[0]


def _variant_of(value: str | None) -> str | None:
    if not value or not Path(value).exists():
        return None
    return pipeline.load_landmarks(Path(value))[1]


_DONE: set[str] = set()
_T0: dict[str, float] = {}


def _echo_progress(stage: str, fraction: float) -> None:
    """Tick one line per finished stage, with how long it took — the numbers that go
    in a timing table."""
    _T0.setdefault(stage, time.perf_counter())
    if fraction >= 1.0 and stage not in _DONE:
        _DONE.add(stage)
        typer.secho(f"  ✓ {stage} {time.perf_counter() - _T0[stage]:.1f}s", fg=typer.colors.GREEN)


@app.command()
def run(
    input: Annotated[Path, typer.Option("--input", "-i", help="Source video")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output directory")],
    calib: Annotated[
        Path | None, typer.Option(help="landmarks.json or an existing calib.json")
    ] = None,
    landmarks: Annotated[str | None, typer.Option(help="Inline landmark JSON, or a path")] = None,
    sport: str = "basketball",
    variant: str | None = None,
    detector: Annotated[str, typer.Option(help="yolo | synthetic")] = "yolo",
    ground_truth: Annotated[
        Path | None, typer.Option(help="ground_truth.json for --detector synthetic")
    ] = None,
    backend: Annotated[str, typer.Option(help="Inference backend: pt | openvino | onnx")] = "pt",
    stride: int | None = None,
    max_frames: int | None = None,
    stages: Annotated[
        str | None, typer.Option(help="Comma-separated subset, e.g. detect,track")
    ] = None,
    title: str | None = None,
) -> None:
    """Run the pipeline end to end (or just `--stages`) and write `out/game.json`."""
    if detector == "synthetic" and ground_truth is None:
        guess = input.parent / "ground_truth.json"
        ground_truth = guess if guess.exists() else None
    if calib is None and landmarks is None:
        guess = input.parent / "landmarks.json"
        calib = guess if guess.exists() else None
    game = pipeline.run(
        input,
        out,
        sport=sport,
        variant=variant or _variant_of(str(calib) if calib else None),
        landmarks_px=_landmarks(landmarks),
        calib=calib,
        detector=detector,
        ground_truth=ground_truth,
        backend=backend,
        stages=[s.strip() for s in stages.split(",") if s.strip()] if stages else None,
        stride=stride,
        max_frames=max_frames,
        title=title,
        progress=_echo_progress,
    )
    typer.echo(str(game))


@app.command()
def calibrate(
    landmarks: Annotated[str, typer.Option(help="landmarks.json path or inline JSON")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Where to write calib.json")],
    sport: str = "basketball",
    variant: str | None = None,
) -> None:
    """Landmark clicks → homography. Fails if reprojection error exceeds 5 px."""
    points = _landmarks(landmarks)
    assert points is not None
    profile = load_profile(sport)
    data = calib_mod.calibrate(points, profile, variant or _variant_of(landmarks))
    calib_mod.write_calib(out, data)
    typer.echo(f"{out}  reprojection error {data['reproj_error_px']:.3f} px")


@app.command()
def autocalib(
    frame: Annotated[Path, typer.Option("--frame", help="Calibration frame (JPEG/PNG)")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write landmarks.json")] = None,
    sport: str = "basketball",
    variant: str | None = None,
    backend: Annotated[
        str, typer.Option(help="auto (= template) | template | vlm | claude-cli | lines")
    ] = "auto",
    overlay: Annotated[Path | None, typer.Option(help="Draw the proposal onto a JPEG")] = None,
    ask_optional: Annotated[
        bool, typer.Option(help="Also ask for the profile's landmarks_optional")
    ] = False,
    prior: Annotated[
        Path | None,
        typer.Option(help="A landmarks.json / cached proposal to leash the template fit to"),
    ] = None,
) -> None:
    """Fit the court template to the painted lines (or ask a vision model, `--backend vlm`)."""
    from . import autocalib as auto_mod

    img = auto_mod.read_frame(frame)
    profile = load_profile(sport)
    proposal = auto_mod.autocalibrate(
        img,
        profile,
        variant,
        backend=backend,
        optional=ask_optional,
        prior=_landmarks(str(prior)) if prior else None,
    )
    if overlay:
        auto_mod.draw_overlay(img, proposal, overlay, template=profile.template(variant))
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "variant": variant or profile.default_variant(),
                    "landmarks_px": proposal.as_dict()["landmarks_px"],
                    "autocalib": {
                        k: v for k, v in proposal.as_dict().items() if k != "landmarks_px"
                    },
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    err = proposal.reprojection_error_px
    typer.secho(
        f"{proposal.source}: {len(proposal.landmarks_px)} landmarks, "
        f"ok={proposal.ok} reproj={err:.1f}px"
        if err is not None
        else f"{proposal.source}: {len(proposal.landmarks_px)} landmarks, ok={proposal.ok}",
        fg=typer.colors.GREEN if proposal.ok else typer.colors.YELLOW,
    )
    if proposal.notes:
        typer.echo(f"  notes: {proposal.notes}")
    for name, (x, y) in sorted(proposal.landmarks_px.items()):
        snap = " snapped" if proposal.snapped.get(name) else ""
        typer.echo(f"  {name:<10} {x:8.1f} {y:8.1f}  conf {proposal.confidence[name]:.2f}{snap}")


HEADLINE = ("corner_nl", "corner_nr", "corner_fl", "corner_fr", "rim")
NEAR_PX = 20.0


@app.command("autocalib-eval")
def autocalib_eval(
    samples: Annotated[Path, typer.Option(help="Directory of *_240s.jpg frames")] = Path(
        "samples/real"
    ),
    sport: Annotated[
        str | None, typer.Option(help="Override the sport; default: the clip's filename prefix")
    ] = None,
    backend: Annotated[
        str, typer.Option(help="auto (= template) | template | vlm | claude-cli | lines")
    ] = "auto",
    clips: Annotated[str | None, typer.Option(help="Comma-separated clip stems to run")] = None,
    reuse: Annotated[bool, typer.Option(help="Score cached proposals, no model calls")] = False,
    ask_optional: Annotated[bool, typer.Option(help="Also ask for landmarks_optional")] = False,
) -> None:
    """Per-landmark pixel error against the hand-made `*.landmarks.json` ground truth.

    Ground-truth landmarks that fall OUTSIDE the frame are skipped, not counted as
    misses: `northsidewide.corner_fl` sits at x = 2709 on a 2560 px frame and neither
    2560 px clip has a `corner_fr` at all. A backend that refuses to invent a point it
    cannot see is right to, so scoring it against one is scoring the wrong thing.
    """
    from . import autocalib as auto_mod

    frames_dir = samples / "frames"
    tag = "" if backend in ("auto", "vlm", "claude-cli") else f"{backend}_"
    wanted = {c.strip() for c in clips.split(",")} if clips else None
    rows: list[tuple[str, dict[str, float], float, dict]] = []
    for jpg in sorted(samples.glob("*_240s.jpg")):
        stem = jpg.stem
        if wanted and stem not in wanted and stem.split("_")[1] not in wanted:
            continue
        truth_path = samples / f"{stem}.landmarks.json"
        if not truth_path.is_file():
            continue
        truth_doc = json.loads(truth_path.read_text(encoding="utf-8"))
        frame_size = _frame_size(jpg)
        truth = {
            k: tuple(v)
            for k, v in truth_doc["landmarks_px"].items()
            if 0 <= v[0] < frame_size[0] and 0 <= v[1] < frame_size[1]
        }
        offframe = len(truth_doc["landmarks_px"]) - len(truth)
        cache = frames_dir / f"autocalib_{tag}{stem}.json"
        if reuse and cache.is_file():
            doc = json.loads(cache.read_text(encoding="utf-8"))
            proposal = auto_mod.Proposal(
                landmarks_px={k: tuple(v) for k, v in doc["landmarks_px"].items()},
                confidence=doc.get("confidence", {}),
                snapped=doc.get("snapped", {}),
                source=doc.get("source", "cache"),
                notes=doc.get("notes", ""),
                ok=doc.get("ok", False),
                reprojection_error_px=doc.get("reprojection_error_px"),
            )
        else:
            img = auto_mod.read_frame(jpg)
            t0 = time.perf_counter()
            # `samples/real` mixes sports: basketball_*, pickleball_*, badminton_*.
            profile = load_profile(sport or stem.split("_")[0])
            proposal = auto_mod.autocalibrate(
                img,
                profile,
                truth_doc.get("variant"),
                backend=backend,
                optional=ask_optional,
            )
            proposal.notes = f"{proposal.notes} [{time.perf_counter() - t0:.0f}s]".strip()
            frames_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(proposal.as_dict(), indent=1), encoding="utf-8")
            auto_mod.draw_overlay(
                img,
                proposal,
                frames_dir / f"autocalib_{tag}{stem}.jpg",
                truth,
                template=profile.template(truth_doc.get("variant")),
            )
        errors = {
            name: float(
                (
                    (proposal.landmarks_px[name][0] - p[0]) ** 2
                    + (proposal.landmarks_px[name][1] - p[1]) ** 2
                )
                ** 0.5
            )
            for name, p in truth.items()
            if name in proposal.landmarks_px
        }
        rows.append((stem, errors, proposal.reprojection_error_px or float("nan"), truth))
        typer.echo(
            f"\n{stem}  source={proposal.source} ok={proposal.ok}"
            + (f"  ({offframe} ground-truth landmark(s) off-frame, skipped)" if offframe else "")
        )
        if proposal.notes:
            typer.echo(f"  {proposal.notes}")
        for name in sorted(truth):
            got = errors.get(name)
            mark = "" if got is None else ("ok " if got <= NEAR_PX else "BAD")
            head = "*" if name in HEADLINE else " "
            typer.echo(
                f" {head}{name:<10} "
                + ("       missing" if got is None else f"{got:8.1f} px  {mark}")
            )

    if not rows:
        typer.echo("no clips with ground truth found")
        raise typer.Exit(1)
    typer.echo("\n== summary (* = headline: 4 corners + rim) ==")
    typer.echo(f"{'clip':<32}{'n':>4}{'mean px':>10}{'<20px':>8}{'head<20':>9}{'reproj':>9}")
    for stem, errors, reproj, truth in rows:
        head = [errors[n] for n in HEADLINE if n in errors]
        want = [n for n in HEADLINE if n in truth]
        values = list(errors.values())
        typer.echo(
            f"{stem:<32}{len(values):>4}"
            f"{(sum(values) / len(values) if values else float('nan')):>10.1f}"
            f"{(sum(v <= NEAR_PX for v in values) / max(len(values), 1)):>8.0%}"
            f"{sum(v <= NEAR_PX for v in head):>5}/{len(want):<3}"
            f"{reproj:>9.1f}"
        )
    allv = [v for _, e, _, _ in rows for v in e.values()]
    typer.echo(
        f"{'ALL':<32}{len(allv):>4}{(sum(allv) / max(len(allv), 1)):>10.1f}"
        f"{(sum(v <= NEAR_PX for v in allv) / max(len(allv), 1)):>8.0%}"
    )


@app.command()
def synth(
    out: Annotated[Path, typer.Option("--out", "-o", help="Directory for the clip + truth")],
    sport: str = "basketball",
    variant: str | None = None,
    duration: float = 20.0,
    fps: int = 30,
    seed: int = 7,
) -> None:
    """Generate a synthetic clip, ground truth and landmarks for CI."""
    from .synth import generate

    paths = generate(out, sport=sport, variant=variant, duration_s=duration, fps=fps, seed=seed)
    for name, path in paths.items():
        typer.echo(f"{name}: {path}")


@app.command()
def overlay(
    out: Annotated[Path, typer.Option("--out", "-o", help="Pipeline output directory")],
    dest: Annotated[
        Path | None, typer.Option(help="Overlay MP4 (default out/media/overlay.mp4)")
    ] = None,
    max_frames: int | None = None,
) -> None:
    """Render a debug MP4 with court polygon, raw tracklets and kept players drawn."""
    from .identity import read_players
    from .render import render_overlay
    from .track import read_tracklets

    work = out / "_work"
    calib = calib_mod.read_calib(out / "calib.json") if (out / "calib.json").exists() else {}
    raw: dict[int, list] = {}
    players_px: dict[int, list] = {}
    stride = 1
    if (work / "tracklets.json").exists():
        tracklets, meta = read_tracklets(work / "tracklets.json")
        stride = int(meta.get("stride", 1))
        kept = set()
        if (work / "players.json").exists():
            for p in read_players(work / "players.json")[0]:
                kept |= set(p.members)
        for t in tracklets:
            if t.track_id in kept:
                continue
            for f, box in zip(t.frames.tolist(), t.boxes.tolist(), strict=True):
                for k in range(stride):
                    raw.setdefault(f + k, []).append((t.track_id, box))
    if (work / "players.json").exists():
        for p in read_players(work / "players.json")[0]:
            tl = p.track.tracklet
            for f, box in zip(tl.frames.tolist(), tl.boxes.tolist(), strict=True):
                for k in range(stride):
                    players_px.setdefault(f + k, []).append((p.player_id, box, p.color_hex))
    dest = dest or out / "media" / "overlay.mp4"
    render_overlay(
        out / pipeline.WIDE_REL,
        dest,
        raw_boxes=raw,
        player_boxes=players_px,
        court_polygon_px=calib.get("court_polygon_px"),
        rim_px=calib.get("rim_px"),
        max_frames=max_frames,
    )
    typer.echo(str(dest))


@app.command()
def render(
    out: Annotated[Path, typer.Option("--out", "-o", help="Pipeline output directory")],
    player: Annotated[str, typer.Option(help="player_id, e.g. p1")],
    height: int = 720,
    max_frames: int | None = None,
) -> None:
    """Rendition mode: bake one player's follow-cam crop path into an MP4 (D-6 fallback)."""
    from .render import render_crop

    crops = read_json(out / pipeline.CROPS_TEMPLATE.format(player_id=player), CropPath)
    rel = f"media/{player}.mp4"
    render_crop(out / pipeline.WIDE_REL, crops, out / rel, height=height, max_frames=max_frames)
    pipeline.record_rendition(out, player, rel)
    typer.echo(str(out / rel))


@app.command()
def sports() -> None:
    """List the installed sport profiles."""
    for name in available_sports():
        p = load_profile(name)
        typer.echo(f"{p.id}\ttier {p.tier}\tvariants {p.court.variants}\tevents {p.events}")


if __name__ == "__main__":
    app()
