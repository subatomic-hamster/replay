"""Tier D experiment A, CPU half: render MoGe-2 point clouds from virtual cameras, next
to Tier B on the very same views.

* static scene = the plate's point map (subsampled 2x), with points MoGe puts within
  `SNAP_M` of the floor snapped onto the exact calibrated plane (removes floor ripple);
* players = the per-frame lifted SAM-masked pixels from `pointmaps.py`;
* both are drawn as z-buffered square splats sized by each point's source footprint,
  then small holes are filled by normalised blur; the void stays Tier B's backdrop colour.

`TierB` re-runs the production Tier B drawing (`replay_render.virtual.tierb`) for an
arbitrary `View`, so both tiers see identical cameras. CLI: side-by-side MP4 along the
production camera paths (`orbit`, `broadcast_high`) + a still sheet.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from courtcam.profiles import load_profile
from courtcam.render import open_encoder
from geom import camera, floor_depth, to_world
from replay_render.gamedata import load_tracks
from replay_render.virtual import tierb as B
from replay_render.virtual.replays import frame_count, play, probe_video, read_window
from replay_render.virtual.segment import Masks

SNAP_M = 0.15
ANCHOR_Z_M = 0.9  # hybrid: a player cloud's median depth is put at its tracked point at this height
MAX_R = 2  # splat half-size cap, px


def splat(xyz, rgb, foot_m, view: B.View, size) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-buffered square splats. Returns (BGR image, depth (inf = empty), winner index or -1)."""
    w, h = size
    d = view.depth(xyz)
    keep = np.nonzero(d > B.NEAR_M)[0]
    d = d[keep]
    uv = view.project(xyz[keep])
    rad = np.clip(np.rint(0.5 * foot_m[keep] * view.k[0, 0] / d), 0, MAX_R).astype(np.int8)
    u, v = np.rint(uv[:, 0]).astype(np.int64), np.rint(uv[:, 1]).astype(np.int64)
    pix, dep, src = [], [], []
    for dy in range(-MAX_R, MAX_R + 1):
        for dx in range(-MAX_R, MAX_R + 1):
            s = np.nonzero(rad >= max(abs(dx), abs(dy)))[0]
            uu, vv = u[s] + dx, v[s] + dy
            inb = (uu >= 0) & (uu < w) & (vv >= 0) & (vv < h)
            pix.append(vv[inb] * w + uu[inb])
            dep.append(d[s[inb]])
            src.append(s[inb])
    pix, dep, src = np.concatenate(pix), np.concatenate(dep), np.concatenate(src)
    order = np.lexsort((dep, pix))  # by pixel, nearest first
    pix, dep, src = pix[order], dep[order], src[order]
    first = np.r_[True, pix[1:] != pix[:-1]]
    pix, dep, src = pix[first], dep[first], keep[src[first]]
    img = np.zeros((h * w, 3), np.uint8)
    img[pix] = rgb[src]
    zb = np.full(h * w, np.inf)
    zb[pix] = dep
    idx = np.full(h * w, -1, np.int64)
    idx[pix] = src
    return img.reshape(h, w, 3), zb.reshape(h, w), idx.reshape(h, w)


def fill_holes(img: np.ndarray, filled: np.ndarray, k: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """One pass of normalised box blur into empty pixels with >= 40 % filled neighbours."""
    f = filled.astype(np.float32)
    den = cv2.blur(f, (k, k))
    num = cv2.blur(img.astype(np.float32) * f[..., None], (k, k))
    hole = ~filled & (den > 0.4)
    out = img.copy()
    out[hole] = (num[hole] / den[hole, None]).astype(np.uint8)
    return out, filled | hole


class TierD:
    """Plate cloud + per-frame player clouds from a `pointmaps.py` npz.

    `hybrid=True`: every plate point whose MoGe normal is vertical (|n_z| > 0.9) and
    which sits below 0.6 m is put on the calibrated floor plane (Tier B's floor, MoGe
    only for what stands up: hoop, posts, net, walls), and `render(anchors=...)` slides
    each player cloud along the real camera's rays (scales its depth) until its median
    depth is that of the tracked foot point raised to ANCHOR_Z_M."""

    def __init__(self, npz: Path, hybrid: bool = False) -> None:
        z = np.load(npz)
        self.meta = json.loads(str(z["meta"]))
        gd = Path(self.meta["game_dir"])
        cal = json.loads((gd / "calibration.json").read_text())
        k, r, t = camera(cal)
        size = tuple(self.meta["size"])
        plate = cv2.imread(str(gd / "plate" / "plate.jpg"))
        d = z["plate_depth"].astype(np.float64) * self.meta["plate"]["scale"]
        vs, us = np.mgrid[0 : size[1] : 2, 0 : size[0] : 2]
        vs, us = vs.ravel(), us.ravel()
        dd = d[vs, us]
        ok = np.isfinite(dd)
        vs, us, dd = vs[ok], us[ok], dd[ok]
        xyz = to_world(us, vs, dd, k, r, t)
        df = floor_depth(k, r, t, size)[vs, us]
        snap = np.abs(xyz[:, 2]) < SNAP_M
        if hybrid:
            nz = np.abs(z["plate_normal_z"].astype(np.float64)[vs, us])
            snap |= (nz > 0.9) & (xyz[:, 2] < 0.6)
        snap &= np.isfinite(df)
        xyz[snap] = to_world(us[snap], vs[snap], df[snap], k, r, t)
        dd[snap] = df[snap]
        self.plate_xyz, self.plate_rgb = xyz, plate[vs, us]
        self.plate_foot = 2.0 * dd / k[0, 0]
        self.snapped = float(snap.mean())
        self.frames = z["frames"]
        self.pts, self.rgb, self.who, self.when = z["pts"], z["rgb"], z["who"], z["when"]
        self.f_src = k[0, 0]
        self.cam_depth = (self.pts.astype(np.float64) @ r.T + t)[:, 2]
        self.r, self.t, self.c = r, t, -r.T @ t

    def frame_index(self, f: int) -> int | None:
        i = np.searchsorted(self.frames, f)
        return int(i) if i < len(self.frames) and self.frames[i] == f else None

    def render(
        self, view: B.View, f: int, size, anchors: dict | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """(BGR, player mask) of play frame `f` (must be a processed frame).
        `anchors`: {pid: court xy} to re-seat each player cloud on its tracked foot point."""
        i = self.frame_index(f)
        sel = np.nonzero(self.when == i)[0]
        pts = self.pts[sel].astype(np.float64)
        for pid, xy in (anchors or {}).items():
            if pid in self.meta["pids"] and np.isfinite(xy).all():
                m = self.who[sel] == self.meta["pids"].index(pid)
                if m.any():  # slide along the real camera's rays: the source view is unchanged
                    target = float((np.r_[xy, ANCHOR_Z_M] @ self.r.T + self.t)[2])
                    s = target / float(np.median(self.cam_depth[sel][m]))
                    pts[m] = self.c + (pts[m] - self.c) * s
        xyz = np.vstack([self.plate_xyz, pts])
        rgb = np.vstack([self.plate_rgb, self.rgb[sel]])
        foot = np.r_[self.plate_foot, self.cam_depth[sel] / self.f_src]
        img, zb, idx = splat(xyz, rgb, foot, view, size)
        filled = np.isfinite(zb)
        player = idx >= len(self.plate_xyz)
        img, filled = fill_holes(img, filled)
        out = np.where(filled[..., None], img, B.background(size))
        return out, player


class TierB:
    """The production Tier B drawing (`tierb.render_angle`'s loop body) for any View."""

    def __init__(self, gd: Path, play_id: str) -> None:
        self.gd = gd = Path(gd)
        self.h = h = play(gd, play_id)
        cal = json.loads((gd / "calibration.json").read_text())
        meta = json.loads((gd / "plate" / "plate.json").read_text())
        self.floor = cv2.imread(str(gd / "plate" / meta["floor"]["file"]))
        self.wall = cv2.imread(str(gd / "plate" / meta["backdrop"]["file"]))
        self.video = gd / "media" / "wide.mp4"
        info = probe_video(self.video)
        self.src_size, self.fps = (info["width"], info["height"]), info["fps"]
        self.n = frame_count(h, self.fps)
        times = h["t_start"] + np.arange(self.n) / self.fps
        tracks = load_tracks(gd, *self.src_size)
        self.ids = tracks.ids
        self.court = tracks.at(tracks.court, times)
        self.masks = Masks(gd, play_id)
        self.real = B._real_view(cal)
        assert np.linalg.det(self.real.r) > 0, "mirrored calibrations are not handled here"
        focus = [
            tracks.index(p) for p in h.get("participants") or [] if tracks.index(p) is not None
        ]
        c = B.play_centre(self.court, focus, self.fps)
        fx0, fy0, fx1, fy1 = meta["floor"]["bounds_m"]
        c[:, 0] = np.clip(c[:, 0], fx0 + 2.5, fx1 - 2.5)
        c[:, 1] = np.clip(c[:, 1], fy0 + 2.5, fy1 - 2.5)
        with np.errstate(all="ignore"):
            ext = np.nanmax(self.court, axis=0) - np.nanmin(self.court, axis=0)
        self.spread = float(np.nanmedian(ext.max(axis=1))) if np.isfinite(ext).any() else 10.0
        self.centre = c
        fl = meta["floor"]
        ppm = fl["px_per_m"]
        x0, _, _, y1 = fl["bounds_m"]
        self.f_plane = (np.array([x0 + 0.5 / ppm, y1 - 0.5 / ppm, 0.0]),
                        np.array([1 / ppm, 0, 0.0]), np.array([0, -1 / ppm, 0.0]))  # fmt: skip
        bd = meta["backdrop"]
        bppm, along = bd["px_per_m"], np.asarray(bd["along"], np.float64)
        b_origin = (
            np.asarray(bd["origin_m"], np.float64)
            + along * 0.5 / bppm
            + B.EZ * (bd["height_m"] - 0.5 / bppm)
        )
        self.b_plane = (b_origin, along / bppm, -B.EZ / bppm)
        tpl = load_profile(cal["sport"]).template(cal.get("variant"))
        self.rims = [tuple(r) for r in (tpl.rims or ([tpl.rim] if tpl.rim else []))]
        self.baselines = (float(tpl.polygon[:, 1].min()), float(tpl.polygon[:, 1].max()))
        from courtcam.calibrate import height_landmarks

        hl = height_landmarks(tpl)
        self.net = [hl["net_top_l"], hl["net_top_r"]] if "net_top_l" in hl else None
        self.billboard = B.Billboard(self.real, 0.0, self.src_size)

    def anchors(self, f: int) -> dict:
        return {pid: self.court[p, f] for p, pid in enumerate(self.ids)}

    def path(self, angle: str, size) -> list[B.View]:
        return B.camera_path(angle, self.real, self.src_size, self.centre, self.spread, size)

    def render(
        self, view: B.View, f: int, frame: np.ndarray, size
    ) -> tuple[np.ndarray, np.ndarray]:
        """(BGR, player alpha mask) — no ball (Tier D has none either)."""
        canvas = B.background(size)
        B.draw_plane(canvas, self.wall, view, *self.b_plane)
        B.draw_plane(canvas, self.floor, view, *self.f_plane)
        people = []
        for p, pid in enumerate(self.ids):
            if not np.isfinite(self.court[p, f, 0]):
                continue
            m = self.masks.get(pid, f)
            if m is not None:
                foot = np.array([*self.court[p, f], 0.0])
                people.append((float(view.depth(foot + 0.9 * B.EZ)[0]), foot, m))
        for _, foot, _ in people:
            B.draw_shadow(canvas, view, foot)
        if self.rims:
            B.draw_hoops(canvas, view, self.rims, self.baselines)
        people.sort(key=lambda q: -q[0])
        net_d = float(view.depth(np.mean(self.net, axis=0, keepdims=True))[0]) if self.net else -1.0
        alpha = np.zeros((size[1], size[0], 3), np.uint8)
        white = np.full_like(frame, 255)
        for i, (d, foot, (xy0, m)) in enumerate(people):
            if self.net and d <= net_d and (i == 0 or people[i - 1][0] > net_d):
                B.draw_net(canvas, view, self.net)
            self.billboard.draw(canvas, view, frame, foot, xy0, m)
            self.billboard.draw(alpha, view, white, foot, xy0, m)
        if self.net and (not people or people[-1][0] > net_d):
            B.draw_net(canvas, view, self.net)
        return canvas, alpha[..., 0] > 127


def caption(img: np.ndarray, text: str, sub: str = "") -> None:
    cv2.rectangle(img, (0, 0), (img.shape[1], 40 if sub else 24), (12, 10, 9), -1)
    cv2.putText(img, text, (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1, cv2.LINE_AA)
    if sub:
        cv2.putText(
            img, sub, (8, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1, cv2.LINE_AA
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Tier B | Tier D side-by-side along Tier B paths")
    ap.add_argument("npz", type=Path)
    ap.add_argument("--angles", default="orbit,broadcast_high")
    ap.add_argument("--out", type=Path, required=True, help="output stem")
    ap.add_argument("--tag", default="", help="e.g. SYNTHETIC or 'CC BY 3.0 pickleball4you'")
    a = ap.parse_args()
    d = TierD(a.npz)
    dh = TierD(a.npz, hybrid=True)
    b = TierB(Path(d.meta["game_dir"]), d.meta["play_id"])
    size = (640, 360)
    stills = []
    a.out.parent.mkdir(parents=True, exist_ok=True)
    for angle in a.angles.split(","):
        views = b.path(angle, size)
        enc = open_encoder(
            a.out.with_name(f"{a.out.name}_{angle}.mp4"),
            (3 * size[0], size[1]),
            b.fps / d.meta["stride"],
        )
        pick = {d.frames[int(q * (len(d.frames) - 1))] for q in (0.3, 0.75)}
        try:
            for f, (_, frame) in enumerate(read_window(b.video, b.h["t_start"], b.n)):
                if d.frame_index(f) is None:
                    continue
                tb, _ = b.render(views[f], f, frame, size)
                td, _ = d.render(views[f], f, size)
                th, _ = dh.render(views[f], f, size, anchors=b.anchors(f))
                caption(tb, f"TIER B 2.5D | {angle}", a.tag)
                caption(td, f"TIER D EXPERIMENT | MoGe-2 point splats | {angle}", a.tag)
                caption(th, f"TIER D HYBRID | plane floor + anchored MoGe | {angle}", a.tag)
                row = np.hstack([tb, td, th])
                enc.stdin.write(np.ascontiguousarray(row).tobytes())
                if f in pick:
                    stills.append(row)
        finally:
            enc.stdin.close()
            enc.wait()
    cv2.imwrite(
        str(a.out.with_name(f"{a.out.name}_sheet.jpg")),
        np.vstack(stills),
        [cv2.IMWRITE_JPEG_QUALITY, 85],
    )
    print(
        json.dumps(
            {
                "snapped_floor_fraction": d.snapped,
                "hybrid_snapped": dh.snapped,
                "stills": len(stills),
            }
        )
    )  # ttsr-ignore: py/no-print (CLI)


if __name__ == "__main__":
    main()
