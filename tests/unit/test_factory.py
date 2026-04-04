"""Tests for LLMFactory and LLMConfig."""

from __future__ import annotations

import pytest

from caid_lite.llm.base import LLMBackend, LLMConfig
from caid_lite.llm.factory import LLMFactory
from caid_lite.llm.providers.anthropic_provider import AnthropicBackend
from caid_lite.llm.providers.local import LocalBackend
from caid_lite.llm.providers.openai_provider import OpenAIBackend
from caid_lite.llm.providers.qwen import QwenBackend
from tests.fixtures.mock_llm import MockLLMBackend


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cfg(provider: str, model: str = "test-model") -> LLMConfig:
    return LLMConfig(provider=provider, model=model)


# ── LLMConfig ─────────────────────────────────────────────────────────────────


class TestLLMConfig:
    def test_from_dict_minimal(self):
        cfg = LLMConfig.from_dict({"provider": "qwen", "model": "qwen3"})
        assert cfg.provider == "qwen"
        assert cfg.model == "qwen3"
        assert cfg.temperature == 0.2
        assert cfg.max_tokens == 4096

    def test_from_dict_overrides(self):
        cfg = LLMConfig.from_dict(
            {"provider": "local", "model": "llama", "temperature": 0.5, "max_tokens": 512}
        )
        assert cfg.temperature == 0.5
        assert cfg.max_tokens == 512

    def test_with_env_overrides_provider(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        cfg = _cfg("qwen").with_env_overrides()
        assert cfg.provider == "openai"

    def test_with_env_overrides_model(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        cfg = _cfg("qwen", model="old-model").with_env_overrides()
        assert cfg.model == "gpt-4o"

    def test_with_env_overrides_is_lowercase(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "QWEN")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        cfg = _cfg("local").with_env_overrides()
        assert cfg.provider == "qwen"

    def test_with_env_overrides_no_env(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        original = _cfg("anthropic", model="claude")
        result = original.with_env_overrides()
        assert result.provider == "anthropic"
        assert result.model == "claude"


# ── LLMFactory.create ─────────────────────────────────────────────────────────


class TestLLMFactoryCreate:
    def test_qwen_provider(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        backend = LLMFactory.create(_cfg("qwen"))
        assert isinstance(backend, QwenBackend)

    def test_openai_provider(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        backend = LLMFactory.create(_cfg("openai"))
        assert isinstance(backend, OpenAIBackend)

    def test_anthropic_provider(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        backend = LLMFactory.create(_cfg("anthropic"))
        assert isinstance(backend, AnthropicBackend)

    def test_local_provider(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        backend = LLMFactory.create(_cfg("local"))
        assert isinstance(backend, LocalBackend)

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            LLMFactory.create(_cfg("bogus"))

    def test_unknown_provider_message_lists_supported(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        with pytest.raises(ValueError, match="qwen"):
            LLMFactory.create(_cfg("not_a_real_provider"))

    def test_env_var_overrides_provider(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "local")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        # Config says qwen, but env says local
        backend = LLMFactory.create(_cfg("qwen"))
        assert isinstance(backend, LocalBackend)

    def test_env_var_overrides_model(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "overridden-model")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        backend = LLMFactory.create(_cfg("local", model="original-model"))
        assert backend._config.model == "overridden-model"

    def test_config_fields_passed_through(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        cfg = LLMConfig(provider="local", model="llama", temperature=0.7, max_tokens=512)
        backend = LLMFactory.create(cfg)
        assert backend._config.temperature == 0.7
        assert backend._config.max_tokens == 512


# ── LLMFactory.from_yaml ──────────────────────────────────────────────────────


class TestLLMFactoryFromYaml:
    def test_builds_correct_backend(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        backend = LLMFactory.from_yaml({"provider": "local", "model": "test"})
        assert isinstance(backend, LocalBackend)

    def test_env_override_still_applies(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        backend = LLMFactory.from_yaml({"provider": "local", "model": "test"})
        assert isinstance(backend, OpenAIBackend)


# ── Protocol compliance ───────────────────────────────────────────────────────


class TestLLMBackendProtocol:
    def test_mock_satisfies_protocol(self):
        mock = MockLLMBackend(responses=["hello"])
        assert isinstance(mock, LLMBackend)

    def test_qwen_satisfies_protocol(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        backend = LLMFactory.create(_cfg("qwen"))
        assert isinstance(backend, LLMBackend)

    def test_local_satisfies_protocol(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        backend = LLMFactory.create(_cfg("local"))
        assert isinstance(backend, LLMBackend)

    def test_openai_satisfies_protocol(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        backend = LLMFactory.create(_cfg("openai"))
        assert isinstance(backend, LLMBackend)

    def test_anthropic_satisfies_protocol(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        backend = LLMFactory.create(_cfg("anthropic"))
        assert isinstance(backend, LLMBackend)
