"""Scorecard of a processed game against a hand-labelled moments file
(`replay.moments-truth.v1`, e.g. the owner's samples/real/final_cut.moments.json, which is
local only and gitignored). Read-only: it reads the game dir's pipeline outputs and never
feeds the truth back into the pipeline.

    python scripts/eval_moments.py <game_dir> <truth.json> [--map p3=<name>,p7=<name>,...]
        [--json out.json] [--frames out_dir]

Sections: tracking (ids, coverage, concurrency, off-court share, ids at each moment),
X-gesture triggers vs the truth X's, events / plays / highlights per moment, hype and
highlights reel, replay angles and POVs, worker stage timings (`_work/worker.jsonl`).

`--map` names pipeline ids after a look at the frames (the truth has no pixel labels), so
shooter / team / POV checks can say "right player". `--frames` writes one annotated JPEG
per moment (tracked boxes and ids) from the game's own video, for those spot checks; it
needs OpenCV, and its output is footage: keep it local.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

PAD_S = 2.0  # a pipeline item "overlaps" a moment within this many seconds
X_PAD_S = 1.5  # a gesture matches a truth X within this many seconds of its window
X_NO_TIME_S = 10.0  # a truth X with no time: look this long after the moment
TOP_IDS = 20  # tracking table rows printed (the JSON has every id)


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def overlaps(a0: float, a1: float, b0: float, b1: float, pad: float | None = None) -> bool:
    pad = PAD_S if pad is None else pad
    return a0 <= b1 + pad and b0 - pad <= a1


def fmt_t(t: float | None) -> str:
    if t is None:
        return "-"
    return f"{int(t // 60)}:{t % 60:04.1f}"


# ---------------------------------------------------------------- tracking


def tracking(gd: Path, game: dict, moments: list[dict], names: dict[str, str]) -> dict:
    meta = game.get("tracks") or {}
    rate = float(meta.get("rate_hz") or 10)
    frames = []
    for p in sorted((gd / "tracks").glob("*.json")):
        frames += (load(p) or {}).get("frames", [])
    dur = float((game.get("video") or {}).get("duration_s") or (frames[-1]["t"] if frames else 0))
    poly = (load(gd / "calib.json") or {}).get("court_polygon_m")
    xs = [q[0] for q in poly] if poly else [-7.5, 7.5]
    ys = [q[1] for q in poly] if poly else [0.0, 14.0]
    box = (min(xs), max(xs), min(ys), max(ys))

    seen: dict[str, list[float]] = defaultdict(list)
    off: Counter = Counter()
    conc: Counter = Counter()
    for f in frames:
        conc[len(f["p"])] += 1
        for q in f["p"]:
            seen[q["id"]].append(f["t"])
            ct = q.get("ct")
            if ct and not (box[0] - 1 <= ct[0] <= box[1] + 1 and box[2] - 1 <= ct[1] <= box[3] + 1):
                off[q["id"]] += 1
    n_frames = max(1, round(dur * rate))
    players = {p["id"]: p for p in game.get("players") or []}
    rows = []
    for pid, ts in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        p = players.get(pid, {})
        rows.append(
            {
                "id": pid,
                "name": names.get(pid),
                "team": p.get("team"),
                "color": p.get("color_hex"),
                "team_mixed": p.get("team_mixed"),
                "coverage": round(len(ts) / n_frames, 3),
                "first": round(min(ts), 1),
                "last": round(max(ts), 1),
                "offcourt_frac": round(off[pid] / len(ts), 3),
            }
        )
    at_moments = {}
    for m in moments:
        ids: Counter = Counter()
        n = 0
        for f in frames:
            if m["t0"] <= f["t"] <= m["t1"]:
                n += 1
                ids.update(q["id"] for q in f["p"])
        at_moments[m["id"]] = {k: round(v / max(1, n), 2) for k, v in ids.most_common()}
    total = sum(conc.values()) or 1
    return {
        "duration_s": dur,
        "n_ids": len(seen),
        "n_ids_cov50": sum(r["coverage"] >= 0.5 for r in rows),
        "n_ids_cov20": sum(r["coverage"] >= 0.2 for r in rows),
        "game_players": len(players),
        "teams": game.get("teams"),
        "concurrent": {k: round(v / total, 3) for k, v in sorted(conc.items())},
        "players": rows,
        "ids_at_moments": at_moments,
    }


# ---------------------------------------------------------------- triggers


def gestures(gd: Path, moments: list[dict]) -> dict:
    trig = (load(gd / "triggers.json") or {}).get("triggers", [])
    det = [t for t in trig if t.get("type") == "gesture"]
    truth = []
    for m in moments:
        x = m.get("x_gesture")
        if not x:
            continue
        if x.get("t0") is not None:
            truth.append((m["id"], x["by"], x["t0"], x.get("t1", x["t0"])))
        else:  # "after the shot; time not given"
            truth.append((m["id"], x["by"], m["t1"], m["t1"] + X_NO_TIME_S))
    used, rows = set(), []
    for mid, by, t0, t1 in truth:
        best = None
        for i, d in enumerate(det):
            if i in used:
                continue
            d0 = d.get("t_start") if d.get("t_start") is not None else d["t"]
            if overlaps(d0, d["t"], t0, t1, X_PAD_S):
                err = 0.0 if t0 <= d["t"] <= t1 else min(abs(d["t"] - t0), abs(d["t"] - t1))
                if best is None or err < best[1]:
                    best = (i, err)
        if best:
            used.add(best[0])
            d = det[best[0]]
        rows.append({
            "moment": mid, "by": by, "t0": t0, "t1": t1,
            "detected": bool(best),
            "t": d["t"] if best else None,
            "err_s": round(best[1], 2) if best else None,
            "by_player_id": d.get("by_player_id") if best else None,
            "play_id": d.get("play_id") if best else None,
            "confidence": d.get("confidence") if best else None,
        })  # fmt: skip
    fps = [
        {"t": d["t"], "by_player_id": d.get("by_player_id"), "play_id": d.get("play_id"),
         "confidence": d.get("confidence")}
        for i, d in enumerate(det) if i not in used
    ]  # fmt: skip
    other = Counter(t.get("type") for t in trig if t.get("type") != "gesture")
    voice = [
        {"t": t["t"], "transcript": t.get("transcript")} for t in trig if t.get("type") == "voice"
    ]
    return {
        "truth_x": len(truth),
        "tp": sum(r["detected"] for r in rows),
        "fp": len(fps),
        "rows": rows,
        "false_positives": fps,
        "other_triggers": dict(other),
        "voice": voice,
    }


# ---------------------------------------------------------------- events / plays / highlights


def ev_label(e: dict) -> str:
    s = e["type"]
    if e["type"] == "shot":
        s += {True: " made", False: " miss", None: " ?"}[e.get("made")]
        if e.get("points"):
            s += f" {e['points']}pt"
    if e.get("cause"):
        s += f" ({e['cause']})"
    return s


def per_moment(gd: Path, moments: list[dict], names: dict[str, str]) -> list[dict]:
    events = (load(gd / "events.json") or {}).get("events", [])
    plays = (load(gd / "plays.json") or {}).get("plays", [])
    hype = (load(gd / "hype.json") or {}).get("candidates", [])
    hl = (load(gd / "replays/highlights.json") or {}).get("plays", [])
    mom = (load(gd / "moments.json") or {}).get("moments", [])
    clips = (load(gd / "clips.json") or {}).get("clips", [])
    out = []
    for m in moments:
        t0, t1 = m["t0"], m["t1"]
        evs = [e for e in events if e["type"] != "bookmark"
               and overlaps(e.get("t_start", e["t_key"]), e.get("t_end", e["t_key"]), t0, t1)]  # fmt: skip
        key_evs = [e for e in evs if t0 - PAD_S <= e["t_key"] <= t1 + PAD_S]
        pls = [p for p in plays if overlaps(p["t_start"], p["t_end"], t0, t1)]
        hy = [(i + 1, c) for i, c in enumerate(hype) if overlaps(c["t_start"], c["t_end"], t0, t1)]
        hls = [h for h in hl if overlaps(h["t_start"], h["t_end"], t0, t1)]
        mos = [x for x in mom if overlaps(x.get("t_start", x["t"]), x.get("t_end", x["t"]), t0, t1)]
        cls = [c for c in clips if overlaps(c["t_start"], c["t_end"], t0, t1)]
        shooters = [e.get("player_id") for e in key_evs if e["type"] == "shot"]
        out.append({
            "moment": m["id"], "t0": t0, "t1": t1, "truth": m["kind"], "by": m.get("by"),
            "events_at_key": [f"{fmt_t(e['t_key'])} {ev_label(e)} {e.get('player_id')}"
                              f"{'=' + names[e['player_id']] if e.get('player_id') in names else ''}"
                              f" team{e.get('team')}" for e in key_evs],  # fmt: skip
            "shooter_named": [names.get(s) for s in shooters],
            "events_overlapping": len(evs),
            "plays": [f"{p['id']} {fmt_t(p['t_start'])}-{fmt_t(p['t_end'])} team{p.get('team')}" for p in pls],
            "hype_rank": [r for r, _ in hy],
            "highlight": [h["play_id"] + " " + h.get("label", "") for h in hls],
            "moments_tv": [f"{x['kind']}/{x.get('label')}" for x in mos],
            "clips": [c["id"] for c in cls],
        })  # fmt: skip
    return out


def false_highlights(gd: Path, moments: list[dict]) -> dict:
    hype = (load(gd / "hype.json") or {}).get("candidates", [])
    hl = (load(gd / "replays/highlights.json") or {}).get("plays", [])

    def hits(a0, a1):
        return [m["id"] for m in moments if overlaps(a0, a1, m["t0"], m["t1"])]

    return {
        "hype": [
            {
                "rank": i + 1,
                "t": c["t"],
                "window": f"{fmt_t(c['t_start'])}-{fmt_t(c['t_end'])}",
                "score": c.get("score"),
                "play_id": c.get("play_id"),
                "reasons": c.get("reasons"),
                "truth": hits(c["t_start"], c["t_end"]),
            }
            for i, c in enumerate(hype)
        ],  # fmt: skip
        "highlights": [
            {
                "play_id": h["play_id"],
                "window": f"{fmt_t(h['t_start'])}-{fmt_t(h['t_end'])}",
                "label": h.get("label"),
                "truth": hits(h["t_start"], h["t_end"]),
            }
            for h in hl
        ],  # fmt: skip
    }


def score(gd: Path, names: dict[str, str], truth: dict) -> dict:
    s = (load(gd / "score.json") or {}).get("score", [])
    events = {e["id"]: e for e in (load(gd / "events.json") or {}).get("events", [])}
    shots = [e for e in events.values() if e["type"] == "shot"]
    timeline = []
    for x in s:
        e = events.get(x.get("event_id") or "", {})
        timeline.append(f"{fmt_t(x['t'])} {x['scores']} {e.get('player_id')}"
                        f"{'=' + names[e['player_id']] if e.get('player_id') in names else ''}")  # fmt: skip
    return {
        "final": s[-1]["scores"] if s else None,
        "timeline": timeline,
        "shots": len(shots),
        "made": sum(e.get("made") is True for e in shots),
        "missed": sum(e.get("made") is False for e in shots),
        "unknown": sum(e.get("made") is None for e in shots),
        "event_types": dict(Counter(e["type"] for e in events.values())),
    }


# ---------------------------------------------------------------- replays / POV


def replays(gd: Path, moments: list[dict], names: dict[str, str]) -> dict:
    rows = []
    # a JSON-only copy of the game dir (no media) cannot say which renders are missing
    has_media = any(p.suffix in (".mp4", ".jpg") for p in (gd / "replays").rglob("*"))
    for mf in sorted((gd / "replays").glob("*/manifest.json")):
        m = load(mf) or {}
        angles = m.get("angles", [])
        povs = [a.get("player_id") for a in angles if str(a.get("id", "")).startswith("pov:")]
        rows.append({
            "play_id": m.get("play_id"),
            "window": f"{fmt_t(m.get('t_start'))}-{fmt_t(m.get('t_end'))}",
            "label": m.get("label"),
            "n_angles": len(angles),
            "tiers": dict(Counter(a.get("tier") for a in angles)),
            "povs": [f"{p}{'=' + names[p] if p in names else ''}" for p in povs],
            "missing_files": [a["id"] for a in angles
                              if has_media and a.get("url") and not (gd / a["url"]).exists()],  # fmt: skip
            "truth": [x["id"] for x in moments if overlaps(m.get("t_start", 0), m.get("t_end", 0), x["t0"], x["t1"])],
        })  # fmt: skip
    want = []
    for x in moments:
        pov = (x.get("pov") or {}).get("player")
        if not pov:
            continue
        near = [r for r in rows if x["id"] in r["truth"]]
        right = [r["play_id"] for r in near if any(p.endswith("=" + pov) for p in r["povs"])]
        want.append({"moment": x["id"], "player": pov, "replays_overlapping": [r["play_id"] for r in near],
                     "povs_there": [p for r in near for p in r["povs"]], "pov_of_player": right})  # fmt: skip
    return {"replays": rows, "pov_wanted": want}


# ---------------------------------------------------------------- timings


def timings(gd: Path) -> dict:
    lines = [json.loads(s) for s in (gd / "_work/worker.jsonl").read_text().splitlines() if s.strip()] \
        if (gd / "_work/worker.jsonl").exists() else []  # fmt: skip
    if not lines:
        return {}
    runs: dict[str, list[dict]] = defaultdict(list)
    for x in lines:
        runs[x["run"]].append(x)
    order = sorted(runs, key=lambda r: min(x["started"] for x in runs[r]))
    # the last processing session: runs chained with < 5 min between them
    chain = [order[-1]]
    for r in reversed(order[:-1]):
        nxt = min(x["started"] for x in runs[chain[0]])
        if nxt - max(x["ended"] for x in runs[r]) < 300:
            chain.insert(0, r)
        else:
            break
    sel = [x for r in chain for x in runs[r]]
    stages: dict[str, dict] = defaultdict(
        lambda: {"wall_s": 0.0, "lock_wait_s": 0.0, "n": 0, "hits": 0, "failed": 0}
    )
    for x in sel:
        s = stages[x["stage"]]
        s["n"] += 1
        s["hits"] += x.get("cache") == "hit"
        s["failed"] += x.get("status") != "ok"
        if x.get("cache") != "hit":
            s["wall_s"] = round(s["wall_s"] + float(x.get("wall_s") or 0), 1)
        s["lock_wait_s"] = round(s["lock_wait_s"] + float(x.get("lock_wait_s") or 0), 1)
    span = max(x["ended"] for x in sel) - min(x["started"] for x in sel)
    return {"runs": len(chain), "span_s": round(span, 1), "stages": dict(stages),
            "failed": [f"{x['stage']}:{x.get('item')}" for x in sel if x.get("status") != "ok"]}  # fmt: skip


# ---------------------------------------------------------------- frames


def frames(gd: Path, moments: list[dict], out: Path, names: dict[str, str]) -> None:
    import cv2  # only for the spot-check stills

    src = gd / "media/wide.mp4"
    if not src.exists():
        src = gd / "source.mp4"
    cap = cv2.VideoCapture(str(src))
    out.mkdir(parents=True, exist_ok=True)
    chunks = {}
    for m in moments:
        t = (m["t0"] + m["t1"]) / 2
        ci = int(t // 10)
        if ci not in chunks:
            chunks[ci] = (load(gd / f"tracks/{ci:05d}.json") or {}).get("frames", [])
        fr = min(chunks[ci], key=lambda f: abs(f["t"] - t), default=None)
        cap.set(cv2.CAP_PROP_POS_MSEC, (fr["t"] if fr else t) * 1000)
        ok, img = cap.read()
        if not ok:
            continue
        h, w = img.shape[:2]
        for q in (fr or {}).get("p", []):
            x, y, bw, bh = q["bb"]
            p0, p1 = (int(x * w), int(y * h)), (int((x + bw) * w), int((y + bh) * h))
            cv2.rectangle(img, p0, p1, (0, 255, 255), 2)
            label = q["id"] + ("=" + names[q["id"]] if q["id"] in names else "")
            cv2.putText(img, label, (p0[0], p0[1] - 6), 0, 0.8, (0, 255, 255), 2)
        cv2.putText(
            img,
            f"{m['id']} {fmt_t(fr['t'] if fr else t)} {m['kind']}",
            (20, 40),
            0,
            1.0,
            (0, 0, 255),
            2,
        )
        cv2.imwrite(str(out / f"{m['id']}.jpg"), img)


# ---------------------------------------------------------------- report


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("game_dir", type=Path)
    ap.add_argument("truth", type=Path)
    ap.add_argument("--map", default="", help="pipeline id = truth name, comma-separated")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--frames", type=Path)
    ap.add_argument("--pad", type=float, default=PAD_S, help="moment window padding, s")
    a = ap.parse_args()
    globals()["PAD_S"] = a.pad
    gd, truth = a.game_dir, json.loads(a.truth.read_text())
    names = dict(kv.split("=", 1) for kv in a.map.split(",") if "=" in kv)
    game = load(gd / "game.json") or {}
    moments = truth["moments"]
    rep = {
        "game": game.get("id"),
        "status": game.get("status"),
        "tracking": tracking(gd, game, moments, names),
        "gestures": gestures(gd, moments),
        "moments": per_moment(gd, moments, names),
        "score": score(gd, names, truth),
        "highlights": false_highlights(gd, moments),
        "replays": replays(gd, moments, names),
        "timings": timings(gd),
    }
    if a.frames:
        frames(gd, moments, a.frames, names)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=1))

    tr = rep["tracking"]
    print(f"# {rep['game']} ({rep['status']}), {tr['duration_s']:.0f} s\n")
    print(f"## Tracking: {tr['n_ids']} ids in tracks, {tr['game_players']} in game.json, "
          f"{tr['n_ids_cov50']} with >=50 % coverage, {tr['n_ids_cov20']} with >=20 %")  # fmt: skip
    print(f"teams: {tr['teams']}")
    print(f"people per frame (share of frames): {tr['concurrent']}")
    print("| id | name | team | colour | mixed | coverage | first-last | off-court |")
    print("|---|---|---|---|---|---|---|---|")
    for r in tr["players"][:TOP_IDS]:
        print(f"| {r['id']} | {r['name'] or ''} | {r['team']} | {r['color']} | {r['team_mixed']} | "
              f"{r['coverage']:.0%} | {fmt_t(r['first'])}-{fmt_t(r['last'])} | {r['offcourt_frac']:.0%} |")  # fmt: skip
    rest = tr["players"][TOP_IDS:]
    if rest:
        print(f"| +{len(rest)} more | | | | | {sum(r['coverage'] for r in rest):.0%} summed | | "
              f"{sum(r['offcourt_frac'] > 0.5 for r in rest)} mostly off court |")  # fmt: skip
    print("\nids seen during each moment (share of its frames, ids over 20 %):")
    for k, v in tr["ids_at_moments"].items():
        print(f"- {k}: { {i: s for i, s in v.items() if s > 0.2} }")

    g = rep["gestures"]
    print(f"\n## X gestures: {g['tp']}/{g['truth_x']} found, {g['fp']} false positives "
          f"(other triggers: {g['other_triggers']})")  # fmt: skip
    for r in g["rows"]:
        print(f"- {r['moment']} by {r['by']} {fmt_t(r['t0'])}-{fmt_t(r['t1'])}: "
              + (f"found at {fmt_t(r['t'])} (err {r['err_s']} s, by {r['by_player_id']}, play {r['play_id']})"
                 if r["detected"] else "MISSED"))  # fmt: skip
    for f in g["false_positives"]:
        print(
            f"- FP {fmt_t(f['t'])} by {f['by_player_id']} play {f['play_id']} conf {f['confidence']}"
        )
    for v in g["voice"]:
        print(f"- voice {fmt_t(v['t'])}: {v['transcript']!r}")

    print("\n## Moments")
    print(
        "| m | time | truth | events at the key time | plays | hype rank | highlight (angles) | TV moments |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for r in rep["moments"]:
        print(f"| {r['moment']} | {fmt_t(r['t0'])}-{fmt_t(r['t1'])} | {r['truth']} ({r['by']}) | "
              f"{'; '.join(r['events_at_key']) or '-'} | {len(r['plays'])} | {r['hype_rank'] or '-'} | "
              f"{'; '.join(r['highlight']) or '-'} | {'; '.join(r['moments_tv']) or '-'} |")  # fmt: skip

    s = rep["score"]
    print(f"\n## Score: final {s['final']}; shots {s['shots']} (made {s['made']}, missed {s['missed']}, "
          f"can't tell {s['unknown']}); events {s['event_types']}")  # fmt: skip
    for x in s["timeline"]:
        print(f"- {x}")

    h = rep["highlights"]
    print("\n## Hype candidates (Highlights row)")
    for c in h["hype"]:
        print(f"- #{c['rank']} {c['window']} score {c['score']} {c['reasons']} play {c['play_id']} "
              f"-> {c['truth'] or 'no truth moment'}")  # fmt: skip
    print("\n## Replays (angles)")
    for r in rep["replays"]["replays"]:
        print(f"- {r['play_id']} {r['window']} {r['label']!r}: {r['n_angles']} angles {r['tiers']}, "
              f"POVs {r['povs']} -> {r['truth'] or 'no truth moment'}"
              + (f" MISSING {r['missing_files']}" if r["missing_files"] else ""))  # fmt: skip
    for w in rep["replays"]["pov_wanted"]:
        print(f"- wanted POV {w['moment']} ({w['player']}): replays there {w['replays_overlapping']}, "
              f"POVs {w['povs_there']}, of that player {w['pov_of_player'] or 'none'}")  # fmt: skip

    t = rep["timings"]
    if t:
        print(f"\n## Timings: {t['span_s']:.0f} s wall over {t['runs']} worker runs "
              f"({t['span_s'] / max(tr['duration_s'], 1):.1f}x the game)")  # fmt: skip
        for k, v in sorted(t["stages"].items(), key=lambda kv: -kv[1]["wall_s"]):
            print(f"- {k}: {v['wall_s']} s ({v['n']} tasks, {v['hits']} hits, {v['failed']} failed, "
                  f"lock wait {v['lock_wait_s']} s)")  # fmt: skip
        if t["failed"]:
            print(f"- FAILED: {t['failed']}")


if __name__ == "__main__":
    main()
