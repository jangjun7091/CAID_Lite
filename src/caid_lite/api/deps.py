"""FastAPI dependency helpers."""

from __future__ import annotations

from fastapi import Request

from ..session.manager import SessionManager


def get_manager(request: Request) -> SessionManager:
    """Inject the SessionManager singleton from app state."""
    return request.app.state.manager
