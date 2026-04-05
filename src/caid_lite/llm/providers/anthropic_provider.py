"""Anthropic backend (Claude 3.5 / 4.x models).

Configuration:
  ANTHROPIC_API_KEY — required at generate() time

Install the optional dependency with: pip install caid-lite[anthropic]
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

from ..base import LLMConfig

if TYPE_CHECKING:
    import anthropic as _anthropic

_PLACEHOLDER_KEYS = frozenset({
    "", "none", "sk-ant-placeholder", "your_anthropic_key_here", "placeholder",
})


class AnthropicBackend:
    """Anthropic Claude backend.

    Implements the ``LLMBackend`` protocol using the ``anthropic`` Python SDK.
    Anthropic's messages API uses a separate ``system`` parameter rather than
    a system-role message; this adapter handles the mapping internally.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client: Optional["_anthropic.Anthropic"] = None

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        """Call the Anthropic messages endpoint and return raw text."""
        client = self._get_client()
        message = client.messages.create(
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # Extract text from the first content block
        for block in message.content:
            if hasattr(block, "text"):
                return block.text
        return ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> "_anthropic.Anthropic":
        if self._client is not None:
            return self._client

        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required for AnthropicBackend. "
                "Install it with: pip install caid-lite[anthropic]"
            ) from exc

        api_key = self._config.api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or api_key.lower() in _PLACEHOLDER_KEYS:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set or contains a placeholder value.\n"
                "Steps to fix:\n"
                "  1. Open .env in the project root\n"
                "  2. Set ANTHROPIC_API_KEY=sk-ant-...\n"
                "  3. Get a key at: https://console.anthropic.com/"
            )

        self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def __repr__(self) -> str:
        return f"AnthropicBackend(model={self._config.model!r})"
