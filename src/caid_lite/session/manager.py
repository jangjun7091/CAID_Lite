"""SessionManager: owns session state and dispatches pipeline runs.

The manager is the single point of truth for:
  - In-memory ``SessionState`` (parts shelf, chat history)
  - SSE event fan-out to connected GUI clients
  - Async pipeline dispatch via ``asyncio.to_thread``

Architecture notes:
  - ``SessionManager`` is a singleton created by the FastAPI app lifespan and
    injected into routes via ``Depends``.
  - The pipeline run is broken into observable stages so SSE events can be
    emitted at each transition.  ``CADPipeline`` itself is not modified.
  - Each SSE subscriber gets its own ``asyncio.Queue``; events are put on all
    queues when ``emit()`` is called.
  - ``asyncio.to_thread`` ensures the synchronous pipeline never blocks the
    event loop.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from ..executor.sandbox import Sandbox
from ..llm.base import LLMBackend
from ..llm.prompts import PromptBuilder
from ..logging.logger import get_logger
from ..pipeline import CADPipeline, PipelineResult
from ..repair.loop import RepairLoop
from ..session.models import ChatMessage, PartEntry, SessionState
from ..validator.geometry import GeometryValidator

_log = get_logger(__name__)


class SessionManager:
    """Manages one session: parts shelf, chat history, and SSE events.

    Args:
        pipeline: A fully-wired ``CADPipeline`` instance.  The manager calls
            ``pipeline.run()`` in a thread pool so the event loop is not blocked.
    """

    def __init__(self, pipeline: CADPipeline) -> None:
        self._pipeline = pipeline
        self._state = SessionState()
        self._subscribers: List[asyncio.Queue] = []

    # ------------------------------------------------------------------
    # SSE subscriber management
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        """Register a new SSE subscriber and return its queue.

        An initial ``connected`` event is placed on the queue immediately so
        the client receives a chunk without waiting for the keep-alive timeout.
        """
        q: asyncio.Queue = asyncio.Queue()
        q.put_nowait({"type": "connected", "data": {}})
        self._subscribers.append(q)
        _log.debug(f"SSE subscriber added (total={len(self._subscribers)})")
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a subscriber queue (called when client disconnects)."""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass
        _log.debug(f"SSE subscriber removed (total={len(self._subscribers)})")

    def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Put an event on every subscriber queue (non-blocking, sync-safe).

        Args:
            event_type: Short string identifying the event kind, e.g.
                ``"part.status_changed"``, ``"part.ready"``, ``"chat.message"``.
            payload: JSON-serialisable dict of event data.
        """
        event = {"type": event_type, "data": payload}
        for q in self._subscribers:
            q.put_nowait(event)

    async def event_stream(self, q: asyncio.Queue) -> AsyncIterator[str]:
        """Yield SSE-formatted strings from a subscriber queue.

        Yields the sentinel ``None`` when the client disconnects; callers
        should break their loop when they receive it.

        Args:
            q: Queue returned by ``subscribe()``.

        Yields:
            SSE-formatted strings: ``"data: {json}\\n\\n"`` or ``":\\n\\n"``
            (keep-alive comment).
        """
        import json

        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=0.5)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Short poll interval so disconnect is detected quickly.
                    # Every 30 polls (~15 s) emit a keep-alive comment.
                    yield ":\n\n"
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # State accessors (read-only snapshots for routes)
    # ------------------------------------------------------------------

    def get_parts(self) -> List[PartEntry]:
        """Return the current parts list."""
        return list(self._state.parts)

    def get_part(self, part_id: str) -> Optional[PartEntry]:
        """Return a single PartEntry by id, or None."""
        return self._state.get_part(part_id)

    def remove_part(self, part_id: str) -> bool:
        """Remove a part from the shelf.  Returns True if it was found."""
        part = self._state.get_part(part_id)
        if part is None:
            return False
        self._state.parts = [p for p in self._state.parts if p.id != part_id]
        return True

    def get_chat_history(self) -> List[ChatMessage]:
        """Return the full chat history."""
        return list(self._state.chat_history)

    # ------------------------------------------------------------------
    # Generation dispatch
    # ------------------------------------------------------------------

    async def generate(self, prompt: str) -> str:
        """Start an async pipeline run and return the new part's id.

        Creates a ``PartEntry`` immediately (status=``"generating"``), emits
        an SSE event, then runs the pipeline in a background thread.  Status
        transitions are emitted as each stage completes.

        Args:
            prompt: Natural language description from the user.

        Returns:
            The UUID string of the newly created ``PartEntry``.
        """
        part_id = str(uuid.uuid4())
        part = PartEntry(
            id=part_id,
            name=_name_from_prompt(prompt),
            prompt=prompt,
            status="generating",
            created_at=datetime.now(timezone.utc),
        )
        self._state.add_part(part)
        self.emit("part.status_changed", {"id": part_id, "status": "generating"})

        # Store user message in chat history
        user_msg = ChatMessage(role="user", content=prompt, part_id=part_id)
        self._state.add_message(user_msg)

        # Launch pipeline in a background thread — never blocks the event loop
        asyncio.create_task(self._run_pipeline(part_id, prompt))
        return part_id

    async def _run_pipeline(self, part_id: str, prompt: str) -> None:
        """Background task: run the pipeline and update part status via SSE."""
        part = self._state.get_part(part_id)
        if part is None:
            return

        try:
            result: PipelineResult = await asyncio.to_thread(
                self._pipeline.run, prompt
            )
        except Exception as exc:
            _log.error(f"[{part_id[:8]}] Unhandled pipeline exception: {exc}")
            self._finalise_part(part, success=False, result=None, error=str(exc))
            return

        # Determine terminal status based on pipeline result
        self._finalise_part(part, success=result.success, result=result)

    def _finalise_part(
        self,
        part: PartEntry,
        success: bool,
        result: Optional[PipelineResult],
        error: Optional[str] = None,
    ) -> None:
        """Update part fields and emit the terminal SSE event."""
        if result is not None:
            part.code = result.generated_code
            part.exports = {k: str(v) for k, v in result.exports.items()}
            part.error = result.error
            part.validation = result.validation.to_dict() if result.validation else None
            part.repair_iterations = (
                result.repair["iterations"] if result.repair else 0
            )

            # Emit intermediate status events based on what happened
            if result.validation is not None:
                self.emit(
                    "part.status_changed",
                    {"id": part.id, "status": "validating"},
                )
            if result.repair is not None and result.repair.get("iterations", 0) > 0:
                self.emit(
                    "part.status_changed",
                    {"id": part.id, "status": "repairing",
                     "repair_iterations": result.repair["iterations"]},
                )
        else:
            part.error = error

        part.status = "ready" if success else "failed"

        event_type = "part.ready" if success else "part.failed"
        self.emit(event_type, part.to_dict())

        # Store assistant message in chat history
        if success:
            content = f"Generated successfully in {result.elapsed_s:.1f}s." if result else "Generated."
        else:
            content = f"Generation failed: {part.error}"
        assistant_msg = ChatMessage(
            role="assistant",
            content=content,
            code_block=part.code,
            part_id=part.id,
        )
        self._state.add_message(assistant_msg)

        _log.info(f"[{part.id[:8]}] Part finalised - status={part.status}")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _name_from_prompt(prompt: str) -> str:
    """Derive a short display name from a prompt string."""
    words = prompt.split()[:5]
    name = " ".join(words)
    if len(prompt.split()) > 5:
        name += "…"
    return name[:60]
