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

`<game>` = `<copy>/data/demo/games/g_demo_basketball`.

## Caveats

- The evidence specs in `apps/tv/e2e-evidence` (`M3-walkthrough`, `M13-ui`) did not fully
  pass against the in-progress TV menu restructure (2026-10-06). The tag dialog did not
  open on `t`, and the M13 watch test failed. Only the screenshots up to `04-follow`
  match the screen they are named after, and only those are kept. The run's
  `05-follow-spotlight` showed the pairing screen, so it was dropped.
- Commentary captions are the template lines. Narration is Kokoro TTS when the box's
  `tts` model venv exists.
- The Tier B and Tier C angles are the labelled approximations in D-54..D-59.
