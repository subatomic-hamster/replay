"""TV redesign stages on a synthetic clip (ffmpeg testsrc2): storyboard sheets + manifest,
moment thumbs + labels, the hero frame, cache hits, and hype.json as an optional input
ordered by `soft_after`."""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess

import pytest
from replay_worker import Cache, Stage, run
from replay_worker.stages import load_registry

cv2 = pytest.importorskip("cv2")
if shutil.which("ffmpeg") is None:
    pytest.skip("needs ffmpeg", allow_module_level=True)

DUR = 13.0
EVENTS = [
    {"id": "e_0001", "type": "shot", "made": True, "points": 3, "t_start": 2, "t_key": 3.0,
     "t_end": 4, "player_id": "p1", "confidence": 0.8, "source": "heuristic"},
    {"id": "e_0002", "type": "shot", "made": None, "t_start": 6, "t_key": 7.5, "t_end": 9,
     "player_id": "p2", "confidence": 0.6, "source": "heuristic"},
    {"id": "e_0003", "type": "contact", "t_start": 8, "t_key": 8.0, "t_end": 8.2},
    {"id": "e_0004", "type": "bookmark", "t_start": 8, "t_key": 11.0, "t_end": 12,
     "confidence": 1.0, "source": "user", "confirmed": True},
]  # fmt: skip
GAME = {
    "id": "g_toy",
    "sport": "basketball",
    "video": {"duration_s": DUR, "fps": 30, "width": 640, "height": 360},
    "players": [{"id": "p1", "name": "Maya", "team": 0, "color_hex": "#1f4fa0"},
                {"id": "p2", "name": None, "team": 1, "color_hex": "#e8e8e8"}],
}  # fmt: skip


@pytest.fixture
def gd(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    gd = tmp_path / "g_toy"
    (gd / "media").mkdir(parents=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={DUR}",
         "-c:v", "mpeg4", "-q:v", "5", str(gd / "media/wide.mp4")],
        check=True,
    )  # fmt: skip
    (gd / "events.json").write_text(json.dumps({"schema": "replay.events.v1", "events": EVENTS}))
    (gd / "game.json").write_text(json.dumps(GAME))
    return gd


def _reg() -> dict[str, Stage]:
    """The two stages without the pipeline upstream (the game dir is already processed)."""
    full = load_registry()
    return {n: dataclasses.replace(full[n], after=()) for n in ("storyboard", "moments")}


def _go(gd, cache):
    return {r["stage"]: r["cache"] for r in run(gd, {}, registry=_reg(), cache=cache)}


def test_storyboard_moments_and_hero_then_hits(gd, tmp_path):
    cache = Cache(tmp_path / "cache")
    assert _go(gd, cache) == {"storyboard": "miss", "moments": "miss"}

    sb = json.loads((gd / "storyboard/manifest.json").read_text())
    # frames at 0, 2, ..., 12 s: 7 cells on one sheet, one row tall
    assert {k: sb[k] for k in ("interval_s", "width", "height", "cols", "rows", "count")} == {
        "interval_s": 2, "width": 320, "height": 180, "cols": 10, "rows": 10, "count": 7}  # fmt: skip
    assert sb["sheets"] == ["storyboard/0000.jpg"]
    sheet = cv2.imread(str(gd / sb["sheets"][0]))
    assert sheet.shape[:2] == (180, 3200)
    # 7 cells drawn, the rest black (give or take JPEG ringing at the edge)
    assert sheet[:, 7 * 320 + 8 :].max() < 8 and sheet[:, : 7 * 320].mean() > 10

    doc = json.loads((gd / "moments.json").read_text())
    rows = [(m["id"], m["kind"], m["label"], m.get("thumb")) for m in doc["moments"]]
    assert rows == [
        ("e_0001", "score", "Three-pointer, Maya", "moments/e_0001.jpg"),
        ("e_0002", "play", "Shot", "moments/e_0002.jpg"),  # made unknown: never "basket"
        ("e_0004", "bookmark", "Your bookmark", "moments/e_0004.jpg"),
    ]  # the contact is not a moment
    assert doc["moments"][0]["player"] == {"id": "p1", "name": "Maya", "color_hex": "#1f4fa0"}
    assert cv2.imread(str(gd / "moments/e_0001.jpg")).shape[:2] == (270, 480)
    assert doc["hero"] == {"t": 3.0, "from": "event", "path": "media/hero.jpg"}
    assert cv2.imread(str(gd / "media/hero.jpg")).shape[:2] == (720, 1280)
    a, b = cv2.imread(str(gd / "moments/e_0001.jpg")), cv2.imread(str(gd / "moments/e_0004.jpg"))
    assert abs(a.astype(int) - b).mean() > 1  # different times, different frames

    assert _go(gd, cache) == {"storyboard": "hit", "moments": "hit"}

    # a hype candidate (optional input) re-keys moments only and moves the hero
    hype = {"candidates": [{"t": 9.0, "t_start": 6.0, "t_end": 10.0, "score": 0.9}]}
    (gd / "hype.json").write_text(json.dumps(hype))
    assert _go(gd, cache) == {"storyboard": "hit", "moments": "miss"}
    hero = json.loads((gd / "moments.json").read_text())["hero"]
    assert hero["from"] == "hype" and hero["t"] == 9.0  # no scoring moment inside the window


def test_moments_waits_for_hype_only_when_hype_runs(tmp_path, monkeypatch):
    """soft_after: ordered after hype in the same run; never pulls hype in."""
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    order: list[str] = []

    def mark(name, out):
        def fn(ctx, item):
            order.append(name)
            (ctx.game_dir / out).write_text(name)

        return fn

    reg = {
        "hype": Stage("hype", "1", mark("hype", "hype.json"), outputs=("hype.json",),
                      default=False, resource="io"),
        "moments": Stage("moments", "1", mark("moments", "m.json"), inputs=("hype.json?",),
                         outputs=("m.json",), soft_after=("hype",)),
    }  # fmt: skip
    cache = Cache(tmp_path / "cache")
    run(tmp_path / "a", {}, registry=reg, cache=cache)
    assert order == ["moments"]  # the default run does not pull hype in
    order.clear()
    run(tmp_path / "b", {}, registry=reg, stages=["moments", "hype"], cache=cache)
    assert order == ["hype", "moments"]


def test_both_in_the_default_dag():
    reg = load_registry()
    assert reg["storyboard"].default and reg["moments"].default
    assert reg["storyboard"].after == ("ingest",) and reg["moments"].after == ("game",)
