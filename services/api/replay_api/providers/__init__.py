"""Provider interfaces (Protocols), their local implementations and AWS stubs.

Layout: one module per provider holds its Protocol and its local implementation
(`storage.py`, `index.py`, ..., `speaker.py`); every AWS implementation lives in `aws.py`
as a signature-complete stub naming its target service. Routes only ever see the
Protocol. `REPLAY_PROVIDER_<NAME>=local|aws` picks the implementation (`create`).
docs/aws-integrations.md maps each one to its service and what switching needs.
"""

from __future__ import annotations

import importlib
import os

KINDS = ("local", "aws")

# name -> (Protocol, local implementation, AWS stub), as "module:Class" under this package
REGISTRY: dict[str, tuple[str, str, str]] = {
    "storage": ("storage:Storage", "storage:LocalStorage", "aws:S3Storage"),
    "index": ("index:Index", "index:LocalIndex", "aws:DynamoIndex"),
    "jobs": ("jobs:Jobs", "jobs:LocalJobs", "aws:StepFunctionsJobs"),
    "labeler": ("labeler:Labeler", "labeler:HeuristicLabeler", "aws:NovaLabeler"),
    "query": ("query:QueryEngine", "query:RuleQueryEngine", "aws:ConverseQueryEngine"),
    "tts": ("tts:TTS", "tts:LocalTTS", "aws:PollyTTS"),
    "llm": ("llm:LLM", "llm:LocalLLM", "aws:BedrockLLM"),
    "embeddings": ("embeddings:Embeddings", "embeddings:LocalEmbeddings", "aws:BedrockEmbeddings"),
    "face": ("face:Face", "face:LocalFace", "aws:RekognitionFace"),
    "speaker": ("speaker:Speaker", "speaker:LocalSpeaker", "aws:SageMakerSpeaker"),
}


class NotConfiguredError(RuntimeError):
    """A local provider whose model has not been wired in yet."""


def _load(ref: str) -> type:
    mod, _, cls = ref.partition(":")
    return getattr(importlib.import_module(f".{mod}", __name__), cls)


def kind(name: str) -> str:
    if name not in REGISTRY:
        raise KeyError(f"unknown provider {name!r}; known: {list(REGISTRY)}")
    value = os.environ.get(f"REPLAY_PROVIDER_{name.upper()}", "local").strip().lower()
    if value not in KINDS:
        raise ValueError(f"REPLAY_PROVIDER_{name.upper()}={value!r}; expected one of {KINDS}")
    return value


def protocol(name: str) -> type:
    return _load(REGISTRY[name][0])


def implementation(name: str, which: str | None = None) -> type:
    which = which or kind(name)
    return _load(REGISTRY[name][1 if which == "local" else 2])


def create(name: str, **local_kwargs):
    """The selected implementation. Local ones take their constructor arguments; the
    AWS stubs take none (their config will come from env vars, see their docstrings)."""
    which = kind(name)
    cls = implementation(name, which)
    return cls(**local_kwargs) if which == "local" else cls()
