"""Posed 3D body proxies textured from the real video, for wide virtual angles (D-88).

A cutout is a photo of one side of a person: past ~45° from the real camera it reads
wrong. Behind each cutout stands a proxy: one capsule per body part (torso, hips,
shoulders, thighs, shanks, feet, upper arms, forearms, neck, head) posed on the 3D
scene's joints (`avatars.scene`, court metres) with radii from the player's stature.
We build it ourselves; no body model licence is involved.

Texturing is view-dependent, per pixel of the virtual image:

1. **Now**: the proxy point is projected into the real camera at this frame. If the
   real camera sees that side of the part (normal within ~75° of the line of sight),
   no other part of the same body is in front of it, and the pixel is inside the
   player's SAM mask, the real pixel is used.
2. **History**: else the part's texture atlas: a cylinder map per part (angle round
   the part, measured from the player's facing so the front stays the front, x
   position along it), filled from every frame of the play where that texel was seen
   (`build_atlas`), the nearest such frame in time.
3. **Never seen**: the part's mean seen colour (sleeves stay skin, shorts stay shorts),
   else the kit colour, shaded by a fixed light.

Each player is ray-cast in its own screen box (capsule intersections in numpy), with an
internal depth test, and composited in the painter's order like the cutouts.
"""

from __future__ import annotations

import cv2
import numpy as np

from courtcam import distortion

from ..virtual.tierb import EZ, View

# (joint a, joint b, radius / stature); H36M-17 joint indices (avatars.skeleton)
PARTS = (
    (0, 8, 0.085),  # torso: pelvis -> thorax
    (1, 4, 0.068),  # hips
    (14, 11, 0.048),  # shoulders
    (1, 2, 0.046), (4, 5, 0.046),  # thighs
    (2, 3, 0.033), (5, 6, 0.033),  # shanks
    (3, -1, 0.026), (6, -1, 0.026),  # feet: ankle -> toe (made from the facing)
    (14, 15, 0.029), (11, 12, 0.029),  # upper arms
    (15, 16, 0.025), (12, 13, 0.025),  # forearms
    (8, 9, 0.030),  # neck
    (10, -2, 0.060),  # head (made round the eyes)
)  # fmt: skip
NU, NV = 32, 16  # atlas texels round x along each part
SEEN_COS = 0.26  # the real camera sees a surface point within ~75° of its normal
FADE_COS = 0.45  # ... and its pixel fully from here up
LIGHT = np.array([0.3, -0.4, 0.87]) / np.linalg.norm([0.3, -0.4, 0.87])


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-9)


def facing(joints: np.ndarray, sigma: float = 3.0) -> np.ndarray:
    """(F, 3) horizontal forward unit vectors from the hips (right hip - left hip turned
    90° about up), smoothed over time; NaN where the player is absent."""
    right = joints[:, 1] - joints[:, 4]
    fwd = np.cross(EZ, right)
    fwd[:, 2] = 0
    ok = np.isfinite(fwd[:, 0])
    if ok.sum() >= 2 and sigma > 0:
        idx = np.arange(len(fwd))
        filled = np.stack([np.interp(idx, idx[ok], fwd[ok, k]) for k in range(3)], 1)
        r = int(3 * sigma)
        k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
        k /= k.sum()
        pad = np.pad(filled, ((r, r), (0, 0)), mode="edge")
        filled = np.stack([np.convolve(pad[:, c], k, mode="valid") for c in range(3)], 1)
        fwd = np.where(ok[:, None], filled, np.nan)
    return _unit(fwd)


def capsules(j: np.ndarray, fwd: np.ndarray, height: float):
    """One frame's capsules: ends A, B (P, 3), radii R (P,), and per part a frame
    (e1, e2) round its axis with e1 toward the player's facing."""
    a, b = np.empty((len(PARTS), 3)), np.empty((len(PARTS), 3))
    up = _unit(j[10] - j[8])
    for i, (ja, jb, _) in enumerate(PARTS):
        if jb == -1:  # foot: from the ankle forward and down to the floor
            a[i] = j[ja]
            b[i] = j[ja] + fwd * 0.13 * height / 1.8 - EZ * 0.04
        elif jb == -2:  # head: round the eyes, a little up and back
            c = j[ja] + up * 0.02 * height - fwd * 0.015 * height
            a[i], b[i] = c - up * 0.03 * height, c + up * 0.03 * height
        else:
            a[i], b[i] = j[ja], j[jb]
    r = np.array([p[2] for p in PARTS]) * height
    u = _unit(b - a)
    ref = fwd - (u @ fwd)[:, None] * u
    weak = np.linalg.norm(ref, axis=1) < 0.3  # a part pointing forward: use up instead
    ref[weak] = (EZ - (u @ EZ)[:, None] * u)[weak]
    e1 = _unit(ref)
    e2 = np.cross(u, e1)
    return a, b, r, e1, e2


def ray_capsules(o: np.ndarray, d: np.ndarray, a: np.ndarray, b: np.ndarray, r: np.ndarray):
    """Distance along unit rays `o + t d` (one origin (3,), (N, 3) directions) to each
    capsule (P); inf on a miss or behind the origin. (Quilez's capsule test, with the
    end caps in scalar form: no (N, P, 3) temporaries.)"""
    ba = b - a
    oa = np.asarray(o, np.float64).reshape(3) - a
    baba = (ba * ba).sum(-1)
    baoa = (oa * ba).sum(-1)
    oaoa = (oa * oa).sum(-1)
    bard = d @ ba.T
    rdoa = d @ oa.T
    qa = baba - bard * bard
    qb = baba * rdoa - baoa * bard
    qc = baba * oaoa - baoa * baoa - r * r * baba
    h = qb * qb - qa * qc
    with np.errstate(invalid="ignore", divide="ignore"):
        t = (-qb - np.sqrt(h)) / qa
        y = baoa + t * bard
        side = (h >= 0) & (y > 0) & (y < baba)
        near_a = y <= 0  # the cap at a (oc = oa), else at b (oc = oa - ba)
        b2 = np.where(near_a, rdoa, rdoa - bard)
        c2 = np.where(near_a, oaoa, oaoa - 2 * baoa + baba) - r * r
        h2 = b2 * b2 - c2
        tc = -b2 - np.sqrt(h2)
    out = np.where(side, t, np.where((h >= 0) & (h2 > 0), tc, np.inf))
    return np.where(out > 1e-4, out, np.inf)


def _sample(img: np.ndarray, px: np.ndarray) -> np.ndarray:
    """Bilinear colours (N, 3) float32 of `img` at pixels `px` (N, 2)."""
    n = len(px)
    cols = 1024
    rows = -(-n // cols)
    mp = np.zeros((rows * cols, 2), np.float32)
    mp[:n] = px
    mp = mp.reshape(rows, cols, 2)
    out = cv2.remap(img, mp[..., 0], mp[..., 1], cv2.INTER_LINEAR)
    return out.reshape(-1, 3)[:n].astype(np.float32)


def _surface(caps, k: np.ndarray, p: np.ndarray):
    """Normal, (u, v) atlas coordinates of points `p` on parts `k`."""
    a, b, _, e1, e2 = caps
    ba = b[k] - a[k]
    s = np.clip(((p - a[k]) * ba).sum(-1) / np.maximum((ba * ba).sum(-1), 1e-9), 0, 1)
    n = _unit(p - (a[k] + s[:, None] * ba))
    th = np.arctan2((n * e2[k]).sum(-1), (n * e1[k]).sum(-1))
    return n, (th + np.pi) / (2 * np.pi) * NU - 0.5, s * NV - 0.5


class Proxy:
    """Every player's proxy over one play: joints, facing, stature, atlases."""

    def __init__(self, doc: dict, joints: list[np.ndarray], real: View, k1: float,
                 src_size: tuple[int, int], tints: dict) -> None:  # fmt: skip
        self.real, self.k1, self.src_size = real, k1, src_size
        self.cam = real.centre
        self.feet: dict[str, np.ndarray] = {}  # pid -> (F, 2) tracked court foot points
        self.players = {}
        for p, j in zip(doc["players"], joints, strict=True):
            if np.isfinite(j[:, 0, 0]).sum() < 2:
                continue
            self.players[p["id"]] = {
                "j": j, "fwd": facing(j), "h": float(p.get("height_m") or 1.8),
                "tint": np.asarray(tints.get(p["id"], (150, 150, 150)), np.float32),
            }  # fmt: skip
        self.atlas: dict[str, np.ndarray] = {}  # (F, P, NV, NU, 3) uint8
        self.mean: dict[str, np.ndarray] = {}  # (P, 3) float32, NaN = never seen

    def frame_caps(self, pid: str, f: int):
        q = self.players.get(pid)
        if q is None or f >= len(q["j"]) or not np.isfinite(q["j"][f, 0, 0]):
            return None
        fwd = q["fwd"][f] if np.isfinite(q["fwd"][f, 0]) else np.array([1.0, 0, 0])
        j = q["j"][f]
        foot = self.feet.get(pid)
        if foot is not None and f < len(foot) and np.isfinite(foot[f, 0]):
            # stand where the cutout and its shadow stand (the tracked foot point): the
            # lift's root can sit a metre off, which would also sample the wrong pixels
            j = j + np.r_[foot[f] - (j[3, :2] + j[6, :2]) / 2, 0.0]
        return capsules(j, fwd, q["h"])

    def _src_px(self, p: np.ndarray) -> np.ndarray:
        return distortion.distort_points(self.real.project(p), self.k1, self.src_size)

    def _seen(self, caps, k, p, n, mask_xy0, mask) -> tuple[np.ndarray, np.ndarray]:
        """Weight (N,) the real camera's pixel gets at points `p` (normals `n`, parts
        `k`), and those pixels (N, 2)."""
        to_cam = self.cam - p
        dist = np.linalg.norm(to_cam, axis=1)
        cos = (n * to_cam).sum(-1) / np.maximum(dist, 1e-9)
        w = np.clip((cos - SEEN_COS) / (FADE_COS - SEEN_COS), 0, 1)
        px = self._src_px(p)
        live = w > 0
        if live.any():  # another part of the same body in front of this point
            d = -to_cam[live] / dist[live, None]
            t = ray_capsules(self.cam[None], d, *caps[:3])
            t[np.arange(len(t)), k[live]] = np.inf
            w[np.nonzero(live)[0][t.min(1) < dist[live] - 0.03]] = 0
        x0, y0 = mask_xy0
        mx, my = np.round(px[:, 0] - x0).astype(int), np.round(px[:, 1] - y0).astype(int)
        inside = (mx >= 0) & (my >= 0) & (mx < mask.shape[1]) & (my < mask.shape[0])
        hit = np.zeros(len(p), bool)
        hit[inside] = mask[my[inside], mx[inside]]
        return w * hit, px

    def observe(self, f: int, frame: np.ndarray, masks) -> None:
        """Add frame `f`'s view of every player to their atlas."""
        uu, vv = np.meshgrid((np.arange(NU) + 0.5) / NU * 2 * np.pi - np.pi,
                             (np.arange(NV) + 0.5) / NV)  # fmt: skip
        cu, su, vv = np.cos(uu).ravel(), np.sin(uu).ravel(), vv.ravel()
        for pid, q in self.players.items():
            if pid not in self.atlas:
                n_f = len(q["j"])
                self.atlas[pid] = np.zeros((n_f, len(PARTS), NV, NU, 3), np.uint8)
                q["valid"] = np.zeros((n_f, len(PARTS), NV, NU), bool)
            caps = self.frame_caps(pid, f)
            got = masks.get(pid, f)
            if caps is None or got is None:
                continue
            xy0, m = got
            m = cv2.erode(m.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
            a, b, r, e1, e2 = caps
            n = cu[None, :, None] * e1[:, None] + su[None, :, None] * e2[:, None]  # (P, T, 3)
            p = a[:, None] + vv[None, :, None] * (b - a)[:, None] + r[:, None, None] * n
            k = np.repeat(np.arange(len(PARTS)), len(vv))
            w, px = self._seen(caps, k, p.reshape(-1, 3), n.reshape(-1, 3), xy0, m)
            ok = w > 0.5
            if not ok.any():
                continue
            col = _sample(frame, px[ok])
            flat = self.atlas[pid][f].reshape(-1, 3)
            flat[ok] = col
            q["valid"][f].reshape(-1)[ok] = True

    def finish(self) -> None:
        """Fill every texel at every frame from the nearest frame in time that saw it;
        keep each part's mean seen colour for texels never seen."""
        for pid, at in self.atlas.items():
            valid = self.players[pid].pop("valid").reshape(len(at), -1)
            n_f = len(at)
            idx = np.arange(n_f)[:, None]
            prev = np.where(valid, idx, -1)
            np.maximum.accumulate(prev, axis=0, out=prev)
            nxt = np.where(valid, idx, n_f * 2)
            nxt = np.minimum.accumulate(nxt[::-1], axis=0)[::-1]
            dp = np.where(prev >= 0, idx - prev, 4 * n_f)
            dn = np.where(nxt < n_f, nxt - idx, 4 * n_f)
            src = np.where(dp <= dn, prev, nxt)
            src = np.where((src >= 0) & (src < n_f), src, -1)
            flat = at.reshape(n_f, -1, 3)
            cols = np.arange(flat.shape[1])[None, :].repeat(n_f, 0)
            filled = flat[np.clip(src, 0, n_f - 1), cols]
            seen = valid.reshape(n_f, len(PARTS), -1)
            tot = (flat.reshape(n_f, len(PARTS), -1, 3) * seen[..., None]).sum((0, 2))
            cnt = seen.sum((0, 2))[:, None]
            with np.errstate(invalid="ignore"):
                mean = (tot / cnt).astype(np.float32)  # NaN where a part was never seen
            self.mean[pid] = mean
            fill = np.where(np.isfinite(mean), mean, self.players[pid]["tint"])
            never = np.broadcast_to(fill[None, :, None], (n_f, len(PARTS), NV * NU, 3))
            out = np.where((src >= 0)[..., None], filled, never.reshape(n_f, -1, 3))
            self.atlas[pid] = out.reshape(at.shape).astype(np.uint8)

    def draw(self, canvas: np.ndarray, view: View, f: int, frame: np.ndarray, pid: str,
             masks, opacity: float = 1.0) -> bool:  # fmt: skip
        """Ray-cast player `pid` at frame `f` into `canvas`. False if it has no pose."""
        caps = self.frame_caps(pid, f)
        if caps is None or pid not in self.atlas:
            return False
        a, b, r, _, _ = caps
        ends = np.vstack([a, b])
        dep = view.depth(ends)
        if (dep < 0.3).any():
            return False
        uv = view.project(ends)
        rad = np.concatenate([r, r]) * view.k[0, 0] / dep
        lo = np.floor((uv - rad[:, None]).min(0)).astype(int)
        hi = np.ceil((uv + rad[:, None]).max(0)).astype(int)
        hh, ww = canvas.shape[:2]
        x0, y0, x1, y1 = max(0, lo[0]), max(0, lo[1]), min(ww, hi[0]), min(hh, hi[1])
        if x1 <= x0 or y1 <= y0:
            return True
        step = max(1, int(np.sqrt((x1 - x0) * (y1 - y0) / 60000)))
        xs, ys = np.meshgrid(np.arange(x0, x1, step) + step / 2,
                             np.arange(y0, y1, step) + step / 2)  # fmt: skip
        pix = np.column_stack([xs.ravel(), ys.ravel(), np.ones(xs.size)])
        d = _unit(pix @ np.linalg.inv(view.k).T @ view.r)
        o = view.centre[None]
        t = ray_capsules(o, d, a, b, r)
        k = t.argmin(1)
        tm = t[np.arange(len(t)), k]
        hit = np.isfinite(tm)
        col = np.zeros((len(t), 3), np.float32)
        if hit.any():
            p = o + d[hit] * tm[hit, None]
            kk = k[hit]
            n, u, v = _surface(caps, kk, p)
            # history: the atlas, bilinear (wrapping round the part)
            at = self.atlas[pid][min(f, len(self.atlas[pid]) - 1)].astype(np.float32)
            u0, v0 = np.floor(u).astype(int), np.clip(np.floor(v), 0, NV - 1).astype(int)
            fu, fv = (u - u0)[:, None], np.clip(v - v0, 0, 1)[:, None]
            v1 = np.minimum(v0 + 1, NV - 1)
            u0w, u1w = u0 % NU, (u0 + 1) % NU
            hist = ((at[kk, v0, u0w] * (1 - fu) + at[kk, v0, u1w] * fu) * (1 - fv)
                    + (at[kk, v1, u0w] * (1 - fu) + at[kk, v1, u1w] * fu) * fv)  # fmt: skip
            shade = 0.8 + 0.2 * np.clip(n @ LIGHT, -1, 1)
            hist *= shade[:, None]
            got = masks.get(pid, f)
            if got is not None:  # now: the real camera's pixel where it sees this point
                m = cv2.erode(got[1].astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
                w, px = self._seen(caps, kk, p, n, got[0], m)
                if (w > 0).any():
                    hist = _sample(frame, px) * w[:, None] + hist * (1 - w[:, None])
            col[hit] = hist
        gh, gw = xs.shape
        img = col.reshape(gh, gw, 3)
        alpha = hit.reshape(gh, gw).astype(np.float32)
        if step > 1:
            img = cv2.resize(img, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
            alpha = cv2.resize(alpha, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
        else:
            img, alpha = img[: y1 - y0, : x1 - x0], alpha[: y1 - y0, : x1 - x0]
        alpha = cv2.GaussianBlur(alpha, (0, 0), 0.6)[..., None] * opacity
        roi = canvas[y0:y1, x0:x1]
        roi[:] = (img * alpha + roi * (1 - alpha)).astype(np.uint8)
        return True


def build(doc: dict, joints, real: View, k1: float, src_size, tints, video, h, masks,
          n: int, feet: dict | None = None) -> Proxy:  # fmt: skip
    """A play's proxies with their atlases (one pass over the play's frames); `feet`:
    pid -> (F, 2) tracked foot points the bodies stand on."""
    from ..virtual.replays import read_window

    px = Proxy(doc, joints, real, k1, src_size, tints)
    px.feet = feet or {}
    for f, (_, frame) in enumerate(read_window(video, h["t_start"], n)):
        px.observe(f, frame, masks)
    px.finish()
    return px
