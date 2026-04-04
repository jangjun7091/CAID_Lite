"""Anthropic backend (Claude 3.5 / 4.x models).

Configuration:
  ANTHROPIC_API_KEY — required at generate() time

Install the optional dependency with: pip install caid-lite[anthropic]

Phase 1 status: interface stub — generate() raises NotImplementedError.
Full implementation planned for a future phase once Qwen baseline is complete.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

from ..base import LLMConfig

if TYPE_CHECKING:
    import anthropic as _anthropic


class AnthropicBackend:
    """Anthropic Claude backend.

    Implements the ``LLMBackend`` protocol using the ``anthropic`` Python SDK.
    Note that Anthropic's messages API uses a separate ``system`` parameter
    rather than a system-role message; the adapter handles this internally.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client: Optional[_anthropic.Anthropic] = None

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        raise NotImplementedError(
            "AnthropicBackend.generate() is not yet implemented. "
            "Use provider='qwen' or provider='local' for now."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> "_anthropic.Anthropic":  # pragma: no cover
        if self._client is not None:
            return self._client

        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required for AnthropicBackend. "
                "Install it with: pip install caid-lite[anthropic]"
            ) from exc

        api_key = self._config.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it as an environment variable or pass api_key in LLMConfig."
            )

        self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def __repr__(self) -> str:
        return f"AnthropicBackend(model={self._config.model!r})"
