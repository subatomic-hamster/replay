"""Per-game DAG of stages, run against the content-hash cache.

A `Stage` is a named, versioned function with declared inputs, outputs, params and a
resource class. `run()` expands each stage into tasks (one, or one per fan-out item),
skips every task whose key is already cached (restoring its outputs instead), runs GPU
tasks one at a time under the box-wide GPU lock and CPU/IO tasks in bounded pools, and
appends one JSON line per task to `<game_dir>/_work/worker.jsonl`.

Resuming after a crash is just running again: finished tasks are cache hits.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .cache import Cache, file_hash, remove, task_key

Progress = Callable[[str, float], None]
LOG_REL = "_work/worker.jsonl"
RESOURCES = ("gpu", "cpu", "io")


@dataclass
class Ctx:
    """What a stage function sees: the game dir, the run config and a progress sink."""

    game_dir: Path
    cfg: dict[str, Any]
    progress: Progress = lambda stage, fraction: None


@dataclass(frozen=True)
class Stage:
    name: str
    version: str
    fn: Callable[[Ctx, str | None], None]
    # Game-relative paths, or "{cfg_key}" for a path the run config supplies (skipped when
    # that key is missing or None). "{item}" is replaced by the fan-out item.
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    params: tuple[str, ...] = ()  # cfg keys that change the outputs
    after: tuple[str, ...] = ()  # upstream stages
    resource: str | Callable[[dict], str] = "cpu"
    fanout: Callable[[Ctx], list[str]] | None = None  # -> one task per item
    key_extra: Callable[[dict], Any] | None = None  # e.g. the device detection ran on
    cache: bool = True  # False: always runs (cheap bookkeeping such as game.json)
    default: bool = True  # part of the DAG when `stages` is not given


class StageFailed(RuntimeError):
    pass


@dataclass
class _Run:
    ctx: Ctx
    cache: Cache
    force: set[str]
    log_path: Path
    run_id: str
    gpu_lock: Path
    log_lock: threading.Lock = field(default_factory=threading.Lock)
    records: list[dict] = field(default_factory=list)


def default_gpu_lock(cache: Cache) -> Path:
    """The box-wide lock other users' GPU jobs take too; a private one anywhere else."""
    env = os.environ.get("REPLAY_GPU_LOCK")
    if env:
        return Path(env)
    shared = Path("/workspace/airtools/.gpu.lock")
    return shared if shared.exists() else cache.root / "gpu.lock"


@contextmanager
def file_lock(path: Path):
    """flock(2) — the same lock `flock /workspace/airtools/.gpu.lock cmd` takes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def closure(registry: dict[str, Stage], targets: Iterable[str]) -> list[str]:
    """`targets` plus everything upstream of them, in registry (= dependency) order."""
    need: set[str] = set()
    todo = list(targets)
    while todo:
        name = todo.pop()
        if name not in registry:
            raise ValueError(f"unknown stage {name!r}; known: {list(registry)}")
        if name not in need:
            need.add(name)
            todo.extend(registry[name].after)
    order = [n for n in registry if n in need]
    for i, name in enumerate(order):
        late = [d for d in registry[name].after if d not in order[:i]]
        if late:
            raise ValueError(f"stage {name!r} is registered before its upstream {late}")
    return order


def _resolve_inputs(stage: Stage, ctx: Ctx, item: str | None) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for spec in stage.inputs:
        if spec.startswith("{") and spec.endswith("}") and spec != "{item}":
            value = ctx.cfg.get(spec[1:-1])
            if value is None:  # optional input this run does not have
                continue
            path = Path(value)
        else:
            path = ctx.game_dir / spec.format(item=item)
        if not path.exists():
            raise FileNotFoundError(f"stage {stage.name!r}: input {spec} missing ({path})")
        out[spec] = path
    return out


def _resource(stage: Stage, cfg: dict) -> str:
    res = stage.resource(cfg) if callable(stage.resource) else stage.resource
    if res not in RESOURCES:
        raise ValueError(f"stage {stage.name!r}: resource {res!r} not in {RESOURCES}")
    return res


def _apply_edits(game_dir: Path, outputs: list[str]) -> None:
    """D-61: re-apply the user's corrections (the API's edits.json) to the outputs just
    restored or computed, so they survive any re-run and downstream stages hash and read
    the corrected files. The cache keeps the uncorrected outputs."""
    if not (game_dir / "edits.json").is_file():
        return
    from replay_api import edits  # services/api on the path, as for the narrate stages

    edits.apply(game_dir, outputs)


def _execute(r: _Run, stage: Stage, item: str | None) -> dict:
    ctx = r.ctx
    started = time.time()
    resource = _resource(stage, ctx.cfg)
    outputs = [o.format(item=item) for o in stage.outputs]
    rec: dict[str, Any] = {
        "run": r.run_id,
        "host": socket.gethostname(),
        "game": ctx.game_dir.name,
        "stage": stage.name,
        "version": stage.version,
        "item": item,
        "resource": resource,
        "started": round(started, 3),
        "lock_wait_s": 0.0,
    }
    try:
        inputs = {k: file_hash(p) for k, p in _resolve_inputs(stage, ctx, item).items()}
        params = {k: ctx.cfg.get(k) for k in stage.params}
        if stage.key_extra:
            params["_extra"] = stage.key_extra(ctx.cfg)
        key = task_key(stage.name, stage.version, item, params, inputs)
        rec["key"] = key
        if stage.cache and stage.name not in r.force and r.cache.has(stage.name, key):
            r.cache.restore(stage.name, key, ctx.game_dir, outputs)
            rec["cache"] = "hit"
        else:
            # Stale outputs never leak into a recompute. Uncached stages (game.json) may
            # be updating a file they do not own outright, so theirs stay.
            for rel in outputs if stage.cache else ():
                remove(ctx.game_dir / rel)
            if resource == "gpu":
                t = time.time()
                with file_lock(r.gpu_lock):
                    rec["lock_wait_s"] = round(time.time() - t, 3)
                    stage.fn(ctx, item)
            else:
                stage.fn(ctx, item)
            if stage.cache:
                meta = {"stage": stage.name, "version": stage.version, "item": item}
                r.cache.store(stage.name, key, ctx.game_dir, outputs, {**meta, "params": params})
            rec["cache"] = "miss" if stage.cache else "off"
        _apply_edits(ctx.game_dir, outputs)
        rec["status"] = "ok"
    except BaseException as exc:
        rec.update(status="fail", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        rec["ended"] = round(time.time(), 3)
        rec["wall_s"] = round(rec["ended"] - started, 3)
        with r.log_lock:
            r.records.append(rec)
            r.log_path.parent.mkdir(parents=True, exist_ok=True)
            with r.log_path.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")
    ctx.progress(stage.name, 1.0)
    return rec


def run(
    game_dir: Path,
    cfg: dict[str, Any],
    *,
    registry: dict[str, Stage] | None = None,
    stages: Iterable[str] | None = None,
    force: Iterable[str] = (),
    cache: Cache | None = None,
    cpu_workers: int | None = None,
    progress: Progress | None = None,
) -> list[dict]:
    """Run `stages` (default: every default stage) and their upstream. Returns the task
    records written to the log, in completion order. Raises StageFailed on the first
    failing task, after letting tasks already running finish."""
    if registry is None:
        from .stages import load_registry

        registry = load_registry()
    targets = list(stages) if stages else [n for n, s in registry.items() if s.default]
    order = closure(registry, targets)
    force = set(force)
    if force - set(order):
        raise ValueError(f"--force {sorted(force - set(order))} is not in this run: {order}")
    cache = cache or Cache()
    game_dir = Path(game_dir)
    game_dir.mkdir(parents=True, exist_ok=True)
    r = _Run(
        ctx=Ctx(game_dir, dict(cfg), progress or (lambda s, f: None)),
        cache=cache,
        force=force,
        log_path=game_dir / LOG_REL,
        run_id=time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:4],
        gpu_lock=default_gpu_lock(cache),
    )
    workers = cpu_workers or int(os.environ.get("REPLAY_CPU_WORKERS", "2"))
    pools = {
        "gpu": ThreadPoolExecutor(1, "replay-gpu"),
        "cpu": ThreadPoolExecutor(max(1, workers), "replay-cpu"),
        "io": ThreadPoolExecutor(4, "replay-io"),
    }
    remaining = {name: None for name in order}  # name -> open task count once expanded
    done: set[str] = set()
    running: dict[Future, str] = {}
    failure: BaseException | None = None
    try:
        while (remaining or running) and failure is None:
            for name in [n for n, c in remaining.items() if c is None]:
                stage = registry[name]
                if not set(stage.after) <= done:
                    continue
                items = stage.fanout(r.ctx) if stage.fanout else [None]
                remaining[name] = len(items)
                pool = pools[_resource(stage, r.ctx.cfg)]
                for item in items:
                    running[pool.submit(_execute, r, stage, item)] = name
            for name in [n for n, c in remaining.items() if c == 0]:
                del remaining[name]
                done.add(name)
            if not running:
                if remaining:
                    continue  # a fan-out of zero items just completed a stage
                break
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in finished:
                name = running.pop(fut)
                if fut.exception() is not None:
                    failure = failure or fut.exception()
                    continue
                remaining[name] -= 1
        if failure is not None:
            wait(running)
            raise StageFailed(str(failure)) from failure
    finally:
        for pool in pools.values():
            pool.shutdown(wait=True)
    return r.records
