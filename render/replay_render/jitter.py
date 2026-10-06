"""Camera-path evidence: jitter of each virtual camera before (raw target) and after
smoothing, as numbers (jitter.json) and plots (jitter_<camera>.png)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import camera as cam
from .compositor import Cameras
from .gamedata import load_game


def report(game_dir: Path, out_dir: Path, *, t0: float = 0.0, t1: float | None = None) -> dict:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    game = load_game(game_dir)
    fps = 30.0
    cams = Cameras(game, fps, 1920)
    t1 = min(t1 or game.duration, game.duration)
    sl = slice(int(t0 * fps), int(t1 * fps))
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"game": game.dir.name, "t0": t0, "t1": t1, "metric": cam.jitter.__doc__}
    names = ["wide", "tight"]
    # the follow-cam of the player on screen longest (courtcam croppath, unchanged here)
    present = np.isfinite(game.tracks.box[..., 0]).sum(axis=1)
    if len(present):
        pid = game.tracks.ids[int(np.argmax(present))]
        names.append(f"follow:{pid}")
    for name in names:
        smooth = cams.live(name)[sl]
        if name.startswith("follow:"):
            i = game.tracks.index(name.split(":")[1])
            b = cams.box[i, sl]
            raw = np.column_stack([(b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2, smooth[:, 2]])
            raw = cams._fill(raw, smooth[0])
        else:
            raw = cams.raw[name][sl]
        result[name] = {"raw": cam.jitter(raw), "smoothed": cam.jitter(smooth)}
        t = np.arange(len(smooth)) / fps + t0
        fig, ax = plt.subplots(2, 1, figsize=(10, 5.5), sharex=True)
        ax[0].plot(t, raw[:, 0], color="#9aa4b2", lw=0.8, label="raw target")
        ax[0].plot(t, smooth[:, 0], color="#d97706", lw=1.8, label="camera")
        ax[0].set_ylabel("window centre x (src px)")
        ax[0].legend(loc="upper right", frameon=False)
        ax[0].set_title(
            f"{game.dir.name} — {name}: jitter rms {result[name]['raw']['rms_px']:.2f} → "
            f"{result[name]['smoothed']['rms_px']:.2f} px/frame² (1080p screen)"
        )
        ax[1].plot(t, raw[:, 2], color="#9aa4b2", lw=0.8)
        ax[1].plot(t, smooth[:, 2], color="#d97706", lw=1.8)
        ax[1].set_ylabel("window width (src px)")
        ax[1].set_xlabel("time (s)")
        for a in ax:
            a.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(out_dir / f"jitter_{name.replace(':', '_')}.png", dpi=90)
        plt.close(fig)
    result["followcam"] = followcam_report(game.dir, out_dir, t0=t0, t1=t1)
    (out_dir / "jitter.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def followcam_report(game_dir: Path, out_dir: Path, *, t0: float, t1: float) -> dict:
    """courtcam's follow-cam before (no dead zone, raw-step lead) and after (dead zone +
    EMA lead), recomputed exactly as the crops stage does for every player."""
    import matplotlib.pyplot as plt
    from courtcam.court import resample
    from courtcam.identity import read_players
    from courtcam.profiles import load_profile

    from courtcam import croppath

    game = load_game(game_dir)
    players_json = Path(game_dir) / "_work" / "players.json"
    if not players_json.is_file():
        return {}
    players, _ = read_players(players_json)
    cfg = load_profile(game.sport).followcam
    court_w = croppath.court_px_width(game.calib, game.width)
    times = np.arange(round(game.duration * 30)) / 30.0
    sl = slice(int(t0 * 30), int(t1 * 30))
    rows, best = [], None
    for p in players:
        boxes, _, _ = resample(p.track, times)
        ok = np.isfinite(boxes[sl]).all(axis=1)
        if ok.sum() < 90:
            continue
        paths = {}
        for name, kw in (("before", {"dead_frac": 0.0, "vel_tau_s": 0.0}), ("after", {})):
            rects = croppath.crop_path(boxes, game.width, game.height, cfg, court_px_w=court_w,
                                       **kw)[sl][ok]  # fmt: skip
            paths[name] = np.column_stack(
                [(rects[:, 0] + rects[:, 2] / 2) * game.width,
                 (rects[:, 1] + rects[:, 3] / 2) * game.height, rects[:, 2] * game.width]
            )  # fmt: skip
        rows.append((int(ok.sum()), {k: cam.jitter(v) for k, v in paths.items()}))
        if best is None or ok.sum() > best[0]:
            best = (int(ok.sum()), p.player_id, paths, boxes[sl][ok])
    if not rows:
        return {}
    n = np.asarray([r[0] for r in rows], dtype=np.float64)
    summary = {
        k: {m: round(float(np.sum(n * [r[1][k][m] for r in rows]) / n.sum()), 4)
            for m in ("rms_px", "p95_px")}
        for k in ("before", "after")
    }  # fmt: skip
    summary["players"] = len(rows)
    _, pid, paths, boxes = best
    t = np.arange(len(boxes)) / 30.0 + t0
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(10, 5.5), sharex=True)
    ax.plot(t, (boxes[:, 0] + boxes[:, 2] / 2), color="#9aa4b2", lw=0.8, label="box centre")
    ax.plot(t, paths["before"][:, 0], color="#6b7280", lw=1.2, label="follow-cam before")
    ax.plot(t, paths["after"][:, 0], color="#d97706", lw=1.8, label="follow-cam after")
    ax.set_ylabel("window centre x (src px)")
    ax.set_title(
        f"{Path(game_dir).name} follow-cam {pid}: jitter rms {summary['before']['rms_px']:.2f} "
        f"→ {summary['after']['rms_px']:.2f} px/frame² over {len(rows)} players"
    )
    ax.legend(loc="upper right", frameon=False)
    for name, color, lw in (("before", "#6b7280", 0.9), ("after", "#d97706", 1.2)):
        p = paths[name]
        shake = np.linalg.norm(np.diff(p[:, :2], 2, axis=0), axis=1) * 1920.0 / p[1:-1, 2]
        ax2.plot(t[1:-1], shake, color=color, lw=lw, label=name)
    ax2.set_ylabel("shake (1080p px/frame²)")
    ax2.set_xlabel("time (s, frames with the player tracked)")
    ax2.legend(loc="upper right", frameon=False)
    for a in (ax, ax2):
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_dir / "jitter_followcam_before_after.png", dpi=90)
    plt.close(fig)
    return summary
