"""LLM provider (commentary scripts, advice, card titles, free-text → structured filter).

Grounding rule (vision): callers hand it structured JSON and accept only structured
output; it never invents timestamps. AWS: Bedrock Converse / Nova (`aws.BedrockLLM`).

Local: a llama.cpp server (OpenAI-compatible) running Qwen3-4B-Instruct-2507 Q4_K_M on
the GPU (D-39). `REPLAY_LLM_URL` points at it; unset → NotConfiguredError. Deterministic:
temperature 0 and a fixed seed; with `json_schema` the server constrains decoding to the
schema (syntax only — callers always validate meaning). Start it on the box with:

    D=/workspace/wt/replay-env/models/llama.cpp
    flock /workspace/airtools/.gpu.lock timeout 3600 env \
      LD_LIBRARY_PATH=$D/llama-b11433:$D/rocmlibs:/opt/venv/lib/python3.12/site-packages/torch/lib \
      $D/llama-b11433/llama-server -m /workspace/wt/replay-env/models/gguf/Qwen3-4B-Instruct-2507-Q4_K_M.gguf \
      -ngl 99 -c 4096 --host 127.0.0.1 --port 18081
    export REPLAY_LLM_URL=http://127.0.0.1:18081

(the server holds the GPU lock for its lifetime: run it for a batch, then stop it.)
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol

from . import NotConfiguredError


class LLM(Protocol):
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: dict | None = None,
        max_tokens: int = 512,
    ) -> str:
        """Return the model's text; with `json_schema`, a JSON document matching it."""
        ...


class LocalLLM:
    """llama.cpp server client (stdlib HTTP)."""

    def __init__(self, url: str | None = None, seed: int = 0, timeout_s: float = 120.0):
        self.url = (url or os.environ.get("REPLAY_LLM_URL") or "").rstrip("/")
        self.seed = seed
        self.timeout_s = timeout_s
        self.last: dict = {}  # the server's `timings` for the last call

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: dict | None = None,
        max_tokens: int = 512,
    ) -> str:
        if not self.url:
            raise NotConfiguredError(
                "llm: set REPLAY_LLM_URL to a llama.cpp server (see providers/llm.py)"
            )
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        body: dict = {
            "messages": messages,
            "temperature": 0,
            "seed": self.seed,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "strict": True, "schema": json_schema},
            }
        req = urllib.request.Request(
            f"{self.url}/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            doc = json.loads(resp.read())
        self.last = doc.get("timings") or {}
        return doc["choices"][0]["message"]["content"]
