"""Composite the recorded end-to-end run (apps/tv/e2e-recording) into one MP4.

    python scripts/record_e2e_compose.py <beats.json> <full.mp4> <small.mp4> [--max-mb 25]

beats.json (written by the spec) names the TV video (1920x1080) and the phone video
(390x844), the phone's start offset, each beat with its pass/fail, and the processing
wait to cut. Layout on a 1920x1080 canvas: the TV scaled to 1488x837 on the left, the
phone at 1:1 on the right, a caption band below naming the beat, its result, and the
"SYNTHETIC / web build, not Fire TV" caveat. Captions are PIL-rendered PNGs (the box's
static ffmpeg has no drawtext). Prints the beat table (output-video times) for the README.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 25
TV = (16, 16, 1488, 837)  # x, y, w, h
PHONE = (1514, 16)
BAND_Y = 868
CAVEAT = (
    "SYNTHETIC footage only  ·  TV = react-native-web build of apps/tv in Chrome, NOT a Fire TV"
    "  ·  real services/api + worker pipeline on hfbox, no mocks"
)
# The first that exists (the box has only DejaVu); Pillow's default font lacks → and ×.
FONTS = [
    (
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ),
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
]


def font(size: int, bold: bool = False):
    for pair in FONTS:
        try:
            return ImageFont.truetype(pair[bold], size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def background(path: Path, caveat: str = CAVEAT) -> None:
    im = Image.new("RGB", (W, H), (12, 14, 18))
    d = ImageDraw.Draw(im)
    d.text((TV[0], BAND_Y), "TV (1920×1080, D-pad = keyboard)", font=font(22), fill=(150, 160, 175))
    d.text((PHONE[0], BAND_Y), "Phone browser (390×844)", font=font(22), fill=(150, 160, 175))
    d.text((TV[0], H - 40), caveat, font=font(22), fill=(240, 190, 80))
    im.save(path)


def caption(path: Path, text: str, status: str | None, sub: str = "") -> None:
    im = Image.new("RGBA", (W, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    room = W - 2 * TV[0]
    t, f = fit(d, text, 42, True, room)
    d.text((TV[0], 6), t, font=f, fill=(255, 255, 255))
    x = TV[0]
    if status:  # line 2, left: the beat's assertions, then what it found
        ok = status == "PASS"
        label = "asserted: PASS" if ok else "asserted: FAIL"
        f = font(28, bold=True)
        d.text((x, 62), label, font=f, fill=(90, 210, 120) if ok else (240, 90, 90))
        x += int(d.textlength(label, font=f)) + 24
    if sub:
        t, f = fit(d, sub, 27, False, W - TV[0] - x)
        d.text((x, 64), t, font=f, fill=(200, 205, 215))
    im.save(path)


def fit(d: ImageDraw.ImageDraw, text: str, size: int, bold: bool, width: int):
    """Shrink to at most 9/14 of `size` to fit `width`, then cut with an ellipsis."""
    floor = size * 9 // 14
    while size > floor and d.textlength(text, font=font(size, bold)) > width:
        size -= 1
    f = font(size, bold)
    if d.textlength(text, font=f) > width:
        while text and d.textlength(text + "…", font=f) > width:
            text = text[:-1]
        text += "…"
    return text, f


def out_time(t: float, cuts: list[dict]) -> float:
    """Original-timeline seconds → seconds in the cut video."""
    shift = 0.0
    for c in cuts:
        if t >= c["to"]:
            shift += c["to"] - c["from"]
        elif t > c["from"]:
            shift += t - c["from"]
    return t - shift


def mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def probe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(r.stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("beats")
    ap.add_argument("full")
    ap.add_argument("small")
    ap.add_argument("--max-mb", type=float, default=25)
    ap.add_argument("--caveat", default=CAVEAT, help="the line on every frame")
    ap.add_argument("--title", default="Replay — recorded end-to-end test")
    a = ap.parse_args()
    doc = json.loads(Path(a.beats).read_text())
    beats, cuts, videos = doc["beats"], doc["cuts"], doc["videos"]
    tv_dur = probe_duration(videos["tv"])

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        background(tmp / "bg.png", a.caveat)
        overlays: list[tuple[Path, float, float]] = []
        first = beats[0]["start"] if beats else tv_dur
        caption(tmp / "c_intro.png", a.title, None, "opening Home")
        overlays.append((tmp / "c_intro.png", 0, first))
        for i, b in enumerate(beats):
            p = tmp / f"c_{i}.png"
            sub = b.get("detail", "") if b["ok"] else f"failed: {b.get('error', '')}"
            caption(p, f"{i + 1}/{len(beats)}  {b['caption']}", "PASS" if b["ok"] else "FAIL", sub)
            end = beats[i + 1]["start"] if i + 1 < len(beats) else tv_dur
            overlays.append((p, b["start"], end))
        for j, c in enumerate(cuts):
            p = tmp / f"cut_{j}.png"
            caption(p, f">> {c['note']} (the wait is real; only the waiting is cut)", None)
            overlays.append((p, c["to"], c["to"] + 6))

        inputs = [
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-t",
            f"{tv_dur:.2f}",
            "-i",
            str(tmp / "bg.png"),
            "-i",
            videos["tv"],
            "-i",
            videos["phone"],
        ]
        for p, _, _ in overlays:
            inputs += ["-i", str(p)]
        off = max(0.0, doc.get("phone_offset_s", 0.0))
        f = [
            f"[1:v]setpts=PTS-STARTPTS,scale={TV[2]}:{TV[3]}[tv]",
            f"[2:v]setpts=PTS-STARTPTS+{off:.3f}/TB[ph]",
            f"[0:v][tv]overlay={TV[0]}:{TV[1]}:eof_action=repeat[v0]",
            f"[v0][ph]overlay={PHONE[0]}:{PHONE[1]}:eof_action=repeat[v1]",
        ]
        last = "v1"
        for k, (_, s, e) in enumerate(overlays):
            f.append(
                f"[{last}][{k + 3}:v]overlay=0:{BAND_Y + 30}:enable='between(t,{s:.2f},{e:.2f})'[o{k}]"
            )
            last = f"o{k}"
        keep = "*".join(f"not(between(t,{c['from']:.2f},{c['to']:.2f}))" for c in cuts) or "1"
        f.append(f"[{last}]fps={FPS},select='{keep}',setpts=N/{FPS}/TB,format=yuv420p[out]")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                *inputs,
                "-filter_complex",
                ";".join(f),
                "-map",
                "[out]",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-movflags",
                "+faststart",
                a.full,
            ],
            check=True,
        )

    dur = probe_duration(a.full)
    kbps = int(a.max_mb * 8 * 1024 * 0.92 / dur)  # 8% headroom for the container
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            a.full,
            "-vf",
            "scale=1280:720",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "24",  # the maxrate below keeps it under --max-mb
            "-maxrate",
            f"{kbps}k",
            "-bufsize",
            f"{2 * kbps}k",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            a.small,
        ],
        check=True,
    )
    size_mb = Path(a.small).stat().st_size / 2**20
    if size_mb > a.max_mb:
        print(f"{a.small} is {size_mb:.1f} MB > {a.max_mb} MB", file=sys.stderr)
        return 1

    print("| # | beat | video time | result | what it found |\n|---|---|---|---|---|")
    for i, b in enumerate(beats):
        res = "PASS" if b["ok"] else f"FAIL: {b.get('error', '')}"
        span = f"{mmss(out_time(b['start'], cuts))}–{mmss(out_time(b['end'], cuts))}"
        print(f"| {i + 1} | {b['name']} | {span} | {res} | {b.get('detail', '')} |")
    for c in cuts:
        print(
            f"\ncut: {mmss(c['from'])}–{mmss(c['to'])} of the raw run ({c['note']}) at {mmss(out_time(c['to'], cuts))}"
        )
    print(f"\nfull {a.full}: {dur:.1f} s; small {a.small}: {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
