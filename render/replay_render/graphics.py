"""The broadcast graphics package: score bug, LIVE / REPLAY bugs, lower third, replay
sting, and the replay telestrator (spotlight ring, movement trail, shot / pass arcs).

One typeface (Barlow Condensed, SIL OFL 1.1, bundled in assets/ with its licence), one
dark panel colour, one accent, and the two team colours from the game's identity stage.
Layout is designed at 1080p and scaled to the output height. Text is rasterised with
Pillow (FreeType) into BGRA sprites that are cached and alpha-composited with numpy.
"""

from __future__ import annotations

import colorsys
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).parent / "assets"
FONT_BOLD = ASSETS / "BarlowCondensed-Bold.ttf"
FONT_SEMI = ASSETS / "BarlowCondensed-SemiBold.ttf"

PANEL = (14, 17, 22)  # RGB
PANEL_2 = (30, 36, 46)
WHITE = (245, 247, 250)
MUTED = (160, 170, 184)
LIVE_RED = (229, 72, 77)
ACCENT = (255, 184, 0)  # replay amber: bug, sting, telestrator


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def broadcast_color(h: str) -> tuple[int, int, int]:
    """A jersey colour made legible on a dark panel: keep the hue, lift dark/grey
    colours into a readable lightness/saturation band."""
    r, g, b = (v / 255 for v in hex_rgb(h))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    ll = min(max(ll, 0.45), 0.7)
    ss = max(ss, 0.35) if ss > 0.08 else ss
    return tuple(round(v * 255) for v in colorsys.hls_to_rgb(hh, ll, ss))  # type: ignore[return-value]


def distinct_team_colors(hexes: list[str]) -> list[tuple[int, int, int]]:
    """Two team colours; if identity's are too alike to tell apart, keep team 0's and
    give team 1 the panel-contrast white so the bug never shows two identical chips."""
    a, b = broadcast_color(hexes[0]), broadcast_color(hexes[1])
    if np.linalg.norm(np.subtract(a, b)) < 60:
        b = (235, 235, 240) if sum(a) < 450 else (60, 66, 80)
    return [a, b]


@lru_cache(maxsize=32)
def font(path: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, max(8, px))


def _rgba(img: Image.Image) -> np.ndarray:
    """Pillow RGBA -> numpy BGRA."""
    a = np.asarray(img)
    return a[..., [2, 1, 0, 3]].copy()


def blit(frame: np.ndarray, sprite: np.ndarray, x: int, y: int, alpha: float = 1.0) -> None:
    """Alpha-composite a BGRA sprite onto a BGR frame at (x, y), clipped to the frame."""
    h, w = sprite.shape[:2]
    fh, fw = frame.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, fw), min(y + h, fh)
    if x1 <= x0 or y1 <= y0:
        return
    s = sprite[y0 - y : y1 - y, x0 - x : x1 - x]
    a = s[..., 3:4].astype(np.float32) * (alpha / 255.0)
    roi = frame[y0:y1, x0:x1]
    roi[:] = (roi * (1 - a) + s[..., :3] * a).astype(np.uint8)


def _text_w(f: ImageFont.FreeTypeFont, text: str) -> int:
    return round(f.getlength(text))


class Package:
    """All graphics for one rendition size and one pair of teams."""

    def __init__(self, out_w: int, out_h: int, teams: list[dict]):
        self.w, self.h = out_w, out_h
        self.s = out_h / 1080.0
        self.team_rgb = distinct_team_colors([t["color"] for t in teams])
        self.team_label = [t["label"].upper() for t in teams]
        self._cache: dict = {}

    def px(self, v: float) -> int:
        return round(v * self.s)

    # ------------------------------------------------------------------ score bug

    def score_bug(self, scores: tuple[int, int], clock: str, flash: tuple[int, float] | None):
        """Sprite for the top-left bug. `flash` = (team, 0..1 strength) after a score."""
        key = ("bug", scores, clock, None if flash is None else (flash[0], round(flash[1], 1)))
        if key in self._cache:
            return self._cache[key]
        s = self.px
        h, chip, lab_w, sc_w, clk_w = s(58), s(10), s(92), s(66), s(104)
        w = 2 * (chip + lab_w + sc_w) + clk_w
        img = Image.new("RGBA", (w, h), (*PANEL, 232))
        d = ImageDraw.Draw(img)
        f_lab, f_sc, f_clk = (
            font(str(FONT_SEMI), s(32)),
            font(str(FONT_BOLD), s(44)),
            font(str(FONT_SEMI), s(34)),
        )
        x = 0
        for team in (0, 1):
            col = self.team_rgb[team]
            d.rectangle([x, 0, x + chip - 1, h], fill=(*col, 255))
            x += chip
            d.text((x + s(12), h / 2), self.team_label[team][:5], font=f_lab, fill=WHITE,
                   anchor="lm")  # fmt: skip
            x += lab_w
            bg = PANEL_2
            if flash and flash[0] == team:
                k = flash[1]
                bg = tuple(int(PANEL_2[i] * (1 - k) + col[i] * k) for i in range(3))
            d.rectangle([x, 0, x + sc_w - 1, h], fill=(*bg, 255))
            d.text((x + sc_w / 2, h / 2 + s(1)), str(scores[team]), font=f_sc, fill=WHITE,
                   anchor="mm")  # fmt: skip
            x += sc_w
        d.rectangle([x, 0, w, h], fill=(*PANEL, 255))
        d.text((x + clk_w / 2, h / 2), clock, font=f_clk, fill=MUTED, anchor="mm")
        d.rectangle([0, h - s(3), w, h], fill=(*ACCENT, 255))
        out = _rgba(img)
        self._cache[key] = out
        return out

    def draw_score_bug(self, frame, scores, clock, flash) -> None:
        blit(frame, self.score_bug(scores, clock, flash), self.px(48), self.px(40))

    # ------------------------------------------------------------------ LIVE / REPLAY

    def bug(self, kind: str) -> np.ndarray:
        key = ("pill", kind)
        if key in self._cache:
            return self._cache[key]
        s = self.px
        f = font(str(FONT_BOLD), s(34))
        if kind == "live":
            text, bg, fg = "LIVE", LIVE_RED, WHITE
        else:
            text, bg, fg = "REPLAY", ACCENT, PANEL
        dot = s(14) if kind == "live" else 0
        sub = "0.5×" if kind == "replay" else ""
        f_sub = font(str(FONT_SEMI), s(26))
        w = s(28) + dot + (s(10) if dot else 0) + _text_w(f, text)
        w += (s(12) + _text_w(f_sub, sub)) if sub else 0
        h = s(50)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=s(8), fill=(*bg, 240))
        x = s(14)
        if dot:
            d.ellipse([x, h / 2 - dot / 2, x + dot, h / 2 + dot / 2], fill=fg)
            x += dot + s(10)
        d.text((x, h / 2), text, font=f, fill=fg, anchor="lm")
        if sub:
            x += _text_w(f, text) + s(12)
            d.text((x, h / 2 + s(1)), sub, font=f_sub, fill=fg, anchor="lm")
        out = _rgba(img)
        self._cache[key] = out
        return out

    def draw_bug(self, frame, kind: str, blink: float = 1.0) -> None:
        spr = self.bug(kind)
        blit(frame, spr, self.w - self.px(48) - spr.shape[1], self.px(40), alpha=blink)

    # ------------------------------------------------------------------ lower third

    def lower_third(self, name: str, line2: str, team: int) -> np.ndarray:
        key = ("l3", name, line2, team)
        if key in self._cache:
            return self._cache[key]
        s = self.px
        f1, f2 = font(str(FONT_BOLD), s(54)), font(str(FONT_SEMI), s(32))
        w = max(_text_w(f1, name), _text_w(f2, line2)) + s(80)
        w = max(w, s(380))
        h1, h2, stripe = s(70), s(44), s(12)
        img = Image.new("RGBA", (w + stripe, h1 + h2), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        col = self.team_rgb[team]
        d.rectangle([0, 0, stripe - 1, h1 + h2], fill=(*col, 255))
        d.rectangle([stripe, 0, w + stripe, h1], fill=(*WHITE, 245))
        d.text((stripe + s(26), h1 / 2 + s(2)), name.upper(), font=f1, fill=PANEL, anchor="lm")
        d.rectangle([stripe, h1, w + stripe, h1 + h2], fill=(*PANEL, 235))
        d.rectangle([stripe, h1, stripe + s(8), h1 + h2], fill=(*col, 255))
        d.text((stripe + s(26), h1 + h2 / 2), line2, font=f2, fill=WHITE, anchor="lm")
        out = _rgba(img)
        self._cache[key] = out
        return out

    def draw_lower_third(self, frame, l3: dict, t: float) -> None:
        dur_in, dur_out = 0.35, 0.3
        u_in = (t - l3["t_start"]) / dur_in
        u_out = (l3["t_end"] - t) / dur_out
        if u_in <= 0 or u_out <= 0:
            return
        spr = self.lower_third(l3["name"], l3["line2"], l3["team"])
        k = float(_smooth(min(u_in, 1.0)))
        x = int(self.px(96) - (1 - k) * (spr.shape[1] + self.px(96)))
        y = self.h - self.px(96) - spr.shape[0]
        blit(frame, spr, x, y, alpha=float(min(1.0, u_out)))

    def draw_label(self, frame, text: str) -> None:
        """Small provenance label, bottom right (e.g. "SYNTHETIC")."""
        key = ("label", text)
        if key not in self._cache:
            f = font(str(FONT_SEMI), self.px(26))
            w, h = _text_w(f, text) + self.px(24), self.px(38)
            img = Image.new("RGBA", (w, h), (*PANEL, 170))
            ImageDraw.Draw(img).text((w / 2, h / 2), text, font=f, fill=MUTED, anchor="mm")
            self._cache[key] = _rgba(img)
        spr = self._cache[key]
        blit(frame, spr, self.w - self.px(24) - spr.shape[1], self.h - self.px(24) - spr.shape[0])

    # ------------------------------------------------------------------ sting

    def draw_sting(self, frame, u: float, team: int = 0) -> None:
        """Diagonal wipe for u in 0..1; the frame is fully covered at u = 0.5, which is
        where the compositor swaps live <-> replay."""
        w, h = self.w, self.h
        slant = 0.35 * w
        band = 1.0 * w + slant
        x = -band - slant + float(_smooth(u)) * (w + 2 * band)  # band's left edge
        layers = (
            (0.0, self.team_rgb[team], 0.10),
            (0.10, PANEL, 0.80),
            (0.90, ACCENT, 0.10),
        )
        for off, rgb, frac in layers:
            a = x + off * band
            b = a + frac * band
            pts = np.asarray([[a + slant, 0], [b + slant, 0], [b, h], [a, h]], dtype=np.int32)
            cv2.fillPoly(frame, [pts], rgb[::-1], lineType=cv2.LINE_AA)
        if 0.32 < u < 0.68:
            spr = self.wordmark()
            k = 1.0 - abs(u - 0.5) / 0.18
            blit(frame, spr, (w - spr.shape[1]) // 2, (h - spr.shape[0]) // 2, alpha=min(1, k))

    def wordmark(self) -> np.ndarray:
        if "mark" in self._cache:
            return self._cache["mark"]
        s = self.px
        f = font(str(FONT_BOLD), s(150))
        text = "REPLAY"
        w, h = _text_w(f, text) + s(40), s(190)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((w / 2, h / 2), text, font=f, fill=WHITE, anchor="mm")
        d.rectangle([s(20), h - s(14), w - s(20), h - s(6)], fill=(*ACCENT, 255))
        self._cache["mark"] = out = _rgba(img)
        return out


def _smooth(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return u * u * u * (u * (u * 6 - 15) + 10)


# ---------------------------------------------------------------------- telestrator


def glow_polyline(frame, pts: np.ndarray, rgb, width: int, alpha: float = 1.0) -> None:
    """A soft glow under a crisp line (the broadcast telestrator look)."""
    if len(pts) < 2:
        return
    p = np.round(pts).astype(np.int32).reshape(-1, 1, 2)
    x0, y0 = np.maximum(p.min(axis=(0, 1)) - 4 * width, 0)
    x1, y1 = p.max(axis=(0, 1)) + 4 * width
    x1, y1 = min(x1, frame.shape[1]), min(y1, frame.shape[0])
    if x1 <= x0 or y1 <= y0:
        return
    roi = frame[y0:y1, x0:x1]
    layer = roi.copy()
    q = p - [x0, y0]
    cv2.polylines(layer, [q], False, rgb[::-1], 3 * width, cv2.LINE_AA)
    layer = cv2.GaussianBlur(layer, (0, 0), max(1.0, width * 1.2))
    cv2.addWeighted(layer, 0.45 * alpha, roi, 1 - 0.45 * alpha, 0, dst=roi)
    crisp = roi.copy()
    cv2.polylines(crisp, [q], False, rgb[::-1], width, cv2.LINE_AA)
    cv2.polylines(crisp, [q], False, (255, 255, 255), max(1, width // 3), cv2.LINE_AA)
    cv2.addWeighted(crisp, alpha, roi, 1 - alpha, 0, dst=roi)


def spotlight(frame, ring_pts: np.ndarray, outer_pts: np.ndarray, rgb, pulse: float) -> None:
    """Translucent disc + bright rim under a player (points already in output px)."""
    if len(ring_pts) < 3:
        return
    p = np.round(ring_pts).astype(np.int32)
    o = np.round(outer_pts).astype(np.int32)
    x0, y0 = np.maximum(np.minimum(p.min(0), o.min(0)) - 8, 0)
    x1, y1 = np.maximum(p.max(0), o.max(0)) + 8
    x1, y1 = min(x1, frame.shape[1]), min(y1, frame.shape[0])
    if x1 <= x0 or y1 <= y0:
        return
    roi = frame[y0:y1, x0:x1]
    layer = roi.copy()
    cv2.fillPoly(layer, [p - [x0, y0]], rgb[::-1], cv2.LINE_AA)
    cv2.addWeighted(layer, 0.35, roi, 0.65, 0, dst=roi)
    cv2.polylines(roi, [p - [x0, y0]], True, rgb[::-1], 3, cv2.LINE_AA)
    rim = roi.copy()
    cv2.polylines(rim, [o - [x0, y0]], True, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.addWeighted(rim, 0.25 + 0.5 * pulse, roi, 0.75 - 0.5 * pulse, 0, dst=roi)


def trail(frame, pts: np.ndarray, rgb, width: int) -> None:
    """Movement trail on the floor: tapering from thin (oldest) to full width (now)."""
    n = len(pts)
    if n < 2:
        return
    p = np.round(pts).astype(np.int32)
    x0, y0 = np.maximum(p.min(0) - 2 * width, 0)
    x1, y1 = p.max(0) + 2 * width
    x1, y1 = min(x1, frame.shape[1]), min(y1, frame.shape[0])
    if x1 <= x0 or y1 <= y0:
        return
    roi = frame[y0:y1, x0:x1]
    layer = roi.copy()
    q = p - [x0, y0]
    for i in range(1, n):
        th = max(1, round(width * (0.25 + 0.75 * i / (n - 1))))
        cv2.line(layer, tuple(int(v) for v in q[i - 1]), tuple(int(v) for v in q[i]),
                 rgb[::-1], th, cv2.LINE_AA)  # fmt: skip
    cv2.addWeighted(layer, 0.75, roi, 0.25, 0, dst=roi)
