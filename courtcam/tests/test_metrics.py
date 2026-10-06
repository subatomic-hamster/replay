"""CLEAR-MOT / IDF1 on hand-built cases, then end to end on a synthetic run."""

from __future__ import annotations

import numpy as np
import pytest

from courtcam import pipeline
from courtcam.metrics import evaluate, evaluate_run, iou_matrix
from courtcam.synth import generate


def box(x: float) -> np.ndarray:
    return np.array([x, 0.0, 10.0, 20.0])


def test_iou():
    assert iou_matrix(box(0), box(0))[0, 0] == pytest.approx(1.0)
    assert iou_matrix(box(0), box(5))[0, 0] == pytest.approx(1 / 3)
    assert iou_matrix(box(0), box(50))[0, 0] == 0.0


def test_perfect_tracking():
    gt = {f: [(1, box(0)), (2, box(100))] for f in range(10)}
    pred = {f: [(7, box(1)), (8, box(101))] for f in range(10)}
    m = evaluate(gt, pred)
    assert (m["mota"], m["idf1"], m["id_switches"], m["recall"], m["precision"]) == (
        1.0, 1.0, 0, 1.0, 1.0,
    )  # fmt: skip


def test_an_id_swap_halfway_costs_two_switches_and_half_the_idf1():
    gt = {f: [(1, box(0)), (2, box(100))] for f in range(10)}
    pred = {
        f: [(7, box(0)), (8, box(100))] if f < 5 else [(8, box(0)), (7, box(100))]
        for f in range(10)
    }
    m = evaluate(gt, pred)
    assert m["id_switches"] == 2
    assert m["mota"] == pytest.approx(1 - 2 / 20)
    assert m["idf1"] == pytest.approx(0.5)


def test_misses_false_positives_and_dont_care_boxes():
    gt = {f: [(1, box(0))] for f in range(4)}
    pred = {
        0: [(5, box(0)), (6, box(300))],
        1: [],
        2: [(5, box(0)), (9, box(200))],
        3: [(5, box(0))],
    }
    ignore = {2: [(3, box(200))]}  # a hidden player: a hit on it is neither TP nor FP
    m = evaluate(gt, pred, ignore=ignore)
    assert (m["tp"], m["fn"], m["fp"]) == (3, 1, 1)
    assert m["mota"] == pytest.approx(1 - 2 / 4)


def test_ground_truth_detector_run_scores_near_perfect(tmp_path):
    """`--detector synthetic` replays the truth, so detection is exact by construction and
    whatever the players score is the tracking/court/identity stages' own error."""
    synth = tmp_path / "synth"
    generate(
        synth, sport="basketball", variant="half", duration_s=12.0, size=(960, 540), video=True
    )
    out = tmp_path / "out"
    pipeline.run(
        synth / "clip.mp4",
        out,
        sport="basketball",
        variant="half",
        detector="synthetic",
        ground_truth=synth / "ground_truth.json",
        calib=synth / "landmarks.json",
        stages=["ingest", "calibrate", "detect", "track", "court", "identity"],
        show_progress=False,
    )
    report = evaluate_run(synth / "ground_truth.json", out)
    det = report["detections"]
    assert det["recall"] == 1.0 and det["precision"] == 1.0 and det["id_switches"] == 0
    players = report["players"]
    assert players["recall"] >= 0.95 and players["precision"] >= 0.95
    assert players["id_switches"] == 0
    assert players["court_err_m"]["median"] < 0.25
