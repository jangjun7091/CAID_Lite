# pipeline/ — Top-Level Orchestrator

## Purpose
`pipeline.py` wires together the LLM, executor, validator, and repair loop into a single
`CADPipeline.run(prompt)` call. It owns the run lifecycle but holds no state between calls.

## Note on location
`pipeline.py` lives at `src/caid_lite/pipeline.py` (module root), not in a subdirectory.
This CLAUDE.md documents its rules.

## Interface contract
```python
class CADPipeline:
    def __init__(self, llm: LLMBackend, sandbox: Optional[Sandbox] = None,
                 prompts_dir: Optional[Path] = None) -> None: ...
    def run(self, prompt: str) -> PipelineResult: ...
    @staticmethod
    def _extract_code(response: str) -> str: ...
    @classmethod
    def from_config(cls, config_path=...) -> "CADPipeline": ...

@dataclass
class PipelineResult:
    run_id: str; success: bool; prompt: str; generated_code: str; elapsed_s: float
    execution: Optional[ExecutionResult] = None
    exports: Dict[str, Path] = field(default_factory=dict)
    repair: Optional[Dict[str, Any]] = None   # populated in Phase 3
    error: Optional[str] = None
```

## Architecture rules
- **Stateless**: `CADPipeline` holds no session, run history, or GUI references.
- Depends on `LLMBackend` (Protocol) and `Sandbox` (duck-typed) — never on concrete classes.
- `run()` generates a UUID `run_id` at entry; all downstream components receive it.
- `_extract_code()` strips markdown fences; first code block wins; plain code returned as-is.
- Phase 3 repair loop insertion point is marked with a comment in `run()` — add logic there,
  do not restructure the method signature.
- `from_config()` is the production factory; direct constructor is for testing.

## Dependency constraints
- Imports `LLMBackend` from `llm/base.py`, `Sandbox`/`ExecutionResult` from `executor/`.
- May import `validator` and `repair` in Phase 3 — not before.
- No imports from `session`, `api`, or `gui`.
- `PipelineResult.to_dict()` must remain JSON-safe (Path → str, no unserializable objects).
