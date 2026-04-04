"""GET /api/events — SSE stream for live status updates."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..deps import get_manager
from ...session.manager import SessionManager

router = APIRouter(tags=["events"])


@router.get("/events")
async def get_events(
    manager: SessionManager = Depends(get_manager),
) -> StreamingResponse:
    """Server-Sent Events stream.

    Each event is a JSON object with ``type`` and ``data`` fields::

        data: {"type": "part.status_changed", "data": {"id": "...", "status": "validating"}}

        data: {"type": "part.ready", "data": {<PartEntry dict>}}

        data: {"type": "part.failed", "data": {<PartEntry dict>}}

    A keep-alive comment (``:``) is sent every 15 seconds when idle.
    """
    q = manager.subscribe()

    async def stream():
        # Iterate event_stream without checking is_disconnected() — that call
        # awaits the ASGI receive channel which deadlocks against the streaming
        # client in test environments.  Disconnect is handled via CancelledError:
        # Starlette cancels this generator when the client closes the connection.
        try:
            async for chunk in manager.event_stream(q):
                yield chunk
        except asyncio.CancelledError:
            pass
        finally:
            manager.unsubscribe(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
