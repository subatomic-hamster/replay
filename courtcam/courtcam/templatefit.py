"""Fit the sport's court template to the painted lines — classic CV, no model.

D-23's second attempt. The vision model reads a picture well and a ruler badly, so it
never got a corner within 20 px on the panoramic corpus. This module never asks it
anything: it finds the painted lines, builds every quadrilateral two pairs of them can
make, matches each one to a rectangle the *template* knows about (the court outline, the
key, the kitchen box, ...) and keeps the homography under which the whole template —
every sideline, arc and service line — lands on painted pixels.

The pipeline, in the order the functions appear:

1. `line_mask` — a pixel is on a line when it is brighter (or darker, or more saturated)
   than what sits `tau` px away on BOTH sides. That two-sided test is what separates a
   3 px painted line from a wall, a shadow edge or a bleacher; a plain top-hat lights up
   a quarter of the frame. Components shorter than 40 px are dropped.
2. `distance_map` — the same mask as a distance transform, which is what scoring reads.
3. `segments` + `merge_collinear` — Hough, then collinear fragments folded into one
   infinite line each. Panorama lines are curved, so a long line fragments; merging
   with a loose offset tolerance puts the pieces back together.
4. `quads` — every convex quadrilateral made by two pairs of lines, pruned to the ones
   that cover enough of the frame and whose four edges are actually painted.
5. `score` — project every template line, sampled every 10 cm, and sum
   `exp(-d^2/2*sigma^2)` over the samples that land in frame.
6. `fit` — the best scoring (quad, rectangle, corner assignment), then coordinate
   descent on the four corners.

Lens (D-25's one-parameter division model): `fit(..., k1=...)` builds its lines and
quads in UNDISTORTED pixels — where a barrelled court edge is straight again — but every
read of the mask goes back through `distortion.distort_points` to the SOURCE frame. So
there is one mask, one distance map and one score for every `k1`, and scores at different
`k1` are the same measurement. (The first cut redrew a straightened mask per `k1` and
rescaled it by `1 + k1` to keep it on the canvas; at `k1 = -0.65` that shrank the court
to a third and the true fit scored 0.000.)

ponytail: no vanishing-point RANSAC to split the lines into two families. With 30 lines
there are only ~95k pair-of-pairs to enumerate and numpy prunes them in under a second,
and a family split is exactly the thing that breaks on a panorama, where a baseline and
the far sideline can share an image direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import cv2
import numpy as np

from . import distortion
from .profiles import CourtTemplate

#: L/S-channel contrast a pixel needs over BOTH flanks to count as line paint.
LINE_DELTA = 14
#: Connected components shorter than this (longest bbox side) are not lines.
MIN_COMPONENT_PX = 40
#: Scoring kernel width: a template sample this far from paint is worth 1/e.
SIGMA_PX = 4.0
#: Merged lines kept for the quad search — the longest ones, by supporting pixels.
MAX_LINES = 30
#: Quads handed to the (much more expensive) template scorer.
MAX_QUADS = 1200
#: Template rectangles tried as the matched quad, court outline first.
MAX_RECTS = 12
#: A quad must cover this fraction of the frame. Kills the thousands of slivers.
MIN_AREA_FRAC = 0.15
#: ...and no quad edge shorter than this fraction of the long side: that is a triangle.
MIN_EDGE_FRAC = 0.05
#: Template line sampling, and the cap on how many samples the scorer carries.
SAMPLE_M = 0.1
MAX_SAMPLES = 2400
#: A fit that puts less than this of the template in frame is not scored at all, and
#: one that puts less than `FULL_COVER_FRAC` in frame is discounted proportionally —
#: otherwise the best fit is always the one that shrinks the court onto one bright line.
MIN_INFRAME_FRAC = 0.30
FULL_COVER_FRAC = 0.60
#: Corner refinement: pixel steps, tried in this order until nothing improves. The lens
#: search starts bigger: its seeds are further off (a quad at the wrong `k1`).
REFINE_STEPS = (8, 4, 2, 1)
LENS_REFINE_STEPS = (32, 16, 8, 4, 2, 1)
#: Candidates are first scored against this many template samples, and only the best
#: `RESCORE` of each order are scored in full: the full pass over ~30k candidates was
#: most of `fit`'s time.
COARSE_SAMPLES = 600
RESCORE = 128
#: `covered` counts painted pixels in cells this big.
COVER_CELL_PX = 4
#: Cap on one sample's image-arc weight, so a single huge jump cannot carry a fit.
MAX_STEP_PX = 40.0
#: Hardest perspective a court camera is allowed to have (near edge : far edge).
MAX_SQUASH = 8.0
#: Two fits are "the same answer" when every corner is within this many pixels.
SAME_FIT_PX = 20.0
#: Letterbox detection: a row/column is picture when this fraction of it is brighter
#: than `BAR_LEVEL`. A 16:9 export of a 4:3 action cam has black bars whose edges are the
#: two longest straight "lines" in the frame.
BAR_LEVEL = 40
BAR_FRAC = 0.05
#: Corner refinement moves `k1` by this much per pixel of corner step (8 px -> 0.04).
K1_PER_PX = 0.005
#: Focal lengths a court camera can have, as multiples of the frame width (118 deg to
#: 9.5 deg horizontal field of view in undistorted pixels), and the grid `physical`
#: searches them on.
FOCAL_RANGE = (0.3, 6.0)
FOCAL_STEPS = 48


@dataclass
class Fit:
    """One scored homography and where it came from."""

    h_inv: np.ndarray  # metres -> UNDISTORTED pixels (plain pixels when k1 == 0)
    corners_px: np.ndarray  # (4, 2) the matched quad in SOURCE pixels, rectangle order
    rect_m: np.ndarray  # (4, 2) which template rectangle those corners are
    score: float  # fraction of the in-frame template on paint: the quality gate
    inframe_frac: float
    k1: float = 0.0
    explained_px: float = 0.0  # source pixels of template line on paint (lens refine)
    covered_px: float = 0.0  # the same, each painted pixel counted once (the lens rank)


Box = tuple[int, int, int, int]  # x0, y0, x1, y1 of the picture, in source pixels


def content_box(frame_bgr: np.ndarray) -> Box:
    """The picture inside any letterbox or pillarbox bars."""
    lit = frame_bgr.max(axis=2) > BAR_LEVEL
    rows = np.flatnonzero(lit.mean(axis=1) > BAR_FRAC)
    cols = np.flatnonzero(lit.mean(axis=0) > BAR_FRAC)
    h, w = lit.shape
    if not len(rows) or not len(cols):
        return 0, 0, w, h
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def physical(h_inv: np.ndarray, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """(N, 3, 3) the nearest homographies a real camera can make, and each one's (N,) skew.

    A homography has 8 degrees of freedom; a pinhole camera looking at a plane has 7
    (focal length, rotation, position) once the principal point is fixed at the
    distortion centre. The spare one is a shear of the court, and it is what every wrong
    fit on the fisheye badminton clip used to put template lines on paint they do not
    belong to. For K = diag(f, f, 1), the first two columns of K^-1 H are the court's two
    axes in camera space and must be orthogonal and of equal length: the skew is how far
    from that they are at the best f. Measured: 0.002-0.023 on all five hand-clicked
    clips, 0.1-1.1 on nearly every wrong fit. The nearest camera is then rebuilt at that
    f with the two axes made orthonormal (polar decomposition).
    """
    w, h = size
    centre = np.array([[1.0, 0.0, -w / 2.0], [0.0, 1.0, -h / 2.0], [0.0, 0.0, 1.0]])
    g = np.einsum("ij,njk->nik", centre, h_inv)

    def skew_at(f: np.ndarray) -> np.ndarray:  # f: (N, F) -> (N, F)
        r1 = g[:, None, :2, 0] / f[:, :, None]
        r2 = g[:, None, :2, 1] / f[:, :, None]
        z1, z2 = g[:, None, 2, 0], g[:, None, 2, 1]
        n1 = np.sqrt((r1 * r1).sum(2) + z1 * z1)
        n2 = np.sqrt((r2 * r2).sum(2) + z2 * z2)
        with np.errstate(divide="ignore", invalid="ignore"):
            out = np.hypot(((r1 * r2).sum(2) + z1 * z2) / (n1 * n2), (n1 - n2) / (n1 + n2))
        return np.nan_to_num(out, nan=9.0)

    # Coarse log grid, then a fine one between the neighbours of the coarse minimum: the
    # rebuilt camera is sensitive to f (3 % off moves a wide-angle court by 30 px).
    coarse = np.geomspace(FOCAL_RANGE[0] * w, FOCAL_RANGE[1] * w, FOCAL_STEPS)
    f = np.broadcast_to(coarse, (len(g), FOCAL_STEPS))
    k = skew_at(f).argmin(1)
    ratio = coarse[1] / coarse[0]
    f = coarse[k][:, None] * ratio ** np.linspace(-1.0, 1.0, 41)[None]
    skew = skew_at(f)
    best = skew.argmin(1)
    fb = f[np.arange(len(g)), best]
    scale = np.stack([1.0 / fb, 1.0 / fb, np.ones_like(fb)], axis=1)  # (N, 3)
    m = g * scale[:, :, None]
    norms = np.linalg.norm(m[:, :, 0], axis=1) + np.linalg.norm(m[:, :, 1], axis=1)
    lam = 2.0 / np.maximum(norms, 1e-12)
    u, _, vt = np.linalg.svd(m[:, :, :2] * lam[:, None, None], full_matrices=False)
    axes = u @ vt
    rebuilt = np.concatenate([axes, m[:, :, 2:] * lam[:, None, None]], axis=2) / scale[:, :, None]
    return np.einsum("ij,njk->nik", np.linalg.inv(centre), rebuilt), skew[np.arange(len(g)), best]


def to_source(xy: np.ndarray, k1: float, size: tuple[int, int]) -> np.ndarray:
    """Undistorted pixels (any leading shape) -> source pixels. Identity at k1 = 0."""
    if not k1:
        return xy
    return distortion.distort_points(xy.reshape(-1, 2), k1, size).reshape(xy.shape)


def covered(
    h_inv: np.ndarray, samples: np.ndarray, dist: np.ndarray, *, k1: float = 0.0, box: Box
) -> float:
    """Pixels of paint the fit's lines lie on, each counted once (in `COVER_CELL_PX` cells).

    The explained length counts a painted pixel once per template line on it, so a
    strong `k1` that bends several court lines onto one bright curve is paid several
    times over: on the fisheye badminton clip that stack (all the lines on the arc at
    the bottom of the frame) out-scored the true court by 20 %. Counting cells ranks it
    last. Too coarse to refine on (it is flat within a few pixels), so it only ranks.
    """
    h, w = dist.shape
    x0, y0, x1, y1 = box
    p = to_source(project(samples, h_inv), k1, (w, h))
    inside = (p[:, 0] >= x0) & (p[:, 0] < x1) & (p[:, 1] >= y0) & (p[:, 1] < y1)
    xi = np.clip(np.rint(p[inside]), 0, [w - 1, h - 1]).astype(np.int64)
    on = xi[dist[xi[:, 1], xi[:, 0]] <= 2.0 * SIGMA_PX] // COVER_CELL_PX
    return float(len(np.unique(on[:, 1] * w + on[:, 0])) * COVER_CELL_PX)


# --------------------------------------------------------------------------- the mask


def _ridge(channel: np.ndarray, tau: int, delta: int) -> np.ndarray:
    """Pixels that stand `delta` above what is `tau` px away on both sides, either axis."""
    ch = channel.astype(np.int16)
    out = np.zeros(ch.shape, np.uint8)
    for axis in (0, 1):
        flank = np.maximum(np.roll(ch, tau, axis=axis), np.roll(ch, -tau, axis=axis))
        out |= (ch - flank > delta).astype(np.uint8)
    return out


def line_mask(
    frame_bgr: np.ndarray, *, delta: int = LINE_DELTA, min_len: int = MIN_COMPONENT_PX
) -> np.ndarray:
    """Court paint: bright lines, dark lines and coloured lines, thinned by length."""
    tau = max(3, round(0.004 * max(frame_bgr.shape[:2])))
    blur = cv2.GaussianBlur(frame_bgr, (3, 3), 0)
    lightness = cv2.cvtColor(blur, cv2.COLOR_BGR2LAB)[:, :, 0]
    saturation = cv2.cvtColor(blur, cv2.COLOR_BGR2HSV)[:, :, 1]
    raw = (
        _ridge(lightness, tau, delta)
        | _ridge(255 - lightness, tau, delta)  # dark lines on a pale gym floor
        | _ridge(saturation, tau, delta)  # blue/red lines on a pale gym floor
    )
    # The bar edges are ridges too (JPEG ringing), and the longest lines in the frame.
    x0, y0, x1, y1 = content_box(frame_bgr)
    if (x0, y0, x1, y1) != (0, 0, raw.shape[1], raw.shape[0]):
        keep = np.zeros_like(raw)
        keep[y0 + tau + 1 : y1 - tau - 1, x0 + tau + 1 : x1 - tau - 1] = 1
        raw &= keep
    count, labels, stats, _ = cv2.connectedComponentsWithStats(raw, 8)
    if count < 2:
        return raw * 255
    long_enough = np.maximum(stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT]) >= min_len
    long_enough[0] = False
    return (long_enough[labels] * 255).astype(np.uint8)


def distance_map(mask: np.ndarray) -> np.ndarray:
    """Pixel distance to the nearest line pixel."""
    return cv2.distanceTransform(255 - mask, cv2.DIST_L2, 3)


# -------------------------------------------------------------------------- the lines


def segments(mask: np.ndarray, *, min_len: int | None = None) -> np.ndarray:
    """Hough segments on the mask, as an (N, 4) array of x1, y1, x2, y2."""
    if min_len is None:
        min_len = max(30, round(0.03 * max(mask.shape)))
    found = cv2.HoughLinesP(
        mask, 1, np.pi / 360, threshold=50, minLineLength=min_len, maxLineGap=10
    )
    return np.empty((0, 4)) if found is None else found.reshape(-1, 4).astype(np.float64)


@dataclass
class Lines:
    """Infinite lines with the extent and pixel support that produced them."""

    point: np.ndarray  # (N, 2) a point on the line
    direction: np.ndarray  # (N, 2) unit direction
    span: np.ndarray  # (N, 2) min/max parameter along `direction` of the support
    support: np.ndarray  # (N,) total supporting segment length

    def __len__(self) -> int:
        return len(self.point)


def merge_collinear(
    segs: np.ndarray, shape: tuple[int, int], *, angle_tol_deg: float = 3.0
) -> Lines:
    """Fold collinear Hough fragments into one line each, longest-first."""
    if not len(segs):
        empty = np.empty((0, 2))
        return Lines(empty, empty, empty, np.empty(0))
    offset_tol = max(6.0, 0.006 * max(shape))
    sin_tol = np.sin(np.deg2rad(angle_tol_deg))
    lengths = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    groups: list[dict] = []
    for i in np.argsort(-lengths):
        p, q = segs[i, :2], segs[i, 2:]
        length = float(lengths[i])
        if length < 1e-6:
            continue
        d = (q - p) / length
        for g in groups:
            gd = g["dir"]
            if abs(float(gd[0] * d[1] - gd[1] * d[0])) > sin_tol:
                continue
            normal = np.array([-gd[1], gd[0]])
            if max(abs(normal @ (p - g["point"])), abs(normal @ (q - g["point"]))) > offset_tol:
                continue
            g["pts"].extend((p, q))
            g["w"].extend((length, length))
            g["support"] += length
            break
        else:
            groups.append(
                {
                    "point": p.copy(),
                    "dir": d,
                    "pts": [p, q],
                    "w": [length, length],
                    "support": length,
                }
            )

    point, direction, span, support = [], [], [], []
    for g in groups:
        pts = np.asarray(g["pts"])
        w = np.asarray(g["w"])[:, None]
        centre = (pts * w).sum(0) / w.sum()
        # Total least squares: the principal axis of the weighted endpoint cloud.
        _, _, vt = np.linalg.svd((pts - centre) * np.sqrt(w), full_matrices=False)
        d = vt[0] / np.linalg.norm(vt[0])
        t = (pts - centre) @ d
        point.append(centre)
        direction.append(d)
        span.append([float(t.min()), float(t.max())])
        support.append(float(g["support"]))
    return Lines(np.asarray(point), np.asarray(direction), np.asarray(span), np.asarray(support))


def longest(lines: Lines, keep: int = MAX_LINES) -> Lines:
    order = np.argsort(-lines.support)[:keep]
    return Lines(
        lines.point[order], lines.direction[order], lines.span[order], lines.support[order]
    )


def intersections(lines: Lines, *, min_sin: float = 0.10) -> tuple[np.ndarray, np.ndarray]:
    """(N, N, 2) pairwise intersection points and an (N, N) 'they really cross' mask."""
    n = len(lines)
    d = lines.direction
    p = lines.point
    cross = d[:, None, 0] * d[None, :, 1] - d[:, None, 1] * d[None, :, 0]
    ok = np.abs(cross) > min_sin  # < ~6 degrees apart: the crossing is not localisable
    np.fill_diagonal(ok, False)
    delta = p[None, :, :] - p[:, None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (delta[:, :, 0] * d[None, :, 1] - delta[:, :, 1] * d[None, :, 0]) / cross
    t = np.where(ok, t, 0.0)
    pts = p[:, None, :] + t[:, :, None] * d[:, None, :]
    return pts.reshape(n, n, 2), ok


# -------------------------------------------------------------------------- the quads


def quads(
    lines: Lines,
    dist: np.ndarray,
    *,
    max_quads: int = MAX_QUADS,
    k1: float = 0.0,
    box: Box | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Convex quadrilaterals two pairs of lines make, best-supported first.

    `lines` are in undistorted pixels at `k1`; `dist` is always the SOURCE frame's.
    Returns (K, 4, 2) corners in cyclic order and their (K,) edge-support prescore.
    """
    h, w = dist.shape
    n = len(lines)
    if n < 4:
        return np.empty((0, 4, 2)), np.empty(0)
    pts, ok = intersections(lines)

    # ponytail: no vanishing-point clustering to split the lines into a "horizontal" and
    # a "vertical" family. It is tempting (it would cut this from ~95k pairs-of-pairs to
    # ~10k) and it is exactly what a panorama breaks: on powellgym the two BASELINES
    # meet at (1454, 262), which is inside the frame, so every screen-position rule for
    # "these two are the same family" throws the right answer away. numpy prunes the
    # unclustered set in well under a second, so there is nothing to buy.
    pair = np.asarray(list(combinations(range(n), 2)))
    u, v = np.triu_indices(len(pair), 1)
    a, b, c, d = pair[u, 0], pair[u, 1], pair[v, 0], pair[v, 1]
    disjoint = (a != c) & (a != d) & (b != c) & (b != d)
    a, b, c, d = a[disjoint], b[disjoint], c[disjoint], d[disjoint]
    valid = ok[a, c] & ok[a, d] & ok[b, c] & ok[b, d]
    a, b, c, d = a[valid], b[valid], c[valid], d[valid]
    if not len(a):
        return np.empty((0, 4, 2)), np.empty(0)
    # A->B along line a, B->C along line d, C->D along line b, D->A along line c.
    corner = np.stack([pts[a, c], pts[a, d], pts[b, d], pts[b, c]], axis=1)

    edge = np.roll(corner, -1, axis=1) - corner
    turn = (
        edge[:, :, 0] * np.roll(edge, -1, axis=1)[:, :, 1]
        - edge[:, :, 1] * np.roll(edge, -1, axis=1)[:, :, 0]
    )
    convex = (turn > 0).all(1) | (turn < 0).all(1)
    area = 0.5 * np.abs(
        (corner[:, :, 0] * np.roll(corner, -1, axis=1)[:, :, 1]).sum(1)
        - (corner[:, :, 1] * np.roll(corner, -1, axis=1)[:, :, 0]).sum(1)
    )
    centre = corner.mean(1)
    edge_len = np.hypot(edge[:, :, 0], edge[:, :, 1]).min(1)
    keep = (
        convex
        & (area >= MIN_AREA_FRAC * h * w)
        # No near-coincident corners: a quad with a 10 px edge is a triangle, and the
        # homography onto it foreshortens the far half of the court into nothing.
        & (edge_len >= MIN_EDGE_FRAC * max(h, w))
        & (np.abs(corner).max((1, 2)) < 4 * max(h, w))
        & (centre[:, 0] > -0.5 * w)
        & (centre[:, 0] < 1.5 * w)
        & (centre[:, 1] > -0.5 * h)
        & (centre[:, 1] < 1.5 * h)
    )
    corner = corner[keep]
    if not len(corner):
        return np.empty((0, 4, 2)), np.empty(0)

    prescore = _edge_support(corner, dist, k1=k1, box=box)
    order = np.argsort(-prescore)[:max_quads]
    return corner[order], prescore[order]


def _edge_support(
    corner: np.ndarray,
    dist: np.ndarray,
    *,
    samples: int = 16,
    k1: float = 0.0,
    box: Box | None = None,
) -> np.ndarray:
    """Fraction of the quad's four edges that runs along painted pixels."""
    h, w = dist.shape
    x0, y0, x1, y1 = box or (0, 0, w, h)
    t = np.linspace(0.04, 0.96, samples)
    out = np.empty(len(corner))
    for lo in range(0, len(corner), 20000):
        block = corner[lo : lo + 20000]
        nxt = np.roll(block, -1, axis=1)
        pts = block[:, :, None, :] + t[None, None, :, None] * (nxt - block)[:, :, None, :]
        pts = to_source(pts.reshape(len(block), -1, 2), k1, (w, h))
        x = np.rint(pts[:, :, 0]).astype(np.int32)
        y = np.rint(pts[:, :, 1]).astype(np.int32)
        inside = (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
        on = np.zeros(x.shape, bool)
        xi, yi = np.clip(x, 0, w - 1), np.clip(y, 0, h - 1)
        on[inside] = dist[yi[inside], xi[inside]] <= 2.5
        out[lo : lo + 20000] = on.sum(1) / np.maximum(inside.sum(1), 1)
    return out


# ---------------------------------------------------------- the template side of things


def template_segments(template: CourtTemplate) -> list[np.ndarray]:
    """Every painted line the template knows, as polylines in court metres."""
    out = [np.vstack([template.polygon, template.polygon[:1]])]
    for pts in template.features.values():
        arr = np.asarray(pts, dtype=np.float64)
        if len(arr) < 2:
            continue
        # 3+ points is a ring (the key, a three-point arc closed by the baseline);
        # 2 points is a single painted line and closing it would double it.
        out.append(np.vstack([arr, arr[:1]]) if len(arr) > 2 else arr)
    return out


def template_samples(
    template: CourtTemplate, *, step: float = SAMPLE_M, cap: int = MAX_SAMPLES
) -> tuple[np.ndarray, np.ndarray]:
    """`template_segments` sampled every `step` metres.

    Returns (S, 2) court-metre points and an (S,) flag saying whether the next sample
    continues the same painted line — which is what lets the scorer weight a sample by
    how many IMAGE pixels it stands for.
    """
    pts: list[np.ndarray] = []
    link: list[np.ndarray] = []
    for poly in template_segments(template):
        run: list[np.ndarray] = []
        for p, q in zip(poly[:-1], poly[1:], strict=True):
            n = max(2, int(np.linalg.norm(q - p) / step) + 1)
            run.append(p + np.linspace(0, 1, n)[:, None] * (q - p))
        chunk = np.vstack(run)
        pts.append(chunk)
        joined = np.ones(len(chunk), bool)
        joined[-1] = False  # the last sample of a polyline links to nothing
        link.append(joined)
    if not pts:
        return np.empty((0, 2)), np.empty(0, bool)
    all_pts, all_link = np.vstack(pts), np.concatenate(link)
    if len(all_pts) > cap:  # even sampling, not a head slice: keep every line represented
        take = np.linspace(0, len(all_pts) - 1, cap).round().astype(int)
        # Subsampling breaks the "next sample" relation wherever it skipped a boundary.
        keep = np.minimum.reduceat(all_link.astype(np.int8), take[:-1]).astype(bool)
        all_pts, all_link = all_pts[take], np.append(keep, False)
    return all_pts, all_link


def _all_painted(edges: np.ndarray, p: np.ndarray, q: np.ndarray, step: float = 0.25) -> bool:
    """Is every point of the segment p->q on a line the template actually draws?"""
    n = max(2, int(np.linalg.norm(q - p) / step) + 1)
    pts = p + np.linspace(0.0, 1.0, n)[:, None] * (q - p)
    a, b = edges[:, 0], edges[:, 1]
    ab = b - a
    t = np.clip(((pts[:, None, :] - a) * ab).sum(2) / np.maximum((ab * ab).sum(1), 1e-12), 0.0, 1.0)
    foot = a + t[:, :, None] * ab
    return bool((np.linalg.norm(foot - pts[:, None, :], axis=2).min(1) < 1e-6).all())


def rectangles(template: CourtTemplate, *, cap: int = MAX_RECTS) -> list[np.ndarray]:
    """Rectangles the template's own landmarks pin down, court outline first.

    The court outline is always first; the rest are the key, the kitchen box, the
    service boxes — the quads a camera can still see when an outer corner is off-frame.
    A rectangle only counts when all FOUR of its edges are lines the template draws:
    `key_nl..key_fl` is a perfectly good pair of landmarks, but there is no paint
    between the free-throw line and the far key, so the "rectangle" they span is a
    fiction and matching a detected quad to it is a fit that cannot be checked.
    Each comes back as 4 court-metre points wound the same way as the outline.
    """
    poly = template.polygon
    outline = np.array(
        [
            [poly[:, 0].min(), poly[:, 1].min()],
            [poly[:, 0].max(), poly[:, 1].min()],
            [poly[:, 0].max(), poly[:, 1].max()],
            [poly[:, 0].min(), poly[:, 1].max()],
        ]
    )
    court_area = float(
        (outline[:, 0].max() - outline[:, 0].min()) * (outline[:, 1].max() - outline[:, 1].min())
    )
    edges = np.vstack(
        [np.stack([line[:-1], line[1:]], axis=1) for line in template_segments(template)]
    )
    have = {(round(x, 4), round(y, 4)) for x, y in template.landmarks.values()}
    xs = sorted({x for x, _ in have})
    ys = sorted({y for _, y in have})
    found: list[tuple[float, np.ndarray]] = []
    for x0, x1 in combinations(xs, 2):
        for y0, y1 in combinations(ys, 2):
            if not all(c in have for c in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))):
                continue
            area = (x1 - x0) * (y1 - y0)
            if area < 0.05 * court_area or area > 0.999 * court_area:
                continue
            rect = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
            if all(_all_painted(edges, rect[i], rect[(i + 1) % 4]) for i in range(4)):
                found.append((area, rect))
    found.sort(key=lambda it: -it[0])
    return [outline] + [rect for _, rect in found[: cap - 1]]


def near_end_is_left(template: CourtTemplate) -> bool:
    """How the profile decides which end of the court is the 'near' (n) one.

    A net sport is filmed from behind a baseline, so `near` is simply the end closer to
    the camera — lower in the picture. A court sport is filmed from the side, where both
    ends are the same distance away and 'near' is pure convention: every sport YAML's
    `orientation_hint` says it is the end further LEFT in the picture. Keyed off
    `net_y`, not off the sport id (REPLAY_PLAN.md §12 rule 6).
    """
    return template.net_y is None


# ------------------------------------------------------------------------- the scoring


def _batch_homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """(N, 4, 2) -> (N, 4, 2) correspondences to (N, 3, 3) homographies."""
    n = len(src)
    x, y = src[:, :, 0], src[:, :, 1]
    u, v = dst[:, :, 0], dst[:, :, 1]
    zero = np.zeros_like(x)
    one = np.ones_like(x)
    rows_u = np.stack([x, y, one, zero, zero, zero, -u * x, -u * y], axis=2)
    rows_v = np.stack([zero, zero, zero, x, y, one, -v * x, -v * y], axis=2)
    a = np.concatenate([rows_u, rows_v], axis=1)  # (N, 8, 8)
    b = np.concatenate([u, v], axis=1)[:, :, None]  # (N, 8, 1)
    try:
        h = np.linalg.solve(a, b)[:, :, 0]
    except np.linalg.LinAlgError:
        h = np.einsum("nij,njk->nik", np.linalg.pinv(a), b)[:, :, 0]
    return np.concatenate([h, np.ones((n, 1))], axis=1).reshape(n, 3, 3)


def score(
    h_inv: np.ndarray,
    samples: np.ndarray,
    link: np.ndarray,
    dist: np.ndarray,
    outline_m: np.ndarray,
    *,
    sigma: float = SIGMA_PX,
    k1: float = 0.0,
    box: Box | None = None,
    absolute: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Score (N,) and in-frame fraction (N,) for N metres->pixels homographies.

    `absolute=True` returns the EXPLAINED arc length instead of the fraction: source
    pixels of template line that land on paint. See `_score`.
    """
    fraction, explained, frac = _score(
        h_inv, samples, link, dist, outline_m, sigma=sigma, k1=k1, box=box
    )
    return (explained if absolute else fraction), frac


def _score(
    h_inv: np.ndarray,
    samples: np.ndarray,
    link: np.ndarray,
    dist: np.ndarray,
    outline_m: np.ndarray,
    *,
    sigma: float = SIGMA_PX,
    k1: float = 0.0,
    box: Box | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(fraction, explained px, in-frame fraction), each (N,).

    The fraction of the in-frame template that lands on paint is the honest quality
    number (it is what `ok` is gated on) but a bad thing to rank by: it pays a fit for
    piling the template onto a few strong lines and leaving the rest of the court off
    frame or collapsed. On the fisheye badminton clip, where one `k1` cannot bend the
    frame edges right, the true court reaches 0.63-0.70 while a court collapsed onto the
    near sideline reaches 0.77. The lens search refines on the explained length
    (unnormalised) instead, and ranks on `covered`, which also stops a fit being paid
    twice for stacking lines.

    The homographies land in undistorted pixels at `k1`; samples are bent back onto the
    source frame before anything is looked up or counted, so "in frame" means inside
    `box` (the picture, bars excluded) and a step's weight is its SOURCE arc length.

    `outline_m` is the court outline in metres, and it is a *guard*, not part of the
    score: without it the winning fit is always a projective collapse. Wrap the court
    across the vanishing line and half of it comes back on the far side of the image,
    piling every sample onto whatever paint is there — that fit scored a clean 1.000 on
    every clip until the sign of w and the projected court area were checked.
    """
    h, w = dist.shape
    x0, y0, x1, y1 = box or (0, 0, w, h)
    hom = np.concatenate([samples, np.ones((len(samples), 1))], axis=1)
    guard = np.concatenate([outline_m, np.ones((len(outline_m), 1))], axis=1)
    out = np.zeros(len(h_inv))
    expl = np.zeros(len(h_inv))
    frac = np.zeros(len(h_inv))
    for lo in range(0, len(h_inv), 256):  # chunked: (N, S, 3) is the memory hog
        chunk = h_inv[lo : lo + 256]
        proj = np.einsum("nij,sj->nsi", chunk, hom)
        z = proj[:, :, 2]
        good = np.abs(z) > 1e-9
        with np.errstate(divide="ignore", invalid="ignore"):
            x = np.where(good, proj[:, :, 0] / z, -1e6)
            y = np.where(good, proj[:, :, 1] / z, -1e6)
        if k1:
            src = to_source(np.stack([x, y], axis=2), k1, (w, h))
            x, y = src[:, :, 0], src[:, :, 1]
        xi = np.clip(np.rint(x), 0, w - 1).astype(np.int32)
        yi = np.clip(np.rint(y), 0, h - 1).astype(np.int32)
        inside = good & (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
        d = dist[yi, xi]
        hit = np.exp(-(d * d) / (2.0 * sigma * sigma))
        # Weight each sample by the IMAGE arc length it stands for, not by its 10 cm of
        # court. Uniform-in-metres weighting pays a fit for squashing the far half of
        # the court onto a handful of pixels: 600 samples then land on one line and the
        # score is a perfect 1.000. In pixels that far half is worth almost nothing,
        # which is the honest accounting.
        step = np.hypot(np.diff(x, axis=1), np.diff(y, axis=1))
        weight = np.zeros_like(x)
        weight[:, :-1] = np.minimum(step, MAX_STEP_PX) * link[None, :-1]
        weight *= inside
        total = weight.sum(1)
        seen = inside.sum(1)
        f = seen / samples.shape[0]
        e = (hit * weight).sum(1)
        s = e / np.maximum(total, 1e-9) * np.clip(f / FULL_COVER_FRAC, 0.0, 1.0)

        corners = np.einsum("nij,sj->nsi", chunk, guard)
        cz = corners[:, :, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            cx = corners[:, :, 0] / cz
            cy = corners[:, :, 1] / cz
        area = 0.5 * np.abs(
            (cx * np.roll(cy, -1, axis=1)).sum(1) - (cy * np.roll(cx, -1, axis=1)).sum(1)
        )
        # How hard the camera foreshortens the court: the near baseline over the far
        # one, and the two sidelines against each other. A real gym camera is somewhere
        # between 1:1 (a panorama from the halfway line) and about 1:8 (behind a
        # baseline). Past that the "court" is a wedge running off to the horizon, which
        # is exactly the shape that wins on line score alone.
        side = np.hypot(np.diff(cx, append=cx[:, :1]), np.diff(cy, append=cy[:, :1]))
        ends = np.sort(side[:, [0, 2]], axis=1)
        flanks = np.sort(side[:, [1, 3]], axis=1)
        squash = np.maximum(
            ends[:, 1] / np.maximum(ends[:, 0], 1e-9), flanks[:, 1] / np.maximum(flanks[:, 0], 1e-9)
        )
        sane = (
            ((cz > 0).all(1) | (cz < 0).all(1))  # the court never crosses the horizon
            & ((z > 0).all(1) | (z < 0).all(1))
            & np.isfinite(area)
            & (area >= MIN_AREA_FRAC * h * w)
            & (f >= MIN_INFRAME_FRAC)
            & (total > 1.0)
            & (squash <= MAX_SQUASH)
        )
        out[lo : lo + 256] = np.where(sane, s, 0.0)
        expl[lo : lo + 256] = np.where(sane, e, 0.0)
        frac[lo : lo + 256] = f
    return out, expl, frac


def _orderings(corner: np.ndarray, rect: np.ndarray, near_left: bool) -> np.ndarray:
    """Every cyclic relabelling of these quads that could be this rectangle, from above.

    Eight orderings exist per quad. Four are mirror images — a court is symmetric about
    its long axis, so reprojection error cannot tell those apart; only the winding can,
    because image y points down — and two of the survivors put the 'near' end of the
    court at the wrong side of the picture (`near_end_is_left`). Two are left, and they
    differ by which template axis runs along which pair of quad edges.

    Returns (M, 2, 4, 2): the quads that had a usable ordering, times their orderings.
    """
    signed = 0.5 * (
        (corner[:, :, 0] * np.roll(corner, -1, axis=1)[:, :, 1]).sum(1)
        - (corner[:, :, 1] * np.roll(corner, -1, axis=1)[:, :, 0]).sum(1)
    )
    rect_signed = 0.5 * (
        (rect[:, 0] * np.roll(rect, -1, axis=0)[:, 1]).sum()
        - (rect[:, 1] * np.roll(rect, -1, axis=0)[:, 0]).sum()
    )
    corner = np.where((signed * rect_signed > 0)[:, None, None], corner[:, ::-1], corner)
    is_near = rect[:, 1] <= rect[:, 1].min() + 1e-6
    rolls = np.stack([np.roll(corner, r, axis=1) for r in range(4)], axis=1)  # (K, 4, 4, 2)
    near = rolls[:, :, is_near].mean(2)
    far = rolls[:, :, ~is_near].mean(2)
    keep = (near[:, :, 0] < far[:, :, 0]) if near_left else (near[:, :, 1] > far[:, :, 1])
    # Exactly two rolls survive for a convex quad; anything else is degenerate.
    good = keep.sum(1) == 2
    return rolls[good][keep[good]].reshape(-1, 2, 4, 2)


# ------------------------------------------------------------------------------- fit


def _candidates(
    corner: np.ndarray, template: CourtTemplate, rects: list[np.ndarray]
) -> tuple[np.ndarray, np.ndarray]:
    """Every (quad ordering, template rectangle) pair, as aligned (M, 4, 2) arrays."""
    near_left = near_end_is_left(template)
    pix: list[np.ndarray] = []
    met: list[np.ndarray] = []
    for rect in rects:
        ordered = _orderings(corner, rect, near_left).reshape(-1, 4, 2)
        pix.append(ordered)
        met.append(np.repeat(rect[None], len(ordered), axis=0))
    if not pix or not sum(len(p) for p in pix):
        return np.empty((0, 4, 2)), np.empty((0, 4, 2))
    return np.concatenate(pix), np.concatenate(met)


def _refine(
    candidate: Fit,
    samples: np.ndarray,
    link: np.ndarray,
    dist: np.ndarray,
    outline_m: np.ndarray,
    *,
    steps: tuple[int, ...] = REFINE_STEPS,
    box: Box | None = None,
    lens_search: bool = False,
) -> Fit:
    """Coordinate descent on the four image corners, largest step first.

    With `lens_search` it also moves `k1`, keeps every trial a real camera (`physical`)
    and climbs the explained length instead of the fraction (see `_score`). The corners
    move in SOURCE pixels, so a `k1` step bends the rest of the court about the matched
    quad instead of dragging the quad itself off the paint.
    """
    size = (dist.shape[1], dist.shape[0])
    rect = candidate.rect_m

    def run(pix: np.ndarray, k1: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        und = distortion.undistort_points(pix.reshape(-1, 2), k1, size).reshape(pix.shape)
        h_inv = _batch_homography(np.repeat(rect[None], len(pix), axis=0), und)
        if lens_search:
            h_inv, _ = physical(h_inv, size)
        return (h_inv, *_score(h_inv, samples, link, dist, outline_m, k1=k1, box=box))

    def objective(fraction: np.ndarray, explained: np.ndarray) -> np.ndarray:
        return explained if lens_search else fraction

    best_px, best_k1 = candidate.corners_px, candidate.k1
    best = float(objective(np.array([candidate.score]), np.array([candidate.explained_px]))[0])
    offsets = np.array([(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)])
    lo, hi = distortion.K1_RANGE
    for step in steps:
        for _ in range(12):
            improved = False
            trials = [best_px]
            for k in range(4):
                for off in offsets * step:
                    moved = best_px.copy()
                    moved[k] = moved[k] + off
                    trials.append(moved)
            pix = np.asarray(trials)
            _, r, e, _ = run(pix, best_k1)
            got = objective(r, e)
            k = int(np.argmax(got))
            if got[k] > best + 1e-9:
                best_px, best, improved = pix[k], float(got[k]), True
            for k1 in (best_k1 + step * K1_PER_PX, best_k1 - step * K1_PER_PX):
                if lens_search and lo <= k1 <= hi:
                    _, r, e, _ = run(best_px[None], k1)
                    if objective(r, e)[0] > best + 1e-9:
                        best_k1, best, improved = k1, float(objective(r, e)[0]), True
            if not improved:
                break
    h_inv, r, e, f = run(best_px[None], best_k1)
    return Fit(h_inv[0], best_px, rect, float(r[0]), float(f[0]), best_k1, float(e[0]))


def _leash(
    pix: np.ndarray,
    met: np.ndarray,
    outline_m: np.ndarray,
    prior_quad: np.ndarray,
    radius: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Drop candidates whose court outline strays further than `radius` from the prior."""
    h_inv = _batch_homography(met, pix)
    hom = np.concatenate([outline_m, np.ones((4, 1))], axis=1)
    proj = np.einsum("nij,sj->nsi", h_inv, hom)
    with np.errstate(divide="ignore", invalid="ignore"):
        xy = proj[:, :, :2] / proj[:, :, 2:3]
    close = np.isfinite(xy).all((1, 2)) & (
        np.linalg.norm(xy - prior_quad[None], axis=2).max(1) <= radius
    )
    kept = int(close.sum())
    if not kept:  # the prior is nowhere near anything the lines can make: ignore it
        return pix, met, 0
    return (
        np.concatenate([pix[close], prior_quad[None]]),
        np.concatenate([met[close], outline_m[None]]),
        kept,
    )


def _same_fit(a: Fit, b: Fit, outline_m: np.ndarray, size: tuple[int, int]) -> bool:
    """Same answer? Compare where the COURT lands, not which quad or rectangle made it."""
    pa = to_source(project(outline_m, a.h_inv), a.k1, size)
    pb = to_source(project(outline_m, b.h_inv), b.k1, size)
    return bool(np.linalg.norm(pa - pb, axis=1).max() < SAME_FIT_PX)


def fit(
    frame_bgr: np.ndarray,
    template: CourtTemplate,
    *,
    keep: int = 6,
    mask: np.ndarray | None = None,
    refine: bool = True,
    prior_quad: np.ndarray | None = None,
    prior_radius: float | None = None,
    k1: float = 0.0,
    lens_search: bool = False,
) -> tuple[list[Fit], str]:
    """Best homographies for this frame, best first, plus a one-line note.

    `k1` is the lens to search under: lines and quads are built in undistorted pixels
    and the score reads the source frame. `lens_search` is the second pass `autocalib`
    runs when the straight one fails: every candidate is made a real camera
    (`physical`), `k1` is refined too (on explained paint rather than the fraction:
    `_score` says why) and fits are ranked by `covered` paint; seeds come from both
    orders.

    `prior_quad` is where something else (a vision model, a previous calibration) thinks
    the court outline is, as 4 image points in the template's outline order. It is used
    as a *leash*, not an answer: candidates whose court lands more than `prior_radius`
    from it (in undistorted pixels) are dropped, the prior itself is added as one more
    candidate so the line refinement can start from it, and if the leash leaves nothing
    the search runs unrestricted rather than returning nothing.
    """
    if mask is None:
        mask = line_mask(frame_bgr)
    dist = distance_map(mask)
    box = content_box(frame_bgr)
    size = (mask.shape[1], mask.shape[0])
    segs = segments(mask)
    straight = distortion.undistort_points(segs.reshape(-1, 2), k1, size).reshape(-1, 4)
    lines = longest(merge_collinear(straight, mask.shape))
    corner, _ = quads(lines, dist, k1=k1, box=box)
    note = f"{len(segs)} segments, {len(lines)} lines, {len(corner)} quads"
    if not len(corner):
        return [], note + " - nothing to fit"

    samples, link = template_samples(template)
    rects = rectangles(template)
    pix, met = _candidates(corner, template, rects)
    if not len(pix):
        return [], note + " - no quad had the template's orientation"
    outline = rects[0]
    if prior_quad is not None:
        pix, met, kept = _leash(
            pix,
            met,
            outline,
            distortion.undistort_points(prior_quad, k1, size),
            prior_radius or 0.15 * frame_bgr.shape[1],
        )
        note += f", prior kept {kept}"
    h_inv = _batch_homography(met, pix)
    if lens_search:
        h_inv, _ = physical(h_inv, size)
    if len(h_inv) > 2 * RESCORE:
        coarse = template_samples(template, cap=COARSE_SAMPLES)
        fraction, explained, _ = _score(h_inv, *coarse, dist, outline, k1=k1, box=box)
        best = [np.argsort(-fraction)[:RESCORE], np.argsort(-explained)[:RESCORE]]
        pick = np.unique(np.concatenate(best))
        pix, met, h_inv = pix[pick], met[pick], h_inv[pick]
    fraction, explained, frac = _score(h_inv, samples, link, dist, outline, k1=k1, box=box)
    out: list[Fit] = []
    for order in (-fraction, -explained) if lens_search else (-fraction,):
        taken = 0
        for i in np.argsort(order):
            if fraction[i] <= 0.0 or taken >= keep:
                break
            candidate = Fit(
                h_inv[i],
                to_source(pix[i], k1, size),
                met[i],
                float(fraction[i]),
                float(frac[i]),
                k1,
                float(explained[i]),
            )
            if any(_same_fit(candidate, done, outline, size) for done in out):
                continue
            out.append(candidate)
            taken += 1
    if refine:
        steps = LENS_REFINE_STEPS if lens_search else REFINE_STEPS
        out = [
            _refine(c, samples, link, dist, outline, steps=steps, box=box, lens_search=lens_search)
            for c in out
        ]
    for c in out:
        c.covered_px = covered(c.h_inv, samples, dist, k1=c.k1, box=box)
    out.sort(key=lambda c: -(c.covered_px if lens_search else c.score))
    return out, note + f", {len(rects)} template rectangles"


def project(points: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Apply a homography to an (N, 2) array."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, np.asarray(h, dtype=np.float64)).reshape(-1, 2)
