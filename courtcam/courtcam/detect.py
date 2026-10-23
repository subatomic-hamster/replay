"""Stage 3 — person detection (plan §4.4 step 3).

Ultralytics runs detection and tracker association (BoT-SORT) in one pass (D-5), so the
detector already emits track ids; `track.py` turns those per-frame rows into
tracklets. A `Detector` is just a callable, which is how the synthetic
ground-truth detector stands in for YOLO in CI.
"""

from __future__ import annotations

import json
import os
import shutil
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from tqdm import tqdm

from .extras import require
from .profiles import DetectionCfg
from .track import box_iou

DETS_SCHEMA = "courtcam.dets.v1"

BACKENDS = ("pt", "openvino", "onnx")
TRACKER = str(Path(__file__).parent / "botsort.yaml")
CACHE_DIR = Path(os.environ.get("COURTCAM_CACHE", Path.home() / ".cache" / "courtcam"))


def export_dir(model: str, backend: str, imgsz: int) -> Path:
    stem = Path(model).stem
    suffix = "_openvino_model" if backend == "openvino" else ".onnx"
    return CACHE_DIR / f"{stem}_{imgsz}{suffix}"


def resolve_weights(cfg: DetectionCfg, backend: str = "pt") -> tuple[str, str]:
    """Pick the weights to load for `backend`, exporting once into the cache if needed.

    Returns (path, backend_actually_used). Any export/import failure falls back to the
    `.pt` model, because a slow run beats a failed one.

    `pt` is the default because it measured *fastest* on this CPU — see
    "Detection speed" in the README; OpenVINO/ONNX are kept for boxes where the
    ranking flips (measure before switching).
    """
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r} (expected one of {list(BACKENDS)})")
    if backend == "pt":
        return cfg.model, "pt"
    dest = export_dir(cfg.model, backend, cfg.imgsz)
    try:
        if not dest.exists():
            from ultralytics import YOLO

            # the export bakes in imgsz, so the cache key has to carry it too
            out = YOLO(cfg.model).export(format=backend, imgsz=cfg.imgsz, dynamic=False)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(out), str(dest))  # the cache may be on another filesystem
        return str(dest), backend
    except Exception as exc:  # noqa: BLE001 — a failed export is just a slower run
        warnings.warn(f"{backend} export failed ({exc}); falling back to {cfg.model}", stacklevel=2)
        return cfg.model, "pt"


@dataclass(frozen=True, slots=True)
class Detection:
    track_id: int
    box: tuple[float, float, float, float]  # x, y, w, h in pixels
    conf: float


@dataclass(frozen=True, slots=True)
class FrameDets:
    index: int  # frame index in the mezzanine (0-based)
    t: float  # seconds from video start
    dets: list[Detection]


class Detector(Protocol):
    """Yield one `FrameDets` per *sampled* frame, in increasing time order."""

    def __call__(
        self, video: Path, *, stride: int, max_frames: int | None = None
    ) -> Iterator[FrameDets]: ...


def gpu_available() -> bool:
    """True when torch sees a GPU. ROCm builds report through `torch.cuda` too."""
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


class YoloDetector:
    """Ultralytics YOLO + its built-in BoT-SORT (`botsort.yaml`); on the GPU when there
    is one, with `gpu_model` in place of `model`."""

    def __init__(
        self,
        cfg: DetectionCfg,
        fps: float = 30.0,
        tracker: str = TRACKER,
        backend: str = "pt",
    ):
        self.cfg = cfg
        self.fps = fps
        self.tracker = tracker
        # the OpenVINO/ONNX exports are CPU paths; only plain torch weights go on the GPU
        gpu = backend == "pt" and gpu_available()
        if gpu and cfg.gpu_model:
            cfg = cfg.model_copy(update={"model": cfg.gpu_model})
        self.weights, self.backend = resolve_weights(cfg, backend)
        self.device = "0" if gpu else "cpu"

    def __call__(
        self, video: Path, *, stride: int, max_frames: int | None = None
    ) -> Iterator[FrameDets]:
        require("yolo", "YoloDetector", "ultralytics")
        from ultralytics import YOLO  # slow import; keep it off the CLI's hot path

        model = YOLO(self.weights)
        names = {v: k for k, v in model.names.items()}
        classes = [names[c] for c in self.cfg.classes if c in names] or None
        # The tracker keeps only boxes it can give an id; the rest are kept too (id 0, which
        # no tracklet takes) for identity.fill_gaps (D-97). Registered before `track` adds
        # its own callback, so this sees the detector's boxes first.
        raw: dict[str, np.ndarray] = {}

        def keep_raw(predictor) -> None:
            b = predictor.results[0].boxes  # stream mode: one frame per call
            raw["xywh"], raw["conf"] = b.xywh.cpu().numpy(), b.conf.cpu().numpy()

        model.add_callback("on_predict_postprocess_end", keep_raw)
        stream = model.track(
            source=str(video),
            stream=True,
            persist=True,
            tracker=self.tracker,
            classes=classes,
            imgsz=self.cfg.imgsz,
            conf=self.cfg.conf,
            vid_stride=stride,
            device=self.device,
            verbose=False,
        )
        next_id = -1
        for i, result in enumerate(stream):
            index = i * stride
            if max_frames is not None and index >= max_frames:
                break
            dets: list[Detection] = []
            boxes = result.boxes
            if boxes is not None and len(boxes):
                xywh = boxes.xywh.cpu().numpy()
                confs = boxes.conf.cpu().numpy()
                ids = boxes.id.cpu().numpy() if boxes.id is not None else None
                for j in range(len(xywh)):
                    cx, cy, w, h = (float(v) for v in xywh[j])
                    if ids is None:
                        # the tracker drops low-confidence boxes before assigning an id;
                        # give them a throwaway negative id so nothing merges onto them.
                        tid = next_id
                        next_id -= 1
                    else:
                        tid = int(ids[j])
                    dets.append(Detection(tid, (cx - w / 2, cy - h / 2, w, h), float(confs[j])))
            if boxes is not None and boxes.id is not None and raw:
                dets += untracked(raw["xywh"], raw["conf"], [d.box for d in dets])
            yield FrameDets(index, index / self.fps, dets)


def untracked(xywh: np.ndarray, conf: np.ndarray, kept: list) -> list[Detection]:
    """The detector's boxes (centre xywh) that no tracked box in `kept` (xywh) overlaps at
    IoU >= 0.5, as id-0 detections."""
    held = np.asarray(kept, dtype=np.float64).reshape(-1, 4)
    out = []
    for (cx, cy, w, h), c in zip(xywh.tolist(), conf.tolist(), strict=True):
        b = np.asarray([cx - w / 2, cy - h / 2, w, h])
        if not len(held) or box_iou(b, held).max() < 0.5:
            out.append(Detection(0, tuple(float(v) for v in b), float(c)))
    return out


class SyntheticDetector:
    """Replays boxes from a synthetic clip's `ground_truth.json` (plan §7.4).

    Lets the whole pipeline run in CI with no model weights.
    """

    def __init__(self, ground_truth: Path):
        self.gt = json.loads(Path(ground_truth).read_text(encoding="utf-8"))

    def __call__(
        self, video: Path, *, stride: int, max_frames: int | None = None
    ) -> Iterator[FrameDets]:
        fps = float(self.gt.get("fps", 30.0))
        for frame in self.gt["frames"]:
            index = int(frame["f"])
            if index % stride:
                continue
            if max_frames is not None and index >= max_frames:
                break
            yield FrameDets(
                index,
                index / fps,
                [
                    Detection(
                        int(d["id"]), tuple(float(v) for v in d["bb"]), float(d.get("c", 1.0))
                    )
                    for d in frame["d"]
                ],
            )


def run_detect(
    video: Path,
    out_path: Path,
    detector: Detector,
    *,
    fps: float,
    width: int,
    height: int,
    stride: int,
    max_frames: int | None = None,
    total_frames: int | None = None,
    show_progress: bool = True,
    on_progress: Any = None,
) -> Path:
    """Run `detector` over `video` and write `out_path` (`courtcam.dets.v1`).

    Skipped entirely if `out_path` already exists — detection is the expensive stage.
    """
    out_path = Path(out_path)
    if out_path.exists():
        return out_path
    limit = max_frames if max_frames is not None else total_frames
    total = (limit + stride - 1) // stride if limit else None
    frames: list[dict[str, Any]] = []
    bar = tqdm(total=total, unit="frame", desc="detect", disable=not show_progress)
    with bar:
        for fd in detector(video, stride=stride, max_frames=max_frames):
            frames.append(
                {
                    "f": fd.index,
                    "t": round(fd.t, 4),
                    "d": [
                        [d.track_id, *(round(v, 2) for v in d.box), round(d.conf, 4)]
                        for d in fd.dets
                    ],
                }
            )
            bar.update(1)
            if on_progress and total:
                on_progress(min(0.99, len(frames) / total))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "schema": DETS_SCHEMA,
                "fps": fps,
                "stride": stride,
                "width": width,
                "height": height,
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )
    return out_path


def make_detector(
    kind: str,
    cfg: DetectionCfg,
    *,
    fps: float = 30.0,
    ground_truth: Path | None = None,
    backend: str = "pt",
) -> Detector:
    if kind == "synthetic":
        if ground_truth is None:
            raise ValueError("--detector synthetic needs a ground_truth.json (--ground-truth)")
        return SyntheticDetector(ground_truth)
    if kind == "yolo":
        require("yolo", "--detector yolo", "ultralytics", "torch")
        return YoloDetector(cfg, fps=fps, backend=backend)
    raise ValueError(f"unknown detector {kind!r} (expected 'yolo' or 'synthetic')")
