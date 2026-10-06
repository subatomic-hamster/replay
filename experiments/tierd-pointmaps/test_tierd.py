"""Checks for the Tier D helpers (CPU): `python -m pytest experiments/tierd-pointmaps -q`."""

import numpy as np
from geom import _demo
from replay_render.virtual import tierb as B
from scene import fill_holes, splat


def test_geom_roundtrip_and_scale_fit():
    _demo()


def test_splat_nearest_point_wins_and_footprint_grows():
    view = B.look_at(np.array([0.0, -10.0, 0.0]), np.array([0.0, 0.0, 0.0]), 100.0, (64, 48))
    xyz = np.array([[0.0, 0.0, 0.0], [0.0, 2.0, 0.0], [1.0, 0.0, 0.0]])  # 2nd is behind the 1st
    rgb = np.array([[0, 0, 255], [255, 0, 0], [0, 255, 0]], np.uint8)
    foot = np.array([0.01, 0.01, 0.4])  # the 3rd covers 2 px around itself
    img, zb, idx = splat(xyz, rgb, foot, view, (64, 48))
    assert tuple(img[24, 32]) == (0, 0, 255) and idx[24, 32] == 0 and zb[24, 32] == 10.0
    assert (idx == 1).sum() == 0  # fully hidden
    assert (idx == 2).sum() == 25  # 5x5 splat at (42, 24)
    hole = np.isfinite(zb)
    hole[24, 42] = False  # punch the centre of the green splat: filled from its neighbours
    filled, ok = fill_holes(img * hole[..., None], hole)
    assert ok[24, 42] and tuple(filled[24, 42]) == (0, 255, 0)
    assert not ok[0, 0]  # edges of the void stay void
