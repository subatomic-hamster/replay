#!/usr/bin/env python3
"""End-to-end smoke test of the LIVE cloud stack (D-80): the phone/TV flow against the
deployed API, with the hfbox remote runner doing the processing.

  POST /games (key) -> token checks -> multipart upload (token only) -> calib frame ->
  calibrate with the clip's ground-truth landmarks -> process -> poll until ready ->
  renditions/events/media Range checks; plus the TV web build and phone page config.

SYNTHETIC footage only (D-7/D-76): make the clip with `courtcam synth`, e.g.
  python -m courtcam.cli synth --out DIR --sport basketball --variant half \
      --duration 20 --seed 7 --size 1280x720
and pass DIR/clip.mp4 (its landmarks.json sits next to it).

Usage (on hfbox): replay_py <copy> scripts/cloud-smoke.py --api URL --web URL \
  --key-file /workspace/wt/replay-env/api-key --clip DIR/clip.mp4
The key is read from --key-file and never printed. Exit code 1 if any step fails.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

RESULTS: list[tuple[str, bool, float, str]] = []


class Fail(Exception):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise Fail(msg)


def step(name: str, fn, *, fatal: bool = True):
    t0 = time.monotonic()
    try:
        out = fn()
        RESULTS.append((name, True, time.monotonic() - t0, ""))
        print(f"[PASS] {name} ({time.monotonic() - t0:.1f}s)", flush=True)
        return out
    except Exception as exc:  # report every failure, including HTTP/transport errors
        msg = f"{type(exc).__name__}: {exc}" if not isinstance(exc, Fail) else str(exc)
        RESULTS.append((name, False, time.monotonic() - t0, msg))
        print(f"[FAIL] {name} ({time.monotonic() - t0:.1f}s): {msg}", flush=True)
        if fatal:
            summary()
        return None


def summary() -> None:
    print("\n==== cloud smoke summary ====")
    for name, ok, dt, msg in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {dt:7.1f}s  {name}{'  -- ' + msg if msg else ''}")
    ok = all(r[1] for r in RESULTS)
    print(f"OVERALL: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


def body(r: httpx.Response) -> str:
    return r.text[:300].replace("\n", " ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--web", required=True)
    ap.add_argument("--key-file", required=True)
    ap.add_argument(
        "--clip", required=True, help="courtcam synth clip.mp4 (landmarks.json beside it)"
    )
    ap.add_argument("--timeout-min", type=float, default=25)
    ap.add_argument("--game", help="resume: skip steps 1-4, poll + check this game with the key")
    ap.add_argument("--runner-log", default="/workspace/wt/replay-env/runner.log")
    a = ap.parse_args()
    api, web = a.api.rstrip("/"), a.web.rstrip("/")
    key = Path(a.key_file).read_text().strip()
    clip = Path(a.clip)
    marks = json.loads((clip.parent / "landmarks.json").read_text())
    check("samples" not in clip.resolve().parts, "refusing a clip under samples/ (D-7/D-76)")

    # IPv4 only: hfbox resolves CloudFront AAAA records but has no IPv6 route, and httpx
    # tries every address in turn with no happy-eyeballs fallback (minutes per request).
    c = httpx.Client(timeout=60, transport=httpx.HTTPTransport(local_address="0.0.0.0"))
    KEY = {"X-Replay-Key": key}
    st: dict = {}

    # 0. static web: TV build + phone page, config.json apiBase == API
    def web_checks():
        for page, cfg in (
            (f"{web}/tvapp/", f"{web}/tvapp/config.json"),
            (f"{web}/", f"{web}/config.json"),
        ):
            r = c.get(page)
            check(r.status_code == 200 and "<html" in r.text.lower(), f"{page} -> {r.status_code}")
            r = c.get(cfg)
            check(r.status_code == 200, f"{cfg} -> {r.status_code}")
            base = (r.json().get("apiBase") or "").rstrip("/")
            check(base == api, f"{cfg} apiBase {base!r} != {api!r}")

    step("web: /tvapp/ + / load, config.json apiBase == API", web_checks, fatal=False)

    # 1. create the game with the app key
    def create():
        r = c.post(
            f"{api}/games",
            headers=KEY,
            json={"title": "cloud smoke (synthetic)", "sport": "basketball"},
        )
        check(r.status_code == 201, f"POST /games -> {r.status_code} {body(r)}")
        g = r.json()
        check(bool(g.get("upload_token")), "no upload_token")
        page = urlparse(g.get("upload_page_url") or "")
        check(
            page.netloc == urlparse(web).netloc, f"upload_page_url host {page.netloc!r} != web host"
        )
        check(page.path.rstrip("/") == f"/u/{g['id']}", f"upload_page_url path {page.path!r}")
        check(
            page.fragment == f"t={g['upload_token']}",
            "token is not in the upload_page_url fragment",
        )
        check((g.get("upload") or {}).get("mode") == "multipart", f"upload {g.get('upload')}")
        st.update(id=g["id"], token=g["upload_token"], page=g["upload_page_url"])
        print(f"      game {g['id']}", flush=True)

    fresh = not a.game
    if fresh:
        step("1 POST /games (key): token, upload_page_url, multipart", create)
        gid, TOK = st["id"], {"X-Replay-Upload-Token": st["token"]}
    else:
        gid, TOK = a.game, KEY

    def phone_page():
        r = c.get(st["page"].split("#")[0])
        check(r.status_code == 200 and "<html" in r.text.lower(), f"phone page -> {r.status_code}")

    if fresh:
        step("web: phone page /u/{id} loads (200)", phone_page, fatal=False)

    # 2. auth: nothing, token on another game, tampered token
    def tokens():
        r = c.get(f"{api}/games/{gid}")
        check(r.status_code == 401, f"no key/token -> {r.status_code}")
        r = c.get(f"{api}/games/{gid}", headers=TOK)
        check(r.status_code == 200, f"own token -> {r.status_code}")
        r = c.get(f"{api}/games/g_not_this_game", headers=TOK)
        check(r.status_code == 401, f"token on another game id -> {r.status_code}")
        r = c.post(f"{api}/games/g_not_this_game/process", headers=TOK)
        check(r.status_code == 401, f"token POST on another game id -> {r.status_code}")
        t = st["token"]
        i = len(t) // 2
        bad = t[:i] + ("A" if t[i] != "A" else "B") + t[i + 1 :]
        r = c.get(f"{api}/games/{gid}", headers={"X-Replay-Upload-Token": bad})
        check(r.status_code == 401, f"tampered token -> {r.status_code}")
        r = c.get(f"{api}/games", headers=TOK)
        check(r.status_code == 401, f"token on GET /games (list) -> {r.status_code}")

    if fresh:
        step("2 token checks (none/other game/tampered -> 401)", tokens)

    # 3. multipart upload with the token only
    def upload():
        data = clip.read_bytes()
        r = c.post(
            f"{api}/games/{gid}/upload/multipart",
            headers=TOK,
            json={"size": len(data), "content_type": "video/mp4"},
        )
        check(r.status_code == 200, f"multipart init -> {r.status_code} {body(r)}")
        init = r.json()
        size, parts = init["part_size"], []
        for p in init["parts"]:
            chunk = data[(p["n"] - 1) * size : p["n"] * size]
            pr = c.put(p["url"], content=chunk, timeout=300)
            check(pr.status_code == 200, f"PUT part {p['n']} -> {pr.status_code} {body(pr)}")
            parts.append({"n": p["n"], "etag": pr.headers["etag"]})
        r = c.post(
            f"{api}/games/{gid}/upload/complete",
            headers=TOK,
            json={"upload_id": init["upload_id"], "parts": parts},
        )
        check(r.status_code == 200, f"complete -> {r.status_code} {body(r)}")
        check(r.json().get("status") == "uploaded", f"status {r.json().get('status')}")
        print(f"      {len(data)} bytes in {len(parts)} part(s)", flush=True)
        g = c.get(f"{api}/games/{gid}", headers=TOK).json()
        check(g.get("status") == "uploaded", f"GET status {g.get('status')}")
        r = c.get(f"{api}/media/games/{gid}/media/calib.jpg")
        check(r.status_code == 302, f"calib.jpg -> {r.status_code}, want 302")
        loc = r.headers["location"]
        check(
            ".s3." in urlparse(loc).netloc or "amazonaws.com" in loc,
            f"calib.jpg redirects to {urlparse(loc).netloc}",
        )
        img = c.get(loc)
        check(
            img.status_code == 200 and img.content[:2] == b"\xff\xd8",
            f"calib.jpg download {img.status_code}",
        )
        r = c.get(f"{api}/media/games/{gid}/source.mp4")
        check(r.status_code == 404, f"source.mp4 -> {r.status_code}, want 404")

    if fresh:
        step("3 multipart upload (token) + calib.jpg 302->S3 + source.mp4 404", upload)

    # 4. calibrate with the synthetic ground truth, then process
    def calibrate_process():
        r = c.post(
            f"{api}/games/{gid}/calibration",
            headers=TOK,
            json={
                "sport": marks["sport"],
                "variant": marks["variant"],
                "landmarks_px": marks["landmarks_px"],
            },
        )
        check(r.status_code == 200, f"calibration -> {r.status_code} {body(r)}")
        print(f"      reprojection_error_px {r.json().get('reprojection_error_px')}", flush=True)
        r = c.post(f"{api}/games/{gid}/process", headers=TOK)
        check(r.status_code == 202, f"process -> {r.status_code} {body(r)}")
        print(f"      job {r.json().get('job_id')} {r.json().get('status')}", flush=True)

    if fresh:
        step("4 calibrate (ground truth) + process (token)", calibrate_process)

    # 5. poll until ready/failed; tail the runner log alongside
    log = Path(a.runner_log)
    log_pos = log.stat().st_size if log.is_file() else 0

    def tail_runner():
        nonlocal log_pos
        if not log.is_file():
            return
        with log.open() as f:
            f.seek(log_pos)
            for line in f.read().splitlines():
                print(f"      runner| {line}", flush=True)
            log_pos = f.tell()

    def poll():
        t0, last = time.monotonic(), None
        while time.monotonic() - t0 < a.timeout_min * 60:
            r = c.get(f"{api}/games/{gid}", headers=TOK)
            check(r.status_code == 200, f"GET game -> {r.status_code} {body(r)}")
            g = r.json()
            now = (g.get("status"), json.dumps(g.get("stages")), json.dumps(g.get("progress")))
            if now != last:
                print(
                    f"      +{time.monotonic() - t0:5.0f}s status={g.get('status')} "
                    f"stages={g.get('stages')} progress={g.get('progress')}",
                    flush=True,
                )
                last = now
            tail_runner()
            if g.get("status") in ("ready", "failed"):
                jobs = c.get(f"{api}/games/{gid}/jobs", headers=TOK).json()
                check(g["status"] == "ready", f"failed: {[j.get('error') for j in jobs]}")
                st["processing_s"] = time.monotonic() - t0
                print(f"      processing took {st['processing_s']:.0f}s", flush=True)
                return
            time.sleep(10)
        raise Fail(f"not ready after {a.timeout_min} min")

    step("5 poll until ready", poll)
    tail_runner()

    # 6. the finished game: renditions, events, media Range
    def finished():
        g = c.get(f"{api}/games/{gid}", headers=TOK).json()
        rend = g.get("renditions") or {}
        print(f"      renditions: {sorted(rend)}", flush=True)
        wide = rend.get("wide")
        check(isinstance(wide, str) and wide.startswith("http"), f"no wide rendition URL: {wide!r}")
        ev_url = g.get("events_url")
        check(bool(ev_url), "no events_url")
        r = c.get(ev_url, follow_redirects=True)
        check(r.status_code == 200, f"events -> {r.status_code}")
        ev = r.json()
        ev = ev.get("events", ev) if isinstance(ev, dict) else ev
        print(f"      events: {len(ev)} ({sorted({e.get('type') for e in ev})})", flush=True)
        check(len(ev) > 0, "no events")
        r = c.get(wide)
        check(r.status_code == 302, f"wide -> {r.status_code}, want 302")
        r = c.get(r.headers["location"], headers={"Range": "bytes=0-1023"})
        check(
            r.status_code == 206 and len(r.content) == 1024,
            f"wide Range -> {r.status_code}, {len(r.content)} B",
        )
        check(r.content[4:8] == b"ftyp", "wide rendition is not an MP4")

    step("6 ready game: renditions, events, wide 302 + Range 206", finished)

    print(f"\ngame {gid}  processing {st.get('processing_s', 0):.0f}s")
    summary()


if __name__ == "__main__":
    main()
