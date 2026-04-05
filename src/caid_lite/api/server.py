"""FastAPI application factory for CAID Lite.

Usage::

    from caid_lite.api.server import create_app
    app = create_app("config/default.yaml")

Or via ``scripts/run_server.py``::

    uvicorn caid_lite.api.server:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from ..pipeline import CADPipeline
from ..session.manager import SessionManager
from .routes import chat, events, parts, workspace

# Resolve GUI static directory relative to this file (works whether installed
# or run in-place from the project root).
_STATIC_DIR = Path(__file__).resolve().parent.parent.parent.parent / "gui" / "static"


class _NoCacheJsCss(BaseHTTPMiddleware):
    """Set Cache-Control: no-cache for .js and .css static files.

    Prevents browsers from serving stale GUI assets after a server update.
    index.html is already served via FileResponse (no StaticFiles caching),
    so only the script/stylesheet assets need this header.
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        path = request.url.path.split("?")[0]
        if path.endswith((".js", ".css")):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


def create_app(config_path: str | Path = "config/default.yaml") -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config_path: Path to the YAML config file.  Passed to
            ``CADPipeline.from_config()``.

    Returns:
        Configured ``FastAPI`` instance with all routes mounted.
    """
    manager: SessionManager | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal manager
        pipeline = CADPipeline.from_config(config_path)
        manager = SessionManager(pipeline=pipeline)
        app.state.manager = manager
        yield
        # Nothing to clean up — pipeline is stateless

    app = FastAPI(
        title="CAID Lite",
        description="NL → CadQuery → STEP/STL generation API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(_NoCacheJsCss)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat.router, prefix="/api")
    app.include_router(parts.router, prefix="/api")
    app.include_router(workspace.router, prefix="/api")
    app.include_router(events.router, prefix="/api")

    # Serve the GUI static files.  Mount last so API routes take priority.
    if _STATIC_DIR.is_dir():
        @app.get("/")
        async def serve_index() -> FileResponse:
            return FileResponse(_STATIC_DIR / "index.html")

        app.mount("/", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app


# Module-level app instance for ``uvicorn caid_lite.api.server:app``
app = create_app()
