"""`courtcam` command line (plan §4.4: every stage runnable from the CLI)."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Annotated, Any

import typer

from . import calibrate as calib_mod
from . import pipeline
from .profiles import available_sports, load_profile
from .schema import CropPath, read_json

app = typer.Typer(add_completion=False, help="Court-aware video pipeline for Replay.")


#: D-23: an ok=false `courtcam autocalib` proposal is refused unless this is passed.
ACCEPT_LOW = typer.Option(
    "--accept-low-confidence",
    help="Use an auto-calibration proposal with ok=false anyway (recorded in calib.json)",
)


def _refuse(exc: Exception) -> typer.Exit:
    typer.secho(f"refused: {exc}", fg=typer.colors.RED, err=True)
    return typer.Exit(2)


def _landmarks(
    value: str | None, accept_low: bool = False
) -> dict[str, tuple[float, float]] | None:
    """`--landmarks` takes a path to a JSON file or an inline JSON object."""
    if not value:
        return None
    source: Any = Path(value)
    if not source.exists():
        source = json.loads(value)
    try:
        return pipeline.load_landmarks(source, accept_low_confidence=accept_low)[0]
    except pipeline.LowConfidenceLandmarks as exc:
        raise _refuse(exc) from exc


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
    # Only the variant is read here; the ok=false gate runs where the points are used.
    return pipeline.load_landmarks(Path(value), accept_low_confidence=True)[1]


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
    model: Annotated[
        str | None, typer.Option(help="YOLO weights, e.g. yolo11m.pt (default: the profile's)")
    ] = None,
    stride: int | None = None,
    max_frames: int | None = None,
    stages: Annotated[
        str | None, typer.Option(help="Comma-separated subset, e.g. detect,track")
    ] = None,
    title: str | None = None,
    accept_low_confidence: Annotated[bool, ACCEPT_LOW] = False,
) -> None:
    """Run the pipeline end to end (or just `--stages`) and write `out/game.json`."""
    if detector == "synthetic" and ground_truth is None:
        guess = input.parent / "ground_truth.json"
        ground_truth = guess if guess.exists() else None
    if landmarks and Path(landmarks).exists():
        # A file goes the `--calib` way, so an accepted ok=false proposal is recorded.
        calib, landmarks = Path(landmarks), None
    if calib is None and landmarks is None:
        guess = input.parent / "landmarks.json"
        calib = guess if guess.exists() else None
    try:
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
            model=model,
            stages=[s.strip() for s in stages.split(",") if s.strip()] if stages else None,
            stride=stride,
            max_frames=max_frames,
            title=title,
            progress=_echo_progress,
            accept_low_confidence=accept_low_confidence,
        )
    except pipeline.LowConfidenceLandmarks as exc:
        raise _refuse(exc) from exc
    typer.echo(str(game))


@app.command()
def calibrate(
    landmarks: Annotated[str, typer.Option(help="landmarks.json path or inline JSON")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Where to write calib.json")],
    sport: str = "basketball",
    variant: str | None = None,
    accept_low_confidence: Annotated[bool, ACCEPT_LOW] = False,
) -> None:
    """Landmark clicks → homography. Fails if reprojection error exceeds 5 px."""
    points = _landmarks(landmarks, accept_low_confidence)
    assert points is not None
    profile = load_profile(sport)
    data = calib_mod.calibrate(points, profile, variant or _variant_of(landmarks))
    path = Path(landmarks)
    raw = json.loads(path.read_text(encoding="utf-8") if path.exists() else landmarks)
    if block := pipeline.low_confidence(raw):  # reached only with --accept-low-confidence
        data["low_confidence_override"] = block
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
        # A prior only leashes the fit — dots to drag are exactly what it is for.
        prior=_landmarks(str(prior), accept_low=True) if prior else None,
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

    Errors are taken under whichever whole-court relabelling (as clicked, l<->r, n<->f,
    or both) fits best: the template is symmetric, the fit's labelling follows a winding
    convention (`templatefit._orderings`) that a hand-clicked set need not, and the
    homography is the same court either way. The relabelling used is printed.

    A `<clip>_smoke` frame named in full in `--clips` is scored against the clip's
    `_240s` ground truth (same fixed camera).
    """
    from . import autocalib as auto_mod

    frames_dir = samples / "frames"
    tag = "" if backend in ("auto", "vlm", "claude-cli") else f"{backend}_"
    wanted = {c.strip() for c in clips.split(",")} if clips else None
    relabels = {
        "as clicked": lambda n: n,
        "l<->r": lambda n: auto_mod._swap(n, "l", "r"),
        "n<->f": lambda n: auto_mod._swap(n, "n", "f"),
        "rotated": lambda n: auto_mod._swap(auto_mod._swap(n, "l", "r"), "n", "f"),
    }
    rows: list[tuple[str, dict[str, float], float, dict, bool, float, str]] = []
    jpgs = sorted(samples.glob("*_240s.jpg")) + sorted(
        samples / f"{c}.jpg" for c in wanted or () if c.endswith("_smoke")
    )
    for jpg in jpgs:
        stem = jpg.stem
        if wanted and stem not in wanted and stem.split("_")[1] not in wanted:
            continue
        truth_path = samples / f"{stem}.landmarks.json"
        if not truth_path.is_file():
            truth_path = samples / f"{stem.removesuffix('_smoke')}_240s.landmarks.json"
        if not jpg.is_file() or not truth_path.is_file():
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
        runtime = float("nan")
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
            runtime = time.perf_counter() - t0
            proposal.notes = f"{proposal.notes} [{runtime:.0f}s]".strip()
            frames_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(proposal.as_dict(), indent=1), encoding="utf-8")
            auto_mod.draw_overlay(
                img,
                proposal,
                frames_dir / f"autocalib_{tag}{stem}.jpg",
                truth,
                template=profile.template(truth_doc.get("variant")),
            )
        got = proposal.landmarks_px

        def errors_as(rename, got=got, truth=truth) -> dict[str, float]:
            return {
                name: math.dist(got[rename(name)], p)
                for name, p in truth.items()
                if rename(name) in got
            }

        def median(errs: dict[str, float]) -> float:
            return sorted(errs.values())[len(errs) // 2] if errs else float("inf")

        relabel = min(relabels, key=lambda k: median(errors_as(relabels[k])))
        errors = errors_as(relabels[relabel])
        rows.append(
            (
                stem,
                errors,
                proposal.reprojection_error_px or float("nan"),
                truth,
                proposal.ok,
                runtime,
                relabel,
            )
        )
        typer.echo(
            f"\n{stem}  source={proposal.source} ok={proposal.ok}  labels {relabel}"
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
    typer.echo(
        f"{'clip':<32}{'ok':>6}{'n':>4}{'median':>8}{'worst':>8}{'mean px':>9}{'<20px':>7}"
        f"{'head<20':>9}{'reproj':>8}{'time s':>8}"
    )
    nan = float("nan")
    for stem, errors, reproj, truth, ok, runtime, _ in rows:
        head = [errors[n] for n in HEADLINE if n in errors]
        want = [n for n in HEADLINE if n in truth]
        values = sorted(errors.values())
        typer.echo(
            f"{stem:<32}{ok!s:>6}{len(values):>4}"
            f"{(values[len(values) // 2] if values else nan):>8.1f}"
            f"{(values[-1] if values else nan):>8.1f}"
            f"{(sum(values) / len(values) if values else nan):>9.1f}"
            f"{(sum(v <= NEAR_PX for v in values) / max(len(values), 1)):>7.0%}"
            f"{sum(v <= NEAR_PX for v in head):>5}/{len(want):<3}"
            f"{reproj:>8.1f}{runtime:>8.1f}"
        )
    allv = [v for row in rows for v in row[1].values()]
    typer.echo(
        f"{'ALL':<32}{len(allv):>4}{(sum(allv) / max(len(allv), 1)):>10.1f}"
        f"{(sum(v <= NEAR_PX for v in allv) / max(len(allv), 1)):>8.0%}"
    )


def _floats(value: str | None, n: int) -> tuple[float, ...] | None:
    if not value:
        return None
    out = tuple(float(v) for v in value.replace("x", ",").split(","))
    if len(out) != n:
        raise typer.BadParameter(f"expected {n} comma-separated numbers, got {value!r}")
    return out


# The repo's TTS clips for the voice triggers; absent (a bare courtcam install) the
# generator falls back to a labelled tone pattern.
VOICE_DIR = Path(__file__).resolve().parents[2] / "samples" / "synthetic" / "voice"


@app.command()
def synth(
    out: Annotated[Path, typer.Option("--out", "-o", help="Directory for the clip + truth")],
    sport: str = "basketball",
    variant: str | None = None,
    duration: float = 40.0,
    fps: int = 30,
    seed: int = 7,
    size: Annotated[str, typer.Option(help="WxH, e.g. 1920x1080 or 3840x2160 (4K)")] = "1280x720",
    eye: Annotated[str | None, typer.Option(help="Camera position x,y,z in court metres")] = None,
    target: Annotated[str | None, typer.Option(help="Camera look-at x,y,z")] = None,
    focal: Annotated[
        float | None, typer.Option(help="Focal length in px (default: fit court)")
    ] = None,
    k1: Annotated[float, typer.Option(help="Division-model lens k1 (< 0 = barrel)")] = 0.0,
    voice_dir: Annotated[Path | None, typer.Option(help="TTS clips for voice triggers")] = None,
    video: Annotated[bool, typer.Option(help="Encode clip.mp4 (off: truth + audio only)")] = True,
) -> None:
    """Generate a synthetic clip (video + audio) with full ground truth."""
    from .synth import CameraSpec, generate

    w, h = (int(v) for v in _floats(size, 2))  # type: ignore[misc]
    spec = CameraSpec(eye=_floats(eye, 3), target=_floats(target, 3), f_px=focal, k1=k1)
    voices = voice_dir or (VOICE_DIR if VOICE_DIR.is_dir() else None)
    t0 = time.perf_counter()
    paths = generate(
        out, sport=sport, variant=variant, duration_s=duration, fps=fps, seed=seed,
        size=(w, h), camera=spec, voice_dir=voices, video=video,
    )  # fmt: skip
    for name, path in paths.items():
        typer.echo(f"{name}: {path}")
    typer.echo(f"generated in {time.perf_counter() - t0:.1f}s")


@app.command("eval")
def eval_cmd(
    truth: Annotated[Path, typer.Option("--gt", help="Synthetic ground_truth.json")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Pipeline output directory")],
    iou: float = 0.5,
    json_out: Annotated[Path | None, typer.Option("--json", help="Write the metrics here")] = None,
) -> None:
    """MOTA / IDF1 / ID switches / detection P-R of a pipeline run against synthetic truth."""
    from .metrics import evaluate_run

    report = evaluate_run(truth, out, iou=iou)
    text = json.dumps(report, indent=1)
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(text, encoding="utf-8")
    typer.echo(text)


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
