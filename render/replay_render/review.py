"""Post-game review stills (vision item 26): the shot chart as a PNG in the broadcast
package's look, from the API's stats response (`replay.stats.v1`, services/api stats.py)
and courtcam's court template. The TV draws its own chart from the same data; this is
the shareable / evidence picture.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .graphics import FONT_BOLD, FONT_SEMI, MUTED, PANEL, PANEL_2, WHITE, distinct_team_colors, font

PX_PER_M = 40
MARGIN = 60
HEADER = 120
LINE = (200, 208, 220)


def shot_chart_png(
    stats: dict,
    sport: str,
    variant: str | None,
    out: Path,
    *,
    team_colors: list[str] | None = None,
    title: str = "SHOT CHART",
    label: str | None = None,
) -> Path:
    """Court drawn top-down with its length across the image; makes are filled team-colour
    dots, misses crosses, unknown outcomes hollow grey rings."""
    from courtcam.profiles import load_profile

    tpl = load_profile(sport).template(variant)
    xs = [p[0] for p in tpl.court]
    ys = [p[1] for p in tpl.court]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    W = round((y1 - y0) * PX_PER_M) + 2 * MARGIN
    H = round((x1 - x0) * PX_PER_M) + 2 * MARGIN + HEADER

    def px(x: float, y: float) -> tuple[float, float]:  # court (x, y) -> image; y across
        return MARGIN + (y - y0) * PX_PER_M, HEADER + MARGIN + (x1 - x) * PX_PER_M

    img = Image.new("RGB", (W, H), PANEL)
    d = ImageDraw.Draw(img)
    d.rectangle([MARGIN, HEADER + MARGIN, W - MARGIN, H - MARGIN], fill=PANEL_2)
    d.polygon([px(*p) for p in tpl.court], outline=LINE, width=3)
    for name, pts in (tpl.features or {}).items():
        closed = len(pts) == 4 and "paint" in name
        line = [px(*p) for p in pts] + ([px(*pts[0])] if closed else [])
        d.line(line, fill=LINE, width=3)
    for rx, ry in tpl.rims or ([tpl.rim] if tpl.rim else []):
        cx, cy = px(rx, ry)
        d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], outline=(255, 140, 60), width=3)
    if tpl.net_y is not None:
        d.line([px(x0 - 0.3, tpl.net_y), px(x1 + 0.3, tpl.net_y)], fill=WHITE, width=4)

    cols = distinct_team_colors(team_colors or ["#1F6FEB", "#E5484D"])
    shots = stats.get("shots") or []
    for s in shots:
        cx, cy = px(*s["court"])
        team = s.get("team")
        col = cols[team] if team in (0, 1) else (230, 230, 235)
        r = 13
        if s.get("outcome") == "make" or (s.get("outcome") is None and s.get("made")):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col, outline=WHITE, width=2)
        elif s.get("outcome") == "miss":
            d.line([cx - r, cy - r, cx + r, cy + r], fill=col, width=5)
            d.line([cx - r, cy + r, cx + r, cy - r], fill=col, width=5)
        else:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=MUTED, width=3)

    f1, f2 = font(str(FONT_BOLD), 54), font(str(FONT_SEMI), 30)
    makes = sum(1 for s in shots if s.get("outcome") == "make")
    known = sum(1 for s in shots if s.get("outcome") in ("make", "miss"))
    conf = stats.get("confidence")
    d.text((MARGIN, 34), title, font=f1, fill=WHITE)
    sub = f"AUTO-DETECTED  ·  {makes}/{known} MADE OF KNOWN  ·  {len(shots)} SHOTS"
    sub += f"  ·  CONFIDENCE {conf:.2f}" if isinstance(conf, float) else ""
    d.text((MARGIN, 90), sub, font=f2, fill=MUTED)
    lx = W - MARGIN - 470
    for i, (txt, kind) in enumerate((("MADE", "make"), ("MISSED", "miss"), ("UNKNOWN", "?"))):
        cx, cy = lx + i * 160, 62
        if kind == "make":
            d.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], fill=cols[0], outline=WHITE, width=2)
        elif kind == "miss":
            d.line([cx - 11, cy - 11, cx + 11, cy + 11], fill=cols[0], width=5)
            d.line([cx - 11, cy + 11, cx + 11, cy - 11], fill=cols[0], width=5)
        else:
            d.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], outline=MUTED, width=3)
        d.text((cx + 20, cy), txt, font=f2, fill=WHITE, anchor="lm")
    if label:
        d.text((W - MARGIN, H - 18), label, font=f2, fill=MUTED, anchor="rb")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    return out
