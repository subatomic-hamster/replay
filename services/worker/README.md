# replay-worker

Local job orchestrator for Replay: a per-game DAG of stages over a content-hash cache.
It is the local stand-in for Step Functions + SageMaker Processing (infra/ mirrors the
same DAG; docs/aws-integrations.md).

```bash
# on the box (docs/compute.md): source /workspace/wt/replay-env/env.sh
d=/workspace/wt/replay-<you>; export PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker

python -m replay_worker run samples/synthetic/basketball_half/clip.mp4 \
    --out data/games/g_demo --detector synthetic          # landmarks/ground truth: sibling files
python -m replay_worker run data/games/g_abc               # an API game dir (source.mp4 + game.json)
python -m replay_worker run <video> --stages events        # events and everything upstream
python -m replay_worker run <video> --force detect         # recompute detect despite the cache
python -m replay_worker status data/games/g_demo           # last result per stage
python -m replay_worker perf data/games/* --write docs/perf.md
python -m replay_worker dag > infra/dag.json               # DAG shape for the CDK mirror
```

The API uses it with `REPLAY_PIPELINE=worker` (services/api `pipeline_adapter.run`).

## Model

- **Stage** (`dag.Stage`): a name, a version, a function `fn(ctx, item)`, declared
  `inputs` / `outputs` (game-relative paths; `"{cfg_key}"` for a path from the run
  config such as `{source}`; `{item}` inside fan-out paths), `params` (run-config keys
  that change the output), `after` (upstream stages) and a `resource` class `gpu | cpu | io`.
- **Cache key** = sha256(stage name + version + item + params + sha256 of every input
  file/dir). Entries live in `$REPLAY_CACHE_DIR` (default
  `/workspace/wt/replay-env/cache` on the box, `~/.cache/replay-worker` elsewhere) as
  `<stage>/<key[:2]>/<key>/{outputs..., meta.json}`, written under a temp name and
  renamed, so an entry is whole or absent. A hit restores the outputs into the game dir
  and never calls the stage. Because keys hash input *content*, a recompute that
  produces identical bytes leaves every downstream stage a hit.
- **Resume**: there is no resume mode — rerun the same command; finished tasks are hits.
- **Fan-out**: `fanout=lambda ctx: [...]` turns a stage into one task per item
  (per player / play / angle); each item has its own key and runs in parallel.
- **Scheduling**: GPU tasks run one at a time and hold the box-wide GPU lock
  (`$REPLAY_GPU_LOCK`, default `/workspace/airtools/.gpu.lock` when it exists, else
  `<cache>/gpu.lock`) only while they compute; CPU tasks run in a pool of
  `$REPLAY_CPU_WORKERS` (default 2); IO tasks in a pool of 4. The CLI caps numeric
  libraries at 6 threads (`OMP_NUM_THREADS` etc., unless already set).
- **Log**: one JSON line per task in `<game_dir>/_work/worker.jsonl`
  (`run, host, stage, item, resource, cache: hit|miss|off, status, wall_s, lock_wait_s,
  key, started, ended`). `perf` renders docs/perf.md from these logs.
- **Versioning**: bump a stage's version when its code changes meaning. courtcam stages
  use `"1+" + hash(courtcam sources and sport profiles)`, so any courtcam edit invalidates
  them.

## Adding a stage (one module + one registration line)

1. Write `replay_worker/stages/<name>.py`:

   ```python
   from ..dag import Ctx, Stage

   def render_angles(ctx: Ctx, item: str | None) -> None:
       ...  # read inputs under ctx.game_dir, write exactly the declared outputs

   STAGES = [
       Stage(
           "angles", "1", render_angles,
           inputs=("events.json", "media/wide.mp4"),
           outputs=("replays/{item}/manifest.json",),
           params=("sport",),
           after=("events",),
           resource="gpu",
           fanout=lambda ctx: [p["id"] for p in load_plays(ctx.game_dir)],
       ),
   ]
   ```

2. Add `"replay_worker.stages.<name>"` to `MODULES` in `replay_worker/stages/__init__.py`
   (after the modules it depends on).
3. Regenerate the infra mirror: `python -m replay_worker dag > infra/dag.json` (CI diffs it).

Rules: write only declared outputs (undeclared files are not cached and will be missing
after a hit); put every knob that changes the output in `params`; set `default=False` for
stages that should only run when named with `--stages`; `cache=False` only for cheap
bookkeeping (the `game` stage that writes `game.json`).

## Tests

```bash
cd services/worker && python -m pytest -q
```

`test_dag.py` covers hit/miss, invalidation on params/version/input content, `--force`,
resume after a crash, fan-out, the GPU lock (held, never overlapping) and the CPU pool.
`test_courtcam_stages.py` runs the synthetic sample through `courtcam.pipeline.run` and
through the worker and requires byte-identical trees, then a second run of all hits.
