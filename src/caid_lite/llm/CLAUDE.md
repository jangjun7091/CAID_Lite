# llm/ — LLM Abstraction Layer

## Purpose
Provider-agnostic interface between the CAD pipeline and any LLM API.
All provider-specific code is confined to `providers/`; nothing leaks outward.

## Files
- `base.py` — `LLMBackend` Protocol + `LLMConfig` dataclass
- `factory.py` — `LLMFactory.create(config)` dispatch; `LLMFactory.from_yaml(section)`
- `prompts.py` — `PromptBuilder`: assembles generation and repair prompt pairs
- `providers/qwen.py` — default provider (OpenAI-compatible DashScope endpoint)
- `providers/openai_provider.py` — stub (raises `NotImplementedError`)
- `providers/anthropic_provider.py` — stub (raises `NotImplementedError`)
- `providers/local.py` — any local OpenAI-compatible server (vLLM, LM Studio, Ollama)

## Interface contract
```python
class LLMBackend(Protocol):
    def generate(self, user_prompt: str, system_prompt: str) -> str: ...
```
- Returns raw text; may contain markdown fences — callers strip them.
- Providers handle auth, retries, and error normalisation internally.
- `PromptBuilder.build_generation_prompt(desc)` → `(system, user)` tuple.
- `PromptBuilder.build_repair_prompt(desc, code, error, iteration)` → `(system, user)` tuple.

## Architecture rules
- `CADPipeline` and `RepairLoop` receive `LLMBackend` only — never a concrete class.
- `LLMFactory` is the single place that maps provider strings to backends.
- Adding a provider = one new file in `providers/` + one `case` line in `factory.py`.
- `LLMConfig.with_env_overrides()` applies `LLM_PROVIDER` / `LLM_MODEL` env vars.
  Priority: env vars > config file > dataclass defaults.

## Dependency constraints
- `base.py` and `prompts.py`: stdlib only.
- `factory.py`: imports from `providers/` only at call time (lazy).
- `providers/qwen.py`, `providers/local.py`: `openai` package.
- `providers/anthropic_provider.py`: `anthropic` package (optional extra).
- No imports from `executor`, `validator`, `repair`, `session`, or `api`.
