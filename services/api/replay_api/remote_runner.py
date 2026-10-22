"""hfbox remote runner (D-80, docs/aws-migration.md "Jobs and the remote worker").

    REPLAY_WORKER_KEY=... REPLAY_DATA_DIR=/path/to/mirror \
      python -m replay_api.remote_runner --api https://<function-url> [--once]

Polls `POST /worker/claim` (every 30 s by default), mirrors the game folder from the
presigned GETs (a file with the claim's size is kept), runs the job through the same code
the local API runs (`main._process_task` -> pipeline_adapter, `main._autocalib_task`),
reports progress, uploads every new or changed file (size or mtime moved since the
mirror; game.json last), and finishes the job ok/failed. Media and the storyboard go up
after every stage while the job runs (`EARLY`), so a game is watchable mid-run. No AWS credentials: only the
worker key and presigned URLs. Transient HTTP failures are retried with backoff; a job
that still cannot be finished is logged and stays `running` in S3, never dropped.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import main
from . import pipeline_adapter as adapter
from .config import Settings, from_env
from .providers.index import GAME_JSON, LocalIndex
from .providers.storage import LocalStorage

log = logging.getLogger("replay_api.remote_runner")


class Transient(RuntimeError):
    """A 5xx / 429: worth retrying."""


def retry(what: str, fn: Callable, tries: int = 8, backoff_s: float = 2.0):
    for i in range(tries):
        try:
            return fn()
        except (httpx.TransportError, Transient) as exc:
            if i == tries - 1:
                raise
            wait = min(60.0, backoff_s * 2**i)
            log.warning("%s failed (%s); retrying in %.0f s", what, exc, wait)
            time.sleep(wait)
    return None


def _redact(url: httpx.URL | str) -> str:
    """A URL's path only: a presigned URL's query carries X-Amz-Security-Token and the
    signature, which must never reach runner.log or a job's error."""
    return httpx.URL(str(url)).path


def _checked(r: httpx.Response) -> httpx.Response:
    if r.status_code >= 500 or r.status_code == 429:
        raise Transient(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.is_error:  # not raise_for_status(): its message holds the full URL
        msg = f"HTTP {r.status_code} for {r.request.method} {_redact(r.request.url)}"
        raise httpx.HTTPStatusError(msg, request=r.request, response=r)
    return r


class Api:
    """The API's /worker routes. `client` is any httpx.Client with the API as base_url
    (tests pass a FastAPI TestClient); `http` fetches the presigned URLs."""

    def __init__(self, client: httpx.Client, key: str, http: httpx.Client, tries: int = 8,
                 backoff_s: float = 2.0):  # fmt: skip
        self.client, self.key, self.http = client, key, http
        self.tries, self.backoff_s = tries, backoff_s

    def post(self, path: str, body: dict | None = None, tries: int | None = None):
        def call():
            return _checked(
                self.client.post(path, json=body or {}, headers={"X-Replay-Worker-Key": self.key})
            )

        return retry(f"POST {path}", call, tries or self.tries, self.backoff_s)

    def download(self, url: str, dest: Path) -> None:
        def call():
            tmp = dest.with_name(dest.name + ".part")
            with self.http.stream("GET", url) as r:
                _checked(r)
                with tmp.open("wb") as fh:
                    for chunk in r.iter_bytes(1 << 20):
                        fh.write(chunk)
            tmp.replace(dest)

        log.info("GET %s", _redact(url))
        dest.parent.mkdir(parents=True, exist_ok=True)
        retry(f"GET {dest.name}", call, self.tries, self.backoff_s)

    def upload(self, url: str, src: Path) -> None:
        # ponytail: one PUT per file (S3 caps it at 5 GB); multipart if outputs outgrow it
        def call():
            with src.open("rb") as fh:
                _checked(self.http.put(url, content=fh,
                                       headers={"Content-Length": str(src.stat().st_size)}))  # fmt: skip

        log.info("PUT %s", _redact(url))
        retry(f"PUT {src.name}", call, self.tries, self.backoff_s)


class _Progress:
    """The `jobs` the local task code reports to: progress goes to the API, best effort
    (a lost progress post must not fail a pipeline run). `on_stage_done(stage)` runs
    after each stage finishes (the early media push)."""

    def __init__(self, api: Api, on_stage_done: Callable[[str], None] | None = None):
        self.api = api
        self.on_stage_done = on_stage_done

    def progress(self, job_id: str, stage: str, fraction: float) -> None:
        if fraction >= 1.0 and self.on_stage_done:
            self.on_stage_done(stage)
        try:
            self.api.post(f"/worker/jobs/{job_id}/progress",
                          {"stage": stage, "fraction": fraction}, tries=2)  # fmt: skip
        except Exception as exc:  # noqa: BLE001
            log.warning("progress for %s not delivered (%s)", job_id, exc)


# Pushed while the job still runs, so the TV can play (wide.mp4 once ingest is done) and
# scrub (the storyboard) before the run ends. Everything else waits for the final push.
EARLY = ("media/", "storyboard/")
# one-stage jobs the runner takes (cloud.S3Jobs.STAGES)
STAGE_JOBS = ("reel", "condensed", "vertical")


class _EarlyPush:
    """After each stage, upload new or changed files under EARLY in a background thread
    (one push at a time, in order), so a multi-GB mezzanine never stalls the pipeline.
    `before` is updated with what went up, so the final push skips it. A file caught
    mid-write goes up again at the end (its size/mtime moved)."""

    def __init__(self, api: Api, job_id: str, root: Path, before: dict):
        self.api, self.job_id, self.root, self.before = api, job_id, root, before
        self.pool = ThreadPoolExecutor(1, "replay-early-push")

    def __call__(self, stage: str) -> None:
        self.pool.submit(self._push)

    def _push(self) -> None:
        try:
            # taken before the push: a file that moves meanwhile just goes up again later
            snap = {r: st for r, st in _snapshot(self.root).items() if r.startswith(EARLY)}
            push(self.api, self.job_id, self.root, self.before, only=EARLY)
            self.before.update(snap)
        except Exception as exc:  # noqa: BLE001 - the final push still uploads it
            log.warning("early push for %s failed (%s)", self.job_id, exc)

    def close(self) -> None:
        self.pool.shutdown(wait=True)


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file() and not p.name.endswith((".tmp", ".part"))
    }


def mirror(api: Api, root: Path, files: list[dict]) -> dict[str, tuple[int, int]]:
    """Make `root` the claim's listing: fetch what is missing or a different size, drop
    what S3 no longer has. Returns the snapshot uploads are compared against."""
    want = {}
    for f in files:
        rel = Path(f["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"claim lists a path outside the game: {f['path']!r}")
        want[rel.as_posix()] = f
    root.mkdir(parents=True, exist_ok=True)
    for rel in set(_snapshot(root)) - set(want):
        (root / rel).unlink()
    for rel, f in want.items():
        p = root / rel
        if not (p.is_file() and p.stat().st_size == f["size"]):
            api.download(f["url"], p)
    return _snapshot(root)


def push(api: Api, job_id: str, root: Path, before: dict[str, tuple[int, int]],
         only: tuple[str, ...] | None = None) -> int:  # fmt: skip
    """Upload every file that is new or changed since `before` (and under one of the
    `only` prefixes, when given); game.json goes last, as it is what flips the game to
    ready. Returns how many were uploaded."""
    changed = sorted(r for r, st in _snapshot(root).items()
                     if before.get(r) != st and (only is None or r.startswith(only)))  # fmt: skip
    changed.sort(key=lambda r: r == GAME_JSON)
    for i in range(0, len(changed), 500):
        batch = changed[i : i + 500]
        urls = api.post(f"/worker/jobs/{job_id}/upload-urls", {"paths": batch}).json()
        for rel in batch:
            api.upload(urls[rel], root / rel)
    return len(changed)


def run_job(job: dict, settings: Settings, api: Api, before: dict) -> None:
    """The job, through the same task code the local API runs."""
    storage = LocalStorage(settings.games_dir)
    index = LocalIndex(storage)
    gid, job_id = job["game_id"], job["id"]
    if job["kind"] == "process":
        # The API built `stages` from its own pipeline setting (Lambda has no courtcam);
        # this runner's pipeline decides what is reported, so show that list right away.
        game = index.load(gid)
        if game is None:
            raise FileNotFoundError(f"game {gid} has no game.json")
        game["stages"] = dict.fromkeys(adapter.stage_names(settings.pipeline), "pending")
        game["status"] = "processing"
        index.save(game)
        push(api, job_id, storage.game_dir(gid), {k: v for k, v in before.items()
                                                  if k != GAME_JSON})  # fmt: skip
        before[GAME_JSON] = _snapshot(storage.game_dir(gid))[GAME_JSON]
        early = _EarlyPush(api, job_id, storage.game_dir(gid), before)
        try:
            main._process_task(settings, storage, index, _Progress(api, early), gid)(job_id)
        finally:
            early.close()  # the final push (run_once) must not race it
    elif job["kind"] == "autocalib":
        p = job.get("params") or {}
        main._autocalib_task(settings, storage, gid, p["sport"], p["variant"],
                             p.get("backend") or "auto")(job_id)  # fmt: skip
    elif (job.get("params") or {}).get("stage") in STAGE_JOBS:
        # one worker stage on a processed game (the reel, a condensed or vertical render),
        # as discovery_routes._submit runs it in local mode
        from replay_worker import run as run_worker
        from replay_worker.stages.discovery import standalone

        stage = job["params"]["stage"]
        prog = _Progress(api)
        run_worker(storage.game_dir(gid), {}, registry=standalone(stage), stages=[stage],
                   cpu_workers=1, progress=lambda s, f: prog.progress(job_id, s, f))  # fmt: skip
    else:
        raise ValueError(f"the remote runner does not run {job['kind']!r} jobs")


def run_once(api: Api, settings: Settings) -> bool:
    """Claim one job and see it through. False when the queue was empty."""
    r = api.post("/worker/claim")
    if r.status_code == 204:
        return False
    claim = r.json()
    job, gid = claim["job"], claim["game_id"]
    root = settings.games_dir / gid
    log.info("claimed %s (%s, game %s, %d files)", job["id"], job["kind"], gid,
             len(claim["files"]))  # fmt: skip
    error = None
    before: dict = {}
    try:
        before = mirror(api, root, claim["files"])
        run_job(job, settings, api, before)
    except Exception as exc:
        log.exception("job %s failed", job["id"])
        error = f"{type(exc).__name__}: {exc}"
    try:  # a failed run still uploads: _process_task wrote status "failed" to game.json
        n = push(api, job["id"], root, before) if root.is_dir() else 0
        log.info("uploaded %d files for %s", n, job["id"])
    except Exception as exc:
        log.exception("upload for %s failed", job["id"])
        error = error or f"upload failed: {type(exc).__name__}: {exc}"
    api.post(f"/worker/jobs/{job['id']}/finish", {"ok": error is None, "error": error})
    log.info("finished %s: %s", job["id"], "ok" if error is None else error)
    return True


def quiet_http_logs() -> None:
    """httpx logs every request URL at INFO, presigned query (security token) included;
    the runner logs redacted paths itself (Api.download/upload)."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main_cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--api", required=True, help="the API base URL (Lambda Function URL)")
    ap.add_argument("--once", action="store_true", help="claim at most one job, then exit")
    ap.add_argument("--interval", type=float, default=30.0, help="seconds between polls")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    quiet_http_logs()
    key = os.environ.get("REPLAY_WORKER_KEY")
    if not key:
        ap.error("set REPLAY_WORKER_KEY")
    settings = from_env(storage="local", jobs="local")
    timeout = httpx.Timeout(60.0)
    # IPv4 only: hfbox resolves the Function URL's AAAA records but IPv6 is blackholed, and
    # httpx tries each address in turn (no happy eyeballs), so every new connection sat
    # 8 x 60 s on IPv6 first, stalling the pipeline on each progress post.
    # ponytail: always IPv4; make it a flag if a runner ever lives on an IPv6-only host.
    with (
        httpx.Client(base_url=args.api.rstrip("/"), timeout=timeout,
                     transport=httpx.HTTPTransport(local_address="0.0.0.0")) as client,
        httpx.Client(timeout=timeout,
                     transport=httpx.HTTPTransport(local_address="0.0.0.0")) as http,
    ):  # fmt: skip
        api = Api(client, key, http)
        while True:
            try:
                claimed = run_once(api, settings)
            except Exception:
                log.exception("poll failed")
                claimed = False
            if args.once:
                return 0
            if not claimed:
                time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main_cli())
