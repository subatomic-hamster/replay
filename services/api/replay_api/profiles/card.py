"""Collectible player card (vision §21): deterministic JSON + a rendered PNG.

The JSON is a pure function of the profile and its linked games' JSON (no clock, no
absolute URLs), so the same inputs give the same bytes. The title comes from fixed
templates keyed on the player's strongest stat; the first template that passes
`narrate.grounding.check` wins. An optional LLM paraphrase goes through the same
`commentary.paraphrase` path as commentary and advice: it is used only when it passes the
check, else the template stays. The PNG (810x1080, fits a 1080p screen) uses the broadcast
package's Barlow Condensed (SIL OFL, render/replay_render/assets, read only) and colours.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..config import REPO_ROOT
from ..narrate import commentary as C
from ..narrate import grounding as G
from . import career

SCHEMA = "replay.card.v1"
ASSETS = REPO_ROOT / "render" / "replay_render" / "assets"
SIZE = (810, 1080)
THUMB = (810, 560)
PANEL, PANEL_2 = (14, 17, 22), (30, 36, 46)
AMBER, WHITE, GREY = (255, 184, 0), (245, 247, 250), (150, 158, 170)

# (key, label) in display order; "shots" is made/attempted
STATS = (("points", "PTS"), ("shots", "FG"), ("threes_made", "3PM"), ("rebounds", "REB"),
         ("steals", "STL"), ("blocks", "BLK"), ("rallies", "RALLIES"), ("rallies_won", "WON"),
         ("contacts", "CONTACTS"), ("serves", "SERVES"), ("distance_m", "METRES"),
         ("plays", "PLAYS"))  # fmt: skip
# (stat, minimum, template): first one the player qualifies for AND that passes grounding
TITLES = (
    ("threes_made", 2, "{name} the sharpshooter: {n} three-pointers in {g}"),
    ("points", 1, "{name} the scorer: {n} points in {g}"),
    ("steals", 2, "{name} the pickpocket: {n} steals in {g}"),
    ("rebounds", 2, "{name} on the boards: {n} rebounds in {g}"),
    ("rallies", 1, "{name} the rally machine: {n} rallies in {g}"),
    ("contacts", 1, "{name}: {n} contacts in {g}"),
    ("plays", 1, "{name}: {n} plays in {g}"),
)
SYSTEM = (
    "You write titles for collectible sports trading cards. You get FACTS (JSON) and LINES, "
    "one draft title. Rewrite it as a punchy title, same meaning. Keep the player's name and "
    "the same numbers; no other numbers, names, shot types, records or he/she/his/her. "
    "At most 10 words."
)


def _games(n: int) -> str:
    return f"{n} game" if n == 1 else f"{n} games"


def primary_sport(stats: dict) -> str | None:
    """The sport with the most linked games (ties: alphabetical)."""
    return min(stats, key=lambda s: (-stats[s]["stats"].get("games", 0), s), default=None)


def _facts(profile_id: str, name: str, sport: str, linked: list, numbers: list[int]) -> dict:
    """What a title may claim: the player's own events (re-keyed to the profile) and the
    rallies they played, across the sport's linked games, plus the numbers it cites."""
    evs = []
    for lk in linked:
        if lk.sport != sport:
            continue
        evs += [{**e, "player_id": profile_id, "receiver_id": None} for e in lk.events
                if e.get("player_id") == lk.player_id]  # fmt: skip
        evs += career.rallies_played(lk)
    game = {"sport": sport, "players": [{"id": profile_id, "name": name}]}
    return G.build_facts(game, evs, participants=[{"player_id": profile_id}], numbers=numbers)


def title(profile_id: str, name: str, sport: str, stats: dict, linked: list,
          llm: Any = None) -> dict:  # fmt: skip
    g = int(stats.get("games", 0))
    tried = []
    for key, minimum, tpl in TITLES:
        n = stats.get(key)
        if not isinstance(n, (int, float)) or n < minimum:
            continue
        text = tpl.format(name=name, n=int(n), g=_games(g))
        facts = _facts(profile_id, name, sport, linked, [int(n), g])
        check = G.check(text, facts)
        tried.append({"template": tpl, "ok": check["ok"], "violations": check["violations"]})
        if check["ok"]:
            break
    else:
        text, facts = name, _facts(profile_id, name, sport, linked, [])
    out = {"title": text, "title_source": "template", "title_template": text,
           "grounding": {"template_ok": G.check(text, facts)["ok"], "tried": tried}}  # fmt: skip
    if llm is not None:
        view = {"player": name, "sport": sport, "numbers": facts["numbers"]}
        attempt = C.paraphrase(llm, facts, [text], system=SYSTEM, view=view)
        out["llm"] = C.llm_report(attempt)
        if attempt["lines"] is not None:
            out["title"], out["title_source"] = attempt["lines"][0], "llm"
    return out


def stat_tiles(stats: dict, edited: list[str], k: int = 4) -> list[dict]:
    tiles = []
    for key, label in STATS:
        if key == "shots":
            if "shots_attempted" not in stats:
                continue
            value = f"{stats.get('shots_made', 0)}/{stats['shots_attempted']}"
            ed = bool({"shots_made", "shots_attempted"} & set(edited))
            nonzero = bool(stats["shots_attempted"])
        elif key in stats:
            value, ed, nonzero = stats[key], key in edited, bool(stats[key])
            value = round(value) if key == "distance_m" else value
        else:
            continue
        tiles.append({"key": key, "label": label, "value": value, "edited": ed, "_nz": nonzero})
    keep = sorted(tiles, key=lambda t: not t["_nz"])[:k]  # non-zero first, stable
    return [{k_: v for k_, v in t.items() if k_ != "_nz"} for t in tiles if t in keep]


def build(doc: dict, linked: list, stats_by_sport: dict, llm: Any = None) -> dict:
    pid, name = doc["profile_id"], doc["name"]
    sport = primary_sport(stats_by_sport)
    s = stats_by_sport.get(sport) or {"stats": {}, "edited": []}
    moments = [m for m in career.moments(linked) if m["sport"] == sport]
    best = career.best_moment(moments)
    card = {
        "schema": SCHEMA,
        "profile_id": pid,
        "name": name,
        "sport": sport,
        "sports": doc.get("sports") or sorted(stats_by_sport),
        "positions": doc.get("positions") or [],
        "games": int(s["stats"].get("games", 0)),
        **title(pid, name, sport or "", s["stats"], linked, llm),
        "stats": stat_tiles(s["stats"], s["edited"]),
        "user_edited": bool(s["edited"]),
        "label": "auto-detected",
        "best_moment": {k: v for k, v in best.items() if k != "game_index"} if best else None,
        "photo_url": doc.get("photo_url"),
        "face_enrolled": bool(doc.get("face_enrolled")),
        "png": f"/media/profiles/{pid}/card.png",
        "thumb": f"/media/profiles/{pid}/thumb.jpg" if best else None,
    }
    return card


# --- PNG ---------------------------------------------------------------------------------


def grab_frame(video: Path, t: float):
    """One RGB frame at t seconds (ffmpeg on PATH), or None."""
    from io import BytesIO

    from PIL import Image

    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(video),
           "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]  # fmt: skip
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0 or not res.stdout:
        return None
    return Image.open(BytesIO(res.stdout)).convert("RGB")


def thumbnail(game_dir: Path, game: dict, best: dict):
    """The best moment's frame cropped on the player (THUMB aspect), or None."""
    wide = (game.get("renditions") or {}).get("wide")
    frame = grab_frame(Path(game_dir) / wide, best["t"]) if wide else None
    if frame is None:
        return None
    W, H = frame.size
    bb = career.frame_box(game_dir, best["player_id"], best["t"])
    from PIL import Image, ImageDraw, ImageOps

    if bb is None:
        crop = (0, 0, W, H)
    else:
        cx, cy = (bb[0] + bb[2] / 2) * W, (bb[1] + bb[3] / 2) * H
        bw, bh, foot = bb[2] * W, bb[3] * H, (bb[1] + bb[3]) * H
        # spotlight ring at the player's feet (the broadcast telestrator's amber)
        ImageDraw.Draw(frame).ellipse(
            (cx - 0.9 * bw, foot - 0.18 * bw, cx + 0.9 * bw, foot + 0.18 * bw),
            outline=AMBER, width=max(1, round(bh / 40)),
        )  # fmt: skip
        ch = min(H, max(bh * 1.6, 120.0))
        cw = min(W, ch * THUMB[0] / THUMB[1])
        x0 = min(max(0.0, cx - cw / 2), W - cw)
        y0 = min(max(0.0, cy - ch / 2), H - ch)
        crop = (round(x0), round(y0), round(x0 + cw), round(y0 + ch))
    return ImageOps.fit(frame.crop(crop), THUMB, Image.Resampling.LANCZOS)


def render_png(card: dict, thumb, out: Path, note: str | None = None) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    def font(name: str, px: int):
        return ImageFont.truetype(str(ASSETS / f"BarlowCondensed-{name}.ttf"), px)

    img = Image.new("RGB", SIZE, PANEL)
    d = ImageDraw.Draw(img)
    if thumb is not None:
        img.paste(thumb, (0, 0))
    else:
        d.rectangle((0, 0, *THUMB), fill=PANEL_2)
        initials = "".join(w[0] for w in card["name"].split()[:2]).upper()
        d.text((THUMB[0] / 2, THUMB[1] / 2), initials, font=font("Bold", 220), fill=GREY,
               anchor="mm")  # fmt: skip
    d.rectangle((0, THUMB[1], SIZE[0], THUMB[1] + 10), fill=AMBER)
    x, y = 40, THUMB[1] + 26
    d.text((x, y), card["name"].upper(), font=font("Bold", 104), fill=WHITE)
    y += 116
    f_title = font("SemiBold", 40)
    words, line, lines = card["title"].split(), "", []
    for w in words:  # wrap to the card width, two lines at most
        trial = f"{line} {w}".strip()
        if d.textlength(trial, font=f_title) > SIZE[0] - 2 * x and line:
            lines.append(line)
            line = w
        else:
            line = trial
    lines.append(line)
    for ln in lines[:2]:
        d.text((x, y), ln, font=f_title, fill=AMBER)
        y += 46
    sub = " · ".join(p for p in [(card["sport"] or "").upper(), f"{card['games']} GAMES"
                                 if card["games"] != 1 else "1 GAME",
                                 " / ".join(card["positions"]).upper()] if p)  # fmt: skip
    d.text((x, y + 6), sub, font=font("SemiBold", 30), fill=GREY)
    tiles = card["stats"]
    if tiles:
        col = (SIZE[0] - 2 * x) / len(tiles)
        ty = SIZE[1] - 250
        for i, t in enumerate(tiles):
            cx = x + col * i + col / 2
            d.text((cx, ty), str(t["value"]), font=font("Bold", 84), fill=WHITE, anchor="ma")
            d.text((cx, ty + 92), t["label"], font=font("SemiBold", 28), fill=GREY, anchor="ma")
            if t["edited"]:
                d.text((cx, ty + 126), "EDITED", font=font("SemiBold", 22), fill=AMBER,
                       anchor="ma")  # fmt: skip
    foot = "AUTO-DETECTED STATS" + (" · EDITED VALUES MARKED" if card["user_edited"] else "")
    d.text((x, SIZE[1] - 50), foot, font=font("SemiBold", 24), fill=GREY)
    if note:
        d.text((SIZE[0] - x, SIZE[1] - 50), note.upper(), font=font("SemiBold", 24), fill=AMBER,
               anchor="ra")  # fmt: skip
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    return out
