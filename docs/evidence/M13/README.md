# M13 evidence: the `make demo` game, README media

Everything here is **synthetic**. It comes from the two games that `make demo` builds:
`courtcam synth` basketball full court and pickleball doubles, 60 s each, seed 11, 1920x1080.
The worker runs them with the synthetic detector (scripts/box-demo.sh). There is no real
footage. The README and docs/demo-script.md use these files.

| file | what | how |
|---|---|---|
| `demo_broadcast_replay.gif` (1.0 MB) | broadcast rendition, 17–24 s: score bug, sting, 0.5x REPLAY | `ffmpeg -ss 17 -t 7 -i <game>/renditions/broadcast.mp4 -vf "fps=10,scale=560:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"` |
| `demo_replay_angles_pl_0001.jpg` (168 KB) | highlight `pl_0001` at +6.0 s from all 11 pre-rendered angles (Tier A 3, Tier B 3, Tier C 5) | `python sheet.py <game> pl_0001 6.0 out.jpg` |
| `tv-demo/00-library.png` … `04-follow.png` | TV app (web build, 1920x1080) on the demo games: library, broadcast mode with commentary captions, wide, player select, follow | `tvshots.sh <copy dir>` runs `apps/tv` `--project=evidence` against a hard-linked copy of the demo games (API on :8091) |

| `tv-demo-rerun/M3/01..09.jpg`, `tv-demo-rerun/M13/01..10.jpg` | the full `M3-walkthrough` (library → follow → spotlight → tag dialog → highlights → review) and `M13-ui` (broadcast + captions, hype peak, phone-tap clip, trim, 9:16 share, search, advice, review, rallies, condensed) runs on the demo games, 1280x720 JPEG | as `tvshots.sh`, but `--project=evidence M3-walkthrough` and `M13-ui` separately, each into its own dir, then `ffmpeg -vf scale=1280:-2 -q:v 5` |

`<game>` = `<copy>/data/demo/games/g_demo_basketball`.

## Caveats

- The first run of the evidence specs (`M3-walkthrough`, `M13-ui`) went against the
  in-progress TV menu restructure: the tag dialog did not open on `t` and an M13 test failed,
  so only `tv-demo/00..04` were kept. The 2026-10-06 re-run (`tv-demo-rerun/`, a fresh
  `make demo` build with `DEMO_FAKE_SEGMENT=1`) passes both specs (M3 1/1, M13 4/4) with no
  spec change. One real bug showed up and is fixed: the API reports a 9:16 export (and the
  condensed game) "done" as soon as its MP4 exists, while the render was still muxing into
  that path, so the TV loaded a half-written file and showed "Video unavailable".
  `render/replay_render/compositor.py` now muxes to `<out>.part.mp4` and renames.
- Commentary captions are the template lines. Narration is Kokoro TTS when the box's
  `tts` model venv exists.
- The Tier B and Tier C angles are the labelled approximations in D-54..D-59.
