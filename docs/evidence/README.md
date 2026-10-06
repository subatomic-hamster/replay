# Evidence

Proof that a milestone works: screenshots, short clips, logs, metrics. One folder per
milestone: `docs/evidence/<milestone>/` (e.g. `M2/worker-cache.txt`, `M3/select-mode.png`).

## Rules

- **Committed evidence is synthetic or Creative-Commons only.** Synthetic means produced
  from `samples/synthetic/` (label it "synthetic" in the file name or caption). CC footage
  only when its license allows redistribution and it is listed in docs/test-data.md.
- **Anything derived from `samples/real/`** (YouTube-licensed local test footage, D-7) —
  frames, renders, crops, GIFs — goes to `docs/evidence/local/<milestone>/`, which is
  gitignored. Reference it from progress notes by path only; never copy it elsewhere.
  Numbers measured on real footage (timings, P/R) may be committed as text.
- Keep files small: PNG/GIF/MP4 under ~5 MB each. Prefer a PNG or a 5–10 s clip to a
  full render.
- No faces or voices of people who have not opted in, no music, no broadcaster logos.
- Every file says how it was produced (a caption line in the progress entry or a
  sibling `.txt` with the exact command). Never hand-edit pipeline output and present it
  as evidence.
