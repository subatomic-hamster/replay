"""Per-player advice grounded in the player's own stats (vision item 10).

Shooting by shot value (2 vs 3, from the events' `points`) and make %, passes, steals,
turnovers, rebounds, serves, rally outcomes and how the player's rallies ended (net /
out / winner), distance covered (from the stats response) against the team average.
Every line passes `grounding.check` against facts built from the same events and the
numbers it cites. No biomechanics: body words are in the check's invented-fact list.
"""

from __future__ import annotations

from typing import Any

from . import commentary as C
from . import grounding as G

SCHEMA = "replay.advice.v1"
MIN_ATTEMPTS = 2  # per shot value, before comparing efficiencies
GAP_PCT = 20  # make-% gap worth a suggestion
COVERAGE_SHARE = 0.5  # of the best-covered player's track samples, to compare distances

SYSTEM = (
    "You are a friendly amateur-sports coach. You get FACTS (JSON) about one player's game "
    "and LINES, draft insights. Rewrite each line as a short, encouraging tip, same order, "
    "same count. Use only what FACTS states: the same names and numbers, no other numbers, "
    "no court areas, shot types or body mechanics, no he/she/his/her. At most 18 words a line."
)


def _pct(m: int, a: int) -> int:
    return round(100 * m / a)


def player_lines(game: dict, events: list[dict], plays: list[dict], stats: dict, pid: str):
    """(lines, facts events, numbers cited) for one player."""
    names = G.roster(game)
    a = names.get(pid) or G.id_label(pid)
    team = next((p.get("team") for p in game.get("players") or [] if p["id"] == pid), None)
    lines: list[str] = []
    nums: list[int] = []
    used: list[dict] = []

    def cite(*ns: int) -> None:
        nums.extend(int(n) for n in ns)

    def by(typ: str, cause: str | None = None) -> list[dict]:
        return [
            e for e in events
            if e.get("type") == typ and e.get("player_id") == pid
            and (cause is None or (e.get("cause") or "").endswith(cause))
        ]  # fmt: skip

    shots = by("shot")
    used += shots
    known = [s for s in shots if s.get("made") is not None]
    if known:
        m = sum(bool(s["made"]) for s in known)
        lines.append(f"{a} shot {m} for {len(known)} ({_pct(m, len(known))}%).")
        cite(m, len(known), _pct(m, len(known)))
        split = {}
        for v, where in ((2, "Inside the arc"), (3, "From three")):
            sv = [s for s in known if s.get("points") == v]
            if sv:
                mv = sum(bool(s["made"]) for s in sv)
                lines.append(f"{where}: {mv} for {len(sv)}.")
                cite(mv, len(sv))
                split[v] = (mv, len(sv))
        if all(split.get(v, (0, 0))[1] >= MIN_ATTEMPTS for v in (2, 3)):
            p2, p3 = (_pct(*split[v]) for v in (2, 3))
            if abs(p2 - p3) >= GAP_PCT:
                cite(p2, p3)
                if p2 > p3:
                    lines.append(f"{a} is more efficient inside the arc ({p2}% against {p3}%"
                                 " from three): worth looking for more of those shots.")  # fmt: skip
                else:
                    lines.append(f"{a} is more efficient from three ({p3}% against {p2}%"
                                 " inside the arc): worth looking for more of those shots.")  # fmt: skip
    elif shots:
        lines.append(f"{a} put up {len(shots)} shots; their results were not detected.")
        cite(len(shots))

    for typ, cause, text in (
        ("pass", None, "{a} completed {n} passes."),
        ("possession_change", "steal", "{a} had {n} steals."),
        ("turnover", None, "{a} had {n} turnovers."),
        ("possession_change", "rebound", "{a} pulled in {n} rebounds."),
        ("serve", None, "{a} served {n} times."),
        ("block", None, "{a} had {n} blocks."),
    ):
        mine = by(typ, cause)
        if mine:
            used += mine
            lines.append(text.format(a=a, n=len(mine)))
            cite(len(mine))

    by_id = {e["id"]: e for e in events}
    rallies = [
        p for p in plays
        if p.get("grammar") == "rally"
        and any(q.get("player_id") == pid for q in p.get("participants") or [])
    ]  # fmt: skip
    if rallies and team is not None:
        rally_evs = [
            by_id[i] for p in rallies for i in p.get("event_ids", [])
            if i in by_id and by_id[i].get("type") == "rally"
        ]  # fmt: skip
        used += rally_evs + by("point")
        if rally_evs:
            won = sum(e.get("winner_side") == team for e in rally_evs)
            lines.append(f"{a}'s team took {won} of the {len(rally_evs)} rallies {a} played.")
            cite(won, len(rally_evs))
        endings = {c: len(by("point", c)) for c in ("winner", "net", "out")}
        parts = []
        if endings["winner"]:
            parts.append(f"{endings['winner']} with a winner")
        if endings["net"]:
            parts.append(f"{endings['net']} into the net")
        if endings["out"]:
            parts.append(f"{endings['out']} that went out")
        if parts:
            lines.append(f"{a} ended rallies " + ", ".join(parts) + ".")
            cite(*endings.values())

    rows = {r["player_id"]: r for r in (stats or {}).get("box_score", [])}
    me = rows.get(pid)
    # D-92: a track fragment seen for a few seconds is not a teammate to compare with
    # (a quarter read "191 metres; the team average was 44"): only players followed for
    # at least COVERAGE_SHARE of the best-covered player's samples count
    most = max((r.get("samples") or 0 for r in rows.values()), default=0)
    full = [r for r in rows.values() if r.get("distance_m")
            and (r.get("samples") or 0) >= COVERAGE_SHARE * most]  # fmt: skip
    if me in full:
        d = round(me["distance_m"])
        mates = [r["distance_m"] for r in full if r.get("team") == team]
        if len(mates) > 1:
            avg = round(sum(mates) / len(mates))
            lines.append(f"{a} covered {d} metres; the team average was {avg} metres.")
            cite(d, avg)
        else:
            lines.append(f"{a} covered {d} metres.")
            cite(d)
    if not lines:
        lines.append(f"No stats for {a} yet.")
    return lines, used, nums


def player_advice(
    game: dict,
    events: list[dict],
    plays: list[dict],
    stats: dict,
    pid: str,
    llm: Any = None,
) -> dict:
    lines, used, nums = player_lines(game, events, plays, stats, pid)
    facts = G.build_facts(game, used, participants=[{"player_id": pid}], numbers=nums)
    checks = [G.check(t, facts) for t in lines]
    out = {
        "schema": SCHEMA,
        "game_id": game.get("id"),
        "player_id": pid,
        "name": facts["roster"].get(pid),
        "auto_detected": True,
        "source": "template",
        "lines": lines,
        "grounding": {
            "template_ok": all(c["ok"] for c in checks),
            "violations": [v for c in checks for v in c["violations"]],
        },
        "facts": facts,
    }
    if llm is not None:
        view = {"player": out["name"], "stats_lines": lines, "numbers": facts["numbers"]}
        attempt = C.paraphrase(llm, facts, lines, system=SYSTEM, view=view)
        out["llm"] = C.llm_report(attempt)
        if attempt["lines"] is not None:
            out["source"], out["template_lines"], out["lines"] = "llm", lines, attempt["lines"]
    return out
