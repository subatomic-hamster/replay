#!/usr/bin/env python
"""Generate the synthetic CI fixtures (plan §7.4).

Thin wrapper around `courtcam.synth`; identical to `courtcam synth`.

    uv run python samples/synthetic/generate.py --out samples/synthetic/basketball_half
"""

from __future__ import annotations

import sys

from courtcam.cli import app

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "synth", *sys.argv[1:]]
    app()
