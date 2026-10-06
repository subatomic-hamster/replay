"""M10 `face_match`: opt-in, gated on enrolled profiles; never opens the video otherwise."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from replay_worker.dag import Ctx
from replay_worker.stages import faces, load_registry

FAKE_GAME = Path(__file__).resolve().parents[2] / "api" / "fixtures" / "fake_game"


def test_registered_off_by_default():
    stage = load_registry()["face_match"]
    assert stage.default is False and "{face_dir}" in stage.inputs


def test_skips_without_store_or_enrollment(tmp_path, monkeypatch):
    monkeypatch.delenv("REPLAY_FACE_DIR", raising=False)
    gd = tmp_path / "g"
    shutil.copytree(FAKE_GAME, gd)  # no media/wide.mp4: opening the video would fail
    faces.run_face_match(Ctx(gd, {}), None)
    doc = json.loads((gd / "faces.json").read_text())
    assert doc["matches"] == [] and "opt-in" in doc["skipped"]
    faces.run_face_match(Ctx(gd, {"face_dir": str(tmp_path / "store")}), None)
    doc = json.loads((gd / "faces.json").read_text())
    assert doc["skipped"] == "no enrolled profiles" and doc["samples"] == 0
