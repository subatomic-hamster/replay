"""Semantic search over plays (vision item 23).

Per play: `KEYFRAMES` frames spread over the play's span → image embeddings, averaged;
plus the play's template commentary text (deterministic, grounded) → a text embedding.
Stored as `embeddings/{play_id}.npy` (2 x D float32: [image, text]) with
`embeddings/index.json` listing the plays, their spans and texts and the model.

A query text is embedded once; plays are ranked by reciprocal-rank fusion of the
query↔image and query↔text cosines (SigLIP's cross-modal cosines are tiny next to
text↔text ones, so ranks are fused, not scores), then re-ranked by the structured filter
from the query engine (rules, or the validated LLM filter): plays holding an event the
filter selects come first.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from . import commentary as C

INDEX = "embeddings/index.json"
KEYFRAMES = 4
RRF_K = 60
SCHEMA = "replay.embeddings_index.v1"


def safe_id(play_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", play_id)


def play_text(game: dict, play: dict, events: list[dict], score: list[dict]) -> str:
    by_id = {e["id"]: e for e in events}
    s = C.script_for_play(game, play, by_id, C.score_index(score))
    head = f"{game.get('sport', '')} {play.get('grammar', 'play')}".strip()
    return " ".join([head + "."] + [ln["text"] for ln in s["lines"]])


def keyframe_times(play: dict, k: int = KEYFRAMES) -> list[float]:
    t0, t1 = float(play["t_start"]), float(play["t_end"])
    return [round(t0 + (i + 0.5) * (t1 - t0) / k, 3) for i in range(k)]


def extract_keyframes(video: Path, times: list[float], out_dir: Path) -> list[Path]:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, t in enumerate(times):
        p = out_dir / f"k{i}.jpg"
        subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=448:-2", str(p)], check=True)  # fmt: skip
        if p.is_file():
            paths.append(p)
    if not paths:
        raise RuntimeError(f"no keyframes from {video} at {times}")
    return paths


def _unit(v: np.ndarray) -> np.ndarray:
    return v / max(float(np.linalg.norm(v)), 1e-12)


def embed_plays(emb: Any, video: Path, items: list[tuple[dict, str, Path]]) -> dict:
    """Embed many (play, text, out_npy) in ONE provider call: every play's keyframes and
    texts go to the model runner together, so the model loads once per batch."""
    tmp = items[0][2].parent / "_kf_batch"
    try:
        frames = [extract_keyframes(video, keyframe_times(p), tmp / str(i))
                  for i, (p, _, _) in enumerate(items)]  # fmt: skip
        flat, texts = [f for fs in frames for f in fs], [t for _, t, _ in items]
        if hasattr(emb, "embed"):  # one model load for both
            imgs, txts = emb.embed(flat, texts)
        else:
            imgs, txts = emb.embed_images(flat), emb.embed_texts(texts)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    i0, dim = 0, 0
    for (_, _, out_npy), fs, txt in zip(items, frames, txts, strict=True):
        img = np.asarray(imgs[i0 : i0 + len(fs)], np.float32)
        i0 += len(fs)
        vec = np.stack([_unit(img.mean(axis=0)), _unit(np.asarray(txt, np.float32))])
        out_npy.parent.mkdir(parents=True, exist_ok=True)
        np.save(out_npy, vec.astype(np.float32))
        dim = int(vec.shape[1])
    return {"plays": len(items), "frames": len(flat), "dim": dim}


def embed_play(emb: Any, video: Path, play: dict, text: str, out_npy: Path) -> dict:
    return embed_plays(emb, video, [(play, text, out_npy)])


def write_index(game_dir: Path, plays: list[dict], texts: dict[str, str], model: str) -> dict:
    gd = Path(game_dir)
    rows = [
        {"id": p["id"], "t_start": p["t_start"], "t_end": p["t_end"],
         "event_ids": p.get("event_ids", []), "text": texts.get(p["id"], ""),
         "file": f"embeddings/{safe_id(p['id'])}.npy"}
        for p in plays
        if (gd / "embeddings" / f"{safe_id(p['id'])}.npy").is_file()
    ]  # fmt: skip
    doc = {"schema": SCHEMA, "model": model, "keyframes": KEYFRAMES, "plays": rows}
    (gd / INDEX).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


def _stems(text: str) -> set[str]:
    # ponytail: 5-letter prefix stemming (steals/steal, missed/misses); a real stemmer if needed
    return {w[:5] for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3}


def rank(
    game_dir: Path,
    index: dict,
    query_vec: list[float],
    event_ids=(),
    k: int = 5,
    query_text: str = "",
) -> list[dict]:
    """Top `k` plays for `query_vec`; plays holding one of the structured filter's
    `event_ids` first, then plays sharing more words with `query_text`, then similarity.
    The word tier exists because SigLIP's text tower barely separates short play texts
    and synthetic keyframes look alike (measured on the box, docs/evidence/M7/README.md)."""
    rows = index["plays"]
    picked = set(event_ids)
    if not rows:
        return []
    m = np.stack([np.load(Path(game_dir) / r["file"]) for r in rows])  # (N, 2, D)
    q = _unit(np.asarray(query_vec, np.float32))
    cos = m @ q  # (N, 2): image, text
    fused = np.zeros(len(rows))
    for j in range(2):
        order = np.argsort(-cos[:, j], kind="stable")
        fused[order] += 1.0 / (RRF_K + 1 + np.arange(len(rows)))
    qs = _stems(query_text)
    lex = [len(qs & _stems(r["text"])) for r in rows]

    def hit(r: dict) -> bool:
        return bool(picked & set(r.get("event_ids", ())))

    out = [
        {"play_id": r["id"], "t_start": r["t_start"], "t_end": r["t_end"], "text": r["text"],
         "filter_match": hit(r), "words": lex[i], "score": round(float(fused[i]), 5),
         "cos_image": round(float(cos[i, 0]), 4), "cos_text": round(float(cos[i, 1]), 4)}
        for i, r in enumerate(rows)
    ]  # fmt: skip
    out.sort(key=lambda r: (not r["filter_match"], -r["words"], -r["score"]))
    return out[:k]
