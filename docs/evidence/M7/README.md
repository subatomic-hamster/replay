# M7 evidence: grounded commentary, advice, free-text query, semantic search

**Everything in this folder is synthetic.** `g_bb90` is the full pipeline (ingest to plays) run on
`courtcam.synth` basketball half-court footage (seed 7, 90 s). The plays agent made it in
`_eval/out/basketball_half_s7_gt`. `g_half_gt` is the committed synthetic ground truth with
the test roster (Alex, Sam, Jordan...). The real-clip run (Kennesaw, 240 s) lives in
`docs/evidence/local/M7/` (gitignored; D-7).

Everything was measured on hfbox (RX 9070 XT, ROCm). The setup was the following:

- Box copy: `d=/workspace/wt/replay-commentary`.
- `PYTHONPATH=$d/courtcam:$d/services/api:$d/services/worker:$d/render`.
- `REPLAY_MODEL_VENVS=/workspace/wt/replay-env/venvs`.
- LLM: llama.cpp `llama-server` running Qwen3-4B-Instruct-2507 Q4_K_M with `-ngl 99`. The
  command is in the `providers/llm.py` docstring. Requests use temperature 0, seed 0 and
  json_schema output.

`make_evidence.py` holds every command used below (`python make_evidence.py -h`).

## Files

| file | what |
|---|---|
| `synthetic_bb90_narrated.mp4` | Director plus broadcast render (0–45 s, 960x540) with the Kokoro narration mixed in by `replay_render`'s mixer. Game audio ducks under the voice. |
| `script_bb90.json` | Commentary script (`replay.commentary.v1`). Each line carries its game time and audio slot. Each play carries its grounding report, the template lines and the LLM attempt. |
| `commentary_g_bb90.json` | Worker `commentary` stage run with the LLM paraphrase and CPU TTS, plus timings. |
| `grounding_template.json`, `grounding_llm.json` | Grounding pass rates over every synthetic play. |
| `ttsbench_cuda_bb90.json` | Kokoro on the GPU, all 23 lines of `g_bb90`. |
| `queries_half_gt.json` | Free-text query: rules first, then the validated LLM filter. |
| `advice_g_bb90.json`, `advice_g_half_gt.json` | Per-player advice (template, then LLM paraphrase, then grounding check). |
| `search_bb90.json` | `embeddings` (fan-out per play) and `search_index` stages, then 6 queries. |

## Results (measured)

Grounding uses the `grounding_*.json` commands. It covers 28 synthetic plays: 18 committed
`samples/synthetic/*` plays across five sports, plus 10 `g_bb90` plays.

- **Template path: 28/28 grounded (100%).** The unit test
  `test_templates_are_grounded_on_every_synthetic_play` also checks every committed synthetic
  play: named and unnamed rosters, with and without injected points and score.
- **LLM paraphrase: 26/28 accepted (92.9%).** Both rejections were `absent_action`. One was
  "Team B scores." on a pickleball point: "scores" is a basketball made-shot claim, so the
  check rejects it and the line falls back to the template. LLM latency was a median of
  0.267 s per play (max 0.321 s) at about 131 tokens/s.
- The run with the real Kennesaw plays added (local only): 30/32 LLM accepted, template 32/32.

Commentary stage on `g_bb90` (`commentary g_bb90 ... --llm`, TTS on CPU because llama-server
held the GPU lock):

- 10/10 plays grounded, 10/10 LLM paraphrases accepted; the stage took 16.2 s.
- LLM: median 0.277 s per play.
- Kokoro on CPU: load 1.08 s, median 0.346 s per line, 61.3 s of audio for 23 lines.

TTS on the GPU (`ttsbench`, `REPLAY_MODEL_DEVICE=cuda`):

- Median 0.185 s per line (max 0.963 s, the first line includes warm-up); RTF 0.085, 0.52 s per play.
- Load 1.19 s; the child process took 10.2 s including imports.
- The 267 s wall time was almost entirely waiting on the shared GPU lock.

Free-text query (`queries g_half_gt ...`). When the rules match a vocab phrase, the rules
answer alone. Otherwise the LLM may only fill a json_schema filter (event type, made/missed,
shot value, rostered player, half, longest). It never produces a time. A deterministic
validator then keeps only the fields the text grounds.

- "show me every time Quinn stole the ball" gives Quinn — steals.
- "passes from Jordan" gives Jordan — passes.
- "baskets in the second half" gives shots — 2nd half.
- "Morgan three pointers" gives Morgan — three-point shots.
- For "the crowd going wild", the validator dropped the whole filter, so there is no match.
- LLM median: 0.581 s per query.

Advice (`advice ... --llm`):

- Templates are grounded for every player: 10/10 in `g_bb90` and 8/8 in `g_half_gt`.
- LLM paraphrases accepted: 7/10 and 8/8. The rejections were an unknown capitalised word
  ("Grab", "Perfect") and "you're ahead" read as a lead claim. The templates were kept.
- LLM median: 0.294 s and 0.187 s per player.

Search (`search g_bb90 ...`, SigLIP ViT-B-16 on the GPU). Each play stores a (2, 768) vector:
the mean of four keyframes plus the play text. On this footage SigLIP alone does not separate
the plays:

- Image cosines are almost identical (synthetic frames look alike).
- The text tower prefers short texts.

So ranking is: the structured-filter hit first, then word overlap with the play text, then RRF
over the image and text cosines. With that order, "a steal" ranks the two steal plays first,
"rebound" the two rebound plays, and "Player 4 scores" puts Player 4's basket first. Index
build took 107 s for 10 plays (about 6 s per runner call plus waiting on the GPU lock).

## Integration point for the broadcast mixer

The `commentary` stage writes `<game>/commentary/narration.wav` on the game clock. It also
writes `<play_id>.wav` per play and `script.json`. To hand the narration to the broadcast
stage, set `cfg["narration"] = "<game>/commentary/narration.wav"` (an optional
`"{narration}"` input; see `cmd_render`). The same path works with
`python -m replay_render ... --narration`.
