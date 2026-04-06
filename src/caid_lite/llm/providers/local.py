"""Local OpenAI-compatible server backend (vLLM, LM Studio, Ollama, etc.).

Any server that exposes a ``/v1/chat/completions`` endpoint can be used here.

Configuration:
  LOCAL_API_BASE — server URL, e.g. http://localhost:8000/v1
  LOCAL_API_KEY  — set to "none" for servers that don't require authentication

This backend shares the same ``openai`` client as ``QwenBackend`` but reads
different env vars and defaults, making it convenient for local development
without cloud API costs.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

from ..base import LLMConfig

if TYPE_CHECKING:
    from openai import OpenAI as _OpenAI


_DEFAULT_API_BASE = "http://localhost:8000/v1"
_DEFAULT_API_KEY = "none"


class LocalBackend:
    """Backend for any OpenAI-compatible local inference server.

    The OpenAI client is created lazily so that ``LLMFactory.create()``
    succeeds without a running server — the error surfaces at ``generate()``
    time instead.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client: Optional[_OpenAI] = None

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        """Call the local server and return the raw response text."""
        client = self._get_client()
        response = client.chat.completions.create(
            model=self._config.model,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            timeout=self._config.timeout_s,
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
                "The 'openai' package is required for LocalBackend. "
                "Install it with: pip install openai"
            ) from exc

        api_key = (
            self._config.api_key
            or os.getenv("LOCAL_API_KEY", _DEFAULT_API_KEY)
        )
        api_base = (
            self._config.api_base
            or os.getenv("LOCAL_API_BASE", _DEFAULT_API_BASE)
        )

        self._client = OpenAI(api_key=api_key, base_url=api_base)
        return self._client

    def __repr__(self) -> str:
        api_base = self._config.api_base or os.getenv(
            "LOCAL_API_BASE", _DEFAULT_API_BASE
        )
        return f"LocalBackend(model={self._config.model!r}, base_url={api_base!r})"
