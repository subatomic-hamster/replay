"""D-23 autocalibration. No model is called: the vision pass is stubbed out."""

from __future__ import annotations

import numpy as np
import pytest

from courtcam import autocalib
from courtcam.profiles import load_profile

# The conftest/fixture click set: projects from the basketball_half template with a
# reprojection error of ~0.02 px, so anything this file measures is our own error.
TRUTH: dict[str, tuple[float, float]] = {
    "corner_nl": (180.0, 660.0),
    "corner_nr": (1100.0, 660.0),
    "corner_fl": (430.0, 300.0),
    "corner_fr": (860.0, 300.0),
    "rim": (641.1, 583.2),
}
WIDTH, HEIGHT = 1280, 720


@pytest.fixture
def profile():
    return load_profile("basketball")


def blank() -> np.ndarray:
    """A frame with a white patch top-left, so a stub can tell a mirrored copy apart."""
    frame = np.full((HEIGHT, WIDTH, 3), 30, dtype=np.uint8)
    frame[:24, :48] = 255
    return frame


def is_straight(img: np.ndarray) -> bool:
    return float(img[:24, :48].mean()) > float(img[:24, -48:].mean())


def mirrored_answer(points: dict[str, tuple[float, float]]) -> dict[str, list[float]]:
    """What the model would say about the left-right flipped frame: the same physical
    points, mirrored, and with near/far swapped because the other basket is now left."""
    return {
        autocalib._swap(name, "n", "f"): [WIDTH - 1 - x, y] for name, (x, y) in points.items()
    }


def stub(straight: dict, flipped: dict):
    def ask(img, prompt, *, timeout_s=0):  # noqa: ARG001
        return straight if is_straight(img) else flipped

    return ask


# ------------------------------------------------------------------------ the picture


def test_grid_downscales_and_labels_in_source_pixels():
    big = np.zeros((960, 2560, 3), dtype=np.uint8)
    img, scale = autocalib.gridded(big)
    assert max(img.shape[:2]) == autocalib.MAX_SIDE_PX
    assert scale == pytest.approx(autocalib.MAX_SIDE_PX / 2560)
    # 8:3 in, 8:3 out — a squashed frame would make every read-off coordinate wrong.
    assert img.shape[1] / img.shape[0] == pytest.approx(2560 / 960, rel=0.01)
    assert img.any(), "the grid should have drawn something on a black frame"


def test_small_frames_are_not_upscaled():
    img, scale = autocalib.gridded(blank())
    assert scale == 1.0 and img.shape[:2] == (HEIGHT, WIDTH)


def test_prompt_carries_the_profile_glossary(profile):
    prompt = autocalib.build_prompt(profile, "half", (WIDTH, HEIGHT))
    assert f"{WIDTH} x {HEIGHT}" in prompt
    assert "corner_nl: the court corner where the NEAR baseline" in prompt
    assert "NOT the hoop itself" in prompt  # the rim is a floor point, not the ring
    # Only the landmarks a human is walked through, unless asked for more.
    assert "key_nl" not in prompt
    assert "key_nl" in autocalib.build_prompt(profile, "half", (WIDTH, HEIGHT), optional=True)


def test_half_court_prompt_omits_landmarks_the_template_lacks(profile):
    assert "key_fl" not in autocalib.build_prompt(
        profile, "half", (WIDTH, HEIGHT), optional=True
    )
    assert "key_fl" in autocalib.build_prompt(profile, "full", (WIDTH, HEIGHT), optional=True)


# ------------------------------------------------------------------------- the parsing


def test_swap_only_touches_the_name_suffix():
    assert autocalib._swap("corner_nl", "n", "f") == "corner_fl"
    assert autocalib._swap("corner_fr", "n", "f") == "corner_nr"
    assert autocalib._swap("corner_nl", "l", "r") == "corner_nr"
    assert autocalib._swap("centre_l", "l", "r") == "centre_r"
    assert autocalib._swap("rim", "n", "f") == "rim"  # no suffix to swap


def test_extract_json_survives_a_chatty_model():
    assert autocalib._extract_json('Sure!\n```json\n{"a": [1, 2]}\n```\ndone') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        autocalib._extract_json("I could not see the court.")


def test_nulls_and_junk_are_dropped_not_guessed():
    raw = {"corner_nl": [1, 2], "corner_nr": None, "corner_fl": "left", "corner_fr": [3]}
    assert autocalib._parse_points(raw, ["corner_nl", "corner_nr", "corner_fl", "corner_fr"]) == {
        "corner_nl": (1.0, 2.0)
    }


# --------------------------------------------------------------------- the two passes


def test_agreeing_passes_are_kept_with_high_confidence(profile, monkeypatch):
    straight = {k: list(v) for k, v in TRUTH.items()}
    monkeypatch.setattr(autocalib, "ask_sdk", stub(straight, mirrored_answer(TRUTH)))
    out = autocalib.propose_vlm(blank(), profile, "half")
    assert set(out.landmarks_px) == set(TRUTH)
    for name, point in TRUTH.items():
        assert out.landmarks_px[name] == pytest.approx(point, abs=0.01)
    # The four corners were confirmed by both passes; `rim` has no mirror twin.
    for name in ("corner_nl", "corner_nr", "corner_fl", "corner_fr"):
        assert out.confidence[name] == pytest.approx(1.0)
    assert out.confidence["rim"] == autocalib.SINGLE_PASS_CONFIDENCE


def test_a_landmark_the_two_passes_disagree_on_is_dropped(profile, monkeypatch):
    flipped = mirrored_answer(TRUTH)
    flipped["corner_nr"] = [flipped["corner_nr"][0] - 300, flipped["corner_nr"][1]]
    monkeypatch.setattr(autocalib, "ask_sdk", stub({k: list(v) for k, v in TRUTH.items()}, flipped))
    out = autocalib.propose_vlm(blank(), profile, "half")
    # `corner_nr` in the mirrored answer carries the label `corner_fr` once un-mirrored,
    # so that is the point that loses its second opinion: a disagreement costs one
    # landmark, it does not quietly poison the fit.
    assert "corner_fr" not in out.landmarks_px
    assert set(out.landmarks_px) == set(TRUTH) - {"corner_fr"}
    assert "disagreed" in out.notes


def test_the_near_rim_has_no_mirror_twin_and_survives_single_pass(profile, monkeypatch):
    """Flipping the frame swaps which basket is near, so the mirrored answer's `rim` is
    the *other* rim — comparing them would drop the landmark on every single run."""
    assert autocalib.twinless(profile, "full") == {"rim"}
    # The half-court template has no far key at all, so those lose their twin too.
    assert autocalib.twinless(profile, "half") == {"rim", "key_nl", "key_nr", "ft_nl", "ft_nr"}

    flipped = mirrored_answer(TRUTH)
    flipped["rim"] = [0.0, 0.0]  # the far rim: nowhere near the near one
    monkeypatch.setattr(autocalib, "ask_sdk", stub({k: list(v) for k, v in TRUTH.items()}, flipped))
    out = autocalib.propose_vlm(blank(), profile, "half")
    assert out.landmarks_px["rim"] == pytest.approx(TRUTH["rim"], abs=0.01)
    assert out.confidence["rim"] == autocalib.SINGLE_PASS_CONFIDENCE


def test_a_dead_model_is_an_empty_proposal_not_an_exception(profile, monkeypatch):
    def boom(img, prompt, *, timeout_s=0):  # noqa: ARG001
        raise RuntimeError("claude CLI exited 1")

    monkeypatch.setattr(autocalib, "ask_sdk", boom)
    out = autocalib.propose_vlm(blank(), profile, "half")
    assert out.landmarks_px == {} and "failed" in out.notes


# ------------------------------------------------------------------------- the snapper


def test_snap_pulls_a_point_onto_a_line_crossing():
    import cv2

    frame = np.full((720, 1280, 3), 20, dtype=np.uint8)
    cv2.line(frame, (100, 500), (1180, 500), (255, 255, 255), 3)
    cv2.line(frame, (600, 80), (640, 700), (255, 255, 255), 3)
    snapper = autocalib.LineSnapper(frame)
    assert len(snapper.segments) > 0

    point, snapped = snapper.snap((650, 520))
    assert snapped
    assert point[0] == pytest.approx(627, abs=12) and point[1] == pytest.approx(500, abs=6)

    # Nothing within the radius: the point is returned untouched, not invented.
    far, moved = snapper.snap((60, 60), radius=20)
    assert far == (60, 60) and moved is False


def test_lines_backend_reports_what_it_can_see_and_names_nothing(profile):
    import cv2

    frame = np.full((720, 1280, 3), 20, dtype=np.uint8)
    cv2.line(frame, (100, 500), (1180, 500), (255, 255, 255), 3)
    out = autocalib.autocalibrate(frame, profile, "half", backend="lines")
    assert out.landmarks_px == {} and out.source == "lines"
    assert "line segments" in out.notes


# ---------------------------------------------------------------------------- the auto


def test_auto_end_to_end_produces_a_usable_homography(profile, monkeypatch):
    monkeypatch.setattr(
        autocalib, "ask_sdk", stub({k: list(v) for k, v in TRUTH.items()}, mirrored_answer(TRUTH))
    )
    out = autocalib.autocalibrate(blank(), profile, "half", backend="vlm")
    assert out.ok is True
    assert out.reprojection_error_px is not None and out.reprojection_error_px < 1.0
    assert set(out.landmarks_px) == set(TRUTH)
    assert out.as_dict()["landmarks_px"]["rim"] == pytest.approx(list(TRUTH["rim"]), abs=0.01)


def test_a_mirrored_labelling_is_corrected_from_the_winding(profile, monkeypatch):
    """The court is symmetric about its long axis, so a global left/right swap fits
    exactly as well — only the winding says which one is a view from above."""
    swapped = {autocalib._swap(k, "l", "r"): v for k, v in TRUTH.items()}
    monkeypatch.setattr(
        autocalib,
        "ask_sdk",
        stub({k: list(v) for k, v in swapped.items()}, mirrored_answer(swapped)),
    )
    out = autocalib.autocalibrate(blank(), profile, "half", backend="vlm")
    assert "left/right" in out.notes
    assert out.ok is True
    assert out.landmarks_px["corner_nl"] == pytest.approx(TRUTH["corner_nl"], abs=0.01)


def test_too_few_confident_landmarks_is_not_ok_but_still_returns_them(profile, monkeypatch):
    few = {"corner_nl": list(TRUTH["corner_nl"]), "rim": list(TRUTH["rim"])}
    monkeypatch.setattr(autocalib, "ask_sdk", stub(few, mirrored_answer(
        {k: TRUTH[k] for k in ("corner_nl", "rim")}
    )))
    out = autocalib.autocalibrate(blank(), profile, "half", backend="vlm")
    assert out.ok is False
    assert set(out.landmarks_px) == {"corner_nl", "rim"}
    assert "above confidence" in out.notes


def test_backend_auto_falls_back_to_lines_without_a_key_or_a_cli(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(autocalib.shutil, "which", lambda _name: None)
    assert autocalib._resolve_backend("auto") == "lines"
    monkeypatch.setattr(autocalib.shutil, "which", lambda _name: "/usr/bin/claude")
    assert autocalib._resolve_backend("auto") == "claude-cli"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert autocalib._resolve_backend("auto") == "vlm"
    assert autocalib._resolve_backend("lines") == "lines"
