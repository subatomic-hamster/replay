"""Broadcast compositor: cuts.json + the wide source -> one H.264 "broadcast" rendition.

Per output frame: pick the cut, map rendition time to source time (live: the same;
replay: `src_t_start + (t - t_start) * speed`, frames repeated for slow motion), crop the
camera's window out of the wide source, draw the telestrator (replays), the graphics
package and the replay sting, and pipe BGR frames to ffmpeg. Audio is mixed separately
(audio.py) and muxed at the end.
"""

from __future__ import annotations

import bisect
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from . import audio as audio_mod
from . import camera as cam
from .gamedata import Game, load_game, read_json
from .graphics import ACCENT, Package, glow_polyline, spotlight, trail

STING_S = 0.7
EASE_S = 0.9


class FrameSource:
    """Sequential decode with seeking for replays (OpenCV, CFR mezzanine)."""

    def __init__(self, path: Path):
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise FileNotFoundError(f"cannot open {path}")
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1 << 30
        self.i = -1
        self.frame: np.ndarray | None = None

    def get(self, i: int) -> np.ndarray:
        i = int(min(max(i, 0), self.n - 1))
        if i == self.i and self.frame is not None:
            return self.frame
        if i < self.i or i > self.i + 45:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            self.i = i - 1
        while self.i < i:
            ok, f = self.cap.read()
            if not ok:
                break
            self.i += 1
            self.frame = f
        if self.frame is None:
            raise RuntimeError("no frames decoded")
        return self.frame

    def close(self) -> None:
        self.cap.release()


# --------------------------------------------------------------------------- cameras


class Cameras:
    """Smoothed windows for every live camera on the source clock at `fps`, and per-
    replay windows on the rendition clock."""

    def __init__(self, game: Game, fps: float, out_w: int):
        self.g, self.fps = game, fps
        self.W, self.H = game.width, game.height
        self.w_max = min(float(self.W), self.H * cam.ASPECT)
        poly = np.asarray(game.calib.get("court_polygon_px") or [], dtype=np.float64)
        if len(poly):
            xs = np.clip(poly[:, 0], 0, self.W)
            self.w_wide = float(np.clip((xs.max() - xs.min()) * 1.08, 0.5 * self.w_max,
                                        self.w_max))  # fmt: skip
        else:
            self.w_wide = self.w_max
        self.min_w = min(max(out_w / 3.0, 0.3 * self.w_wide), self.w_max)
        n = int(np.ceil(game.duration * fps)) + 1
        self.t = np.arange(n) / fps
        self.box = game.tracks.at(game.tracks.box, self.t) if len(game.tracks.t) else None
        self.court = game.tracks.at(game.tracks.court, self.t) if len(game.tracks.t) else None
        self.paths: dict[str, np.ndarray] = {}
        self.raw: dict[str, np.ndarray] = {}

    def _fill(self, raw: np.ndarray, default: np.ndarray) -> np.ndarray:
        """Hold the last finite target through gaps; start at the first one."""
        ok = np.isfinite(raw).all(axis=1)
        if not ok.any():
            return np.tile(default, (len(raw), 1))
        idx = np.where(ok, np.arange(len(raw)), 0)
        np.maximum.accumulate(idx, out=idx)
        out = raw[idx]
        out[: int(np.argmax(ok))] = raw[int(np.argmax(ok))]
        return out

    def _raw_wide(self) -> np.ndarray:
        centre = np.array([self.W / 2, self.H / 2, self.w_wide])
        if self.box is None:
            return np.tile(centre, (len(self.t), 1))
        cx = (self.box[..., 0] + self.box[..., 2]) / 2
        with np.errstate(all="ignore"):
            x = np.nanmedian(cx, axis=0)
            y = np.nanmedian((self.box[..., 1] + self.box[..., 3]) / 2, axis=0)
        raw = np.column_stack([x, y, np.full(len(x), self.w_wide)])
        return self._fill(raw, centre)

    def _raw_tight(self) -> np.ndarray:
        """Ball-side framing without a ball: the players within 8 m of the on-court
        centroid (drops the lone back defender), boxed with headroom."""
        centre = np.array([self.W / 2, self.H / 2, self.w_wide])
        if self.box is None:
            return np.tile(centre, (len(self.t), 1))
        raw = np.full((len(self.t), 3), np.nan)
        for k in range(len(self.t)):
            b, c = self.box[:, k], self.court[:, k]
            ok = np.isfinite(b).all(axis=1) & np.isfinite(c).all(axis=1)
            if not ok.any():
                continue
            b, c = b[ok], c[ok]
            near = np.linalg.norm(c - np.median(c, axis=0), axis=1) < 8.0
            if near.sum() >= 2:
                b = b[near]
            x0, y0 = b[:, 0].min(), b[:, 1].min()
            x1, y1 = b[:, 2].max(), b[:, 3].max()
            w = max((x1 - x0) * 1.35, (y1 - y0) * 1.6 * cam.ASPECT)
            raw[k] = ((x0 + x1) / 2, (y0 + y1) / 2, w)
        return self._fill(raw, centre)

    def _clamp_raw(self, raw: np.ndarray, min_w: float) -> np.ndarray:
        return np.asarray([cam.fit_window(*r, self.W, self.H, min_w) for r in raw])

    def live(self, name: str) -> np.ndarray:
        if name in self.paths:
            return self.paths[name]
        if name == "wide":
            raw = self._clamp_raw(self._raw_wide(), self.w_wide)
            path = cam.smooth(raw, cam.WIDE_FEEL, self.fps, self.W, self.H, self.w_wide)
        elif name.startswith("follow:"):
            raw = path = self._follow(name.split(":", 1)[1])
        else:  # "tight" (and a live "tight:<pid>" falls back to the team framing)
            raw = self._clamp_raw(self._raw_tight(), self.min_w)
            path = cam.smooth(raw, cam.TIGHT_FEEL, self.fps, self.W, self.H, self.min_w)
        self.raw[name], self.paths[name] = raw, path
        return path

    def _follow(self, pid: str) -> np.ndarray:
        """courtcam's follow-cam path (crops/<pid>.json) — the same window the TV's
        follow mode shows — resampled to the render clock."""
        got = self.g.crop_rects(pid)
        if got is None:
            return self.live("tight")
        rects, rate = got
        idx = np.clip(np.round(self.t * rate).astype(int), 0, len(rects) - 1)
        return np.asarray([cam.from_rect_norm(r, self.W, self.H) for r in rects[idx]])

    def replay(self, cut: dict, n: int) -> np.ndarray:
        """Window for each of the replay's `n` output frames: the key player plus the
        shot's release and rim points, spring-smoothed on the rendition clock."""
        rp = cut["replay"]
        src = rp["src_t_start"] + np.arange(n) / self.fps * rp["speed"]
        pid = rp.get("player_id")
        i = self.g.tracks.index(pid) if pid else None
        boxes = (
            self.g.tracks.at(self.g.tracks.box[i : i + 1], src)[0]
            if i is not None
            else np.full((n, 4), np.nan)
        )
        extra = []
        arc = rp.get("shot_arc")
        if arc and self.g.projector is not None:
            extra = self.g.projector.project(np.asarray([arc["from"], arc["to"]]))
        raw = np.full((n, 3), np.nan)
        for k in range(n):
            pts = []
            if np.isfinite(boxes[k]).all():
                pts += [boxes[k, :2], boxes[k, 2:]]
            pts += list(extra)
            if not pts:
                continue
            p = np.asarray(pts)
            x0, y0 = p.min(axis=0)
            x1, y1 = p.max(axis=0)
            w = max((x1 - x0) * 1.3, (y1 - y0) * 1.45 * cam.ASPECT, self.min_w * 0.9)
            raw[k] = ((x0 + x1) / 2, (y0 + y1) / 2, w)
        tight = self.live("tight")
        start = tight[min(round(rp["src_t_start"] * self.fps), len(tight) - 1)]
        raw = self._clamp_raw(self._fill(raw, start), self.min_w * 0.9)
        return cam.smooth(raw, cam.REPLAY_FEEL, self.fps, self.W, self.H, self.min_w * 0.9)


# --------------------------------------------------------------------------- drawing


def crop(frame: np.ndarray, win: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    cx, cy, w = (float(v) for v in win)
    h = w * out_h / out_w  # the window has the output's aspect (16:9, or 9:16 vertical)
    s = out_w / w
    if s < 0.8:  # big downscale: area filter, integer crop
        x0, y0 = round(cx - w / 2), round(cy - h / 2)
        sub = frame[max(y0, 0) : y0 + round(h), max(x0, 0) : x0 + round(w)]
        return cv2.resize(sub, (out_w, out_h), interpolation=cv2.INTER_AREA)
    m = np.float32([[s, 0, -(cx - w / 2) * s], [0, s, -(cy - h / 2) * s]])
    return cv2.warpAffine(frame, m, (out_w, out_h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)  # fmt: skip


def _to_out(px: np.ndarray, win: np.ndarray, out_w: int) -> np.ndarray:
    cx, cy, w = win
    h = w / cam.ASPECT
    return (np.asarray(px, dtype=np.float64) - [cx - w / 2, cy - h / 2]) * (out_w / w)


def _circle(c: np.ndarray, r: float, n: int = 40) -> np.ndarray:
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([c[0] + r * np.cos(a), c[1] + r * np.sin(a)])


def _arc_points(arc: dict, s_max: float, n: int = 48) -> np.ndarray:
    s = np.linspace(0.0, s_max, max(2, int(n * s_max) + 2))
    a, b = np.asarray(arc["from"]), np.asarray(arc["to"])
    xyz = a[None] + (b - a)[None] * s[:, None]
    mid = (a[2] + b[2]) / 2
    xyz[:, 2] = a[2] + (b[2] - a[2]) * s + 4 * (arc.get("apex_z", mid + 1) - mid) * s * (1 - s)
    return xyz


def telestrate(frame, game: Game, rp: dict, src_t: float, win, out_w: int, scale: float):
    proj = game.projector
    if proj is None:
        return
    pid = rp.get("player_id")
    i = game.tracks.index(pid) if pid else None
    width = max(2, round(5 * scale))
    if i is not None:
        hist = np.arange(max(src_t - 2.5, rp["src_t_start"] - 1.0), src_t + 1e-6, 0.1)
        ct = game.tracks.at(game.tracks.court[i : i + 1], hist)[0]
        ct = ct[np.isfinite(ct).all(axis=1)]
        if len(ct) >= 2:
            trail(frame, _to_out(proj.ground(ct), win, out_w), ACCENT, width)
        if len(ct):
            pulse = 0.5 + 0.5 * np.sin(src_t * 2 * np.pi * 1.5)
            spotlight(
                frame,
                _to_out(proj.ground(_circle(ct[-1], 0.75)), win, out_w),
                _to_out(proj.ground(_circle(ct[-1], 0.75 + 0.25 * pulse)), win, out_w),
                ACCENT,
                float(pulse),
            )
    for p in rp.get("passes") or []:
        fade = 1.0 - (src_t - p["t1"]) / 1.0  # gone a second after the catch
        if src_t >= p["t0"] and fade > 0:
            u = min(1.0, (src_t - p["t0"]) / max(p["t1"] - p["t0"], 1e-3))
            pts = _arc_points({**p, "apex_z": 1.8}, u, 24)
            glow_polyline(frame, _to_out(proj.project(pts), win, out_w), (90, 200, 255),
                          max(2, width - 1), alpha=min(1.0, fade))  # fmt: skip
    arc = rp.get("shot_arc")
    if arc and src_t >= arc["t_release"]:
        u = min(1.0, (src_t - arc["t_release"]) / max(arc["t_rim"] - arc["t_release"], 1e-3))
        pts = _to_out(proj.project(_arc_points(arc, u)), win, out_w)
        glow_polyline(frame, pts, ACCENT, width)
        if u < 1.0:
            cv2.circle(frame, tuple(int(v) for v in pts[-1]), max(4, 2 * width), (255, 255, 255),
                       -1, cv2.LINE_AA)  # fmt: skip
        elif arc.get("made"):
            rim = _to_out(proj.project(np.asarray([arc["to"]])), win, out_w)[0]
            k = min(1.0, (src_t - arc["t_rim"]) / 0.6)
            cv2.circle(frame, tuple(int(v) for v in rim), int(width * (3 + 6 * k)), ACCENT[::-1],
                       max(2, width // 2), cv2.LINE_AA)  # fmt: skip


def _score_at(score: list[dict], t: float) -> tuple[tuple[int, int], tuple[int, float] | None]:
    cur, flash, prev = (0, 0), None, (0, 0)
    for s in score:
        if s["t"] > t:
            break
        prev, cur = cur, (int(s["scores"][0]), int(s["scores"][1]))
        dt = t - s["t"]
        flash = (0 if cur[0] != prev[0] else 1, 1.0 - dt / 1.5) if dt < 1.5 else None
    return cur, flash


# --------------------------------------------------------------------------- render


def _encoder(out: Path, size: tuple[int, int], fps: float, crf: int) -> subprocess.Popen:
    from courtcam.ingest import h264_args, h264_encoder

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH")
    enc = h264_encoder()
    vargs = (
        ["-c:v", enc, "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p"]
        if enc == "libx264"
        else h264_args(crf=crf)
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{size[0]}x{size[1]}", "-r", f"{fps:g}", "-i", "-", *vargs, str(out)]  # fmt: skip
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def render(
    game_dir: Path,
    out_path: Path,
    *,
    cuts_path: Path | None = None,
    size: tuple[int, int] = (1920, 1080),
    t0: float = 0.0,
    t1: float | None = None,
    fps: float = 30.0,
    crf: int = 20,
    audio_bitrate: str = "128k",
    narration: Path | None = None,
    source: Path | None = None,
    label: str | None = None,
    progress: Callable[[float], None] | None = None,
) -> dict:
    """Render [t0, t1) of the rendition (source seconds) to `out_path` (MP4, H.264+AAC)."""
    gd = Path(game_dir)
    doc = read_json(cuts_path or gd / "cuts.json")
    if not doc:
        raise FileNotFoundError(f"no cuts.json in {gd}")
    game = load_game(gd)
    src_path = source or gd / "media" / "wide.mp4"
    t1 = min(t1 if t1 is not None else game.duration, game.duration)
    out_w, out_h = size
    cuts = doc["cuts"]
    starts = [c["t_start"] for c in cuts]
    gfx = doc.get("graphics") or {}
    pkg = Package(out_w, out_h, gfx.get("teams") or [
        {"label": "HOME", "color": "#1F6FEB"}, {"label": "AWAY", "color": "#E5484D"}])  # fmt: skip
    cams = Cameras(game, fps, out_w)
    replay_paths: dict[int, np.ndarray] = {}
    boundaries = [(c["t_start"], c) for c in cuts if c["kind"] == "replay"] + [
        (c["t_end"], c) for c in cuts if c["kind"] == "replay"
    ]
    lower = gfx.get("lower_thirds") or []
    score = gfx.get("score") or []
    src = FrameSource(src_path)
    tmp_video = out_path.with_suffix(".video.mp4")
    proc = _encoder(tmp_video, size, fps, crf)
    assert proc.stdin is not None
    n_out = round((t1 - t0) * fps)
    started = time.time()
    try:
        for k in range(n_out):
            t = t0 + k / fps
            ci = max(0, bisect.bisect_right(starts, t + 1e-9) - 1)
            cut = cuts[ci]
            li = min(round(t * fps), len(cams.t) - 1)
            if cut["kind"] == "replay":
                rp = cut["replay"]
                if ci not in replay_paths:
                    n = int(np.ceil((cut["t_end"] - cut["t_start"]) * fps)) + 2
                    replay_paths[ci] = cams.replay(cut, n)
                j = min(round((t - cut["t_start"]) * fps), len(replay_paths[ci]) - 1)
                win = replay_paths[ci][j]
                src_t = rp["src_t_start"] + (t - cut["t_start"]) * rp["speed"]
            else:
                win = cams.live(cut["camera"])[li]
                into = t - cut["t_start"]
                if cut.get("transition") == "ease" and ci > 0 and into < EASE_S:
                    prev = cams.live(cuts[ci - 1]["camera"])[li]
                    win = cam.blend(prev, win, into / EASE_S)
                src_t = t
            frame = crop(src.get(round(src_t * game.fps)), win, out_w, out_h)
            if cut["kind"] == "replay":
                telestrate(frame, game, cut["replay"], src_t, win, out_w, pkg.s)
            sc, flash = _score_at(score, t)
            pkg.draw_score_bug(frame, sc, f"{int(t) // 60:02d}:{int(t) % 60:02d}", flash)
            stinging = [(b, c) for b, c in boundaries if abs(t - b) < STING_S / 2]
            if not stinging:
                pkg.draw_bug(frame, "replay" if cut["kind"] == "replay" else "live")
            if cut["kind"] == "live":
                for l3 in lower:
                    if l3["t_start"] <= t < l3["t_end"]:
                        pkg.draw_lower_third(frame, l3, t)
            if label:
                pkg.draw_label(frame, label)
            for b, c in stinging:
                team = 0
                ev_pid = (c.get("replay") or {}).get("player_id")
                if ev_pid:
                    team = int((game.players.get(ev_pid) or {}).get("team") or 0)
                pkg.draw_sting(frame, (t - (b - STING_S / 2)) / STING_S, team)
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
            if progress and k % 30 == 0:
                progress(0.9 * k / max(n_out, 1))
    finally:
        src.close()
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed encoding the broadcast video")
    wall = time.time() - started
    replays = [(c["t_start"], c["t_end"]) for c in cuts if c["kind"] == "replay"]
    mix = audio_mod.mix(src_path, t0, t1, replays, narration=narration)
    wav = out_path.with_suffix(".mix.wav")
    audio_mod.write_wav(wav, mix)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(tmp_video), "-i", str(wav), "-c:v", "copy",
         "-c:a", "aac", "-b:a", audio_bitrate, "-shortest", "-movflags", "+faststart", str(out_path)],
        check=True,
    )  # fmt: skip
    tmp_video.unlink(missing_ok=True)
    wav.unlink(missing_ok=True)
    if progress:
        progress(1.0)
    return {
        "frames": n_out,
        "seconds": round(t1 - t0, 3),
        "render_wall_s": round(wall, 2),
        "render_fps": round(n_out / max(wall, 1e-6), 2),
        "size": [out_w, out_h],
        "replays": len([r for r in replays if r[1] > t0 and r[0] < t1]),
    }


def render_segments(
    source: Path,
    segments: list[tuple[float, float]],
    out_path: Path,
    *,
    size: tuple[int, int],
    fps: float,
    window: Callable[[int, float], np.ndarray],
    draw: Callable[[np.ndarray, int, float], None] | None = None,
    crf: int = 23,
    audio_bitrate: str = "128k",
    progress: Callable[[float], None] | None = None,
) -> dict:
    """Source segments [(a, b), ...] (seconds) back to back into one H.264 + AAC MP4 at
    the source frame rate: each output frame is `window(i, t)` ([cx, cy, w] in source px,
    the output's aspect) cut from the source at time t of segment i, then `draw(frame, i,
    t)` overlays graphics. The audio is the same segments, with 15 ms fades at the joins.
    Used by the condensed game and the vertical share export."""
    out_path = Path(out_path)
    src = FrameSource(source)
    counts = [max(1, round((b - a) * fps)) for a, b in segments]
    tmp_video = out_path.with_suffix(".video.mp4")
    proc = _encoder(tmp_video, size, fps, crf)
    assert proc.stdin is not None
    total, done = sum(counts), 0
    started = time.time()
    try:
        for i, ((a, _), n) in enumerate(zip(segments, counts, strict=True)):
            for k in range(n):
                t = a + k / fps
                frame = crop(src.get(round(t * fps)), window(i, t), *size)
                if draw:
                    draw(frame, i, t)
                proc.stdin.write(np.ascontiguousarray(frame).tobytes())
                done += 1
                if progress and done % 60 == 0:
                    progress(0.9 * done / total)
    finally:
        src.close()
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed encoding segments")
    wall = time.time() - started
    fade = int(0.015 * audio_mod.SR)
    ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
    parts = []
    for (a, _), n in zip(segments, counts, strict=True):
        part = audio_mod.read_audio(Path(source), a, n / fps)
        if len(part) > 2 * fade:
            part[:fade] *= ramp
            part[-fade:] *= ramp[::-1]
        parts.append(part)
    wav = audio_mod.write_wav(out_path.with_suffix(".mix.wav"), np.concatenate(parts))
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(tmp_video), "-i", str(wav), "-c:v", "copy",
         "-c:a", "aac", "-b:a", audio_bitrate, "-shortest", "-movflags", "+faststart", str(out_path)],
        check=True,
    )  # fmt: skip
    tmp_video.unlink(missing_ok=True)
    wav.unlink(missing_ok=True)
    if progress:
        progress(1.0)
    return {
        "frames": total,
        "seconds": round(total / fps, 3),
        "render_wall_s": round(wall, 2),
        "render_fps": round(total / max(wall, 1e-6), 2),
        "size": list(size),
    }
