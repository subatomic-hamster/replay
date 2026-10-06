# M13 UI evidence: broadcast, clips, hype, rallies, review, share, search

1080p screenshots of the react-native-tvos app (its react-native-web build), produced by
`apps/tv/e2e-evidence/M13-ui.spec.ts`. Every frame here is **synthetic**. No frame comes
from `samples/real/`.

## `tv-synthetic-live/`: the real API on worker-processed synthetic games

`services/api` (uvicorn, `REPLAY_PIPELINE=fake`) serves a data dir holding two games. The
worker processed each one from a `samples/synthetic` render:

- `g_synbb`: "SYNTHETIC basketball half (seed 7)", 40 s. The worker ran the courtcam
  stages, then director, hype, commentary (Kokoro TTS narration) and broadcast.
- `g_synpb`: "SYNTHETIC pickleball doubles (seed 11)", 40 s. The worker ran the courtcam
  stages, then hype.

What the run does against the real API:

- **Phone tap.** The spec POSTs `/games/g_synbb/triggers` at the end of the first play,
  as the phone companion does. That cuts a "Phone tap" clip (03).
- **Trim.** `PATCH /clips/c_0001` (04).
- **9:16 export.** `POST /exports/vertical`, rendered as an API job (05).
- **Search.** `POST /search` returns 409 because the game has no embeddings index, so the
  client falls back to `/query` and labels the result as a fallback (06).
- **Advice and review.** Template advice (07) and `GET /review/queue` with the extended
  box score (08).
- **Rallies.** The rally browser (09), then `POST /condensed` renders the condensed game,
  which plays with the rally counter (10).

## `tv-mock/`: the mock fixture

The same spec runs against `packages/tv-core/src/mock.ts`, the synthetic fixtures every
Playwright spec uses. Here the video for every rendition, export and condensed game is
the same 20 s fixture clip, so 05 shows the 16:9 fixture squeezed into the 9:16 preview.

## Screens

| File | Screen |
| --- | --- |
| 01 | Watch in broadcast mode. The rendition carries its own audio mix, so it is unmuted. Commentary captions are on and the hype meter sits above the scrubber. |
| 02 | Hype peak: the playhead jumps to 3 s before the next hype candidate. |
| 03 | Clips: the trigger type (X gesture / Phone tap / Voice) and attribution. |
| 04 | The D-pad trimmer after Save trim. |
| 05 | Share 9:16: the export rendered, with a portrait preview and its link. |
| 06 | Search: matches are ranked first, and the fallback is labelled. |
| 07 | The per-player advice panel. |
| 08 | Review: the API queue, the confidence label, an unknown-outcome ring, and the box score with Pts, Stl and Dist columns. |
| 09 | Rallies sorted longest first, playing one with the rally counter. |
| 10 | The condensed game playing, with the counter in sync. |

## How to reproduce (on the box)

```sh
# API on the synthetic data dir
REPLAY_PIPELINE=fake REPLAY_DATA_DIR=<data> python -m uvicorn replay_api.main:app --port 8020 &

cd apps/tv

# against the API
REPLAY_TV_API=http://localhost:8020 REPLAY_TV_EVIDENCE_DIR=<out> \
  REPLAY_TV_EVIDENCE_GAME=g_synbb REPLAY_TV_EVIDENCE_NET_GAME=g_synpb \
  pnpm exec playwright test --project=evidence M13

# against the mock fixture
REPLAY_TV_API=mock REPLAY_TV_EVIDENCE_DIR=<out> pnpm exec playwright test --project=evidence M13
```

Run both under `flock /workspace/wt/replay-env/.pw.lock`. Both runs passed, 4/4 each.
