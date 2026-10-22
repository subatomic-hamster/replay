"""D-88 body proxy: capsule ray test, and a proxy seen from the real camera shows the real
pixels while its unseen back falls back to the colours it was seen in (not the kit)."""

from __future__ import annotations

import numpy as np
from replay_render.avatars import proxy
from replay_render.avatars.skeleton import rest_pose
from replay_render.virtual.tierb import look_at

SIZE = (1280, 720)


def test_ray_capsules_hits_side_and_cap_and_misses():
    a, b, r = np.array([[0.0, 0, 0]]), np.array([[0.0, 0, 1]]), np.array([0.2])
    side = proxy.ray_capsules(np.array([-5.0, 0, 0.5]), np.array([[1.0, 0, 0]]), a, b, r)
    cap = proxy.ray_capsules(np.array([0.0, 0, 5]), np.array([[0.0, 0, -1]]), a, b, r)
    miss = proxy.ray_capsules(np.array([-5.0, 0, 0.5]), np.array([[0.0, 1, 0]]), a, b, r)
    assert np.isclose(side[0, 0], 4.8)
    assert np.isclose(cap[0, 0], 3.8)
    assert np.isinf(miss[0, 0])


class _FullMasks:
    def get(self, pid, f):
        return (0, 0), np.ones(SIZE[::-1], bool)


def _proxy(frame):
    real = look_at(np.array([0.0, -8, 1.2]), np.array([0.0, 0, 1]), 800.0, SIZE)
    doc = {"players": [{"id": "p1", "height_m": 1.85}]}
    joints = [np.stack([rest_pose(1.85)] * 3)]
    px = proxy.Proxy(doc, joints, real, 0.0, SIZE, {"p1": (0, 255, 0)})
    for f in range(3):
        px.observe(f, frame, _FullMasks())
    px.finish()
    return px, real


def test_proxy_shows_real_pixels_frontally_and_seen_colours_behind():
    yy, xx = np.mgrid[: SIZE[1], : SIZE[0]]
    frame = np.dstack([xx % 256, yy % 256, np.full_like(xx, 40)]).astype(np.uint8)
    px, real = _proxy(frame)
    canvas = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
    assert px.draw(canvas, real, 1, frame, "p1", _FullMasks())
    u, v = real.project(np.array([[0.0, 0, 1.2]]))[0].round().astype(int)  # the chest
    assert np.abs(canvas[v, u].astype(int) - frame[v, u]).max() <= 3

    plain = np.full((SIZE[1], SIZE[0], 3), (200, 60, 60), np.uint8)
    px, _ = _proxy(plain)
    back = look_at(np.array([0.0, 8, 1.2]), np.array([0.0, 0, 1]), 800.0, SIZE)
    canvas[:] = 0
    assert px.draw(canvas, back, 1, plain, "p1", _FullMasks())
    u, v = back.project(np.array([[0.0, 0, 1.2]]))[0].round().astype(int)
    b, g, r = canvas[v, u].astype(int)
    assert b > 100 and g < 80 and r < 80  # the seen kit colour, shaded; not the green tint
