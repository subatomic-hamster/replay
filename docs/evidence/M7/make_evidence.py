"""M7 evidence driver — run on hfbox (commands and results: README.md next to this file).

PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker:$d/render python make_evidence.py <cmd> ...

  grounding <out.json> [--llm] [--games DIR...]  template + LLM pass rates over every synthetic play
  commentary <game_dir> <out.json> [--llm] [--no-tts]   the worker's `commentary` stage
  ttsbench <game_dir> <out.json>                 TTS latency per line (current REPLAY_MODEL_DEVICE)
  search <game_dir> <out.json> QUERY...          `embeddings` + `search_index` stages, then queries
  queries <game_dir> <out.json> TEXT...          free text -> rules / validated LLM filter
  advice <game_dir> <out.json> [--llm]           advice for every rostered player
  render <game_dir> <out.mp4> [--t0 --t1 --size --crf]   director + broadcast with the narration
  mix <game_dir> <out.mp4> [--width]             source video + narration through replay_render's mixer

Model config comes from the env (REPLAY_MODEL_VENVS, REPLAY_MODEL_DEVICE, REPLAY_LLM_URL).
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from replay_api import stats as stats_mod
from replay_api.narrate import advice as A
from replay_api.narrate import commentary as C
from replay_api.narrate import search as S
from replay_api.providers.embeddings import LocalEmbeddings
from replay_api.providers.llm import LocalLLM
from replay_api.providers.query import LLMQueryEngine, RuleQueryEngine, merged_vocab
from replay_api.providers.tts import LocalTTS
from replay_worker import Cache, run

REPO = Path(__file__).resolve().parents[3]
NAMES = [
    "Alex",
    "Sam",
    "Jordan",
    "Riley",
    "Casey",
    "Morgan",
    "Taylor",
    "Jamie",
    "Avery",
    "Quinn",
    "Drew",
    "Blake",
]  # fmt: skip  (courtcam.synth.NAMES; a test roster)
LLM_CALLS: list[dict] = []
_orig_complete = LocalLLM.complete


def _timed_complete(self, *a, **k):
    t = time.time()
    try:
        return _orig_complete(self, *a, **k)
    finally:
        LLM_CALLS.append({"wall_s": round(time.time() - t, 3), **(self.last or {})})


LocalLLM.complete = _timed_complete


def _llm_stats() -> dict:
    if not LLM_CALLS:
        return {}
    w = sorted(c["wall_s"] for c in LLM_CALLS)
    tok = [c.get("predicted_n", 0) for c in LLM_CALLS]
    return {"calls": len(w), "median_s": w[len(w) // 2], "max_s": w[-1],
            "mean_tokens": round(sum(tok) / len(tok), 1),
            "gen_tok_per_s_median": sorted(c.get("predicted_per_second", 0) for c in LLM_CALLS)[len(w) // 2]}  # fmt: skip


def _dump(path: str, doc: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(
        json.dumps({k: v for k, v in doc.items() if k in ("summary", "timing", "stats")}, indent=1)
    )


def _synthetic_game(events: list[dict], sport: str) -> dict:
    pids = sorted({e[k] for e in events for k in ("player_id", "receiver_id") if e.get(k)},
                  key=lambda p: int(p[1:]))  # fmt: skip
    team = {e["player_id"]: e.get("team") for e in events if e.get("player_id")}
    return {"id": "synthetic", "sport": sport, "synthetic": True,
            "players": [{"id": p, "name": NAMES[(int(p[1:]) - 1) % 12], "team": team.get(p)}
                        for p in pids]}  # fmt: skip


def cmd_grounding(a) -> None:
    llm = LocalLLM() if a.llm else None
    sets = []
    for ev in sorted((REPO / "samples" / "synthetic").glob("*/*/events.json")):
        if ev.with_name("plays.json").is_file():
            doc = json.loads(ev.read_text())
            plays = json.loads(ev.with_name("plays.json").read_text())["plays"]
            sets.append((ev.parent.relative_to(REPO).as_posix(), _synthetic_game(doc["events"], doc["sport"]), doc["events"], plays, []))  # fmt: skip
    for gd in a.games or []:
        game, events, plays, score = C.load_docs(Path(gd))
        sets.append((Path(gd).name, game, events, plays, score))
    rows, kinds, examples = [], collections.Counter(), []
    for name, game, events, plays, score in sets:
        s = C.game_script(game, events, plays, score, llm=llm)
        tried = [p for p in s["plays"] if "llm" in p]
        for p in tried:
            kinds.update(v["kind"] for v in p["llm"]["violations"])
        rows.append({"set": name, **s["summary"]})
        for p in s["plays"][:2]:
            examples.append({"set": name, "play_id": p["play_id"], "source": p["source"],
                             "template": p.get("template_lines") or [ln["text"] for ln in p["lines"]],
                             "llm_raw": (p.get("llm") or {}).get("raw"),
                             "llm_violations": (p.get("llm") or {}).get("violations")})  # fmt: skip
    tot = {k: sum(r[k] for r in rows) for k in ("plays", "lines", "template_grounded", "llm_attempted", "llm_accepted")}  # fmt: skip
    summary = {**tot, "template_pass_rate": round(tot["template_grounded"] / tot["plays"], 4),
               "llm_acceptance_rate": round(tot["llm_accepted"] / tot["llm_attempted"], 4) if tot["llm_attempted"] else None,
               "llm_rejection_kinds": dict(kinds.most_common()), "llm_latency": _llm_stats()}  # fmt: skip
    _dump(a.out, {"note": "synthetic plays (labelled synthetic; names are a test roster)",
                  "summary": summary, "sets": rows, "examples": examples})  # fmt: skip


def _stage(name: str, *after_free: str, game_dir: Path | None = None):
    """Registry slice; `after_free` stages run standalone on an already-processed dir. A
    dir processed before the plays stage existed has no plays.json / score.json: those
    optional inputs are dropped for it (the stage then derives one-event plays)."""
    from replay_worker.stages import load_registry

    reg = load_registry()
    out = {}
    for n in name.split(","):
        s = dataclasses.replace(reg[n], after=()) if n in after_free else reg[n]
        if game_dir is not None:
            keep = tuple(i for i in s.inputs if i not in ("plays.json", "score.json")
                         or (game_dir / i).exists())  # fmt: skip
            s = dataclasses.replace(s, inputs=keep)
        out[n] = s
    return out


def _cache() -> Cache:
    return Cache(Path(os.environ.get("M7_CACHE", "/workspace/wt/replay-commentary-scratch/cache")))


def cmd_commentary(a) -> None:
    gd = Path(a.game_dir)
    cfg = {"commentary_llm": a.llm, "commentary_tts": not a.no_tts,
           "commentary_voice": a.voice}  # fmt: skip
    t = time.time()
    recs = run(gd, cfg, registry=_stage("commentary", "commentary", game_dir=gd),
               stages=["commentary"], cache=_cache(), force=["commentary"])  # fmt: skip
    script = json.loads((gd / "commentary" / "script.json").read_text())
    tts = (script.get("tts") or {}).get("runner") or {}
    items = tts.get("items") or []
    timing = {"stage_wall_s": round(time.time() - t, 2), "records": recs,
              "llm": _llm_stats(),
              "tts": {"device": os.environ.get("REPLAY_MODEL_DEVICE", "cuda"), "lines": len(items),
                      "load_s": tts.get("load_s"), "child_s": tts.get("child_s"),
                      "synth_s_per_line_median": sorted(i["synth_s"] for i in items)[len(items) // 2] if items else None,
                      "audio_s_total": round(sum(i["seconds"] for i in items), 2),
                      "synth_s_total": round(sum(i["synth_s"] for i in items), 2)}}  # fmt: skip
    _dump(a.out, {"game_dir": str(gd), "summary": script["summary"], "timing": timing,
                  "plays": [{k: p.get(k) for k in ("play_id", "source", "lines", "template_lines", "llm", "grounding")}
                            for p in script["plays"]]})  # fmt: skip


def cmd_ttsbench(a) -> None:
    script = json.loads((Path(a.game_dir) / "commentary" / "script.json").read_text())
    lines = [ln["text"] for p in script["plays"] for ln in p["lines"]]
    tmp = Path(tempfile.mkdtemp())
    tts = LocalTTS()
    t = time.time()
    tts.synthesize_many([(x, tmp / f"{i:03d}.wav") for i, x in enumerate(lines)])
    wall = time.time() - t
    shutil.rmtree(tmp)
    items = tts.last["items"]
    per = sorted(i["synth_s"] for i in items)
    audio = sum(i["seconds"] for i in items)
    _dump(a.out, {"timing": {"device": os.environ.get("REPLAY_MODEL_DEVICE", "cuda"), "lines": len(items),
                             "wall_s": round(wall, 2), "child_s": tts.last.get("child_s"), "load_s": tts.last.get("load_s"),
                             "synth_s_per_line_median": per[len(per) // 2], "synth_s_per_line_max": per[-1],
                             "audio_s": round(audio, 2), "rtf": round(sum(per) / audio, 3),
                             "per_play_s": round(sum(per) / max(1, len(script["plays"])), 3)}})  # fmt: skip


def _engine(game: dict, llm: bool):
    from replay_api.pipeline_adapter import get_profile

    vocab = merged_vocab((get_profile(game.get("sport", "")) or {}).get("query_vocab"))
    return LLMQueryEngine(vocab, LocalLLM()) if llm else RuleQueryEngine(vocab)


def cmd_search(a) -> None:
    gd = Path(a.game_dir)
    t = time.time()
    recs = run(gd, {}, registry=_stage("embeddings,search_index", "embeddings", game_dir=gd),
               stages=["search_index"], cache=_cache())  # fmt: skip
    build_s = time.time() - t
    index = json.loads((gd / S.INDEX).read_text())
    game, events, _, _ = C.load_docs(gd)
    emb = LocalEmbeddings()
    t = time.time()
    qv = emb.embed_texts(a.queries)
    q_s = time.time() - t
    eng = _engine(game, bool(os.environ.get("REPLAY_LLM_URL")))
    out = []
    for q, v in zip(a.queries, qv):
        f = eng.query(q, game, events)
        out.append({"query": q, "interpretation": f["interpretation"], "filter_source": f.get("source", "rules"),
                    "top": S.rank(gd, index, v, f.get("event_ids", []), k=3, query_text=q)})  # fmt: skip
    per_play = [r["wall_s"] for r in recs if r["stage"] == "embeddings"]
    _dump(a.out, {"note": "synthetic game (pipeline output on courtcam.synth footage)", "model": index["model"],
                  "timing": {"index_build_s": round(build_s, 2), "plays": len(per_play),
                             "embed_s_per_play_median": sorted(per_play)[len(per_play) // 2] if per_play else None,
                             "query_embed_s": round(q_s, 2), "queries": len(a.queries),
                             "runner_child_s": emb.last.get("child_s"), "runner_load_s": emb.last.get("load_s")},
                  "records": recs, "results": out})  # fmt: skip


def cmd_queries(a) -> None:
    gd = Path(a.game_dir)
    game, events, _, _ = C.load_docs(gd)
    eng = _engine(game, True)
    out = []
    for text in a.texts:
        t = time.time()
        r = eng.query(text, game, events)
        out.append({"text": text, "wall_s": round(time.time() - t, 3), "interpretation": r["interpretation"],
                    "source": r.get("source", "rules"), "llm_filter": r.get("llm_filter"),
                    "dropped": r.get("dropped"), "clips": len(r["clips"])})  # fmt: skip
    _dump(a.out, {"results": out, "timing": {"llm": _llm_stats()}})


def cmd_advice(a) -> None:
    gd = Path(a.game_dir)
    game, events, plays, _ = C.load_docs(gd)
    from replay_api.pipeline_adapter import get_profile

    frames = (
        f
        for c in sorted((gd / "tracks").glob("*.json"))
        for f in json.loads(c.read_text()).get("frames", [])
    )
    stats = stats_mod.compute(game, events, frames, get_profile(game.get("sport", ""), (game.get("court") or {}).get("variant")))  # fmt: skip
    llm = LocalLLM() if a.llm else None
    rows = [
        A.player_advice(game, events, plays, stats, p["id"], llm=llm)
        for p in game.get("players") or []
    ]
    rows = [r for r in rows if r["lines"] != [f"No stats for {r['name']} yet."]]
    for r in rows:
        r.pop("facts")
    summary = {"players": len(rows), "template_grounded": sum(r["grounding"]["template_ok"] for r in rows),
               "llm_accepted": sum(r.get("llm", {}).get("accepted", False) for r in rows), "llm": _llm_stats()}  # fmt: skip
    _dump(a.out, {"summary": summary, "advice": rows})


def cmd_render(a) -> None:
    gd = Path(a.game_dir)
    cfg = {"source": str(gd / "media" / "wide.mp4"), "narration": str(gd / "commentary" / "narration.wav"),
           "broadcast_size": a.size, "broadcast_t0": a.t0, "broadcast_t1": a.t1, "broadcast_crf": a.crf}  # fmt: skip
    t = time.time()
    run(
        gd,
        cfg,
        registry=_stage("director,broadcast", "director"),
        stages=["broadcast"],
        cache=_cache(),
    )
    shutil.copyfile(gd / "renditions" / "broadcast.mp4", a.out)
    print(f"{a.out}: {Path(a.out).stat().st_size / 1e6:.1f} MB in {time.time() - t:.0f}s")


def cmd_mix(a) -> None:
    from replay_render.audio import SR, mix, write_wav

    gd = Path(a.game_dir)
    game = json.loads((gd / "game.json").read_text())
    dur = float(game["video"]["duration_s"])
    src = gd / "media" / "wide.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        wav = write_wav(
            Path(tmp) / "mix.wav",
            mix(src, 0.0, dur, [], narration=gd / "commentary" / "narration.wav"),
        )
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", str(wav), "-map", "0:v", "-map", "1:a",
                        "-vf", f"scale={a.width}:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
                        "-c:a", "aac", "-b:a", "96k", "-shortest", a.out], check=True)  # fmt: skip
    print(
        f"{a.out}: {Path(a.out).stat().st_size / 1e6:.1f} MB (audio {SR} Hz, game ducked under narration)"
    )


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grounding")
    g.add_argument("out")
    g.add_argument("--llm", action="store_true")
    g.add_argument("--games", nargs="*")
    c = sub.add_parser("commentary")
    c.add_argument("game_dir")
    c.add_argument("out")
    c.add_argument("--llm", action="store_true")
    c.add_argument("--no-tts", action="store_true")
    c.add_argument("--voice")
    t = sub.add_parser("ttsbench")
    t.add_argument("game_dir")
    t.add_argument("out")
    s = sub.add_parser("search")
    s.add_argument("game_dir")
    s.add_argument("out")
    s.add_argument("queries", nargs="+")
    q = sub.add_parser("queries")
    q.add_argument("game_dir")
    q.add_argument("out")
    q.add_argument("texts", nargs="+")
    ad = sub.add_parser("advice")
    ad.add_argument("game_dir")
    ad.add_argument("out")
    ad.add_argument("--llm", action="store_true")
    r = sub.add_parser("render")
    r.add_argument("game_dir")
    r.add_argument("out")
    r.add_argument("--t0", type=float, default=0.0)
    r.add_argument("--t1", type=float)
    r.add_argument("--size", default="960x540")
    r.add_argument("--crf", type=int, default=30)
    m = sub.add_parser("mix")
    m.add_argument("game_dir")
    m.add_argument("out")
    m.add_argument("--width", type=int, default=960)
    a = p.parse_args()
    globals()[f"cmd_{a.cmd}"](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
