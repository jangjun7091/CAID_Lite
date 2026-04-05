"""OpenAI backend (GPT-4o, GPT-4.1, o1, etc.).

Configuration:
  OPENAI_API_KEY — required at generate() time
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

from ..base import LLMConfig

if TYPE_CHECKING:
    from openai import OpenAI as _OpenAI

_PLACEHOLDER_KEYS = frozenset({
    "", "none", "sk-placeholder", "your_openai_key_here", "placeholder",
})


class OpenAIBackend:
    """OpenAI GPT model backend.

    Implements the same ``LLMBackend`` protocol as ``QwenBackend`` using the
    official ``openai`` Python client.  The client is created lazily so that
    ``LLMFactory.create()`` succeeds even without an API key present.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client: Optional[_OpenAI] = None

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        """Call the OpenAI chat completions endpoint and return raw text."""
        client = self._get_client()
        response = client.chat.completions.create(
            model=self._config.model,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> "_OpenAI":
        if self._client is not None:
            return self._client

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for OpenAIBackend. "
                "Install it with: pip install openai"
            ) from exc

        api_key = self._config.api_key or os.getenv("OPENAI_API_KEY", "")
        if not api_key or api_key.lower() in _PLACEHOLDER_KEYS:
            raise EnvironmentError(
                "OPENAI_API_KEY is not set or contains a placeholder value.\n"
                "Steps to fix:\n"
                "  1. Open .env in the project root\n"
                "  2. Set OPENAI_API_KEY=sk-...\n"
                "  3. Get a key at: https://platform.openai.com/api-keys"
            )

        self._client = OpenAI(api_key=api_key)
        return self._client

    def __repr__(self) -> str:
        return f"OpenAIBackend(model={self._config.model!r})"
