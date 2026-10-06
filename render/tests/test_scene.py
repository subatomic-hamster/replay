"""2.5D scene package: the package reproduces the real camera, the envelope holds it,
and the presets are inside the envelope."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
from courtcam.profiles import load_profile
from replay_render import testing as toy
from replay_render.virtual import replays, scene, segment

from courtcam import calibrate as calib_mod
from courtcam import plate as plate_mod

if shutil.which("ffmpeg") is None:
    pytest.skip("needs ffmpeg", allow_module_level=True)


@pytest.fixture(scope="module")
def pkg(tmp_path_factory):
    gd = toy.make_toy_game(tmp_path_factory.mktemp("scene") / "g", duration=14.0)
    calib = json.loads((gd / "calib.json").read_text())
    tpl = load_profile("basketball").template("full")
    names = list(tpl.landmarks)
    px = toy.project(np.column_stack([tpl.landmark_array(names), np.zeros(len(names))]))
    calib.update(
        image_size=[toy.W, toy.H],
        court_polygon_m=tpl.polygon.tolist(),
        landmarks_px={n: p.tolist() for n, p in zip(names, px, strict=True)},
    )
    (gd / "calib.json").write_text(json.dumps(calib))
    cal = calib_mod.camera_calibration(calib, load_profile("basketball"))
    (gd / "calibration.json").write_text(json.dumps(cal))
    video = gd / "media" / "wide.mp4"
    plate_mod.build_plate(video, calib, cal, gd / "plate", tracks_dir=gd / "tracks")
    replays.write_highlights(gd, n=1, synthetic=True)
    play_id = replays.read_highlights(gd)["plays"][0]["play_id"]
    segment.segment_play(gd, video, play_id, fake=True)
    out = gd / "pkg"
    meta = scene.build_package(gd, video, play_id, out, max_frames=40)
    return gd, video, play_id, out, meta


def test_package_files_and_atlas_contract(pkg):
    out = pkg[3]
    lay = json.loads((out / "layout.json").read_text())
    assert lay["schema"] == scene.SCHEMA and lay["n_frames"] == len(lay["frames"]) == 40
    w, h = lay["atlas"]["size_px"]
    assert w % 16 == 0 and h % 16 == 0 and w <= 2048 and h <= 1024
    cw, ch = lay["atlas"]["cell_px"]
    cols, rows = lay["atlas"]["grid"]
    assert cols * cw * 2 == w and rows * ch == h
    for row in lay["frames"]:
        assert len({it["cell"] for it in row}) == len(row)  # one player per cell
        for it in row:
            u0, v0, u1, v1 = it["uv"]
            assert 0 <= u0 < u1 <= 0.5 and 0 <= v0 < v1 <= 1  # colour half
            s0, z0, s1, z1 = it["rect"]
            assert s0 < 0 < s1 and z0 < 0.3 and 1.0 < z1 < 3.0  # a person standing on the foot
    rgba = scene.Package(out).plates[1][1]
    assert rgba.shape[2] == 4 and 0 < (rgba[..., 3] > 127).mean() < 1  # floor: seen + void
    info = replays.probe_video(out / "atlas.mp4")
    assert (info["width"], info["height"], info["frames"]) == (w, h, 40)


def test_real_preset_is_the_real_camera(pkg):
    out = pkg[3]
    p = scene.Package(out)
    size = tuple(p.layout["camera"]["image_size"])
    v = p.view("real", size)
    pts = np.array([[-7.5, 0, 0], [7.5, 28, 0], [0, 14, 2.0], [3, 10, 1.0]])
    assert np.allclose(v.project(pts), p.real.project(pts), atol=0.05)


def test_reference_render_reproduces_the_source_from_the_real_camera(pkg):
    gd, video, play_id, out, _ = pkg
    res = scene.check_real(gd, video, play_id, out)
    # players only: the toy video is an animated test pattern, so it has no static plate
    assert res["psnr_players"] > 24 and res["ssim_players"] > 0.75


def test_presets_inside_the_envelope_and_edges_meet_the_limits(pkg):
    lay = json.loads((pkg[3] / "layout.json").read_text())
    env = lay["envelope"]
    for p in lay["presets"]:
        assert env["azimuth_deg"][0] - 1e-6 <= p["azimuth_deg"] <= env["azimuth_deg"][1] + 1e-6
        assert (
            env["elevation_deg"][0] - 1e-6 <= p["elevation_deg"] <= env["elevation_deg"][1] + 1e-6
        )
        assert env["distance_m"][0] - 1e-6 <= p["distance_m"] <= env["distance_m"][1] + 1e-6
    for name, m in env["edge_metrics"].items():
        assert m["az_dev"] <= scene.AZ_DEV_MAX and m["el_dev"] <= scene.EL_DEV_MAX, name
        assert m["mag"] <= scene.MAG_MAX, name


def test_billboard_axis_faces_the_camera():
    cam = np.array([0.0, -10.0, 3.0])
    a = scene.billboard_axis(cam, np.array([0.0, 0.0, 0.0]))
    assert np.allclose(a, [1, 0, 0])  # looking along +y, the viewer's right is +x
