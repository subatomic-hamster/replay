# Compute: the hfbox GPU box

All Replay compute (tests, pipelines, renders, benchmarks, builds) runs on **hfbox**, a
shared GPU box. The laptop edits files, syncs, and views results (`make demo` pulls a
processed game back so the API + web app can show it locally). Everything below was
measured on 2026-10-06 unless marked otherwise.

## What the box is

| | measured | how |
|---|---|---|
| GPU | AMD Radeon RX 9070 XT, 15.9 GiB VRAM (torch reports it as `cuda`) | `torch.cuda.get_device_name(0)`, `get_device_properties(0).total_memory` |
| ROCm / torch | HIP 7.2.53211, torch 2.14.0+rocm7.2 (read-only system install in `/opt/venv`) | `torch.version.hip`, `torch.__version__` |
| CPU | AMD Ryzen 7 7800X3D, 8 cores / 16 threads | `lscpu` |
| RAM | 30 GiB, 21–24 GiB available while other users ran; 7 GiB swap | `free -g` |
| Disk | `/workspace` 147 GB, **23–32 GB free** (78–85 % used; moved during the day) | `df -h /workspace` |
| OS | Ubuntu 24.04.5 container on a Fedora 7.1 kernel; you are `root` | `/etc/os-release`, `uname -a` |
| Python stack | Python 3.12.3, ultralytics 8.4.170, OpenCV 5.0.0, FastAPI 0.142.2 | shared venv |
| Other tools | node 22.23.3, pnpm 12.8.1, ffmpeg 7.0.2 static (libx264), tmux 3.4, flock/lslocks (util-linux 2.39.3), nvtop 3.0.2, uv 0.12.18 at `/workspace/bin/uv` | `--version` |
| Not present | `rocm-smi`, `amd-smi`, `/opt/rocm` | `which` |

Network (from the box): huggingface.co, pypi.org, registry.npmjs.org and github.com all
answer 200. A 10 s window of a Hugging Face model download ran at **32 MB/s**; ultralytics
fetched `yolo11m.pt` (38.8 MB) from GitHub at 25 MB/s; `pip download numpy` (16 MB)
works.

## Getting work onto it

```bash
ssh -o BatchMode=yes hfbox '<cmd>'          # TLS ssh proxy; each connection costs ~2.5 s
cat /workspace/wt/replay-env/READY          # the authoritative how-to
source /workspace/wt/replay-env/env.sh      # PATH: venv, ffmpeg, node, pnpm; 6-thread caps
```

- **Your copy**: `/workspace/wt/replay-<name>`, filled by `make sync BOX_DIR=...`
  (rsync laptop → box; `.git`, `node_modules`, `/data/`, `samples/real`, `/*.pt` excluded,
  then `samples/real` is symlinked to `/workspace/wt/replay-env/samples-real`).
  Anything you create on the box that must survive a sync goes under the copy's
  `data/` (excluded, so `--delete` leaves it alone).
- **Python**: `export PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker` and the
  shared venv's `python`. Installs go into `/workspace/wt/replay-env/venv` without ever
  replacing torch, and are logged in `/workspace/wt/replay-env/INSTALLS.md`.
- **Long jobs**: a named tmux session, logs in your copy:
  `tmux new-session -d -s replay-<name>-<job> "bash job.sh > $d/data/job.log 2>&1"`.
  Kill only your own sessions (`tmux kill-session -t ...`), never the server.

## Moving files

Measured with a 20 MB random file over rsync through the ssh proxy:

| direction | wall | throughput (incl. ~2.5 s connection) |
|---|---:|---:|
| laptop → box | 14.7 s | 1.4 MB/s |
| box → laptop | 10.8 s | 1.9 MB/s |

So footage lives on the box (`/workspace/wt/replay-env/samples-real`, uploads under the
box's data dirs) and only small outputs come back: JSON, PNGs, short clips. A processed
20 s synthetic game is 1.9 MB; a 240 s 1080p mezzanine is tens of MB — leave it there.

## Rules of the shared box

| rule | how |
|---|---|
| One GPU job box-wide | every GPU job holds `/workspace/airtools/.gpu.lock` (`flock`); the worker takes it per GPU task. Keep each job to minutes; split long work. |
| Heavy CPU jobs (pipelines, renders, full test suites) | `flock /workspace/wt/replay-env/.cpu.lock <cmd>` |
| Playwright | also `flock /workspace/wt/replay-env/.pw.lock` (ports 5177/5178/8000/8010 are fixed) |
| ≤ 6 threads | `env.sh` sets `OMP/MKL/OPENBLAS/NUMEXPR_NUM_THREADS=6`; the worker CLI sets the same if unset |
| ≥ 8 GB free RAM before starting | `free -g` (column "available"); `scripts/box-demo.sh` refuses below 8 |
| Only `/workspace` persists | apt packages do not survive a restart: reinstall `libglib2.0-0t64` and `pnpm exec playwright install-deps chromium` (READY step 6) |
| Footprint | `df -h /workspace` before big outputs; delete only what you created; `/workspace/envs/*` and `/workspace/.hf/hub` belong to others (read-only) |

## Monitoring

- GPU: `nvtop`; or `cat /sys/class/drm/card1/device/gpu_busy_percent` and
  `.../mem_info_vram_used` (card1 is the 9070 XT; card2 is the CPU's 512 MB iGPU).
- Who holds / waits for the GPU: `lslocks | grep gpu.lock` (a `*` after `WRITE` is a
  waiter). The worker logs its own wait per task (`lock_wait_s`).
- CPU/RAM: `top`, `free -g`; tmux sessions: `tmux ls`.
- Pipeline progress: `python -m replay_worker status <game_dir>` and
  `<game_dir>/_work/worker.jsonl`.

## Throughput anchors

| what | number | source |
|---|---|---|
| YOLO11n, imgsz 960, 2560×960 frames, batch 1 | **8.1 ms/frame** (123 fps; 12.3× realtime at stride 2 on a 20 fps clip) | `bench_yolo.py yolo11n.pt basketball_kennesawwide_240s.mp4`, 2026-10-06 (READY said ~9) |
| YOLO11m, same | **10.7 ms/frame** (93 fps; 9.3× realtime at stride 2) — model only; the `detect` stage below also decodes and tracks and runs at about half this rate (RESULTS.md: decode and the tracker bound the small models) | same script, 2026-10-06 |
| `detect` stage, yolo11m + BoT-SORT, stride 2, 240 s Kennesaw | 50.9 s = **4.7× realtime** (RESULTS.md: 4.1–4.6× across four clips, 2026-09-30) | worker run, docs/perf.md |
| whole courtcam pipeline through the worker, same clip, cold cache | 76.4 s = **3.1× realtime** (ingest 13.0 s, detect 50.9 s, rest 18 s) | docs/perf.md |
| same, warm cache (nothing changed) | 1.4 s (9 hits; detect's 1.3 s is importing torch to key on the device) | docs/perf.md |

## Pipeline execution on the box

The worker (`services/worker`, README there) is how pipelines run:

1. **One command per game**: `python -m replay_worker run <video | game_dir>` runs the
   per-game DAG (courtcam's nine stages + `game.json` bookkeeping; later milestones add
   stage modules). Run it under the CPU lock from a named tmux session; it takes the GPU
   lock itself, only around GPU tasks, so other users get the GPU between stages.
2. **Cache**: `/workspace/wt/replay-env/cache/<stage>/<key>/` keyed by input content +
   stage version + params. Every copy and every agent shares it, so a clip already
   detected by anyone is a hit for everyone. Media ≥ 16 MiB is hard-linked (same
   filesystem), so a cached mezzanine costs its bytes once. Entries are never pruned
   automatically; `rm -rf /workspace/wt/replay-env/cache/<stage>` is always safe (it only
   costs recomputes).
3. **Resource classes**: `gpu` tasks one at a time (GPU lock); `cpu` tasks in a pool of
   2 (`REPLAY_CPU_WORKERS`); `io` tasks in a pool of 4. Fan-out stages (per player /
   play / angle) become independent tasks in those pools.
4. **Crash / box restart**: rerun the same command; finished stages are hits.
5. **Results to the laptop**: `rsync` the game dir (JSON + small media) — `make demo`
   does this for the synthetic sample. Real-footage outputs stay on the box (D-7).
6. **Perf**: every task is a line in `<game>/_work/worker.jsonl`;
   `python -m replay_worker perf <game dirs> --write docs/perf.md`.
