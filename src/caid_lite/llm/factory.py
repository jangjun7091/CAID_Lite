"""LLMFactory: resolves a provider name + config to a concrete LLMBackend."""

from __future__ import annotations

from .base import LLMBackend, LLMConfig
from .providers.qwen import QwenBackend
from .providers.openai_provider import OpenAIBackend
from .providers.anthropic_provider import AnthropicBackend
from .providers.local import LocalBackend


class LLMFactory:
    """Maps ``LLMConfig.provider`` → the correct ``LLMBackend`` subclass.

    Env-var overrides (``LLM_PROVIDER``, ``LLM_MODEL``) are applied here
    before the backend is constructed, so callers never need to read env vars
    themselves.

    Adding a new provider requires:
      1. Create ``llm/providers/myprovider.py`` implementing ``LLMBackend``.
      2. Import it here and add one ``case`` line in ``create()``.
      3. Document its env vars in ``.env.example``.
    No other files need to change.
    """

    @staticmethod
    def create(config: LLMConfig) -> LLMBackend:
        """Return the backend instance for the resolved provider.

        Args:
            config: Base config; env vars are applied on top before dispatch.

        Returns:
            A concrete ``LLMBackend`` implementation.

        Raises:
            ValueError: If the resolved provider name is not recognised.
        """
        resolved = config.with_env_overrides()

        match resolved.provider:
            case "qwen":
                return QwenBackend(resolved)
            case "openai":
                return OpenAIBackend(resolved)
            case "anthropic":
                return AnthropicBackend(resolved)
            case "local":
                return LocalBackend(resolved)
            case _:
                supported = "qwen | openai | anthropic | local"
                raise ValueError(
                    f"Unknown LLM provider: '{resolved.provider}'. "
                    f"Supported providers: {supported}."
                )

    @staticmethod
    def from_yaml(llm_section: dict) -> LLMBackend:
        """Convenience builder from the ``llm:`` dict in ``default.yaml``.

        Example::

            import yaml
            data = yaml.safe_load(Path("config/default.yaml").read_text())
            backend = LLMFactory.from_yaml(data["llm"])
        """
        config = LLMConfig.from_dict(llm_section)
        return LLMFactory.create(config)
