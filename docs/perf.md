# Performance

All numbers were measured on **hfbox** on 2026-10-06 unless a row says otherwise:

- CPU: AMD Ryzen 7 7800X3D (8 cores, 16 threads)
- GPU: AMD Radeon RX 9070 XT, 16 GB, ROCm 7.2, torch 2.14
- RAM: 30 GiB
- Software: Ubuntu 24.04, ffmpeg (libx264)

The box is shared. Every CPU job takes `.cpu.lock` and every GPU job takes `.gpu.lock`,
so wall times include queueing behind other agents. Lock waits are listed where they
were logged.

A *miss* is real compute. A *hit* is a restore from the worker's content-hash cache.
`x RT` is video seconds per wall second, so higher is faster. The stage tables come from
`python -m replay_worker perf <game_dir>...`, which prints to stdout and reads each game's
`_work/worker.jsonl`. They were pasted in here. Do not use `--write docs/perf.md`: it
replaces the whole file.

**Not measured:**

- anything on a Fire TV device or emulator (decode, startup, seek, memory);
- a full-length (10–40 min) game or 4K input;
- real-footage Tier A/B/C replays and commentary/TTS end to end;
- concurrent uploads.

## 1. `make demo` (synthetic, scripts/box-demo.sh)

Two **synthetic** games, each 60 s at 1920x1080, 30 fps, seed 11, synthetic detector:

- basketball full court: everything, including 3 highlights x 11 replay angles;
- pickleball doubles: hype and condensed.

TTS (Kokoro) and embeddings (SigLIP) run on the CPU through the model runner
(`REPLAY_MODEL_DEVICE=cpu`, so they never take the GPU lock). SAM 2.1 runs in-process
on the GPU.

`make demo BOX_DIR=/workspace/wt/replay-m13`, run from the laptop, 2026-10-06:

| phase | cold: worker wall s | cold: script wall s | warm: worker wall s | warm: script wall s |
|---|---:|---:|---:|---:|
| `courtcam synth` of both clips (skipped once `clip.mp4` exists) | – | 117 | – | 0 |
| basketball pass 1: pipeline, commentary + TTS, hype, director, Tier A/B/C x 3 plays, search index (72 tasks) | 304.3 (64 misses) | 305 (lock wait 0) | 0.3 (64 hits) | 102 (lock wait 102) |
| 9:16 spec + basketball pass 2: vertical, broadcast with narration (22 tasks) | 17.2 (2 misses) | 162 (lock wait 145) | 0.1 (21 hits) | 59 (lock wait 58) |
| pickleball: pipeline, hype, condensed (21 tasks) | 10.4 (20 misses) | 75 (lock wait 65) | 0.1 (20 hits) | 51 (lock wait 51) |
| **build total** (`BUILD DONE in`) | **332** | **542 + 117 synth** | **0.5** | **212** |
| `make demo` total (sync, build, start 3 servers, health check) | | 551 (+117 synth) | | 222 |

- The cold run started from an empty `data/demo/games` and `data/demo/cache`. The clips
  had been generated 5 min earlier by an attempt that died with the ssh link (FL-18);
  that attempt measured synth at 117 s.
- Script wall minus worker wall is the CPU-lock wait plus about 1 s of Python start-up
  per worker call. The waits were other agents' jobs on the shared box. On an idle box,
  `make demo` is about 7.5 min cold (117 + 332 s plus start-up) and about 10 s warm.
- The clip hashes are fixed by the seeds: basketball `aed169649a31f428…`, pickleball
  `aae6df2f5dd1e1bf…`. A fresh regeneration of the pickleball clip in a scratch dir gave
  the same sha256 and a byte-identical `ground_truth.json` (78 s including lock wait).
  The whole cache keys off these hashes.
- Disk: games 63 MB, cache 64 MB, source clips plus synthetic truth 38 MB.
- An earlier build of the same games (08:56 box time, under GPU contention) took 510 s for
  pass 1, with SAM at 117 s median per play.

Where the cold time goes (basketball pass 1, 64 misses, 304 s):

- `segment` is SAM 2.1 video masks for every player in each highlight window:
  30 / 62 / 68 s for the 3 plays, 160 s in all.
- Tier C (`tierc_scene` plus 5 angles per play): about 66 s of compute per play.
- Tier B: 3 angles per play at about 8 s each.
- plate: 15 s.
- SigLIP embeddings: 12.4 s.
- Commentary with TTS: 10.1 s.

Several CPU stages run concurrently, so the per-stage sums exceed the wall time. The
broadcast rendition takes 15.3 s for 60 s of video.

**Fallbacks** (box-demo.sh switches them on itself, or you set them):

| condition | what happens | cost |
|---|---|---|
| no `tts` model venv | `--set commentary_tts=`: captions only, no narration track | commentary about 0.1 s |
| no `emb` venv, or `DEMO_SEARCH=0` | no search index; `/search` falls back to keywords | −12 s |
| `DEMO_FAKE_SEGMENT=1` | ellipse masks instead of SAM 2.1; Tier B cutouts look worse | about −160 s cold (−350 s when the GPU is busy) |
| box under load | jobs queue on `.cpu.lock` / `.gpu.lock`; the build prints `cpu lock wait Ns` per worker call | +queue time |

### Per stage: demo games (cold run + warm run above)

| game | stage | resource | misses | hits | median miss s | miss x RT | median hit s |
|---|---|---|---:|---:|---:|---:|---:|
| g_demo_basketball | ingest | cpu | 1 | 3 | 2.84 | 21.1 | 0.00 |
| g_demo_basketball | detect (synthetic) | cpu | 1 | 3 | 0.70 | 85.7 | 0.01 |
| g_demo_basketball | audio | cpu | 1 | 3 | 0.78 | 77.0 | 0.00 |
| g_demo_basketball | identity | cpu | 1 | 3 | 0.43 | 139.2 | 0.00 |
| g_demo_basketball | tracks / crops | cpu | 1 | 3 | 0.45 | 134 | 0.00 |
| g_demo_basketball | pose (synthetic, 6 chunks) | cpu | 6 | 18 | 1.70 | 35.3 | 0.00 |
| g_demo_basketball | events | cpu | 1 | 3 | 0.56 | 106.2 | 0.00 |
| g_demo_basketball | plate (clean background) | cpu | 1 | 1 | 15.36 | 3.9 | 0.00 |
| g_demo_basketball | embeddings (SigLIP, cpu) | cpu | 1 | 1 | 12.43 | 4.8 | 0.02 |
| g_demo_basketball | commentary (+ Kokoro TTS, cpu) | cpu | 1 | 1 | 10.10 | 5.9 | 0.03 |
| g_demo_basketball | hype | cpu | 1 | 1 | 0.24 | 253.2 | 0.00 |
| g_demo_basketball | tiera (per angle) | cpu | 9 | 9 | 0.97 | 61.7 | 0.01 |
| g_demo_basketball | segment (SAM 2.1, per play) | gpu | 3 | 3 | 62.22 | 1.0 | 0.01 |
| g_demo_basketball | tierc_scene (per play) | gpu | 3 | 3 | 11.74 | 5.1 | 0.01 |
| g_demo_basketball | tierb (per angle) | cpu | 9 | 9 | 8.22 | 7.3 | 0.01 |
| g_demo_basketball | tierc (per angle) | cpu | 15 | 15 | 10.86 | 5.5 | 0.00 |
| g_demo_basketball | vertical (9:16) | cpu | 1 | 1 | 1.80 | 33.4 | 0.00 |
| g_demo_basketball | broadcast | cpu | 1 | 1 | 15.32 | 3.9 | 0.01 |
| g_demo_pickleball | ingest | cpu | 1 | 1 | 3.06 | 19.6 | 0.01 |
| g_demo_pickleball | pose (6 chunks) | cpu | 6 | 6 | 0.67 | 89.4 | 0.00 |
| g_demo_pickleball | hype | cpu | 1 | 1 | 0.18 | 331.5 | 0.00 |
| g_demo_pickleball | condensed | cpu | 1 | 1 | 4.46 | 13.5 | 0.00 |

The tables omit stages that take under 0.15 s:

- calibrate, camera, track, court, triggers, plays, game, highlights;
- director, replays, tierc_manifest, search_index.

The GPU-lock wait was 0 for every GPU task. For the full table, run
`python -m replay_worker perf <copy>/data/demo/games/g_demo_basketball <copy>/data/demo/games/g_demo_pickleball`.

## 2. One CC BY clip (real footage, real models)

Clip: the 90 s pickleball doubles cut (`surrey2026`, source 100–190 s; CC BY 3.0,
attribution in docs/test-data.md). It is the same cut M8 and M9 used, with its
hand-clicked court landmarks. It is 1920x1080, 30 fps, AAC 44.1 kHz, about 1.9 Mbps.

The run used:

- YOLO11m detect + BoT-SORT and YOLO11m-pose on the GPU;
- then hype, condensed, director and broadcast;
- its own cache directory, so pass 1 is a true cold run.

Script: `cc_perf.sh` (M13 scratch). It runs `python -m replay_worker run <clip>` with
`--sport pickleball --variant doubles --model yolo11m.pt --set pose_model=yolo11m-pose.pt --stages hype,condensed,broadcast`.

| pass | tasks | misses | hits | worker wall s | x RT | `.cpu.lock` wait |
|---|---:|---:|---:|---:|---:|---|
| cold | 27 | 26 | 0 | 92.8 | 1.0 | not logged (about 0) |
| warm | 27 | 0 | 26 | 1.4 | 66 | 38 s (other agents' jobs) |

| stage | resource | median miss s | miss x RT | median hit s |
|---|---|---:|---:|---:|
| ingest (probe, proxy, audio extract) | cpu | 6.79 | 13.3 | 0.01 |
| calibrate (from landmarks) | cpu | 0.79 | 113.5 | 0.01 |
| audio | cpu | 0.99 | 91.0 | 0.02 |
| detect (YOLO11m + BoT-SORT, 2700 frames, about 114 fps) | gpu | 23.68 | 3.8 | 1.28 |
| track, court, identity, tracks, crops | cpu | 0.57 total | – | 0.00 |
| pose (YOLO11m-pose, 10 chunks) | gpu | 1.50 per chunk | 60.2 | 0.00 |
| triggers, events, plays | cpu | 0.18 total | – | 0.00 |
| hype | cpu | 0.22 | 407.4 | 0.01 |
| condensed (render 57.7 s of rallies) | cpu | 28.25 | 3.2 | 0.00 |
| broadcast (90 s rendition) | cpu | 47.81 | 1.9 | 0.00 |

On this clip, analysis up to `plays` is about 40 s for 90 s of video, or 2.2x real time.
The renders (condensed + broadcast, 76 s) dominate the rest.

An extrapolation that was **not measured**: a 30 min game would take about 13 min of
detect + pose, then linear-time renders. A 240 s cut of the same video was also run,
but its tier-B landmarks gave a degenerate team split (15 vs 1) and **0 events**. That
was not root-caused, so it is not reported here.

## 3. Fire TV rendition notes

These come from ffprobe of what the API serves. All files are H.264 High profile,
yuv420p, 30 fps, MP4. Fire TV Stick 4K and Cube decode H.264 High at 1080p30 in
hardware, so every file is within spec on paper. **Nothing has been played on a device.**

| file | resolution | duration | size | video+audio bitrate | audio |
|---|---|---:|---:|---:|---|
| demo `media/wide.mp4` (source proxy) | 1920x1080 | 60.0 s | 2.6 MB | 0.35 Mbps | AAC 16 kHz |
| demo `renditions/broadcast.mp4` | 1920x1080 | 60.0 s | 11.3 MB | 1.51 Mbps | AAC 48 kHz |
| demo `replays/<play>/<angle>.mp4` (x11 per play) | 1280x720 | 8.0 s | 0.7–0.84 MB | 0.69–0.84 Mbps | none |
| demo `exports/vertical/<id>.mp4` | 720x1280 | 10.5 s | 0.77 MB | 0.59 Mbps | AAC 48 kHz |
| demo pickleball `renditions/condensed.mp4` | 1280x720 | 32.8 s | 1.8 MB | 0.44 Mbps | AAC 48 kHz |
| CC `media/wide.mp4` | 1920x1080 | 90.0 s | 21.1 MB | 1.87 Mbps | AAC 44.1 kHz |
| CC `renditions/broadcast.mp4` | 1920x1080 | 90.0 s | 40.0 MB | 3.56 Mbps | AAC 48 kHz |
| CC `renditions/condensed.mp4` | 1280x720 | 57.7 s | 6.2 MB | 0.87 Mbps | AAC 48 kHz |

What these numbers imply for the device (none of it measured):

- Synthetic frames compress extremely well. The real-footage rows are the ones to plan
  bandwidth on: the broadcast is about 3.6 Mbps at 1080p.
- Replay angles have no audio track. The TV app switches angles at the same media time,
  so each switch is a new source load of a small 720p file.
- Seek latency on Fire OS (ExoPlayer) has not been measured.
- The API serves HTTP Range requests for all media. `Range: bytes=0-999` returned
  206 with 1000 bytes for wide, broadcast and a replay angle on the demo. There is no HLS/DASH
  ladder. An adaptive ladder is the AWS path (MediaConvert, docs/aws-integrations.md)
  and is not built.

## 4. Earlier runs (M2, worker bring-up)

| game | run | tasks | misses | hits | wall s | video s | x RT |
|---|---|---:|---:|---:|---:|---:|---:|
| g_synth_basketball_half (synthetic, 20 s) | cold | 10 | 9 | 0 | 1.3 | 20 | 15.8 |
| g_synth_basketball_half | warm | 10 | 0 | 9 | 0.0 | 20 | 625 |
| g_kennesaw_240s (local real clip, never committed) | cold, detect on GPU 50.9 s | – | – | – | – | 240 | – |
