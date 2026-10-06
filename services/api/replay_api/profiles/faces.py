"""Match a game's tracked players against ENROLLED faces only (opt-in, vision §21).

For each rostered player, up to SAMPLES frames where their box is tallest (≥ GAP_S apart)
are read from the wide rendition; the head region of the box is searched for a face, and
each embeddable face is compared with the enrolled profiles' embeddings only. Nothing about
an unmatched player is kept (no crop, no embedding, no cluster): `faces.json` stores only
counts and, for a player whose face hits one enrolled profile often enough, a suggestion
`{player_id, profile_id, similarity, votes}` that a person must confirm with the link
route. With no enrolled profile the video is never opened.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from . import career

SCHEMA = "replay.faces.v1"
REL = "faces.json"
SAMPLES = 12
GAP_S = 1.0
HEAD = 0.45  # top fraction of the person box searched for the face
MIN_VOTES = 2
MIN_SHARE = 0.5


def sample_boxes(game_dir: Path, player_ids: set[str]) -> dict[str, list[tuple[float, list]]]:
    """Per player: (t, bb) of the tallest boxes, at least GAP_S apart, in time order."""
    allb: dict[str, list[tuple[float, list]]] = {pid: [] for pid in player_ids}
    for f in career.frames(game_dir):
        for p in f.get("p", []):
            if p.get("id") in allb and p.get("bb"):
                allb[p["id"]].append((float(f["t"]), p["bb"]))
    out = {}
    for pid, boxes in allb.items():
        pick: list[tuple[float, list]] = []
        for t, bb in sorted(boxes, key=lambda x: (-x[1][3], x[0])):
            if all(abs(t - u) >= GAP_S for u, _ in pick):
                pick.append((t, bb))
            if len(pick) >= SAMPLES:
                break
        out[pid] = sorted(pick)
    return out


def head_crop(frame, bb: list[float], upscale_to: int = 320):
    """The head region of a normalised person box, padded and upscaled so YuNet's
    minimum face size is not the limit (the source resolution still is)."""
    import cv2

    H, W = frame.shape[:2]
    x, y, w, h = bb[0] * W, bb[1] * H, bb[2] * W, bb[3] * H
    pad = 0.25 * w
    x0, x1 = int(max(0, x - pad)), int(min(W, x + w + pad))
    y0, y1 = int(max(0, y - 0.1 * h)), int(min(H, y + HEAD * h))
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return None, 1.0
    s = max(1.0, upscale_to / max(crop.shape[:2]))
    if s > 1.0:
        crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    return crop, s


def match_game(game_dir: Path, face) -> dict:
    """`faces.json` for a game: suggestions for enrolled profiles only."""
    game_dir = Path(game_dir)
    game = json.loads((game_dir / "game.json").read_text())
    enrolled = face.enrolled()
    doc = {"schema": SCHEMA, "game_id": game.get("id"), "enrolled_profiles": len(enrolled),
           "threshold": face.threshold, "min_face_px": face.min_face_px, "players_checked": 0,
           "samples": 0, "faces_detected": 0, "samples_with_face": 0, "matches": []}  # fmt: skip
    if not enrolled:
        doc["skipped"] = "no enrolled profiles"
        return doc
    import cv2

    wide = game_dir / ((game.get("renditions") or {}).get("wide") or "media/wide.mp4")
    boxes = sample_boxes(game_dir, {p["id"] for p in game.get("players") or []})
    cap = cv2.VideoCapture(str(wide))
    hits: dict[str, list[dict]] = {}
    usable: dict[str, int] = {}  # samples with an embeddable face, per player
    try:
        reads = sorted((t, pid, bb) for pid, bs in boxes.items() for t, bb in bs)
        for t, pid, bb in reads:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok:
                continue
            crop, s = head_crop(frame, bb)
            if crop is None:
                continue
            doc["samples"] += 1
            faces = face.detect(crop)
            for f in faces:  # judge face size in source pixels, not upscaled ones
                if f["e"] is not None and f["box"][2] / s < face.min_face_px:
                    f["e"] = None
            doc["faces_detected"] += len(faces)
            if any(f["e"] is not None for f in faces):
                doc["samples_with_face"] += 1
                usable[pid] = usable.get(pid, 0) + 1
                hits.setdefault(pid, []).extend(face.match(faces, enrolled)[:1])
    finally:
        cap.release()
    doc["players_checked"] = len(boxes)
    for pid in sorted(hits):
        win = decide([h["profile_id"] for h in hits[pid]], usable[pid])
        if win:
            sims = [h["similarity"] for h in hits[pid] if h["profile_id"] == win[0]]
            doc["matches"].append({"player_id": pid, "profile_id": win[0], "votes": win[1],
                                   "usable": usable[pid], "similarity": round(max(sims), 3)})  # fmt: skip
    return doc


def decide(hits: list[str], usable: int) -> tuple[str, int] | None:
    """(profile, votes) when one enrolled profile won at least MIN_VOTES of the player's
    samples AND at least MIN_SHARE of the samples that had a usable face, else None.
    The share rule is what keeps unenrolled players out: on CC footage single faces of
    an unenrolled player still cross the threshold now and then (docs/evidence/M10)."""
    votes = Counter(hits)
    if not votes:
        return None
    prof, n = votes.most_common(1)[0]
    return (prof, n) if n >= MIN_VOTES and n >= MIN_SHARE * usable else None
