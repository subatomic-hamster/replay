"""Generated text for M7 (vision items 9, 10, 22, 23 and "Grounding").

Everything here reads the game's structured JSON only (game.json roster, events.json,
plays.json, score.json, the stats response) and every generated sentence passes
`grounding.check` against the facts it was generated from:

- `grounding`  — facts doc + the automated check (names, numbers, action classes,
  shot values, score/lead claims, invented attributes)
- `commentary` — per-play play-by-play scripts: deterministic templates (the guaranteed
  path), optional LLM paraphrase that must pass the check or falls back; narration audio
- `advice`     — per-player insights from the player's own stats, same check
- `search`     — per-play embeddings index + text query re-ranked by the structured filter
- `routes`     — the additive API endpoints

It lives in the API package (not render/) because the API serves the text on demand and
must not need render's numpy/opencv stack; the worker's `narrate` stages import it too.
"""
