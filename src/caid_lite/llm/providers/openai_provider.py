"""OpenAI backend (GPT-4o, GPT-4.1, o1, etc.).

Configuration:
  OPENAI_API_KEY — required at generate() time

Phase 1 status: interface stub — generate() raises NotImplementedError.
Full implementation planned for a future phase once Qwen baseline is complete.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

from ..base import LLMConfig

if TYPE_CHECKING:
    from openai import OpenAI as _OpenAI


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
        raise NotImplementedError(
            "OpenAIBackend.generate() is not yet implemented. "
            "Use provider='qwen' or provider='local' for now."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> "_OpenAI":  # pragma: no cover
        if self._client is not None:
            return self._client

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for OpenAIBackend. "
                "Install it with: pip install openai"
            ) from exc

        api_key = self._config.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY is not set. "
                "Export it as an environment variable or pass api_key in LLMConfig."
            )

        self._client = OpenAI(api_key=api_key)
        return self._client

    def __repr__(self) -> str:
        return f"OpenAIBackend(model={self._config.model!r})"
