"""Provider-agnostic LLM interface.

CADPipeline, RepairLoop, and all other modules depend ONLY on LLMBackend.
No provider-specific code leaks beyond the llm/providers/ package.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMBackend(Protocol):
    """Minimal interface every LLM provider must satisfy.

    The single ``generate`` method is the only contract between the CAD
    pipeline and any underlying model API.  Providers handle their own
    authentication, retries, and error normalisation internally.
    """

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        """Return a raw text response for the given prompts.

        Args:
            user_prompt: The user-facing message (NL description or repair
                request assembled by PromptBuilder).
            system_prompt: System-level instructions loaded from
                config/prompts/ or the embedded defaults.

        Returns:
            Raw response string from the model.  May contain markdown fences
            (```python ... ```) — callers strip them via
            ``CADPipeline._extract_code``.
        """
        ...


@dataclass
class LLMConfig:
    """Resolved configuration for a single LLM provider instance.

    Populated from ``config/default.yaml`` (``llm:`` section) plus env-var
    overrides applied by ``LLMFactory``.  Priority at runtime:

        env vars  >  config file  >  hardcoded dataclass defaults
    """

    provider: str
    model: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 4096

    @classmethod
    def from_dict(cls, data: dict) -> "LLMConfig":
        """Build from the ``llm:`` section of ``default.yaml``.

        The YAML uses ``temperature`` (single value); generation vs. repair
        temperatures will be differentiated via separate configs when the
        RepairLoop is implemented in Phase 3.
        """
        return cls(
            provider=data["provider"],
            model=data["model"],
            temperature=data.get("temperature", 0.2),
            max_tokens=data.get("max_tokens", 4096),
        )

    def with_env_overrides(self) -> "LLMConfig":
        """Return a copy with LLM_PROVIDER / LLM_MODEL env vars applied."""
        return LLMConfig(
            provider=os.getenv("LLM_PROVIDER", self.provider).lower(),
            model=os.getenv("LLM_MODEL", self.model),
            api_key=self.api_key,
            api_base=self.api_base,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
