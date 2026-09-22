"""Job runner provider: one background thread draining a queue, state persisted to disk."""

from __future__ import annotations

import json
import logging
import queue
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


class Jobs(Protocol):
    def submit(self, kind: str, game_id: str, fn: Callable[[str], None]) -> dict: ...
    def get(self, job_id: str) -> dict | None: ...
    def for_game(self, game_id: str) -> list[dict]: ...
    def progress(self, job_id: str, stage: str, fraction: float) -> None: ...


class LocalJobs:
    """In-process worker. Single thread on purpose: the pipeline is CPU-bound and one
    laptop runs one game at a time.
    ponytail: single worker thread; add a pool if two games must process at once.
    """

    def __init__(self, state_path: Path):
        self.state_path = Path(state_path)
        self.lock = threading.Lock()
        self.q: queue.Queue = queue.Queue()
        self.state: dict[str, dict] = self._load()
        # a job left "running"/"queued" by a previous process is not coming back
        for job in self.state.values():
            if job["status"] in ("queued", "running"):
                job["status"] = "failed"
                job["error"] = "interrupted by API restart"
        self._flush()
        self.thread = threading.Thread(target=self._worker, daemon=True, name="replay-jobs")
        self.thread.start()

    def _load(self) -> dict[str, dict]:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}

    def _flush(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        tmp.replace(self.state_path)

    def _update(self, job_id: str, **fields) -> None:
        with self.lock:
            self.state.setdefault(job_id, {}).update(fields)
            self._flush()

    def submit(self, kind: str, game_id: str, fn: Callable[[str], None]) -> dict:
        job_id = "j_" + secrets.token_hex(6)
        job = {
            "id": job_id,
            "kind": kind,
            "game_id": game_id,
            "status": "queued",
            "created_at": time.time(),
            "stage": None,
            "fraction": 0.0,
            "error": None,
        }
        with self.lock:
            self.state[job_id] = job
            self._flush()
        self.q.put((job_id, fn))
        return dict(job)

    def progress(self, job_id: str, stage: str, fraction: float) -> None:
        self._update(job_id, stage=stage, fraction=round(float(fraction), 3))

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.state.get(job_id)
            return dict(job) if job else None

    def for_game(self, game_id: str) -> list[dict]:
        with self.lock:
            return [dict(j) for j in self.state.values() if j.get("game_id") == game_id]

    def _worker(self) -> None:
        while True:
            job_id, fn = self.q.get()
            self._update(job_id, status="running", started_at=time.time())
            try:
                fn(job_id)
            except Exception as exc:  # a failed job must not kill the worker
                log.exception("job %s failed", job_id)
                self._update(job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
            else:
                self._update(job_id, status="done", finished_at=time.time())
            finally:
                self.q.task_done()

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Tests only: block until the queue drains."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                busy = any(j["status"] in ("queued", "running") for j in self.state.values())
            if not busy:
                return True
            time.sleep(0.05)
        return False
