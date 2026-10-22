"""Condensed game (net sports, vision item 24): rallies only, dead time removed.

`rally_list(events, plays)` is the rally browser: every rally with its length, shot count
(the audio-fused contact count when the rally has one, else its contact events) and the
last hitter; `browser()` adds totals and the longest rallies. `render_condensed` cuts
every rally (+ `PRE_ROLL_S` before the serve, `POST_ROLL_S` after the point) out of the
wide camera back to back and draws the broadcast package's look on it: a rally counter
(RALLY n / N, shots, length), the score bug when score.json has points, and an optional
provenance label. Writes `renditions/condensed.mp4` and `condensed.json`.

Sports without rallies (basketball) cut `play_list(events)` instead: each shot, turnover
or block from `LEAD_S` before it, counted as PLAY n / N; `condensed.json` then has
`"unit": "play"` and those plays under `rallies`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .compositor import Cameras, _score_at, render_segments
from .director import Rules, graphics_plan
from .gamedata import load_game
from .graphics import ACCENT, FONT_BOLD, FONT_SEMI, MUTED, PANEL, WHITE, Package, _rgba, blit
from .graphics import font as get_font

PRE_ROLL_S = 1.5
POST_ROLL_S = 1.0
MERGE_GAP_S = 0.5  # padded windows closer than this play through as one segment
LONGEST_N = 5
REL = "renditions/condensed.mp4"
DOC_REL = "condensed.json"


def rally_list(events: list[dict], plays: list[dict]) -> list[dict]:
    evs = sorted((e for e in events if not e.get("dismissed")), key=lambda e: e["t_key"])
    out = []
    for r in (e for e in evs if e.get("type") == "rally"):
        a, b = float(r["t_start"]), float(r["t_end"])
        inside = [e for e in evs if a - 0.25 <= e["t_key"] <= b + 0.25]
        contacts = [e for e in inside if e["type"] == "contact"]
        serve = next((e for e in inside if e["type"] == "serve"), None)
        point = next((e for e in inside if e["type"] == "point"), None)
        if r.get("contacts"):  # 0 = audio heard no contacts: unknown, not a 0-shot rally
            shots, src = int(r["contacts"]), "audio_contacts"
        elif contacts:
            shots, src = len(contacts), "contact_events"
        else:
            shots, src = None, None
        play = next(
            (
                p
                for p in plays
                if p.get("grammar") == "rally" and p["t_start"] < b and p["t_end"] > a
            ),
            None,
        )
        out.append(
            {
                "id": f"r{len(out) + 1}",
                "n": len(out) + 1,
                "event_id": r["id"],
                "play_id": play["id"] if play else None,
                "t_start": round(a, 3),
                "t_end": round(b, 3),
                "duration_s": round(b - a, 2),
                "shots": shots,
                "shots_source": src,
                "server_id": serve.get("player_id") if serve else None,
                # the last contact's player / side: who hit last, not necessarily who won
                "last_hit_player_id": point.get("player_id") if point else None,
                "last_hit_team": point.get("team") if point else None,
                "confidence": r.get("confidence"),
                "confirmed": bool(r.get("confirmed")),
            }
        )
    return out


LEAD_S = 4.0  # basketball: kept before a shot / turnover starts (the attack building up)
PLAY_TYPES = ("shot", "turnover", "block")


def play_list(events: list[dict]) -> list[dict]:
    """Basketball and other sports without rallies: every decisive moment (a shot, a
    turnover, a block) from `LEAD_S` before it starts to its end. Bringing the ball up,
    dead balls and stoppages are what gets cut. Same keys as `rally_list`."""
    evs = sorted((e for e in events if not e.get("dismissed") and e.get("type") in PLAY_TYPES),
                 key=lambda e: e["t_key"])  # fmt: skip
    out = []
    for e in evs:
        a = max(0.0, float(e.get("t_start", e["t_key"])) - LEAD_S)
        b = max(float(e.get("t_end", e["t_key"])), float(e["t_key"]))
        out.append(
            {"id": f"r{len(out) + 1}", "n": len(out) + 1, "event_id": e["id"],
             "play_id": None, "t_start": round(a, 3), "t_end": round(b, 3),
             "duration_s": round(b - a, 2), "shots": None, "shots_source": None,
             "kind": e["type"], "player_id": e.get("player_id"),
             "confidence": e.get("confidence"), "confirmed": bool(e.get("confirmed"))}
        )  # fmt: skip
    return out


def browser(rallies: list[dict], duration_s: float) -> dict:
    """The rally browser document (`replay.rallies.v1`)."""
    total = sum(r["duration_s"] for r in rallies)
    by_len = sorted(rallies, key=lambda r: -r["duration_s"])
    by_shots = sorted((r for r in rallies if r["shots"] is not None), key=lambda r: -r["shots"])
    return {
        "schema": "replay.rallies.v1",
        "n": len(rallies),
        "game_s": round(duration_s, 2),
        "rally_s": round(total, 2),
        "dead_time_s": round(max(0.0, duration_s - total), 2),
        "mean_rally_s": round(total / len(rallies), 2) if rallies else None,
        "longest": [r["id"] for r in by_len[:LONGEST_N]],
        "most_shots": [r["id"] for r in by_shots[:LONGEST_N]],
        "rallies": rallies,
    }


def segments(rallies: list[dict], duration_s: float) -> list[tuple[float, float]]:
    """Padded rally windows, merged where they (nearly) touch."""
    segs: list[list[float]] = []
    for r in sorted(rallies, key=lambda r: r["t_start"]):
        a = max(0.0, r["t_start"] - PRE_ROLL_S)
        b = min(duration_s, r["t_end"] + POST_ROLL_S) if duration_s else r["t_end"] + POST_ROLL_S
        if segs and a - segs[-1][1] < MERGE_GAP_S:
            segs[-1][1] = max(segs[-1][1], b)
        else:
            segs.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in segs]


def condensed_offsets(rallies: list[dict], segs: list[tuple[float, float]]) -> None:
    """Set each rally's `condensed_t`: where its pre-roll starts in the condensed video."""
    starts = np.cumsum([0.0] + [b - a for a, b in segs])
    for r in rallies:
        for k, (a, b) in enumerate(segs):
            if a <= r["t_start"] <= b:
                r["condensed_t"] = round(starts[k] + max(r["t_start"] - PRE_ROLL_S, a) - a, 2)
                break


class Counter:
    """RALLY n / N with shots and length: a panel in the package's style, top right."""

    def __init__(self, pkg: Package, word: str = "RALLY"):
        self.pkg, self.word = pkg, word
        self._cache: dict = {}

    def sprite(self, n: int, total: int, line2: str) -> np.ndarray:
        key = (n, total, line2)
        if key in self._cache:
            return self._cache[key]
        s = self.pkg.px
        f_big, f_tot, f_sub = (
            get_font(str(FONT_BOLD), s(46)),
            get_font(str(FONT_SEMI), s(30)),
            get_font(str(FONT_SEMI), s(28)),
        )
        head, tot = f"{self.word} {n}", f" / {total}"
        w = max(round(f_big.getlength(head) + f_tot.getlength(tot)), round(f_sub.getlength(line2)))
        w += s(48)
        h1, h2, stripe = s(62), s(40), s(10)
        img = Image.new("RGBA", (w + stripe, h1 + h2), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, stripe - 1, h1 + h2], fill=(*ACCENT, 255))
        d.rectangle([stripe, 0, w + stripe, h1], fill=(*PANEL, 236))
        d.text((stripe + s(20), h1 / 2), head, font=f_big, fill=WHITE, anchor="lm")
        d.text((stripe + s(20) + f_big.getlength(head), h1 / 2 + s(4)), tot, font=f_tot,
               fill=MUTED, anchor="lm")  # fmt: skip
        d.rectangle([stripe, h1, w + stripe, h1 + h2], fill=(*ACCENT, 240))
        d.text((stripe + s(20), h1 + h2 / 2), line2, font=f_sub, fill=PANEL, anchor="lm")
        self._cache[key] = out = _rgba(img)
        return out

    def draw(self, frame: np.ndarray, n: int, total: int, line2: str, alpha: float) -> None:
        spr = self.sprite(n, total, line2)
        x = self.pkg.w - self.pkg.px(48) - spr.shape[1]
        blit(frame, spr, x, self.pkg.px(40), alpha=alpha)


def _line2(r: dict) -> str:
    parts = [f"{r['shots']} SHOTS"] if r["shots"] is not None else []
    if r.get("kind"):  # a basketball play: what it ended in
        parts = [r["kind"].upper()]
    return "  ·  ".join([*parts, f"{r['duration_s']:.1f} S"])


def render_condensed(
    game_dir: Path,
    out_path: Path | None = None,
    *,
    size: tuple[int, int] = (1280, 720),
    crf: int = 26,
    label: str | None = None,
    progress: Callable[[float], None] | None = None,
) -> dict:
    gd = Path(game_dir)
    game = load_game(gd)
    rallies = rally_list(game.events, game.plays)
    word = "RALLY"
    if not rallies:  # basketball: the plays that ended in a shot or a turnover
        rallies, word = play_list(game.events), "PLAY"
    if not rallies:
        raise ValueError(f"{gd}: no rallies, shots or turnovers in events.json")
    segs = segments(rallies, game.duration)
    condensed_offsets(rallies, segs)
    out = Path(out_path) if out_path else gd / REL
    out.parent.mkdir(parents=True, exist_ok=True)
    fps = game.fps
    wide = Cameras(game, fps, size[0]).live("wide")
    teams = graphics_plan(game, [], Rules())["teams"]
    pkg = Package(size[0], size[1], teams)
    counter = Counter(pkg, word)
    show_score = bool(game.score) and not game.score_provisional

    def window(i: int, t: float) -> np.ndarray:
        return wide[min(round(t * fps), len(wide) - 1)]

    def draw(frame: np.ndarray, i: int, t: float) -> None:
        r = next(
            (r for r in rallies if r["t_start"] - PRE_ROLL_S <= t <= r["t_end"] + POST_ROLL_S),
            None,
        )
        if r is not None:
            fade = min(1.0, (t - (r["t_start"] - PRE_ROLL_S)) / 0.3)
            counter.draw(frame, r["n"], len(rallies), _line2(r), fade)
        if show_score:
            sc, flash = _score_at(game.score, t)
            pkg.draw_score_bug(frame, sc, f"{int(t) // 60:02d}:{int(t) % 60:02d}", flash)
        if label:
            pkg.draw_label(frame, label)

    info = render_segments(
        game.dir / "media" / "wide.mp4", segs, out, size=size, fps=fps, window=window,
        draw=draw, crf=crf, progress=progress,
    )  # fmt: skip
    doc = browser(rallies, game.duration)
    doc.update(
        unit=word.lower(),
        game_id=game.game.get("id") or gd.name,
        video=REL if out == gd / REL else str(out),
        pre_roll_s=PRE_ROLL_S,
        post_roll_s=POST_ROLL_S,
        segments=[list(s) for s in segs],
        condensed_s=info["seconds"],
        render=info,
    )
    (gd / DOC_REL).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc
