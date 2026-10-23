"""Plays: whole-play boundaries from per-sport grammars over events (plan §4.4 "Plays").

A grammar is data in the profile's `plays:` list, so nothing here knows a sport. Two
kinds:

* `machine` — an explicit two-state machine (IDLE / OPEN) over the time-ordered events:
  a `start` event opens a play (closing any open one: a steal ends the last possession
  and starts the next), `member` events join it, an `end` event closes it, and an open
  play older than `max_s` is closed at its last event. `same_team` makes `end` events of
  the other team not count (a defender's block is not the end of my possession);
  `orphan_end` (true, or a list of selectors) turns an end event seen while IDLE into
  a one-event play (a put-back after an offensive rebound). Basketball:
  possession_change -> shot | turnover; net sports: serve -> point with contacts as
  members.
* `sequence` — `count` consecutive `match` events on one team, each within
  `max_step_s` of the previous: volleyball's pass -> set -> attack is three same-side
  contacts.

Selectors are an event `type`, or `type.cause` (`possession_change.steal`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .schema import Event, Participant, Play, ScoreEntry

IDLE, OPEN = "idle", "open"


def _match(e: Event, selectors: Iterable[str]) -> str | None:
    """The first selector that matches `e` (most specific wins when both are listed)."""
    sel = list(selectors)
    for s in sel:
        if "." in s and s == f"{e.type}.{e.cause}":
            return s
    return e.type if e.type in sel else None


def _new(gid: str, sport: str, events: list[Event], roles: dict[str, str], **kw: Any) -> Play:
    parts: list[Participant] = []
    for e in events:
        role = roles.get(f"{e.type}.{e.cause}") or roles.get(e.type)
        if (
            role
            and e.player_id
            and not any(p.player_id == e.player_id and p.role == role for p in parts)
        ):
            parts.append(Participant(player_id=e.player_id, role=role))
    conf = sum(e.confidence for e in events) / len(events) if events else 0.0
    return Play(
        id="",
        sport=sport,
        grammar=gid,
        event_ids=[e.id for e in events],
        participants=parts,
        confidence=round(conf, 3),
        **kw,
    )


def run_machine(events: list[Event], g: dict[str, Any], sport: str) -> list[Play]:
    start, end = g.get("start", []), g.get("end", [])
    member, roles = g.get("member", []), g.get("roles", {})
    max_s, last_n = float(g.get("max_s", 60.0)), g.get("last_n")
    orphans = end if g.get("orphan_end") is True else g.get("orphan_end") or []
    out: list[Play] = []
    state, cur, team, t0 = IDLE, [], None, 0.0

    def close(t_end: float) -> None:
        nonlocal state, cur
        play = _new(
            g["name"], sport, cur, roles, t_start=round(t0, 3), t_end=round(t_end, 3), team=team
        )
        hits = [e for e in cur if e.type == "contact"]
        if last_n and len(hits) > int(last_n):
            play.last_n = {"n": int(last_n), "t_start": round(hits[-int(last_n)].t_key - 0.5, 3)}
        out.append(play)
        state, cur = IDLE, []

    # an end event and a start event at the same instant (turnover + steal): end first
    order = sorted(events, key=lambda e: (e.t_key, 0 if _match(e, end) else 1))
    for e in order:
        if state == OPEN and e.t_key - t0 > max_s:
            close(max(x.t_end for x in cur))
        if (
            state == OPEN
            and _match(e, end)
            and (not g.get("same_team") or e.team is None or team is None or e.team == team)
        ):
            cur.append(e)
            close(max(e.t_end, t0))
        elif _match(e, start):
            if state == OPEN:
                close(max(e.t_key, t0))
            state, cur, team, t0 = OPEN, [e], e.team, e.t_start
            if _match(e, end):  # a one-event play (a block)
                close(e.t_end)
        elif state == OPEN and _match(e, member):
            cur.append(e)
        elif state == IDLE and g.get("orphan_end") and _match(e, orphans):
            t0, team = e.t_start, e.team
            cur = [e]
            close(e.t_end)
    if state == OPEN:
        close(max(x.t_end for x in cur))
    return out


def run_sequence(events: list[Event], g: dict[str, Any], sport: str) -> list[Play]:
    sel, n = g.get("match", []), int(g.get("count", 3))
    step, roles = float(g.get("max_step_s", 2.5)), list(g.get("roles", []))
    hits = sorted(
        (e for e in events if _match(e, sel) and e.team is not None), key=lambda e: e.t_key
    )
    out: list[Play] = []
    run: list[Event] = []
    for e in hits:
        if run and (e.team != run[-1].team or e.t_key - run[-1].t_key > step):
            run = []
        run.append(e)
        if len(run) == n:
            play = _new(
                g["name"], sport, run, {},
                t_start=round(max(0.0, run[0].t_key - float(g.get("pre_s", 0.5))), 3),
                t_end=round(run[-1].t_key + float(g.get("post_s", 1.0)), 3),
                team=run[0].team,
            )  # fmt: skip
            play.participants = [
                Participant(player_id=e.player_id, role=r)
                for e, r in zip(run, roles, strict=False)
                if e.player_id
            ]
            out.append(play)
            run = []
    return out


KINDS = {"machine": run_machine, "sequence": run_sequence}


def build_plays(events: list[Event], grammars: list[dict[str, Any]], sport: str) -> list[Play]:
    """Every grammar over the same events; ids `pl_0001`... in start order. Events a
    person dismissed (the extra key `dismissed`, set by the API) are not part of any play."""
    events = [e for e in events if not getattr(e, "dismissed", False)]
    plays: list[Play] = []
    for g in grammars:
        kind = g.get("kind", "machine")
        if kind not in KINDS:
            raise ValueError(f"unknown play grammar kind {kind!r} (have {sorted(KINDS)})")
        plays += KINDS[kind](events, g, sport)
    plays.sort(key=lambda p: (p.t_start, p.t_end))
    for n, p in enumerate(plays, 1):
        p.id = f"pl_{n:04d}"
    return plays


def score_timeline(
    events: list[Event],
    user: Iterable[ScoreEntry] = (),
    *,
    to: int | None = None,
    win_by: int = 1,
    teams: dict[str, int] | None = None,
) -> list[ScoreEntry]:
    """The running score: every made shot with `points` (basketball) or `point` with a
    `winner_side` adds `points` (unset: 1, rally scoring; 0: a side-out rally the
    receivers won) to its team — for a shot, the shooter's side in `teams` (the user's
    own team corrections) when it is there, else the team the events stage inferred; a
    user entry sets the score outright from its time on, and later automatic entries add
    on top of it. With `to` (pickup: game to 11 or 21, `profile.scoring`), the entry that
    wins a game shows the final score and the next basket starts the next game from 0-0."""
    teams = teams or {}
    items: list[tuple[float, int, Any]] = []
    for e in events:
        team = teams.get(e.player_id or "", e.team) if e.type == "shot" else e.team
        if e.type == "shot" and e.made and e.points and team in (0, 1):
            items.append((e.t_key, 1, (team, e.points, e.id)))
        elif e.type == "point" and e.winner_side in (0, 1) and e.points != 0:
            items.append((e.t_key, 1, (e.winner_side, e.points or 1, e.id)))
    for u in user:
        items.append((u.t, 0, u))
    items.sort(key=lambda x: (x[0], x[1]))
    running = [0, 0]
    out: list[ScoreEntry] = []
    for t, kind, x in items:
        if kind == 0:
            running = list(x.scores)
            out.append(ScoreEntry(t=x.t, scores=tuple(running), event_id=x.event_id, source="user"))
        else:
            team, pts, eid = x
            if to and max(running) >= to and abs(running[0] - running[1]) >= win_by:
                running = [0, 0]  # the previous basket won the game
            running[team] += pts
            out.append(ScoreEntry(t=round(t, 3), scores=tuple(running), event_id=eid))
    return out
