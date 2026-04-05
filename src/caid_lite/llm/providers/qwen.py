"""Qwen backend via OpenAI-compatible API.

Supports:
  - DashScope International: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
  - DashScope China (default fallback): https://dashscope.aliyuncs.com/compatible-mode/v1
  - OpenRouter:              https://openrouter.ai/api/v1
  - Self-hosted vLLM:        http://localhost:8000/v1

Configuration (env vars take precedence over LLMConfig fields):
  QWEN_API_KEY   — required at generate() time
  QWEN_API_BASE  — strongly recommended; set to the correct regional endpoint
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

from ..base import LLMConfig

if TYPE_CHECKING:
    from openai import OpenAI as _OpenAI


_DEFAULT_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Keys that must never be treated as real credentials.
_PLACEHOLDER_KEYS = frozenset({
    "", "none", "your_dashscope_key_here", "your_api_key_here",
    "sk-placeholder", "placeholder", "changeme",
})


class QwenBackend:
    """Qwen3-Coder via an OpenAI-compatible ``/v1/chat/completions`` endpoint.

    The OpenAI client is created lazily on the first call to ``generate()``,
    so ``LLMFactory.create()`` never fails due to a missing API key — the
    error surfaces only when the model is actually called.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client: Optional[_OpenAI] = None

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        """Call the Qwen3-Coder endpoint and return the raw response text."""
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
                "The 'openai' package is required for QwenBackend. "
                "Install it with: pip install openai"
            ) from exc

        api_key = self._config.api_key or os.getenv("QWEN_API_KEY", "")
        if not api_key or api_key.lower() in _PLACEHOLDER_KEYS:
            raise EnvironmentError(
                "QWEN_API_KEY is not set or contains a placeholder value.\n"
                "Steps to fix:\n"
                "  1. Open .env in the project root\n"
                "  2. Replace 'your_dashscope_key_here' with your real DashScope key\n"
                "  3. International endpoint: "
                "https://dashscope-intl.aliyuncs.com/compatible-mode/v1\n"
                "  4. Get a key at: https://www.alibabacloud.com/product/dashscope"
            )

        api_base = (
            self._config.api_base
            or os.getenv("QWEN_API_BASE", _DEFAULT_API_BASE)
        )

        self._client = OpenAI(api_key=api_key, base_url=api_base)
        return self._client

    def __repr__(self) -> str:
        base = self._config.api_base or os.getenv("QWEN_API_BASE", _DEFAULT_API_BASE)
        return f"QwenBackend(model={self._config.model!r}, base_url={base!r})"
