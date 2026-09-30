"""Stage 2a — propose the calibration landmarks so the user does not have to click them.

D-23 (proposal). Two backends, used together:

* `vlm` / `claude-cli` — a Claude vision model reads the calibration frame with a faint
  coordinate grid burned in and answers with source-pixel coordinates per landmark name.
  It is asked twice (once on a horizontally mirrored copy, with the labels un-mirrored);
  a landmark is kept only where the two answers agree, and the agreement *is* the
  confidence. A model is good at "that is the left corner of the paint" and bad at
  "that is pixel 1174"; the grid turns the second question into reading a ruler.
* `lines` — OpenCV. Its own corner candidates are weak, but `LineSnapper.snap` pulls a
  proposed landmark onto the nearest real line intersection within 40 px, which is where
  the pixel accuracy actually comes from.
* `template` — `courtcam.templatefit`, no model at all. It fits the sport's court
  template to the painted lines and reads every landmark off the one homography, so the
  proposal is self-consistent by construction. This is what `auto` runs.

`autocalibrate(..., backend="auto")` fits the template; pass `prior=<landmark pixels>`
(from a model backend, or from a previous calibration) and the fit is leashed to it.
`ok=False` means "show the user the dots but make them fix it" — the manual click path
is never removed.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

from . import calibrate as calib_mod
from . import templatefit as tfit
from .profiles import Profile

#: Claude's image budget — anything longer on the long side is downscaled before sending.
MAX_SIDE_PX = 1568
#: Grid pitch in *source* pixels. Lines every step, labels every other one.
GRID_STEP_PX = 100
#: Two answers count as agreeing if they are this close, as a fraction of image width.
AGREE_FRAC = 0.03
MIN_CONFIDENCE = 0.5
#: How much of the template's visible line length must land on paint before the
#: `template` backend calls a fit `ok`. Measured over the six corpus clips: the two fits
#: that are right score 0.92 and 0.94, and four of the five that are wrong score
#: 0.61-0.74. It is a floor, not a guarantee — `basketball_pavilion` scores 0.89 with a
#: badly wrong court — but it is the only signal the backend has that is not circular.
MIN_TEMPLATE_SCORE = 0.90
#: A fit with most of the template off-frame is unconstrained — badminton_auditorium
#: scored 0.94 for a court 858 px wrong at 65 % in frame.
MIN_INFRAME_FRAC = 0.85
#: ...and one no pinhole camera can make is a wedge of court drawn over the sky:
#: `basketball_parkwide` (no court paint at all) scored 0.95-0.97 with camera skew 0.13
#: (`templatefit.physical`). Every hand-clicked court is 0.002-0.023.
MAX_CAMERA_SKEW = 0.05
SNAP_RADIUS_PX = 40.0
#: The lens search (D-24's "next", D-25's model), run when the straight fit is not `ok`.
#: `templatefit` searches over STRAIGHT lines; on an ultra-wide camera a court edge is a
#: curve that fragments into chords no `HoughLinesP` line represents, so the segments
#: are straightened at each of these `k1` and the fit re-run there; the refinement then
#: moves `k1` continuously (`templatefit.K1_PER_PX`), so the grid only has to land in
#: the right basin. No 0.0: the straight pass is that, and the refinement reaches it.
K1_CANDIDATES = (-0.2, -0.4, -0.6)
#: Wall clock for the whole fit, every candidate included; the last candidates are
#: skipped on a slow frame rather than run.
TEMPLATE_BUDGET_S = 40.0
#: Wall clock per model call. The brief's 90 s is not survivable through the
#: `claude` CLI — a measured pass on a 2560 px panorama is 100-240 s — so the default
#: is 420 s and the two passes run concurrently — a measured pass on the 2560 px
#: kennesaw panorama is 266 s and $0.26. The SDK backend has no agent harness in front
#: of it and is far quicker. `COURTCAM_VLM_TIMEOUT_S` overrides it.
TIMEOUT_S = int(os.environ.get("COURTCAM_VLM_TIMEOUT_S") or 420)
DEFAULT_MODEL = "claude-sonnet-5"
#: `claude -p --effort`, only when `COURTCAM_VLM_EFFORT` is set — the CLI's own default
#: is what the eval numbers were measured with. Measured on the real-footage corpus:
#: `low` answers in 18-100 s instead of 240-300 s but the two passes then disagree by
#: 100-1000 px on every corner, so everything is dropped; `medium` costs $0.42 and 6.5 min
#: on one 2560 px panorama, past the timeout. Neither is an improvement, hence no default.
CLI_EFFORT = os.environ.get("COURTCAM_VLM_EFFORT") or ""
#: A point that only one of the two passes could name (the near rim has no mirror twin).
SINGLE_PASS_CONFIDENCE = 0.5


@dataclass
class Proposal:
    """What a backend thinks the landmarks are, and how much it believes itself."""

    landmarks_px: dict[str, tuple[float, float]] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    source: str = "none"
    notes: str = ""
    ok: bool = False
    reprojection_error_px: float | None = None
    snapped: dict[str, bool] = field(default_factory=dict)
    #: The lens curvature the fit had to take out to find the court, 0.0 for a straight
    #: lens. Same one-parameter division model as `distortion`/`calib.json` (D-25), but
    #: fitted from the LINES rather than from clicked landmarks. Landmarks are reported
    #: in source pixels either way, so a consumer that ignores this still gets dots that
    #: land on the frame.
    k1: float = 0.0
    #: metres -> pixels, when the backend fitted one. Deliberately NOT in `as_dict`:
    #: the API contract is landmark pixels, and the uploader commits those.
    h_inv: np.ndarray | None = field(default=None, repr=False)
    #: Required landmarks (`profile.court.landmarks`) the fit puts outside the picture.
    #: They are absent from `landmarks_px`, which the uploader already reads as "Not
    #: visible"; this names them so the notes and the UI do not have to work it out.
    not_visible: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "landmarks_px": {k: [float(v[0]), float(v[1])] for k, v in self.landmarks_px.items()},
            "confidence": {k: round(float(v), 3) for k, v in self.confidence.items()},
            "snapped": dict(self.snapped),
            "source": self.source,
            "notes": self.notes,
            "ok": self.ok,
            "reprojection_error_px": self.reprojection_error_px,
            "k1": self.k1,
            "not_visible": list(self.not_visible),
        }


class Calibrator(Protocol):
    """Anything that can turn a frame into a landmark proposal."""

    def propose(
        self, frame_bgr: np.ndarray, profile: Profile, variant: str | None = None
    ) -> Proposal: ...


# ------------------------------------------------------------------ the gridded image


def gridded(
    frame_bgr: np.ndarray, *, max_side: int = MAX_SIDE_PX, step: int = GRID_STEP_PX
) -> tuple[np.ndarray, float]:
    """Downscale to `max_side` and burn in a source-pixel coordinate grid.

    Returns (image, scale). Labels are in SOURCE pixels, which is what we want back.
    """
    h, w = frame_bgr.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    img = (
        cv2.resize(frame_bgr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else frame_bgr.copy()
    )
    gh, gw = img.shape[:2]
    grid = img.copy()
    for x in range(0, w, step):
        cv2.line(grid, (round(x * scale), 0), (round(x * scale), gh), (0, 255, 255), 1)
    for y in range(0, h, step):
        cv2.line(grid, (0, round(y * scale)), (gw, round(y * scale)), (0, 255, 255), 1)
    img = cv2.addWeighted(grid, 0.35, img, 0.65, 0.0)

    def label(text: str, at: tuple[int, int]) -> None:
        cv2.putText(img, text, at, cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, text, at, cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1, cv2.LINE_AA)

    for x in range(0, w, step * 2):
        for y_at in (14, gh - 5):
            label(str(x), (min(round(x * scale) + 2, gw - 34), y_at))
    for y in range(0, h, step * 2):
        for x_at in (2, gw - 36):
            label(str(y), (x_at, min(round(y * scale) + 12, gh - 2)))
    return img, scale


def _jpeg(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError("cv2.imencode failed on the calibration frame")
    return bytes(buf)


# ------------------------------------------------------------------------- the prompt


def _descriptions(profile: Profile) -> dict[str, str]:
    return dict(getattr(profile.court, "landmark_descriptions", None) or {})


def wanted_landmarks(
    profile: Profile, variant: str | None = None, *, optional: bool = False
) -> list[str]:
    """What to ask the model for — by default the same list a human is walked through.

    Measured: adding the ten `landmarks_optional` triples the answer and pushes a
    2560 px panorama past a 3-minute call without improving the four corners, so they
    are opt-in (`--ask-optional`).
    """
    known = set(profile.template(variant).landmarks)
    names = list(profile.court.landmarks)
    if optional:
        names += profile.court.landmarks_optional
    return [n for n in dict.fromkeys(names) if n in known]


def build_prompt(
    profile: Profile, variant: str | None, size: tuple[int, int], *, optional: bool = False
) -> str:
    """The whole instruction, including the profile's plain-language landmark glossary."""
    w, h = size
    names = wanted_landmarks(profile, variant, optional=optional)
    desc = _descriptions(profile)
    orientation = getattr(profile.court, "orientation_hint", None) or ""
    glossary = "\n".join(f"- {n}: {desc.get(n, n.replace('_', ' '))}" for n in names)
    skeleton = ", ".join(f'"{n}": [x, y]' for n in names)
    return f"""You are calibrating a fixed camera that is filming a {profile.display_name.lower()} \
court ({variant or profile.default_variant()} court).

The picture has a faint yellow coordinate grid burned into it. A grid line is drawn every \
{GRID_STEP_PX} pixels of the ORIGINAL frame and every other line is labelled along the top, \
bottom, left and right edges. The ORIGINAL frame is {w} x {h} pixels: x runs 0 to {w - 1} \
left to right, y runs 0 to {h - 1} top to bottom. Read every position off the grid labels and \
interpolate between lines. Answer in ORIGINAL-frame pixels, not in the pixels of the picture \
you are shown.

{orientation}

Find the centre of each of these points on the court:
{glossary}

Rules:
- A point that is outside the picture, hidden behind a player, or that you simply cannot \
locate must be `null`. A wrong point is much worse than a missing one.
- Court lines are painted with some width — aim for the middle of the line.
- Do not describe what you are doing and do not use a markdown code fence.

Reply with ONLY this JSON object:
{{{skeleton}}}"""


# ---------------------------------------------------------------------- model backends


def _extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in model reply: {text[:200]!r}")
    depth = 0
    for i in range(start, len(text)):
        depth += (text[i] == "{") - (text[i] == "}")
        if depth == 0:
            return json.loads(text[start : i + 1])
    raise ValueError(f"unterminated JSON object in model reply: {text[:200]!r}")


def _model_id() -> str:
    return os.environ.get("COURTCAM_VLM_MODEL") or DEFAULT_MODEL


def ask_sdk(img: np.ndarray, prompt: str, *, timeout_s: int = TIMEOUT_S) -> dict[str, Any]:
    """One vision call through the Anthropic SDK (`courtcam[vlm]`, `ANTHROPIC_API_KEY`)."""
    import anthropic  # imported lazily: the extra is optional

    client = anthropic.Anthropic().with_options(timeout=float(timeout_s))
    reply = client.messages.create(
        model=_model_id(),
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.standard_b64encode(_jpeg(img)).decode(),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    text = "".join(b.text for b in reply.content if b.type == "text")
    return _extract_json(text)


def ask_cli(img: np.ndarray, prompt: str, *, timeout_s: int = TIMEOUT_S) -> dict[str, Any]:
    """One vision call through the `claude` CLI — the local-dev path with no API key."""
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("no `claude` executable on PATH")
    with tempfile.TemporaryDirectory(prefix="courtcam-autocalib-") as tmp:
        path = Path(tmp) / "calib_grid.jpg"
        path.write_bytes(_jpeg(img))
        # `--safe-mode --strict-mcp-config` strips the developer's CLAUDE.md, plugins,
        # hooks and MCP servers out of the session; `--system-prompt` replaces the
        # coding-agent preamble. Without those a call costs ~4x and drags in whatever
        # the machine happens to have configured.
        argv = [
            exe,
            "-p",
            "--output-format",
            "json",
            "--model",
            _model_id(),
            *(("--effort", CLI_EFFORT) if CLI_EFFORT else ()),
            "--safe-mode",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--tools",
            "Read",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            "--max-turns",
            "4",
            "--system-prompt",
            "You are a precise computer-vision annotator. You look at one image and "
            "reply with only the JSON object you were asked for.",
            f"Use the Read tool on {path} — it is the picture. Read is the only tool "
            "available to you: do not ask for permission to run anything else, and do "
            "not offer to crop or zoom. Answer from the picture as it is. "
            f"{prompt}",
        ]
        done = subprocess.run(  # noqa: S603 - argv list, no shell
            argv, capture_output=True, text=True, timeout=timeout_s, cwd=tmp
        )
    if done.returncode != 0:
        raise RuntimeError(f"claude CLI exited {done.returncode}: {done.stderr[-400:]}")
    envelope = json.loads(done.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude CLI error: {str(envelope.get('result'))[:300]}")
    return _extract_json(str(envelope.get("result", "")))


# --------------------------------------------------------------- the two-pass proposal


def _settle(job: Future) -> Any:
    """A finished pass, or the exception it died of — one bad pass must not kill both."""
    try:
        return job.result()
    except Exception as exc:  # noqa: BLE001 - reported as a note, not raised
        return exc


def _swap(name: str, a: str, b: str) -> str:
    """`corner_nl` <-> `corner_fl` for ('n','f'); `centre_l` <-> `centre_r` for ('l','r')."""
    head, _, tail = name.rpartition("_")
    if not head or not tail:
        return name
    flipped = tail.replace(a, "\0").replace(b, a).replace("\0", b)
    return f"{head}_{flipped}"


def _parse_points(raw: dict[str, Any], names: list[str]) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for name in names:
        value = raw.get(name)
        if not isinstance(value, list | tuple) or len(value) != 2:
            continue
        try:
            out[name] = (float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            continue
    return out


def twinless(profile: Profile, variant: str | None = None) -> set[str]:
    """Landmarks the mirrored pass cannot give a second opinion on.

    Flipping the picture left-right swaps which basket is "near", so the mirrored
    answer's `corner_nl` is the straight answer's `corner_fl` and so on — the name
    transform is a reflection of the court about its half-way line. A landmark whose
    reflected position has no name in the template (the near `rim`: its twin is the far
    rim, which the template does not name) therefore comes back single-pass instead of
    being compared against a different physical point and dropped every time.
    """
    template = profile.template(variant)
    axis = float(template.polygon[:, 1].min() + template.polygon[:, 1].max())
    out = set()
    for name, (x, y) in template.landmarks.items():
        twin = template.landmarks.get(_swap(name, "n", "f"))
        if twin is None or abs(twin[0] - x) > 1e-6 or abs(twin[1] - (axis - y)) > 1e-6:
            out.add(name)
    return out


def propose_vlm(
    frame_bgr: np.ndarray,
    profile: Profile,
    variant: str | None = None,
    *,
    backend: str = "vlm",
    timeout_s: int = TIMEOUT_S,
    optional: bool = False,
) -> Proposal:
    """Ask twice — once straight, once on a mirrored copy — and keep what agrees.

    The mirror is not just noise injection: it swaps which basket is "near", so a model
    that is quietly biased toward one end of the court disagrees with itself and the
    landmark is dropped instead of silently poisoning the fit.
    """
    ask = ask_cli if backend == "claude-cli" else ask_sdk
    w = frame_bgr.shape[1]
    names = wanted_landmarks(profile, variant, optional=optional)
    prompt = build_prompt(profile, variant, (w, frame_bgr.shape[0]), optional=optional)
    notes: list[str] = []

    # ponytail: the `claude` CLI is an agent harness, not an API client — two of them at
    # once reliably time out or exit 1, so that backend runs its passes one after the
    # other (~9 min a clip). The SDK has no such problem and overlaps them.
    with ThreadPoolExecutor(max_workers=1 if ask is ask_cli else 2) as pool:
        jobs = [
            pool.submit(ask, gridded(img)[0], prompt, timeout_s=timeout_s)
            for img in (frame_bgr, cv2.flip(frame_bgr, 1))
        ]
        answers = [_settle(j) for j in jobs]

    if isinstance(answers[0], Exception):
        return Proposal(source=backend, notes=f"first pass failed: {answers[0]}")
    straight = _parse_points(answers[0], names)
    if isinstance(answers[1], Exception):
        mirrored = {}
        notes.append(f"mirror pass failed ({answers[1]}); confidences are single-pass")
    else:
        mirrored = {
            _swap(k, "n", "f"): (w - 1.0 - v[0], v[1])
            for k, v in _parse_points(answers[1], names).items()
        }

    tol = AGREE_FRAC * w
    points: dict[str, tuple[float, float]] = {}
    confidence: dict[str, float] = {}
    dropped: list[str] = []
    alone = twinless(profile, variant)
    for name, p in straight.items():
        q = None if name in alone else mirrored.get(name)
        if q is None:
            points[name], confidence[name] = p, SINGLE_PASS_CONFIDENCE
            continue
        dist = float(np.hypot(p[0] - q[0], p[1] - q[1]))
        if dist > tol:
            # How far apart says *why*: tens of px is noise, hundreds is the model
            # having labelled a different corner. Worth keeping in the note.
            dropped.append(f"{name} ({dist:.0f} px apart)")
            continue
        points[name] = ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)
        confidence[name] = 1.0 - dist / tol
    if dropped:
        notes.append(f"dropped, passes disagreed by more than {tol:.0f} px: {', '.join(dropped)}")
    return Proposal(
        landmarks_px=points,
        confidence=confidence,
        source=backend,
        notes="; ".join(notes),
    )


# ------------------------------------------------------------------- lines and snapping


class LineSnapper:
    """White court lines, and the ability to pull a nearby point onto one.

    ponytail: Hough on an adaptive-threshold L-channel mask, no learned line model. It
    finds painted lines on wood and asphalt and finds nothing on a dusty park court —
    which is the honest answer there. Upgrade path is a line-segment CNN if it matters.
    """

    def __init__(self, frame_bgr: np.ndarray, *, min_len_frac: float = 0.04) -> None:
        self.shape = frame_bgr.shape[:2]
        lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)[:, :, 0]
        lab = cv2.GaussianBlur(lab, (5, 5), 0)
        # Court lines are *brighter than their surroundings*, not bright in absolute
        # terms — a sunlit asphalt court is brighter than an indoor line.
        mask = cv2.adaptiveThreshold(
            lab, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, -12
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        min_len = int(min_len_frac * max(self.shape))
        found = cv2.HoughLinesP(
            mask, 1, np.pi / 360, threshold=60, minLineLength=min_len, maxLineGap=12
        )
        self.mask = mask
        self.segments: np.ndarray = (
            found.reshape(-1, 4).astype(np.float64) if found is not None else np.empty((0, 4))
        )

    def _near(self, point: tuple[float, float], radius: float) -> np.ndarray:
        """Segments whose *body* passes within `radius` of the point."""
        if not len(self.segments):
            return self.segments
        a = self.segments[:, :2]
        b = self.segments[:, 2:]
        ab = b - a
        ap = np.asarray(point, dtype=np.float64) - a
        length2 = np.maximum((ab * ab).sum(1), 1e-9)
        t = np.clip((ap * ab).sum(1) / length2, 0.0, 1.0)
        foot = a + t[:, None] * ab
        return self.segments[np.linalg.norm(foot - point, axis=1) <= radius]

    @staticmethod
    def _intersect(s: np.ndarray, t: np.ndarray) -> tuple[float, float] | None:
        d1 = s[2:] - s[:2]
        d2 = t[2:] - t[:2]
        den = d1[0] * d2[1] - d1[1] * d2[0]
        norm = float(np.linalg.norm(d1) * np.linalg.norm(d2))
        if norm < 1e-9 or abs(den) / norm < 0.34:  # < ~20 degrees apart: not a corner
            return None
        w = s[:2] - t[:2]
        u = (d2[0] * w[1] - d2[1] * w[0]) / den
        return float(s[0] + u * d1[0]), float(s[1] + u * d1[1])

    def snap(
        self, point: tuple[float, float], radius: float = SNAP_RADIUS_PX
    ) -> tuple[tuple[float, float], bool]:
        """Nearest line intersection within `radius`, else nearest line point, else as-is."""
        near = self._near(point, radius)
        best: tuple[float, float] | None = None
        best_d = radius
        for i in range(len(near)):
            for j in range(i + 1, len(near)):
                hit = self._intersect(near[i], near[j])
                if hit is None:
                    continue
                d = float(np.hypot(hit[0] - point[0], hit[1] - point[1]))
                if d < best_d:
                    best, best_d = hit, d
        if best is not None:
            return best, True
        if len(near):
            a, b = near[:, :2], near[:, 2:]
            ab = b - a
            ap = np.asarray(point, dtype=np.float64) - a
            t = np.clip((ap * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-9), 0.0, 1.0)
            foot = a + t[:, None] * ab
            k = int(np.argmin(np.linalg.norm(foot - point, axis=1)))
            return (float(foot[k][0]), float(foot[k][1])), True
        return point, False

    def corner_candidates(self) -> list[tuple[float, float]]:
        """Every in-frame intersection of two detected lines — unnamed, hence unusable
        on its own. This exists so `--backend lines` can report what it can see."""
        n = min(len(self.segments), 60)
        hits = (
            self._intersect(self.segments[i], self.segments[j])
            for i in range(n)
            for j in range(i + 1, n)
        )
        return [c for c in hits if c and 0 <= c[0] < self.shape[1] and 0 <= c[1] < self.shape[0]]

    def propose(
        self, frame_bgr: np.ndarray, profile: Profile, variant: str | None = None
    ) -> Proposal:
        """`lines` alone cannot *name* a corner — it can only say where the corners are."""
        del frame_bgr, profile, variant
        return Proposal(
            source="lines",
            notes=(
                f"{len(self.segments)} line segments, "
                f"{len(self.corner_candidates())} unnamed corner candidates"
            ),
        )


# ----------------------------------------------------------------- the template backend


def _prior_quad(
    prior: dict[str, tuple[float, float]], profile: Profile, variant: str | None
) -> np.ndarray | None:
    """Where a model proposal thinks the court outline is, as 4 image points."""
    template = profile.template(variant)
    known = {n: p for n, p in prior.items() if n in template.landmarks}
    if len(known) < 4:
        return None
    try:
        h, _ = calib_mod.homography(known, template)
    except (calib_mod.CalibrationError, np.linalg.LinAlgError, cv2.error):
        return None
    return tfit.project(tfit.rectangles(template)[0], np.linalg.inv(h))


def propose_template(
    frame_bgr: np.ndarray,
    profile: Profile,
    variant: str | None = None,
    *,
    prior: dict[str, tuple[float, float]] | None = None,
) -> Proposal:
    """Fit the court template to the painted lines and read the landmarks off the fit.

    Every landmark comes from one homography (and one `k1`), so the proposal is
    self-consistent by construction — which the two-pass model proposal never was.
    Landmarks that land outside the picture (letterbox bars excluded) are left out rather
    than guessed at, and the required ones among them are named in `not_visible`;
    `landmarks_optional` are included, because they cost nothing here and a clip with a
    corner off-frame needs them (D-19).
    """
    from .pipeline import calibrate_lens  # the commit path; imported late, it is heavy

    template = profile.template(variant)
    quad = _prior_quad(prior, profile, variant) if prior else None
    h, w = frame_bgr.shape[:2]
    size = (w, h)
    mask = tfit.line_mask(frame_bgr)
    deadline = time.monotonic() + TEMPLATE_BUDGET_S

    fits, note = tfit.fit(frame_bgr, template, mask=mask, prior_quad=quad)
    notes = [note] if note else []
    plain = fits[0] if fits else None
    straight_ok = (
        plain is not None
        and plain.score >= MIN_TEMPLATE_SCORE
        and plain.inframe_frac >= MIN_INFRAME_FRAC
        and tfit.physical(plain.h_inv[None], size)[1][0] <= MAX_CAMERA_SKEW
    )
    skipped = []
    lens: list[tfit.Fit] = []
    # A straight fit that already sits on the paint, with the court in the picture, has
    # no barrel to take out: pickleball passes here and stays a 1-4 s, 10/10 answer. The
    # rest get the lens search; its fits and the straight one are ranked by covered
    # paint (`templatefit.covered`), the one measure that means the same at every k1.
    for candidate in () if straight_ok else K1_CANDIDATES:
        if time.monotonic() > deadline:
            skipped.append(candidate)
            continue
        got, _ = tfit.fit(
            frame_bgr, template, mask=mask, prior_quad=quad, k1=candidate, lens_search=True
        )
        lens += got[:1]
    if lens:
        # The straight fit competes too: on powellgym it is right at the near basket
        # and the lens search is not.
        fits = sorted([*lens, *fits[:1]], key=lambda c: -c.covered_px)
    if skipped:
        notes.append(f"skipped k1 {skipped} — {TEMPLATE_BUDGET_S:.0f} s budget")
    if quad is not None and prior:
        notes.append(f"seeded from a {len(prior)}-landmark prior")
    if not fits:
        return Proposal(source="template", notes="; ".join(notes))

    best = fits[0]
    k1 = best.k1
    if lens and best is not plain:
        notes.append(
            f"lens search: k1 {k1:+.3f}, straight fit scored {plain.score if plain else 0.0:.3f}"
        )
    runner = fits[1].score if len(fits) > 1 else 0.0
    margin = best.score - runner
    # Two numbers the user can act on: is the fit good in absolute terms, and was it
    # the only good one? A clip with two equally good answers is a clip to check.
    confidence = round(float(min(1.0, best.score) * (0.6 + 0.4 * min(1.0, margin / 0.03))), 3)
    names = list(template.landmarks)
    # The fit lives in undistorted pixels; the UI draws on the source frame.
    points = tfit.to_source(tfit.project(template.landmark_array(names), best.h_inv), k1, size)
    x0, y0, x1, y1 = tfit.content_box(frame_bgr)
    landmarks = {
        n: (float(x), float(y))
        for n, (x, y) in zip(names, points, strict=True)
        if x0 <= x < x1 and y0 <= y < y1
    }
    hidden = [n for n in profile.court.landmarks if n in template.landmarks and n not in landmarks]
    notes.append(
        f"score {best.score:.3f} (runner-up {runner:.3f}), "
        f"{best.inframe_frac:.0%} of the template in frame, "
        f"{len(template.landmarks) - len(landmarks)} landmark(s) off-frame"
        + (f" (not visible: {', '.join(hidden)})" if hidden else "")
    )
    proposal = Proposal(
        landmarks_px=landmarks,
        confidence=dict.fromkeys(landmarks, confidence),
        source="template",
        h_inv=best.h_inv,
        k1=k1,
        not_visible=hidden,
    )
    try:
        calib = calibrate_lens(landmarks, profile, variant, size)
    except calib_mod.CalibrationError as exc:
        notes.append(str(exc))
    except Exception as exc:  # noqa: BLE001 - a bad fit is a UI state, not a crash
        notes.append(f"homography failed: {exc}")
    else:
        proposal.reprojection_error_px = float(calib["reproj_error_px"])
        # The reprojection error is ~0 here BY CONSTRUCTION — every landmark came out of
        # the same homography, so it measures nothing at all. The line score is the only
        # honest quality signal, so `ok` (which the uploader reads as "offer Accept")
        # rides on that instead.
        skew = float(tfit.physical(best.h_inv[None], size)[1][0])
        why = []
        if best.score < MIN_TEMPLATE_SCORE:
            why.append(
                f"score {best.score:.2f} < {MIN_TEMPLATE_SCORE}: the court template does "
                "not sit on the paint"
            )
        if best.inframe_frac < MIN_INFRAME_FRAC:
            why.append(
                f"only {best.inframe_frac:.0%} of the template is in frame "
                f"(< {MIN_INFRAME_FRAC:.0%})"
            )
        if skew > MAX_CAMERA_SKEW:
            why.append(f"camera skew {skew:.2f} > {MAX_CAMERA_SKEW}: no real camera sees that")
        proposal.ok = not why
        if why:
            notes.append("; ".join(why) + ", so these are dots to drag, not dots to accept")
    proposal.notes = "; ".join(n for n in notes if n)
    return proposal


# ---------------------------------------------------------------------- handedness fix


def _orientation_ok(
    points: dict[str, tuple[float, float]], profile: Profile, variant: str | None
) -> bool | None:
    """Is the labelling a view from above the court, or a mirror of one?

    A court template is symmetric about its long axis, so a globally swapped
    left/right labelling fits *exactly as well* and reprojection error cannot tell them
    apart — only the winding can. Three non-collinear landmarks that wind one way in
    metres must wind the other way in pixels, because image y points down.
    Returns None when there are not three usable points.
    """
    template = profile.template(variant)
    names = [n for n in points if n in template.landmarks][:3]
    if len(names) < 3:
        return None
    court = template.landmark_array(names)
    pix = np.asarray([points[n] for n in names], dtype=np.float64)

    def cross(p: np.ndarray) -> float:
        # numpy 2 dropped the 2-D form of np.cross; this is the same z component.
        u, v = p[1] - p[0], p[2] - p[0]
        return float(u[0] * v[1] - u[1] * v[0])

    if abs(cross(court)) < 1e-6 or abs(cross(pix)) < 1e-6:
        return None
    return cross(court) * cross(pix) < 0


def _mirror_labels(points: dict[str, Any]) -> dict[str, Any]:
    return {_swap(k, "l", "r"): v for k, v in points.items()}


# --------------------------------------------------------------------------- the `auto`


def autocalibrate(
    frame_bgr: np.ndarray,
    profile: Profile,
    variant: str | None = None,
    *,
    backend: str = "auto",
    snap_radius: float = SNAP_RADIUS_PX,
    min_confidence: float = MIN_CONFIDENCE,
    timeout_s: int = TIMEOUT_S,
    optional: bool = False,
    prior: dict[str, tuple[float, float]] | None = None,
) -> Proposal:
    """Propose landmarks, snap them to the painted lines, and try to fit a homography."""
    model_backend = _resolve_backend(backend)
    if model_backend == "template":
        return propose_template(frame_bgr, profile, variant, prior=prior)
    if model_backend == "lines":
        return LineSnapper(frame_bgr).propose(frame_bgr, profile, variant)

    proposal = propose_vlm(
        frame_bgr, profile, variant, backend=model_backend, timeout_s=timeout_s, optional=optional
    )
    notes = [proposal.notes] if proposal.notes else []

    if proposal.landmarks_px and _orientation_ok(proposal.landmarks_px, profile, variant) is False:
        proposal.landmarks_px = _mirror_labels(proposal.landmarks_px)
        proposal.confidence = _mirror_labels(proposal.confidence)
        notes.append("left/right labels swapped: the camera is on the other sideline")

    snapper = LineSnapper(frame_bgr)
    snapped: dict[str, bool] = {}
    for name, point in list(proposal.landmarks_px.items()):
        proposal.landmarks_px[name], snapped[name] = snapper.snap(point, snap_radius)
    proposal.snapped = snapped

    usable = {
        n: p
        for n, p in proposal.landmarks_px.items()
        if proposal.confidence.get(n, 0) >= min_confidence
    }
    if len(usable) < 4:
        notes.append(f"only {len(usable)} landmark(s) above confidence {min_confidence}")
        proposal.notes = "; ".join(n for n in notes if n)
        return proposal
    try:
        calib = calib_mod.calibrate(usable, profile, variant)
    except calib_mod.CalibrationError as exc:
        notes.append(str(exc))
    except Exception as exc:  # noqa: BLE001 - a bad fit is a UI state, not a crash
        notes.append(f"homography failed: {exc}")
    else:
        proposal.ok = True
        proposal.reprojection_error_px = float(calib["reproj_error_px"])
    proposal.notes = "; ".join(n for n in notes if n)
    return proposal


def _resolve_backend(backend: str) -> str:
    """`auto` is `template`.

    It used to be "the SDK when there is a key, the CLI when there is a `claude` on
    PATH". Measured (samples/real/RESULTS.md, "Auto-calibration, second attempt"): the
    model backends got 0 of 4 clips within 20 px, cost $0.26 and 3-14 minutes a clip,
    and timed out outright on two of them. `template` is free, takes 3-20 s, and is
    exact on the footage the product actually targets (a 1x phone lens). The model is
    still available by name, and its answer can be handed to `template` as `prior=`.
    """
    return "template" if backend == "auto" else backend


# ------------------------------------------------------------------------------ extras


def read_frame(path: Path) -> np.ndarray:
    frame = cv2.imread(str(path))
    if frame is None:
        raise FileNotFoundError(f"could not read an image from {path}")
    return frame


def draw_overlay(
    frame_bgr: np.ndarray,
    proposal: Proposal,
    dest: Path,
    truth: dict | None = None,
    template: Any | None = None,
) -> Path:
    """Debug render: proposed dots (green = confident, amber = shaky), truth as blue rings.

    With a `template` and a fitted `h_inv` the whole court — every sideline, arc and
    service line — is drawn in green, which is the only way to see whether a fit is
    right or merely scored well.
    """
    img = frame_bgr.copy()
    if template is not None and proposal.h_inv is not None:
        size = (frame_bgr.shape[1], frame_bgr.shape[0])
        for poly in tfit.template_segments(template):
            # Densified, so a court line bends with the lens instead of being a chord.
            t = np.linspace(0.0, 1.0, 24)[:, None]
            dense = np.vstack([p + t * (q - p) for p, q in zip(poly[:-1], poly[1:], strict=True)])
            pts = tfit.to_source(tfit.project(dense, proposal.h_inv), proposal.k1, size)
            if np.isfinite(pts).all():
                cv2.polylines(img, [pts.astype(np.int32)], False, (0, 200, 0), 2, cv2.LINE_AA)
    for name, (x, y) in (truth or {}).items():
        cv2.circle(img, (round(x), round(y)), 11, (255, 128, 0), 2)
        del name
    for name, (x, y) in proposal.landmarks_px.items():
        conf = proposal.confidence.get(name, 0.0)
        colour = (0, 220, 0) if conf >= MIN_CONFIDENCE else (0, 190, 255)
        cv2.drawMarker(img, (round(x), round(y)), colour, cv2.MARKER_CROSS, 18, 2)
        cv2.putText(
            img, name, (round(x) + 8, round(y) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3
        )
        cv2.putText(
            img, name, (round(x) + 8, round(y) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), img)
    return dest
