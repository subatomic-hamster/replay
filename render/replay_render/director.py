"""Auto-director: the whole game -> cuts.json (`replay.cuts.v1`).

Rules (a human operator's habits, all knobs in `Rules`):

1. **Base layer** — `wide` while play is dead (set-up, walking, timeouts), `tight` (ball-
   side framing of the active players) while it is live. Live = median on-court player
   speed above `action_on` m/s, with hysteresis, short gaps bridged, short bursts dropped.
   A long lull alternates `lull_wide_s` of wide with `lull_tight_s` on the players.
2. **Shots** — `follow:<shooter>` from `shot_pre_s` before to `shot_post_s` after the
   shot's key time.
3. **Instant replays** after big plays: makes (score.json entries), then plays someone
   clipped ("Replay, clip that"), long rallies, and — only when no make/miss is known at
   all — confident shots. A replay plays `replay_pre_s + replay_post_s` of source around
   the moment at `speed` (0.5x) in the dead time after it, **replacing** live footage, so
   the rendition stays on the source clock (score.json and event times line up). It is
   trimmed to end before the next action and dropped if that leaves < `replay_min_s`;
   replays are at least `replay_spacing_s` apart.
4. **Operator feel** — no live shot shorter than `min_shot_s` (merged into a neighbour),
   no A-B-A ping-pong with a short B, adjacent identical shots merged; live-to-live
   changes `ease` (an eased push / pull of the one virtual camera), replays enter and
   leave through a `sting` wipe.

Output times are rendition = source seconds. Cuts are contiguous, ordered, never overlap.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import pairwise
from typing import Any

import numpy as np

from .gamedata import Game

SCHEMA = "replay.cuts.v1"
GRID = 0.1  # s


@dataclass(frozen=True)
class Rules:
    min_shot_s: float = 3.0
    pingpong_s: float = 5.0
    action_on: float = 1.1  # m/s, median player speed
    action_off: float = 0.7
    action_min_s: float = 2.0
    bridge_s: float = 2.0
    shot_pre_s: float = 2.5
    shot_post_s: float = 1.0
    replay_speed: float = 0.5
    replay_pre_s: float = 3.0
    replay_post_s: float = 1.0
    replay_delay_s: float = 2.0  # after the key moment, before the replay starts
    replay_min_s: float = 4.0  # output seconds
    replay_spacing_s: float = 15.0
    long_rally_s: float = 8.0
    unknown_shot_conf: float = 0.5
    lower_third_s: float = 4.0
    lull_wide_s: float = 12.0  # in a long dead stretch: wide this long, then...
    lull_tight_s: float = 7.0  # ...this long on the players, repeating
    release_z_m: float = 2.3
    rim_z_m: float = 3.05


# --------------------------------------------------------------------------- activity


def activity(game: Game) -> tuple[np.ndarray, np.ndarray]:
    """(times, median on-court player speed m/s) at the tracks rate."""
    tr = game.tracks
    if len(tr.t) < 3:
        return tr.t, np.zeros(len(tr.t))
    dt = float(np.median(np.diff(tr.t)))
    v = np.linalg.norm(np.diff(tr.court, axis=1), axis=2) / dt  # (P, T-1)
    v[v > 6.0] = np.nan  # id jumps, not running
    v = np.concatenate([v[:, :1], v], axis=1)
    v[~np.isfinite(v)] = np.nan
    any_ok = np.isfinite(v).any(axis=0)
    med = np.zeros(v.shape[1])
    med[any_ok] = np.nanmedian(v[:, any_ok], axis=0)
    k = max(1, round(1.0 / dt))
    med = np.convolve(med, np.ones(k) / k, mode="same")
    return tr.t, med


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index runs of True."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0], strict=True))


def action_mask(times: np.ndarray, speed: np.ndarray, r: Rules) -> np.ndarray:
    on = np.zeros(len(times), dtype=bool)
    state = False
    for i, s in enumerate(speed):
        state = s > r.action_on if not state else s > r.action_off
        on[i] = state
    if len(times) < 2:
        return on
    dt = float(np.median(np.diff(times)))
    for a, b in _runs(~on):  # bridge short lulls inside play
        if 0 < a and b < len(on) and (b - a) * dt < r.bridge_s:
            on[a:b] = True
    for a, b in _runs(on):
        if (b - a) * dt < r.action_min_s:
            on[a:b] = False
    return on


# --------------------------------------------------------------------------- helpers


def _court_at(game: Game, pid: str | None, t: float) -> np.ndarray | None:
    i = game.tracks.index(pid) if pid else None
    if i is None:
        return None
    c = game.tracks.at(game.tracks.court[i : i + 1], np.asarray([t]))[0, 0]
    return c if np.isfinite(c).all() else None


def shot_arc(game: Game, ev: dict, r: Rules) -> dict | None:
    """Release point -> nearest rim at 3.05 m, landing at the shot's key time.

    Only with a pinhole projection (calibration K/R/t, or one recovered from the
    homography that passed the player-height check): the vertical-scale fallback cannot
    put a point 3 m up in the right place on a stitched/barrelled frame, and a wrong arc
    is worse than none. Layups (< 1.5 m from the rim) get no arc either."""
    if not game.rims or game.projector is None or game.projector.model == "vertical":
        return None
    pos = _court_at(game, ev.get("player_id"), ev["t_key"] - 1.0)
    if pos is None and ev.get("court"):
        pos = np.asarray(ev["court"], dtype=np.float64)
    if pos is None:
        return None
    rims = np.asarray(game.rims, dtype=np.float64)
    rim = rims[int(np.argmin(np.linalg.norm(rims - pos, axis=1)))]
    dist = float(np.linalg.norm(rim - pos))
    if dist < 1.5:
        return None
    flight = float(np.clip(0.8 + 0.05 * dist, 0.8, 1.6))
    apex = max(r.release_z_m, r.rim_z_m) + 0.6 + 0.12 * dist
    return {
        "t_release": round(ev["t_key"] - flight, 3),
        "t_rim": round(ev["t_key"], 3),
        "from": [round(float(pos[0]), 3), round(float(pos[1]), 3), r.release_z_m],
        "to": [round(float(rim[0]), 3), round(float(rim[1]), 3), r.rim_z_m],
        "apex_z": round(apex, 3),
        "made": ev.get("made"),
    }


def _has_camera(game: Game, pid: str | None) -> bool:
    return bool(pid) and (
        (game.dir / "crops" / f"{pid}.json").is_file() or game.tracks.index(pid) is not None
    )


# --------------------------------------------------------------------------- replays


def replay_candidates(game: Game, r: Rules) -> list[dict]:
    """Big plays, best first: makes > clipped plays > long rallies > unknown-outcome shots."""
    by_id = {e["id"]: e for e in game.events}
    out: list[dict] = []
    for s in game.score:
        ev = by_id.get(s.get("event_id") or "")
        if ev is not None:
            out.append({"rank": 0, "t": ev["t_key"], "event": ev, "reason": "make"})
    for p in game.plays:
        if p.get("trigger"):
            last = [by_id[i] for i in p.get("event_ids", []) if i in by_id]
            ev = max(last, key=lambda e: e["t_key"]) if last else None
            out.append(
                {
                    "rank": 1,
                    "t": ev["t_key"] if ev else p["t_end"],
                    "event": ev,
                    "play_id": p["id"],
                    "reason": f"clipped play {p['id']}",
                }
            )
    for e in game.events:
        if e["type"] == "rally" and e["t_end"] - e["t_start"] >= r.long_rally_s:
            out.append({"rank": 2, "t": e["t_end"] - 1.0, "event": e, "reason": "long rally"})
    shots = [e for e in game.events if e["type"] == "shot"]
    if shots and all(e.get("made") is None for e in shots) and not game.score:
        for e in shots:
            if e.get("confidence", 0.0) >= r.unknown_shot_conf:
                out.append(
                    {"rank": 3, "t": e["t_key"], "event": e, "reason": "shot (outcome unknown)"}
                )
    return sorted(out, key=lambda c: (c["rank"], -(c["event"] or {}).get("confidence", 0), c["t"]))


def _blockers(game: Game, r: Rules) -> list[float]:
    """Times by which a replay must be over: the next action starts here."""
    out = []
    for e in game.events:
        if e["type"] == "shot":
            out.append(e["t_key"] - r.shot_pre_s - 0.5)
        elif e["type"] in ("turnover", "rally", "serve", "block"):
            out.append(e["t_start"] - 0.5)
    return sorted(out)


def place_replays(game: Game, r: Rules) -> list[dict]:
    blockers = _blockers(game, r)
    placed: list[dict] = []
    full = (r.replay_pre_s + r.replay_post_s) / r.replay_speed
    for c in replay_candidates(game, r):
        start = c["t"] + r.replay_delay_s
        if start >= game.duration - r.replay_min_s:
            continue
        nxt = [b for b in blockers if b > start + 0.05]
        limit = min([game.duration, *nxt[:1]])
        length = min(full, limit - start)
        if length < r.replay_min_s:
            continue
        if any(abs(start - p["t_start"]) < r.replay_spacing_s for p in placed):
            continue
        src_end = c["t"] + r.replay_post_s
        ev = c["event"] or {}
        placed.append(
            {
                "t_start": round(start, 3),
                "t_end": round(start + length, 3),
                "src_t_start": round(src_end - length * r.replay_speed, 3),
                "src_t_end": round(src_end, 3),
                "speed": r.replay_speed,
                "reason": c["reason"],
                "event": ev,
                "play_id": c.get("play_id"),
            }
        )
    return sorted(placed, key=lambda p: p["t_start"])


# --------------------------------------------------------------------------- assembly


def _segments(labels: list[tuple]) -> list[dict]:
    segs: list[dict] = []
    for i, lab in enumerate(labels):
        if segs and segs[-1]["_lab"] == lab:
            segs[-1]["t_end"] = (i + 1) * GRID
        else:
            segs.append({"_lab": lab, "t_start": i * GRID, "t_end": (i + 1) * GRID})
    for s in segs:
        kind, camera, reason, ref = s.pop("_lab")
        s.update(kind=kind, camera=camera, reason=reason, _ref=ref)
    return segs


def _dur(s: dict) -> float:
    return s["t_end"] - s["t_start"]


def _merge_equal(segs: list[dict]) -> list[dict]:
    out: list[dict] = []
    for s in segs:
        prev = out[-1] if out else None
        if prev and s["kind"] == prev["kind"] == "live" and prev["camera"] == s["camera"]:
            prev["t_end"] = s["t_end"]
            continue
        out.append(s)
    return out


def enforce_operator_rules(segs: list[dict], r: Rules) -> list[dict]:
    """Min shot length, no ping-pong, merge equal neighbours (live segments only)."""
    segs = _merge_equal(segs)
    changed = True
    while changed:
        changed = False
        # A-B-A with a short B (not a shot follow) -> A throughout
        for i in range(1, len(segs) - 1):
            a, b, c = segs[i - 1], segs[i], segs[i + 1]
            if (
                a["kind"] == b["kind"] == c["kind"] == "live"
                and a["camera"] == c["camera"] != b["camera"]
                and _dur(b) < r.pingpong_s
                and not b["camera"].startswith("follow:")
            ):
                b["camera"], b["reason"], b["_ref"] = a["camera"], a["reason"], a["_ref"]
                changed = True
        segs = _merge_equal(segs)
        # too-short live shot -> absorbed by its longer live neighbour
        for i, s in enumerate(segs):
            if s["kind"] != "live" or _dur(s) >= r.min_shot_s or len(segs) == 1:
                continue
            nb = [j for j in (i - 1, i + 1) if 0 <= j < len(segs) and segs[j]["kind"] == "live"]
            if not nb:
                continue
            j = max(nb, key=lambda j: _dur(segs[j]))
            s["camera"], s["reason"], s["_ref"] = (
                segs[j]["camera"],
                segs[j]["reason"],
                segs[j]["_ref"],
            )
            changed = True
            break
        segs = _merge_equal(segs)
    return segs


def direct(game: Game, rules: Rules | None = None) -> dict[str, Any]:
    r = rules or Rules()
    n = max(1, round(game.duration / GRID))
    grid = (np.arange(n) + 0.5) * GRID
    times, speed = activity(game)
    act = action_mask(times, speed, r)
    live = np.interp(grid, times, act.astype(float)) > 0.5 if len(times) else np.zeros(n, bool)
    labels: list[tuple] = [
        ("live", "tight", "action", None) if a else ("live", "wide", "dead time", None)
        for a in live
    ]
    # a long lull: the operator still works — hold wide, then drift in on the players
    lull = ("live", "tight", "lull: tighten on players", None)
    step, hold = int(r.lull_wide_s / GRID), int(r.lull_tight_s / GRID)
    for a, b in _runs(~live):
        for i in range(a + step, b - step, step + hold):
            labels[i : i + hold] = [lull] * hold
    for e in game.events:
        if e["type"] != "shot" or not _has_camera(game, e.get("player_id")):
            continue
        i0 = int(max(0, (e["t_key"] - r.shot_pre_s) / GRID))
        i1 = int(min(n, (e["t_key"] + r.shot_post_s) / GRID))
        lab = ("live", f"follow:{e['player_id']}", f"shot {e['id']}", e["id"])
        for i in range(i0, i1):
            labels[i] = lab
    replays = place_replays(game, r)
    for k, rp in enumerate(replays):
        pid = (rp["event"] or {}).get("player_id")
        cam = f"tight:{pid}" if _has_camera(game, pid) else "tight"
        lab = ("replay", cam, f"replay: {rp['reason']}", k)
        for i in range(int(rp["t_start"] / GRID), min(n, round(rp["t_end"] / GRID))):
            labels[i] = lab
    segs = enforce_operator_rules(_segments(labels), r)

    cuts = []
    for i, s in enumerate(segs):
        cut = {
            "t_start": round(s["t_start"], 3),
            "t_end": round(min(s["t_end"], game.duration), 3),
            "camera": s["camera"],
            "reason": s["reason"],
            "kind": s["kind"],
            "transition": "cut"
            if i == 0
            else ("sting" if "replay" in (s["kind"], segs[i - 1]["kind"]) else "ease"),
        }
        if s["kind"] == "replay":
            rp = replays[s["_ref"]]
            ev = rp["event"] or {}
            # the replay segment can only lose time at its edges to rounding
            cut["replay"] = {
                "src_t_start": rp["src_t_start"],
                "src_t_end": rp["src_t_end"],
                "speed": rp["speed"],
                "event_id": ev.get("id"),
                "play_id": rp["play_id"],
                "player_id": ev.get("player_id"),
                "shot_arc": shot_arc(game, ev, r) if ev.get("type") == "shot" else None,
                "passes": _passes(game, rp["src_t_start"], rp["src_t_end"]),
            }
        elif s["camera"].startswith("follow:"):
            cut["event_id"] = s["_ref"]
        cuts.append(cut)
    if cuts:
        cuts[-1]["t_end"] = round(game.duration, 3)
    return {
        "schema": SCHEMA,
        "duration_s": round(game.duration, 3),
        "provisional": game.score_provisional,
        "geometry": {
            "projector": game.projector.model if game.projector else None,
            "height_err": round(game.projector.height_err, 3) if game.projector else None,
        },
        "rules": asdict(r),
        "cuts": cuts,
        "graphics": graphics_plan(game, cuts, r),
    }


def _passes(game: Game, t0: float, t1: float) -> list[dict]:
    out = []
    for e in game.events:
        if e["type"] == "pass" and t0 <= e["t_key"] <= t1 and e.get("receiver_id"):
            a = _court_at(game, e.get("player_id"), e["t_key"])
            b = _court_at(game, e["receiver_id"], e["t_key"] + 0.5)
            if a is not None and b is not None:
                out.append(
                    {
                        "t0": e["t_key"],
                        "t1": round(e["t_key"] + 0.5, 3),
                        "from": [round(float(a[0]), 3), round(float(a[1]), 3), 1.3],
                        "to": [round(float(b[0]), 3), round(float(b[1]), 3), 1.3],
                    }
                )
    return out


def graphics_plan(game: Game, cuts: list[dict], r: Rules) -> dict[str, Any]:
    """Score bug data and lower thirds: everything on screen comes from contract files."""
    by_id = {e["id"]: e for e in game.events}
    replays = [(c["t_start"], c["t_end"]) for c in cuts if c["kind"] == "replay"]
    totals: dict[str, int] = {}
    prev = [0, 0]
    lower = []
    for s in game.score:
        scores = [int(v) for v in s["scores"]]
        ev = by_id.get(s.get("event_id") or "") or {}
        delta = max(scores[0] - prev[0], scores[1] - prev[1])
        team = 0 if scores[0] - prev[0] >= scores[1] - prev[1] else 1
        prev = scores
        pid = ev.get("player_id")
        if not pid or delta <= 0:
            continue
        totals[pid] = totals.get(pid, 0) + delta
        t = float(s["t"]) + 0.6
        for a, b in replays:  # no room before the replay: name the scorer right after it
            if t - 0.2 < a < t + 1.7 or a <= t < b:
                t = b + 0.4
        end = min([t + r.lower_third_s, game.duration, *[a - 0.2 for a, _ in replays if a > t]])
        if end - t >= 1.5:
            lower.append(
                {
                    "t_start": round(t, 3),
                    "t_end": round(end, 3),
                    "player_id": pid,
                    "name": game.player_label(pid),
                    "line2": f"+{delta}  ·  {totals[pid]} PTS",
                    "team": team,
                }
            )
    for a, b in pairwise(lower):  # one lower third at a time
        a["t_end"] = round(min(a["t_end"], b["t_start"] - 0.3), 3)
    lower = [l3 for l3 in lower if l3["t_end"] - l3["t_start"] >= 1.5]
    colors = game.team_colors()
    teams = sorted(game.game.get("teams") or [], key=lambda t: t["id"])
    labels = [t.get("name") for t in teams] + [None, None]
    return {
        "teams": [
            {"label": labels[i] or ("HOME", "AWAY")[i], "color": colors[i]} for i in range(2)
        ],
        "score": [
            {"t": s["t"], "scores": list(s["scores"]), "event_id": s.get("event_id")}
            for s in game.score
        ],
        "score_provisional": game.score_provisional,
        "lower_thirds": lower,
        "clock": "elapsed",
    }


def validate(doc: dict) -> None:
    """Contract checks the tests (and the render stage) rely on."""
    cuts = doc["cuts"]
    assert cuts, "empty cut list"
    assert abs(cuts[0]["t_start"]) < 1e-6
    for a, b in pairwise(cuts):
        assert abs(a["t_end"] - b["t_start"]) < 1e-6, f"gap/overlap at {a['t_end']}"
    for c in cuts:
        assert c["t_end"] > c["t_start"], f"empty cut at {c['t_start']}"
        assert c["camera"] == "wide" or c["camera"].split(":")[0] in ("tight", "follow", "wide")
