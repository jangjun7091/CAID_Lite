# assembly/ — Multi-Part Assembly Engine

## Purpose
Build and solve `cq.Assembly` constraint graphs from user-supplied parts.
Mirrors the `executor/` subprocess isolation pattern and the `session/` SSE fan-out pattern.

## Files
- `models.py` — `Constraint`, `AssemblyPart`, `AssemblySession` dataclasses
- `pipeline.py` — `AssemblyPipeline.solve()`: subprocess orchestrator → `AssemblyResult`
- `manager.py` — `AssemblyManager`: session CRUD, part management, SSE emit, solve dispatch
- `runner_assembly.py` — subprocess: `cq.Assembly` → STEP + STL (cadquery required)
- `constraint_parser.py` — `ConstraintParserAgent`: NL text → `List[Constraint]` via LLM

## Interface contracts

```python
# pipeline.py
class AssemblyPipeline:
    def solve(self, session: AssemblySession) -> AssemblyResult: ...
    @classmethod
    def from_config(cls, cfg: dict) -> "AssemblyPipeline": ...

@dataclass
class AssemblyResult:
    assembly_id: str; success: bool
    step_path: Optional[str]; stl_path: Optional[str]
    solve_time_s: float; elapsed_s: float
    timed_out: bool; error: Optional[str]

# manager.py — key methods
class AssemblyManager:
    def __init__(self, pipeline, session_manager, llm=None): ...
    def create_session(self, name="") -> AssemblySession: ...
    def add_part_from_shelf(self, asm_id, part_ref_id) -> AssemblyPart: ...
    def add_constraint(self, asm_id, **kwargs) -> Constraint: ...
    async def solve(self, asm_id: str) -> None: ...  # dispatches to asyncio.to_thread
```

## runner_assembly.py contract
```
python runner_assembly.py <out_dir> <asm_id> <parts_json> <constraints_json>
```
- Loads each part via `cq.importers.importStep(step_path)`
- Builds `cq.Assembly`, calls `.constrain(selector_str, obj, selector_str)` for each constraint
- Selector string format: `"{part_id}@faces@{selector}"` e.g. `"part_a@faces@>Z"`
- Calls `asm.solve()`, exports `STEP` + `STL` to `<out_dir>/<asm_id>/`
- JSON stdout: `{"success": bool, "step_path": str, "stl_path": str, "solve_time_s": float, "error": str|null}`

## Architecture rules
- `AssemblyPipeline` is **stateless** — mirrors `Sandbox` pattern exactly.
- `AssemblyManager._emit()` delegates to the injected `emit_fn` from `SessionManager`
  so assembly events flow through the same SSE channel as part events.
- `solve()` is `async`; dispatches blocking work via `asyncio.to_thread(_run_solve, session)`.
- `runner_assembly.py` must not be imported by the parent process — subprocess only.
- Face selector syntax: CadQuery strings e.g. `">Z"`, `"<X"`, `">Y"`.

## SSE events emitted
- `assembly.updated` — after any CRUD mutation
- `assembly.solved` — on successful solve (payload: full `AssemblySession` dict)
- `assembly.failed` — on solve error (payload includes `error` field)

## Dependency constraints
- `models.py`, `pipeline.py`, `manager.py`: stdlib + project internal only.
- `runner_assembly.py`: `cadquery` — subprocess only, never imported by parent.
- `constraint_parser.py`: imports `LLMBackend` from `llm/base.py`.
- No imports from `session` internals other than receiving `emit_fn` and `PartEntry` lookups.
