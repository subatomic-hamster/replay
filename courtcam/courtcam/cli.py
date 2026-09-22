"""`courtcam` command line (plan §4.4: every stage runnable from the CLI)."""

from __future__ import annotations

import json
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


def _variant_of(value: str | None) -> str | None:
    if not value or not Path(value).exists():
        return None
    return pipeline.load_landmarks(Path(value))[1]


_DONE: set[str] = set()


def _echo_progress(stage: str, fraction: float) -> None:
    if fraction >= 1.0 and stage not in _DONE:
        _DONE.add(stage)
        typer.secho(f"  ✓ {stage}", fg=typer.colors.GREEN)


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
