# api/ — FastAPI Application Layer

## Purpose
HTTP + SSE interface between the GUI and the backend engines.
Thin layer: validate input, call managers, return JSON/SSE/FileResponse.

## Files
```
server.py        — create_app() factory; router registration; static file serving
deps.py          — FastAPI dependency: get_manager() → SessionManager
routes/
  workspace.py   — GET /api/workspace, POST /api/workspace/reset
  parts.py       — /api/parts CRUD + POST /api/parts/import (multipart upload)
  events.py      — GET /api/events  (SSE stream)
  catalog.py     — GET /api/catalog, POST /api/catalog/insert
  assembly.py    — /api/assembly/... (15 endpoints, full CRUD + solve)
  chat.py        — POST /api/chat  (NL → pipeline generate)
```

## server.py — app factory pattern
```python
def create_app(config_path=...) -> FastAPI:
    # 1. Load YAML config
    # 2. Build CADPipeline, SessionManager, AssemblyPipeline, AssemblyManager
    # 3. app.state.manager = manager
    # 4. app.state.asm_manager = asm_manager
    # 5. include_router() for each route module
    # 6. Mount StaticFiles LAST (API routes take priority)
    # 7. Register HTML routes WITH Cache-Control: no-cache headers
```

## Critical rules
- **Static file mounts are LAST** — `app.mount("/", StaticFiles(...))` must come after all
  `include_router()` calls or API routes will be shadowed.
- **HTML responses** (`GET /` and `GET /assembly`) must set:
  `Cache-Control: no-cache, no-store, must-revalidate` + `Pragma: no-cache`
  so browsers always fetch the latest HTML (and thus the correct `?v=N` asset URLs).
- **`python-multipart`** must be installed for `POST /api/parts/import` and
  `POST /api/assembly/{id}/parts/upload` to work.
- Routes access managers via `request.app.state.*` or `Depends(get_manager)`.

## Assembly routes summary (assembly.py)
```
GET    /api/assembly                          list sessions
POST   /api/assembly                          create session
GET    /api/assembly/{id}                     get session
DELETE /api/assembly/{id}                     delete session
POST   /api/assembly/{id}/parts/from-shelf    add part (PartEntry ref)
POST   /api/assembly/{id}/parts/from-catalog  add catalog part
POST   /api/assembly/{id}/parts/upload        add uploaded STEP
DELETE /api/assembly/{id}/parts/{pid}         remove part
POST   /api/assembly/{id}/constraints         add constraint
DELETE /api/assembly/{id}/constraints/{cid}   remove constraint
POST   /api/assembly/{id}/nl-constrain        NL → constraints (LLM)
POST   /api/assembly/{id}/solve               trigger async solve
GET    /api/assembly/{id}/step                download assembled STEP
GET    /api/assembly/{id}/stl                 download assembled STL
```

## Dependency constraints
- Routes import from `session/`, `assembly/` — never from `llm/` or `executor/` directly.
- `server.py` is the only file that instantiates `CADPipeline`, `AssemblyPipeline`,
  `SessionManager`, and `AssemblyManager`.
