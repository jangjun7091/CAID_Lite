# repair/ — LLM-Guided Repair Loop

## Purpose
Iteratively fix failed CadQuery code by feeding the error back to the LLM and re-executing,
up to `max_iterations`. Not yet implemented — stub only.

## Planned interface
```python
@dataclass
class RepairAttempt:
    iteration: int      # 0-indexed
    code: str
    error: str
    exec_result: ExecutionResult

@dataclass
class RepairResult:
    repaired: bool
    iterations: int
    final_code: str
    history: List[RepairAttempt]

class RepairLoop:
    def __init__(self, llm: LLMBackend, sandbox: Sandbox,
                 max_iterations: int = 3) -> None: ...
    def run(self, original_prompt: str, failed_code: str,
            error: str) -> RepairResult: ...
```

## Architecture rules
- `RepairLoop` accepts `LLMBackend` and `Sandbox` by injection — same instances used by
  `CADPipeline`; never construct new ones internally.
- Each iteration: build repair prompt → `llm.generate()` → `_extract_code()` →
  `sandbox.execute()`. If `exec_result.success`, optionally validate, then return.
- `error` passed to `run()` is either a Python traceback or a
  `ValidationResult.errors` list formatted as a string.
- `RepairResult.history` preserves every attempt for dataset logging — do not truncate.
- `RepairLoop` is stateless between `run()` calls; safe to reuse across pipeline runs.
- Insertion point in `CADPipeline.run()` is marked with a comment — add the call there.

## Dependency constraints
- Imports `LLMBackend` from `llm/base.py`, `PromptBuilder` from `llm/prompts.py`.
- Imports `Sandbox`/`ExecutionResult` from `executor/`.
- May import `ValidationResult` from `validator/` for geometry-aware repair prompts.
- No imports from `session`, `api`, or `gui`.
