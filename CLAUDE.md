# CAID_Lite — Project Rules

## What this is
Standalone NL → CadQuery → STEP/STL research engine. Intentionally decoupled from the CAID
multi-agent project so it can be developed and benchmarked independently, then integrated as a
drop-in backend.

## Repository layout
```
src/caid_lite/
  pipeline.py       # top-level orchestrator (Phase 1–3)
  agents/           # multi-agent layer (ArchitectAgent, DesignerAgent, CriticAgent, …)
  llm/              # provider-agnostic LLM interface + backends
  executor/         # subprocess sandbox (Phase 2) + runner_import.py
  validator/        # geometry checks (Phase 3) — stub
  repair/           # LLM-guided repair loop (Phase 3) — stub
  exporter/         # STEP/STL export helpers — future
  session/          # in-memory session state + SSE fan-out (Phase 4)
  assembly/         # multi-part assembly: models, pipeline, manager, runner
  catalog/          # ISO standard parts: dimension data + CadQuery builders
  api/              # FastAPI app + routes (server.py, routes/, deps.py)
  logging/          # structured console + JSONL logging
tests/
  unit/             # no API key, no CadQuery required
  integration/      # real API / real CadQuery; @pytest.mark.integration
  fixtures/         # MockLLMBackend, MockSandbox, code fixtures
gui/
  static/           # index.html, app.js, style.css, assembly.html, app_assembly.js, assembly.css
config/
  default.yaml      # LLM provider, executor timeout, output dirs
```

## Architecture rules
- `CADPipeline` is **stateless** — no session, GUI, or per-request state.
- All modules depend on **protocols / dataclasses**, not concrete implementations.
  - `CADPipeline` accepts `LLMBackend` (Protocol) and `Sandbox` (duck-typed).
  - No provider-specific imports outside `llm/providers/`.
- Session state lives exclusively in `session/manager.py`.
- `AssemblyManager` shares the SSE channel via `emit_fn` injected from `SessionManager`.
- `repair/loop.py` and `validator/geometry.py` are not yet implemented; stub files exist.

## Generated code contract
Every CadQuery script the LLM produces must:
1. `import cadquery as cq`
2. Define `build_model()` — no arguments, returns `cq.Workplane`
3. Not call `cq.exporters`, open files, or print — the executor handles all I/O

## Dependency constraints
- Core runtime deps: `openai`, `pyyaml`, `rich`, `python-dotenv` — no `cadquery` required at import time.
- `cadquery` is an optional extra (`pip install -e ".[cadquery]"`); import it only inside
  executor subprocess or `@requires_cq`-guarded tests.
- `anthropic` is an optional extra; import only inside `llm/providers/anthropic_provider.py`.
- `python-multipart` required for file upload routes.

## Testing rules
- `pytest tests/unit/` must pass with **no API key and no CadQuery installed**.
- Inject `MockLLMBackend` and `MockSandbox` — never monkeypatch production classes for unit tests.
- Integration tests are guarded: `@pytest.mark.skipif(not _CQ_AVAILABLE, ...)` or
  `@pytest.mark.integration`.
- Config: `pyproject.toml` `[tool.pytest.ini_options]` section controls markers and paths.
