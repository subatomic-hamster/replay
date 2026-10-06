"""Scheduler + cache semantics on toy stages (no courtcam, no video)."""

from __future__ import annotations

import fcntl
import itertools
import json
import threading
import time
from pathlib import Path

import pytest
from replay_worker import Cache, Stage, StageFailed, run
from replay_worker.perf import render

CALLS: list[str] = []


def _src(ctx, item):
    CALLS.append("src")
    (ctx.game_dir / "a.txt").write_text(Path(ctx.cfg["source"]).read_text() + ctx.cfg["suffix"])


def _double(ctx, item):
    CALLS.append("double")
    if ctx.cfg.get("crash"):
        raise RuntimeError("boom")
    (ctx.game_dir / "b").mkdir(exist_ok=True)
    (ctx.game_dir / "b" / "x.txt").write_text((ctx.game_dir / "a.txt").read_text() * 2)


def registry(version: str = "1") -> dict[str, Stage]:
    return {
        "src": Stage(
            "src", version, _src, inputs=("{source}",), outputs=("a.txt",), params=("suffix",)
        ),
        "double": Stage("double", "1", _double, inputs=("a.txt",), outputs=("b",), after=("src",)),
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    CALLS.clear()
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    src = tmp_path / "in.txt"
    src.write_text("hello")
    return {
        "game": tmp_path / "game",
        "cache": Cache(tmp_path / "cache"),
        "cfg": {"source": str(src), "suffix": "!"},
        "src": src,
    }


def _go(env, reg=None, **kw):
    return run(env["game"], env["cfg"], registry=reg or registry(), cache=env["cache"], **kw)


def _caches(records):
    return {r["stage"]: r["cache"] for r in records}


def test_miss_then_hit_restores_outputs(env):
    assert _caches(_go(env)) == {"src": "miss", "double": "miss"}
    (env["game"] / "a.txt").unlink()
    (env["game"] / "b" / "x.txt").write_text("tampered")
    CALLS.clear()
    assert _caches(_go(env)) == {"src": "hit", "double": "hit"}
    assert CALLS == []  # never recompute a hit
    assert (env["game"] / "a.txt").read_text() == "hello!"
    assert (env["game"] / "b" / "x.txt").read_text() == "hello!hello!"
    log = (env["game"] / "_work" / "worker.jsonl").read_text().splitlines()
    assert len(log) == 4 and all(json.loads(line)["status"] == "ok" for line in log)


def test_param_change_invalidates_downstream_by_content(env):
    _go(env)
    env["cfg"]["suffix"] = "?"
    assert _caches(_go(env)) == {"src": "miss", "double": "miss"}
    assert (env["game"] / "b" / "x.txt").read_text() == "hello?hello?"
    env["cfg"]["suffix"] = "!"  # back to the first params: both cached
    assert _caches(_go(env)) == {"src": "hit", "double": "hit"}


def test_version_and_input_changes_invalidate(env):
    _go(env)
    assert _caches(_go(env, registry("2")))["src"] == "miss"
    # same output content as before -> the downstream key is unchanged -> hit
    assert _caches(_go(env, registry("2")))["double"] == "hit"
    env["src"].write_text("bye")
    assert _caches(_go(env, registry("2"))) == {"src": "miss", "double": "miss"}


def test_force_recomputes_only_that_stage(env):
    _go(env)
    CALLS.clear()
    assert _caches(_go(env, force=["src"])) == {"src": "miss", "double": "hit"}
    assert CALLS == ["src"]


def test_resume_after_crash(env):
    env["cfg"]["crash"] = True
    with pytest.raises(StageFailed, match="boom"):
        _go(env)
    entries = (
        list((env["cache"].root / "double").rglob("*"))
        if (env["cache"].root / "double").exists()
        else []
    )
    assert entries == []  # nothing half-stored for the failed stage
    del env["cfg"]["crash"]  # not a param of `double`, so its key is unchanged
    CALLS.clear()
    assert _caches(_go(env)) == {"src": "hit", "double": "miss"}
    assert CALLS == ["double"]
    fails = [json.loads(x) for x in (env["game"] / "_work/worker.jsonl").read_text().splitlines()]
    assert [r["status"] for r in fails].count("fail") == 1


def test_optional_cfg_input_absent_or_none_is_skipped(env):
    reg = registry()
    src = reg["src"]
    reg["src"] = Stage(
        "src", "1", _src, inputs=("{source}", "{extra}"), outputs=src.outputs, params=src.params
    )
    assert _caches(_go(env, reg))["src"] == "miss"  # no "extra" key at all
    env["cfg"]["extra"] = None
    assert _caches(_go(env, reg))["src"] == "hit"


def test_stages_selects_upstream_closure(env):
    recs = _go(env, stages=["src"])
    assert _caches(recs) == {"src": "miss"}
    with pytest.raises(ValueError, match="unknown stage"):
        _go(env, stages=["nope"])


def test_fanout_and_gpu_lock(env, tmp_path):
    lock = tmp_path / "gpu.lock"
    spans: list[tuple[float, float]] = []
    held: list[bool] = []

    def per_item(ctx, item):
        t0 = time.time()
        with open(lock, "a") as fh:  # a second open file description must be refused
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(False)
                fcntl.flock(fh, fcntl.LOCK_UN)
            except BlockingIOError:
                held.append(True)
        time.sleep(0.05)
        (ctx.game_dir / f"out_{item}.txt").write_text(item)
        spans.append((t0, time.time()))

    reg = {
        **registry(),
        "per": Stage(
            "per",
            "1",
            per_item,
            inputs=("a.txt",),
            outputs=("out_{item}.txt",),
            after=("src",),
            resource="gpu",
            fanout=lambda ctx: ["p1", "p2", "p3"],
        ),
    }
    recs = _go(env, reg)
    per = [r for r in recs if r["stage"] == "per"]
    assert sorted(r["item"] for r in per) == ["p1", "p2", "p3"]
    assert all(r["cache"] == "miss" and r["resource"] == "gpu" for r in per)
    assert held == [True, True, True]
    spans.sort()
    assert all(a[1] <= b[0] for a, b in itertools.pairwise(spans)), "GPU tasks overlap"
    recs = _go(env, reg)
    assert {r["cache"] for r in recs if r["stage"] == "per"} == {"hit"}
    assert "| game | per | gpu | 3 | 3 | 0 |" in render([env["game"]])


def test_cpu_pool_runs_independent_stages_concurrently(env):
    barrier = threading.Barrier(2, timeout=5)

    def meet(name):
        def fn(ctx, item):
            barrier.wait()  # deadlocks (BrokenBarrierError) unless both run at once
            (ctx.game_dir / f"{name}.txt").write_text(name)

        return fn

    reg = {
        **registry(),
        "l": Stage("l", "1", meet("l"), inputs=("a.txt",), outputs=("l.txt",), after=("src",)),
        "r": Stage("r", "1", meet("r"), inputs=("a.txt",), outputs=("r.txt",), after=("src",)),
    }
    _go(env, reg, cpu_workers=2)
    assert (env["game"] / "l.txt").exists() and (env["game"] / "r.txt").exists()


def test_uncached_stage_runs_every_time_and_keeps_its_file(env):
    def bump(ctx, item):
        p = ctx.game_dir / "count.txt"
        p.write_text(str(int(p.read_text()) + 1 if p.exists() else 1))

    reg = {**registry(), "meta": Stage("meta", "1", bump, outputs=("count.txt",), cache=False)}
    _go(env, reg)
    assert _caches(_go(env, reg))["meta"] == "off"
    assert (env["game"] / "count.txt").read_text() == "2"
