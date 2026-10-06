"""Provider selection (REPLAY_PROVIDER_<NAME>) and the AWS stubs' signatures."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from replay_api import providers
from replay_api.providers import NotConfiguredError

NEW = ("tts", "llm", "embeddings", "face", "speaker")


def _methods(cls: type) -> dict[str, inspect.Signature]:
    return {
        n: inspect.signature(f)
        for n, f in vars(cls).items()
        if callable(f) and not n.startswith("_")
    }


def _dummy(param: inspect.Parameter):
    return {"fraction": 0.5, "t_start": 0.0, "t_end": 1.0}.get(param.name, Path("x"))


@pytest.mark.parametrize("name", list(providers.REGISTRY))
def test_aws_stub_mirrors_protocol_and_raises(name):
    proto = providers.protocol(name)
    stub = providers.implementation(name, "aws")
    assert _methods(stub) == _methods(proto), f"{stub.__name__} drifted from {proto.__name__}"
    assert "Target:" in (stub.__doc__ or "") and "TODO" in (stub.__doc__ or "")
    obj = stub()
    for meth, sig in _methods(stub).items():
        params = [p for p in sig.parameters.values() if p.name != "self"]
        args = [
            _dummy(p) for p in params if p.default is p.empty and p.kind == p.POSITIONAL_OR_KEYWORD
        ]
        with pytest.raises(NotImplementedError, match="stub"):
            getattr(obj, meth)(*args)


@pytest.mark.parametrize("name", list(providers.REGISTRY))
def test_local_implements_protocol(name):
    proto, local = providers.protocol(name), providers.implementation(name, "local")
    for meth, sig in _methods(proto).items():
        assert meth in _methods(local), f"{local.__name__}.{meth} missing"
        assert list(sig.parameters) == list(_methods(local)[meth].parameters)


def test_selection_by_env(monkeypatch, tmp_path):
    assert providers.kind("tts") == "local"
    assert type(providers.create("storage", games_dir=tmp_path)).__name__ == "LocalStorage"
    monkeypatch.setenv("REPLAY_PROVIDER_STORAGE", "aws")
    monkeypatch.setenv("REPLAY_PROVIDER_TTS", "AWS")
    assert type(providers.create("storage", games_dir=tmp_path)).__name__ == "S3Storage"
    assert type(providers.create("tts")).__name__ == "PollyTTS"
    monkeypatch.setenv("REPLAY_PROVIDER_LLM", "azure")
    with pytest.raises(ValueError, match="REPLAY_PROVIDER_LLM"):
        providers.kind("llm")
    with pytest.raises(KeyError):
        providers.kind("nope")


@pytest.mark.parametrize("name", NEW)
def test_new_local_providers_say_not_configured(name):
    obj = providers.create(name)
    meth, sig = next(iter(_methods(type(obj)).items()))
    params = [p for p in sig.parameters.values() if p.name != "self"]
    args = [_dummy(p) for p in params if p.default is p.empty and p.kind == p.POSITIONAL_OR_KEYWORD]
    with pytest.raises(NotConfiguredError, match=name):
        getattr(obj, meth)(*args)


def test_app_exposes_providers(client):
    body = client.get("/healthz").json()
    assert body["provider_kinds"]["tts"] == "local"
    assert type(client.app.state.tts).__name__ == "LocalTTS"
