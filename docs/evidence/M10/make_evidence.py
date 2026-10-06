"""M10 evidence driver — run on hfbox (commands and results: README.md next to this file).

PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker:$d/render python make_evidence.py <cmd> ...

  games <src_root> <data_dir> NAME=SRC...   copy synthetic GT game dirs into an API data dir
                                            (new ids g_<NAME>) and compute hype.json
  cards <data_dir> <out_dir> [--llm]        profiles + links + a user correction through the
                                            API; writes profile / card / reel JSON + card PNGs
  faceyield <out.json> VIDEO...             share of detected people that yield a usable face
  facematch <out.json> VIDEO [--t0 --dur]   tracked people as pseudo-identities: enroll half,
                                            probe everyone, genuine vs unenrolled match rates

Face metrics never store crops or embeddings: everything stays in memory and only counts
and similarity statistics are written. Model config: REPLAY_FACE_MODELS (YuNet + SFace),
YOLO weights via --yolo (person boxes for the face metrics only).
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from replay_api.config import from_env
from replay_api.main import create_app
from replay_api.profiles import card as K
from replay_api.profiles import faces as F
from replay_api.providers.face import LocalFace

YOLO = "/workspace/wt/replay-env/models/yolo/yolo11m.pt"


def cmd_games(a) -> None:
    from replay_render.gamedata import load_game
    from replay_render.hype import REL, hype_series

    games = Path(a.data_dir) / "games"
    for i, spec in enumerate(a.pairs):
        name, src = spec.split("=", 1)
        gd = games / f"g_{name}"
        shutil.rmtree(gd, ignore_errors=True)
        shutil.copytree(Path(a.src_root) / src, gd, ignore=shutil.ignore_patterns("_work"))
        game = json.loads((gd / "game.json").read_text())
        game.update(id=gd.name, title=f"Synthetic {src}", recorded_at=f"2026-10-0{i + 1}T18:00")
        (gd / "game.json").write_text(json.dumps(game, indent=1))
        (gd / REL).write_text(json.dumps(hype_series(load_game(gd))))
        print(gd.name, game["sport"], len(game["players"]), "players")


def _top(client, gid: str, key: str, sign: int = 1) -> str:
    rows = client.get(f"/games/{gid}/stats").json()["box_score"]
    return max(rows, key=lambda r: (sign * r[key], r["player_id"]))["player_id"]


def cmd_cards(a) -> None:
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    settings = from_env(data_dir=Path(a.data_dir), pipeline="fake", api_key=None)
    llm = "true" if a.llm else "false"
    report = {}
    with TestClient(create_app(settings)) as c:
        games = sorted(g["id"] for g in c.get("/games").json())
        bb = [g for g in games if g.startswith("g_bb")]
        bd = [g for g in games if g.startswith("g_bd")]
        plan = {
            # synthetic: the "same person" is whoever scored most in each game
            "Alex": [(g, _top(c, g, "points")) for g in bb],
            "Sam": [(g, _top(c, g, "distance_m")) for g in bd],
            # a two-sport profile: least-moving player of a basketball and a badminton game
            "Jordan": [
                (bb[0], _top(c, bb[0], "distance_m", -1)),
                (bd[0], _top(c, bd[0], "distance_m", -1)),
            ],
        }
        for name, links in plan.items():
            t0 = time.time()
            pid = c.post("/profiles", json={"name": name, "positions": []}).json()["profile_id"]
            for gid, player in links:
                r = c.post(f"/profiles/{pid}/links", json={"game_id": gid, "player_id": player})
                assert r.status_code == 200, r.text
            if name == "Alex":  # a user correction: shown, flagged, auto value kept
                c.patch(f"/profiles/{pid}", json={"positions": ["guard"],
                                                  "stats": {"basketball": {"rebounds": 4}}})  # fmt: skip
            prof = c.get(f"/profiles/{pid}").json()
            card = c.post(f"/profiles/{pid}/card?llm={llm}").json()
            again = c.get(f"/profiles/{pid}/card?llm={llm}").json()
            again.pop("rendered"), card.pop("rendered")
            reel = c.get(f"/profiles/{pid}/reel").json()
            sug = c.get(f"/profiles/{pid}/suggestions").json()
            slug = name.lower()
            for kind, doc in (("profile", prof), ("card", card), ("reel", reel)):
                (out / f"{kind}_{slug}.json").write_text(json.dumps(doc, indent=1))
            # the API's PNG, re-drawn from the same card + thumb with a "synthetic" label
            thumb = settings.data_dir / "profiles" / pid / "thumb.jpg"
            img = Image.open(thumb).convert("RGB") if thumb.is_file() else None
            K.render_png(card, img, out / f"card_{slug}.png", note="synthetic data")
            report[name] = {
                "links": len(links),
                "sports": prof["sports"],
                "title": card["title"],
                "title_source": card["title_source"],
                "template_ok": card["grounding"]["template_ok"],
                "llm": card.get("llm"),
                "card_json_deterministic": json.dumps(card, sort_keys=True)
                == json.dumps(again, sort_keys=True),
                "reel_items": len(reel["items"]),
                "suggestions": len(sug["suggestions"]),
                "user_edited_fields": prof["user_edited_fields"],
                "wall_s": round(time.time() - t0, 2),
            }
    (out / "cards_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


# --- face metrics --------------------------------------------------------------------------


def _people(model, frame, imgsz: int) -> list[list[float]]:
    r = model.predict(frame, classes=[0], imgsz=imgsz, conf=0.3, verbose=False)[0]
    H, W = frame.shape[:2]
    return [[x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H]
            for x0, y0, x1, y1 in r.boxes.xyxy.cpu().numpy().tolist()]  # fmt: skip


def _faces(face: LocalFace, frame, bb):
    crop, s = F.head_crop(frame, bb)
    if crop is None:
        return []
    faces = face.detect(crop)
    for f in faces:
        f["px"] = f["box"][2] / s
        if f["e"] is not None and f["px"] < face.min_face_px:
            f["e"] = None
    return faces


def _pct(xs: list[float], q: float):
    return round(sorted(xs)[min(len(xs) - 1, int(q * len(xs)))], 1) if xs else None


def _q(xs: list[float], qs: tuple[int, ...]):
    import numpy as np

    return [round(float(np.percentile(xs, q)), 3) for q in qs] if xs else None


def cmd_faceyield(a) -> None:
    import cv2
    from ultralytics import YOLO as Y

    model, face = Y(a.yolo), LocalFace(store_dir=Path("/nonexistent"))
    res = {}
    for video in a.videos:
        cap = cv2.VideoCapture(video)
        dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
        n = {"frames": 0, "people": 0, "face_detected": 0, "face_usable": 0}
        heights, widths = [], []
        t = 0.0
        while t < dur:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            t += a.every
            if not ok:
                continue
            n["frames"] += 1
            for bb in _people(model, frame, a.imgsz):
                n["people"] += 1
                heights.append(bb[3] * frame.shape[0])
                faces = _faces(face, frame, bb)
                if faces:
                    n["face_detected"] += 1
                    best = max(faces, key=lambda f: f["px"])
                    widths.append(best["px"])
                    n["face_usable"] += best["e"] is not None
        cap.release()
        key = "/".join(Path(video).parts[-3:])  # g_bb1/media/wide.mp4, not just wide.mp4
        res[key] = {
            **n,
            "usable_share": round(n["face_usable"] / max(1, n["people"]), 3),
            "detected_share": round(n["face_detected"] / max(1, n["people"]), 3),
            "person_height_px_p10_p50_p90": [_pct(heights, q) for q in (0.1, 0.5, 0.9)],
            "face_width_px_p10_p50_p90": [_pct(widths, q) for q in (0.1, 0.5, 0.9)],
            "sample_every_s": a.every,
            "min_face_px": face.min_face_px,
        }
        print(key, json.dumps(res[key]))
    Path(a.out).write_text(json.dumps(res, indent=1))


def _collect(a) -> tuple[dict, dict]:
    """Track people (ByteTrack) and embed their usable faces: ({tid: [(t, e)]}, info).
    `--dump DIR` writes one face contact sheet per track for hand labelling (box-local,
    never committed); `--cache F.npz` keeps the embeddings between the labelling passes
    (delete it afterwards)."""
    import cv2
    import numpy as np
    from ultralytics import YOLO as Y

    if a.cache and Path(a.cache).is_file():
        z = np.load(a.cache)
        per: dict = {}
        for tid, t, e in zip(z["tid"].tolist(), z["t"].tolist(), z["e"]):
            per.setdefault(tid, []).append((t, e))
        return per, json.loads(str(z["info"]))
    model, face = Y(a.yolo), LocalFace(store_dir=Path("/nonexistent"))
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_MSEC, a.t0 * 1000)
    per, seen, sheets = {}, set(), {}
    i, t0 = 0, time.time()
    while True:
        ok, frame = cap.read()
        t = a.t0 + i / fps
        i += 1
        if not ok or t > a.t0 + a.dur:
            break
        if (i - 1) % a.stride:
            continue
        r = model.track(frame, classes=[0], imgsz=a.imgsz, conf=0.3, persist=True,
                        tracker="bytetrack.yaml", verbose=False)[0]  # fmt: skip
        if r.boxes.id is None or ((i - 1) // a.stride) % a.face_every:
            continue
        H, W = frame.shape[:2]
        for (x0, y0, x1, y1), tid in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.id.int().tolist()):
            seen.add(tid)
            bb = [x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H]
            usable = [f for f in _faces(face, frame, bb) if f["e"] is not None]
            if not usable:
                continue
            f = max(usable, key=lambda f: f["px"])
            per.setdefault(tid, []).append((round(t, 2), np.array(f["e"])))
            if a.dump and len(sheets.setdefault(tid, [])) < 12:
                crop, _ = F.head_crop(frame, bb)
                x, y, w, h = (int(v) for v in f["box"])
                sheets[tid].append(cv2.resize(crop[max(0, y) : y + h, max(0, x) : x + w], (64, 64)))
    cap.release()
    info = {"tracks_seen": len(seen), "track_and_embed_s": round(time.time() - t0, 1)}
    if a.dump:
        Path(a.dump).mkdir(parents=True, exist_ok=True)
        for tid, crops in sheets.items():
            span = f"{per[tid][0][0]:.0f}-{per[tid][-1][0]:.0f}s_n{len(per[tid])}"
            cv2.imwrite(str(Path(a.dump) / f"track_{tid:04d}_{span}.jpg"), np.hstack(crops))
    if a.cache:
        rows = [(tid, t, e) for tid, fs in per.items() for t, e in fs]
        np.savez(a.cache, tid=np.array([r[0] for r in rows]), t=np.array([r[1] for r in rows]),
                 e=np.array([r[2] for r in rows]), info=json.dumps(info))  # fmt: skip
    return per, info


def _evaluate(people: dict, enrolled: list, a) -> dict:
    """Enroll `enrolled` from their first faces; every later face of theirs is a genuine
    probe, every face of everyone else an unenrolled probe."""
    import numpy as np

    gallery, probes = {}, []
    for pid in enrolled:
        fs = people[pid]
        e = np.mean([v for _, v in fs[: a.enroll_n]], axis=0)
        gallery[pid] = e / np.linalg.norm(e)
        t_enr = fs[a.enroll_n - 1][0]
        probes += [(pid, True, v) for t, v in fs[a.enroll_n :] if t - t_enr >= 2.0]
    if not gallery:
        return {"enrolled": [], "note": "no eligible person to enroll"}
    probes += [(pid, False, v) for pid, fs in people.items() if pid not in gallery for _, v in fs]
    sims = [(pid, enr, {g: float(v @ e) for g, e in gallery.items()}) for pid, enr, v in probes]
    gen, unk = [s for s in sims if s[1]], [s for s in sims if not s[1]]
    sweep = {}
    for thr in (0.3, 0.363, 0.4, 0.45, 0.5, 0.6):

        def best(s):
            g = max(s[2], key=s[2].get)
            return g if s[2][g] >= thr else None  # noqa: B023

        def share(xs, pred):
            return round(sum(1 for s in xs if pred(s)) / len(xs), 3) if xs else None

        sweep[str(thr)] = {
            "genuine_correct": share(gen, lambda s: best(s) == s[0]),
            "genuine_wrong_profile": share(gen, lambda s: best(s) not in (None, s[0])),
            "unenrolled_face_matched": share(unk, lambda s: best(s) is not None),
        }
        # the game matcher's decision (faces.decide) over windows of F.SAMPLES consecutive
        # usable faces of one person, i.e. one game's worth of samples for one player
        for name, xs in (("genuine", gen), ("unenrolled", unk)):
            wins = []
            for pid in sorted({s[0] for s in xs}):
                mine = [s for s in xs if s[0] == pid]
                for k in range(0, len(mine) - F.SAMPLES + 1, F.SAMPLES):
                    w = mine[k : k + F.SAMPLES]
                    hits = [b for b in map(best, w) if b is not None]
                    wins.append((pid, F.decide(hits, len(w))))
            sweep[str(thr)][f"{name}_windows"] = len(wins)
            sweep[str(thr)][f"{name}_windows_suggested"] = sum(1 for _, d in wins if d)
            sweep[str(thr)][f"{name}_windows_suggested_right"] = sum(
                1 for pid, d in wins if d and d[0] == pid
            )
    return {
        "enrolled": sorted(map(str, gallery)),
        "unenrolled_people": len({s[0] for s in unk}),
        "genuine_probes": len(gen),
        "unenrolled_probes": len(unk),
        "genuine_similarity_p10_p50_p90": _q([s[2][s[0]] for s in gen], (10, 50, 90)),
        "unenrolled_best_similarity_p50_p90_p99": _q(
            [max(s[2].values()) for s in unk], (50, 90, 99)
        ),
        "sweep": sweep,
    }


def cmd_facematch(a) -> None:
    per, info = _collect(a)
    labels = json.loads(Path(a.labels).read_text()) if a.labels else None
    people: dict = {}
    for tid, fs in per.items():
        who = labels.get(str(tid), "x") if labels else str(tid)
        if who != "x":  # "x": not a single clear person (mixed track, false face)
            people.setdefault(who, []).extend(fs)
    for fs in people.values():
        fs.sort(key=lambda x: x[0])
    eligible = sorted(p for p, fs in people.items()
                      if len(fs) >= a.min_faces and fs[-1][0] - fs[0][0] >= 4.0)  # fmt: skip
    res = {
        "video": Path(a.video).name,
        "segment_s": [a.t0, a.t0 + a.dur],
        "stride": a.stride,
        **info,
        "tracks_with_usable_face": len(per),
        "usable_faces": sum(len(v) for v in per.values()),
        "labels": "hand-labelled persons (track contact sheets)"
        if labels
        else "pseudo-identities = ByteTrack track ids (an id switch or fragment counts as an error)",
        "people": len(people),
        "eligible_people": len(eligible),
        # two folds: each eligible person is enrolled in one and unenrolled in the other
        "folds": [_evaluate(people, eligible[k::2], a) for k in (0, 1)],
    }
    print(json.dumps(res, indent=1))
    Path(a.out).write_text(json.dumps(res, indent=1))


def cmd_gamematch(a) -> None:
    """End to end through the product path: a game dir with YOLO+ByteTrack tracks over
    [0, dur] of a CC clip; the longest track's head crops from [0, enroll_s] are the
    enrollment photos (temp files, deleted); faces.match_game then runs on the tracks
    after enroll_s only. `--dump` writes one strip per suggested player for an eye check."""
    import tempfile

    import cv2
    from ultralytics import YOLO as Y

    model = Y(a.yolo)
    with tempfile.TemporaryDirectory(prefix="m10-gm-", dir=a.tmp) as tmp:
        gd, store = Path(tmp) / "g_cc", Path(tmp) / "store"
        (gd / "tracks").mkdir(parents=True)
        (gd / "media").mkdir()
        (gd / "media" / "wide.mp4").symlink_to(Path(a.video).resolve())
        cap = cv2.VideoCapture(a.video)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frames, i = [], 0
        while True:
            ok, frame = cap.read()
            t = i / fps
            i += 1
            if not ok or t > a.dur:
                break
            if (i - 1) % a.stride:
                continue
            r = model.track(frame, classes=[0], imgsz=a.imgsz, conf=0.3, persist=True,
                            tracker="bytetrack.yaml", verbose=False)[0]  # fmt: skip
            if r.boxes.id is None:
                continue
            H, W = frame.shape[:2]
            frames.append({"t": round(t, 3), "frame": frame if t <= a.enroll_s else None, "p": [
                {"id": f"t{tid}", "bb": [x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H], "c": 0.9}
                for (x0, y0, x1, y1), tid in zip(r.boxes.xyxy.cpu().numpy().tolist(),
                                                 r.boxes.id.int().tolist())]})  # fmt: skip
        cap.release()
        early = [f for f in frames if f["t"] <= a.enroll_s]
        counts: dict[str, int] = {}
        for f in early:
            for p in f["p"]:
                counts[p["id"]] = counts.get(p["id"], 0) + 1
        who = max(counts, key=counts.get)
        photos = []
        for k, f in enumerate(early[:: max(1, len(early) // 8)]):
            bb = next((p["bb"] for p in f["p"] if p["id"] == who), None)
            if bb:
                crop, _ = F.head_crop(f["frame"], bb)
                photos.append(Path(tmp) / f"photo{k}.jpg")
                cv2.imwrite(str(photos[-1]), crop)
        face = LocalFace(store_dir=store)
        enr = face.enroll("pr_cc_enrolled", photos)
        late = [{"t": f["t"], "p": f["p"]} for f in frames if f["t"] > a.enroll_s]
        players = sorted({p["id"] for f in late for p in f["p"]})
        (gd / "tracks" / "00000.json").write_text(json.dumps({"frames": late}))
        game = {"id": "g_cc", "players": [{"id": p} for p in players],
                "renditions": {"wide": "media/wide.mp4"}}  # fmt: skip
        (gd / "game.json").write_text(json.dumps(game))
        t0 = time.time()
        doc = F.match_game(gd, face)
        doc["match_s"] = round(time.time() - t0, 1)
        if a.dump:  # eye check of what was suggested (box-local, never committed)
            Path(a.dump).mkdir(parents=True, exist_ok=True)
            cap = cv2.VideoCapture(a.video)
            boxes = F.sample_boxes(gd, {m["player_id"] for m in doc["matches"]} | {who})
            for pid, bs in boxes.items():
                strip = []
                for t, bb in bs[:8]:
                    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                    ok, fr = cap.read()
                    if ok:
                        strip.append(cv2.resize(F.head_crop(fr, bb)[0], (96, 96)))
                if strip:
                    cv2.imwrite(str(Path(a.dump) / f"{pid}.jpg"), cv2.hconcat(strip))
            cap.release()
    res = {"video": Path(a.video).name, "segment_s": [0, a.dur], "enroll_s": a.enroll_s,
           "enrolled_track": who, "enrollment": enr, "players_after_enroll": len(players),
           "faces_json": doc}  # fmt: skip
    print(json.dumps(res, indent=1))
    Path(a.out).write_text(json.dumps(res, indent=1))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(required=True)
    g = sub.add_parser("games")
    g.add_argument("src_root")
    g.add_argument("data_dir")
    g.add_argument("pairs", nargs="+")
    g.set_defaults(fn=cmd_games)
    c = sub.add_parser("cards")
    c.add_argument("data_dir")
    c.add_argument("out_dir")
    c.add_argument("--llm", action="store_true")
    c.set_defaults(fn=cmd_cards)
    y = sub.add_parser("faceyield")
    y.add_argument("out")
    y.add_argument("videos", nargs="+")
    y.add_argument("--every", type=float, default=2.0)
    y.add_argument("--imgsz", type=int, default=1280)
    y.add_argument("--yolo", default=YOLO)
    y.set_defaults(fn=cmd_faceyield)
    m = sub.add_parser("facematch")
    m.add_argument("out")
    m.add_argument("video")
    m.add_argument("--t0", type=float, default=0.0)
    m.add_argument("--dur", type=float, default=60.0)
    m.add_argument("--stride", type=int, default=2)
    m.add_argument("--face-every", type=int, default=3)
    m.add_argument("--imgsz", type=int, default=1280)
    m.add_argument("--min-faces", type=int, default=6)
    m.add_argument("--enroll-n", type=int, default=3)
    m.add_argument("--yolo", default=YOLO)
    m.add_argument("--dump", help="box-local dir for per-track face contact sheets")
    m.add_argument("--cache", help="box-local .npz of the embeddings (delete afterwards)")
    m.add_argument("--labels", help='{"<track id>": "<person>" | "x"} from the contact sheets')
    m.set_defaults(fn=cmd_facematch)
    e = sub.add_parser("gamematch")
    e.add_argument("out")
    e.add_argument("video")
    e.add_argument("--dur", type=float, default=60.0)
    e.add_argument("--enroll-s", type=float, default=10.0)
    e.add_argument("--stride", type=int, default=2)
    e.add_argument("--imgsz", type=int, default=1280)
    e.add_argument("--yolo", default=YOLO)
    e.add_argument("--tmp", help="parent dir for the temporary game + enrollment store")
    e.add_argument("--dump", help="box-local dir for strips of the suggested players")
    e.set_defaults(fn=cmd_gamematch)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
