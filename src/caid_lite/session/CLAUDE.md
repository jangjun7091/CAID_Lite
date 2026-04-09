# session/ — Runtime State & SSE Fan-out

## Purpose
Single source of truth for in-memory session state (parts shelf, chat history).
Owns all async pipeline dispatch and SSE event distribution to connected GUI clients.

## Files
- `models.py` — `PartEntry`, `ChatMessage` dataclasses
- `manager.py` — `SessionManager`: SSE queues, pipeline dispatch, file import, catalog insert

## PartEntry lifecycle
```
generating → validating → repairing (0..N) → ready
                                            → failed
```
`PartEntry.exports` dict keys: `"step"`, `"stl"` — values are server-relative URL strings.

## SessionManager key methods
```python
class SessionManager:
    # SSE
    def subscribe(self) -> asyncio.Queue: ...        # one queue per SSE client
    def unsubscribe(self, q) -> None: ...
    def emit(self, event_type: str, payload: dict) -> None: ...   # puts to ALL queues
    async def event_stream(self, q) -> AsyncIterator[str]: ...    # yields SSE text

    # Parts shelf
    def get_parts(self) -> List[PartEntry]: ...
    def get_part(self, part_id: str) -> Optional[PartEntry]: ...
    def remove_part(self, part_id: str) -> bool: ...

    # Pipeline dispatch
    async def generate(self, prompt: str) -> str: ...        # returns part_id
    async def modify_constraints(self, part_id, message): ...

    # File import (runner_import.py subprocess)
    async def import_file(self, filename: str, content: bytes) -> str: ...  # returns part_id

    # Catalog
    async def insert_catalog_part(self, part_type, size, length=None) -> PartEntry: ...
```

## Pipeline dispatch call chain
```
generate(prompt)
  └─ _run_pipeline_with_plan(part_id, prompt)
       └─ ArchitectAgent.run() → DesignPlan
       └─ _run_pipeline(part_id, prompt)  [asyncio.to_thread]
            └─ CADPipeline.run() → PipelineResult
            └─ _finalise_part(part_id, result)
                 └─ emit("part.ready" | "part.failed", ...)
```

## SSE event types
| Event | When |
|-------|------|
| `part.status_changed` | any status transition |
| `part.ready` | pipeline success, STEP/STL exported |
| `part.failed` | pipeline or import error |
| `assembly.updated` | assembly CRUD (parts/constraints changed) |
| `assembly.solved` | assembly solve complete |
| `assembly.failed` | assembly solve error |

## AssemblyManager integration
`AssemblyManager` receives `emit_fn = manager.emit` at construction in `server.py`.
It calls `_emit(type, payload)` which delegates to the same queues as part events.
Do NOT create a separate SSE channel for assembly events.

## Architecture rules
- `SessionManager` is a **singleton** created in `server.py` lifespan, injected via `Depends`.
- All blocking work runs in `asyncio.to_thread()` — never block the event loop.
- `emit()` is synchronous; it uses `loop.call_soon_threadsafe()` when called from threads.
- Parts are stored in `self._parts: Dict[str, PartEntry]` — no persistence, in-memory only.

## Dependency constraints
- `models.py`: stdlib only.
- `manager.py`: imports `CADPipeline` from `pipeline.py`, agents from `agents/`, runners via subprocess.
- No imports from `assembly/` internals (assembly manager is a sibling, injected at the API layer).
