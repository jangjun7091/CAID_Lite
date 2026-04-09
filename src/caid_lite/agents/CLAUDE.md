# agents/ — Multi-Agent CAD Pipeline

## Purpose
Decompose a natural-language prompt into a structured design plan, then generate
CadQuery code from that plan. Agents are stateless and receive `LLMBackend` by injection.

## Files
- `base.py` — shared dataclasses: `DesignPlan`, `CriticFeedback`
- `architect.py` — `ArchitectAgent`: NL prompt → `DesignPlan` (JSON via LLM)
- `designer.py` — `DesignerAgent`: `DesignPlan` → CadQuery source string
- `critic.py` — `CriticAgent`: code + `ExecutionResult` → `CriticFeedback`
- `pattern_selector.py` — `PatternSelectorAgent`: selects geometry pattern library entry

## Interface contracts
```python
# base.py
@dataclass
class DesignPlan:
    features: List[str]          # ordered geometric features
    geometry_type: str           # "plate" | "cylinder" | "bracket" | ...
    constraints: Dict[str, Any]  # {"width_mm": 50, "hole_dia_mm": 6, ...}
    notes: str                   # free-form guidance for designer

@dataclass
class CriticFeedback:
    passed: bool
    issues: List[str]
    suggestions: str

# agent pattern
class ArchitectAgent:
    def __init__(self, llm: LLMBackend) -> None: ...
    def run(self, prompt: str) -> DesignPlan: ...

class DesignerAgent:
    def run(self, plan: DesignPlan, prompt: str) -> str: ...  # returns code string

class CriticAgent:
    def run(self, code: str, result: ExecutionResult) -> CriticFeedback: ...
```

## Architecture rules
- All agents accept **`LLMBackend` Protocol** — never a concrete provider class.
- Agents are **stateless** — safe to reuse across pipeline runs.
- LLM output is JSON; use `re` regex fallback to strip markdown fences before `json.loads`.
- Agents do **not** emit SSE events and do **not** write files — they return plain data.
- `ArchitectAgent.run()` is called by `SessionManager._run_pipeline_with_plan()`.

## Call chain in SessionManager
```
SessionManager.generate(prompt)
  └─ ArchitectAgent.run(prompt) → DesignPlan
  └─ PatternSelectorAgent.run(plan) → pattern hints  (optional)
  └─ DesignerAgent.run(plan, prompt) → code string
  └─ Sandbox.execute(code, run_id) → ExecutionResult
  └─ CriticAgent.run(code, result) → CriticFeedback  (if repair enabled)
```

## Dependency constraints
- All agents: import `LLMBackend` from `llm/base.py`, dataclasses from `base.py`.
- `critic.py`: may import `ExecutionResult` from `executor/result.py`.
- No imports from `session`, `assembly`, `catalog`, or `api`.
