"""Face provider: opt-in enrollment only (vision §21). Never matches unenrolled people:
`identify` may only return profiles that called `enroll`. AWS: Rekognition collections
(`aws.RekognitionFace`).

Local: OpenCV Zoo YuNet (detector, MIT) + SFace (128-d embedding, Apache-2.0; training-data
provenance undocumented upstream, docs/licenses.md) through OpenCV's built-in
`FaceDetectorYN` / `FaceRecognizerSF`, so no extra Python dependency. Opt-in twice over:
nothing runs until `REPLAY_FACE_DIR` names the enrollment store and the two ONNX files are
in `REPLAY_FACE_MODELS` (default `<REPLAY_MODEL_VENVS>/../models/face`; box:
/workspace/wt/replay-env/models/face). The store holds one mean unit embedding per
enrolled profile (`<dir>/<profile_id>.json`) and nothing else: enrollment photos are not
kept, and faces seen in game footage are compared and dropped, never stored. With no
enrolled profile `identify` returns [] without running the model. `forget` deletes the file.

Threshold: cosine 0.45, above OpenCV's published SFace point 0.363 (samples/dnn/face_match,
tuned on photo pairs): on CC court footage 0.363 matched 18-22 % of an unenrolled player's
faces to the enrolled one, 0.45 matched 3 % and, with the game matcher's majority rule,
suggested no unenrolled window (docs/evidence/M10; one clip, two people: re-tune on real
enrollment data via REPLAY_FACE_THRESHOLD). Faces narrower than MIN_FACE_PX source
pixels are not embedded (too small to identify; docs/evidence/M10 measures how often a
court player's face clears that bar).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Protocol

from . import NotConfiguredError

DETECTOR = "face_detection_yunet_2023mar.onnx"
RECOGNIZER = "face_recognition_sface_2021dec.onnx"
MODEL = "opencv_zoo/sface_2021dec+yunet_2023mar"
THRESHOLD = 0.45
MIN_FACE_PX = 24
DETECT_SCORE = 0.7


class Face(Protocol):
    def enroll(self, profile_id: str, images: list[Path]) -> dict: ...

    def identify(self, image: Path, *, min_similarity: float | None = None) -> list[dict]:
        """`[{profile_id, similarity, box}]` over enrolled profiles only. `None` → the
        provider's own operating point."""
        ...

    def forget(self, profile_id: str) -> None: ...


def _models_dir() -> Path | None:
    d = os.environ.get("REPLAY_FACE_MODELS")
    if d:
        return Path(d)
    venvs = os.environ.get("REPLAY_MODEL_VENVS")
    return Path(venvs).parent / "models" / "face" if venvs else None


class LocalFace:
    def __init__(
        self,
        store_dir: Path | None = None,
        models_dir: Path | None = None,
        threshold: float | None = None,
        min_face_px: int | None = None,
    ):
        d = store_dir or os.environ.get("REPLAY_FACE_DIR")
        self.dir = Path(d) if d else None
        self.models = Path(models_dir) if models_dir else _models_dir()
        self.threshold = threshold or float(os.environ.get("REPLAY_FACE_THRESHOLD", THRESHOLD))
        self.min_face_px = min_face_px or int(os.environ.get("REPLAY_FACE_MIN_PX", MIN_FACE_PX))
        self._det = self._rec = None

    # --- store ---------------------------------------------------------------------------

    def _ready(self) -> Path:
        if self.dir is None:
            raise NotConfiguredError(
                "face: opt-in only; set REPLAY_FACE_DIR (enrollment store) and "
                "REPLAY_FACE_MODELS (YuNet + SFace ONNX, docs/models.md)"
            )
        return self.dir

    def _path(self, profile_id: str) -> Path:
        store = self._ready()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(profile_id)):
            raise ValueError(f"bad profile id {profile_id!r}")
        return store / f"{profile_id}.json"

    def enrolled(self) -> list[dict]:
        store = self._ready()
        return [json.loads(p.read_text()) for p in sorted(store.glob("*.json"))]

    # --- model ---------------------------------------------------------------------------

    def _load(self):
        if self._det is None:
            files = [self.models / f for f in (DETECTOR, RECOGNIZER)] if self.models else []
            if not files or not all(f.is_file() for f in files):
                raise NotConfiguredError(f"face: model files {DETECTOR}, {RECOGNIZER} not found "
                                         f"in REPLAY_FACE_MODELS={self.models}")  # fmt: skip
            import cv2

            self._det = cv2.FaceDetectorYN.create(str(files[0]), "", (320, 320), DETECT_SCORE)
            self._rec = cv2.FaceRecognizerSF.create(str(files[1]), "")
        return self._det, self._rec

    def detect(self, img) -> list[dict]:
        """Every face in a BGR image: `{box [x,y,w,h], score, e (unit 128-d) | None}`;
        `e` is None for faces narrower than min_face_px (detected, too small to embed)."""
        import numpy as np

        det, rec = self._load()
        h, w = img.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        out = []
        for f in faces if faces is not None else []:
            box = [round(float(v), 1) for v in f[:4]]
            e = None
            if box[2] >= self.min_face_px:
                v = rec.feature(rec.alignCrop(img, f)).reshape(-1).astype(np.float64)
                e = (v / (np.linalg.norm(v) or 1.0)).tolist()
            out.append({"box": box, "score": round(float(f[-1]), 3), "e": e})
        return out

    @staticmethod
    def _read(image):
        if not isinstance(image, (str, Path)):
            return image  # already a BGR array (the game matcher's crops)
        import cv2

        img = cv2.imread(str(image))
        if img is None:
            raise ValueError(f"not an image: {Path(image).name}")
        return img

    # --- protocol ------------------------------------------------------------------------

    def enroll(self, profile_id: str, images: list[Path]) -> dict:
        """The largest embeddable face of each photo; photos without one are skipped."""
        path = self._path(profile_id)
        embs = []
        for image in images:
            faces = [f for f in self.detect(self._read(image)) if f["e"] is not None]
            if faces:
                embs.append(max(faces, key=lambda f: f["box"][2] * f["box"][3])["e"])
        if not embs:
            raise ValueError("no usable face in the enrollment photos")
        mean = [sum(col) / len(embs) for col in zip(*embs)]
        n = sum(x * x for x in mean) ** 0.5 or 1.0
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"profile_id": profile_id, "photos": len(images), "faces": len(embs),
               "model": MODEL, "e": [x / n for x in mean]}  # fmt: skip
        path.write_text(json.dumps(doc))
        return {"profile_id": profile_id, "photos": len(images), "faces": len(embs),
                "face_enrolled": True, "model": MODEL}  # fmt: skip

    def identify(self, image: Path, *, min_similarity: float | None = None) -> list[dict]:
        enrolled = self.enrolled()
        if not enrolled:
            return []  # nobody opted in: never run the model on bystanders' faces
        return self.match(self.detect(self._read(image)), enrolled, min_similarity)

    def match(
        self, faces: list[dict], enrolled: list[dict], min_similarity: float | None = None
    ) -> list[dict]:
        """Best enrolled profile per face, kept when ≥ the threshold. Only enrolled
        embeddings are compared against; a face with no hit leaves no trace."""
        thr = self.threshold if min_similarity is None else min_similarity
        hits = []
        for f in faces:
            if f["e"] is None:
                continue
            sims = [(sum(a * b for a, b in zip(f["e"], d["e"])), d["profile_id"]) for d in enrolled]
            sim, pid = max(sims)
            if sim >= thr:
                hits.append({"profile_id": pid, "similarity": round(sim, 3), "box": f["box"]})
        return sorted(hits, key=lambda h: -h["similarity"])

    def forget(self, profile_id: str) -> None:
        self._path(profile_id).unlink(missing_ok=True)
