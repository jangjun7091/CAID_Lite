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

    def rename_part(self, part_id: str, new_name: str) -> bool:
        """Rename a part.  Returns True if the part was found and renamed."""
        part = self._state.get_part(part_id)
        if part is None:
            return False
        stripped = new_name.strip()
        if stripped:
            part.name = stripped
        return True

    def get_chat_history(self) -> List[ChatMessage]:
        """Return the full chat history."""
        return list(self._state.chat_history)

    async def modify_constraints(
        self, part_id: str, constraints: Dict[str, Any]
    ) -> str:
        """Update a part's constraints and re-run from the Designer stage.

        Skips ArchitectAgent — reuses the stored ``DesignPlan`` with merged
        constraints.  Emits the same SSE events as a normal generation run.

        Args:
            part_id: ID of the part to refine.
            constraints: Key/value pairs to merge into ``design_plan.constraints``.
                         Only numeric (int/float) values are expected; the API
                         layer enforces this via Pydantic.

        Returns:
            The same ``part_id`` (part is updated in-place).

        Raises:
            ValueError: Part not found, still generating, or has no design_plan.
        """
        import copy

        part = self._state.get_part(part_id)
        if part is None:
            raise ValueError(f"Part '{part_id}' not found.")
        if part.status not in ("ready", "failed"):
            raise ValueError(
                f"Part '{part_id}' is still {part.status}. "
                "Wait for generation to complete before refining."
            )
        if part.design_plan is None:
            raise ValueError(
                f"Part '{part_id}' has no design plan. "
                "Refine requires multi-agent mode (agents.enabled: true in config)."
            )

        # Merge new constraints into a deep copy of the stored plan.
        # Type-preserving: if the original constraint was int and the incoming
        # value is a whole-number float (e.g. 16.0 from some serialisation path),
        # restore it to int so the Designer prompt shows "n_fins=16" not "n_fins=16.0".
        updated_plan = copy.deepcopy(part.design_plan)
        orig_constraints = part.design_plan.get("constraints", {})
        type_safe: Dict[str, Any] = {}
        for key, new_val in constraints.items():
            orig_val = orig_constraints.get(key)
            if (
                isinstance(orig_val, int)
                and isinstance(new_val, float)
                and new_val.is_integer()
            ):
                type_safe[key] = int(new_val)
            else:
                type_safe[key] = new_val
        updated_plan.setdefault("constraints", {}).update(type_safe)

        # Reset part state for re-generation
        part.status = "generating"
        part.error = None
        part.code = None
        part.validation = None
        part.exports = {}
        part.repair_iterations = 0
        part.design_plan = updated_plan   # persist merged plan immediately

        self.emit("part.status_changed", {"id": part_id, "status": "generating"})
        asyncio.create_task(
            self._run_pipeline_with_plan(part_id, part.prompt, updated_plan)
        )
        return part_id

    # ------------------------------------------------------------------
    # Standard catalog parts (no LLM)
    # ------------------------------------------------------------------

    async def insert_catalog_part(
        self,
        part_type: str,
        size: str,
        length: float | None = None,
    ) -> str:
        """Instantiate a standard catalog part without calling the LLM.

        Looks up the ISO dimension table, generates deterministic CadQuery
        code, and runs it directly in the sandbox.  Emits the same SSE
        events as a normal generation run so the GUI updates identically.

        Args:
            part_type: Catalog key, e.g. ``"iso4762"``.
            size:      Size label, e.g. ``"M6"``.
            length:    Required length in mm for bolts/screws; None for
                       nuts and washers.

        Returns:
            The UUID string of the newly created ``PartEntry``.

        Raises:
            ValueError: Unknown part type, unknown size, or missing length.
        """
        from ..catalog.builder import generate_code

        code, display_name = generate_code(part_type, size, length)

        part_id = str(uuid.uuid4())
        part = PartEntry(
            id=part_id,
            name=display_name,
            prompt=display_name,
            status="generating",
            created_at=datetime.now(timezone.utc),
        )
        self._state.add_part(part)
        self.emit("part.status_changed", {"id": part_id, "status": "generating"})

        asyncio.create_task(self._run_catalog(part, code))
        return part_id

    async def _run_catalog(self, part: PartEntry, code: str) -> None:
        """Background task: run catalog code directly in the sandbox (no LLM)."""
        try:
            result = await asyncio.to_thread(
                self._pipeline._sandbox.execute, code, part.id
            )
        except Exception as exc:
            _log.error(f"[{part.id[:8]}] Catalog sandbox exception: {exc}")
            part.error = str(exc)
            part.status = "failed"
            self.emit("part.failed", part.to_dict())
            return

        part.code = code
        if result.success:
            part.exports = {k: str(v) for k, v in result.exports.items()}
            part.status = "ready"
            self.emit("part.ready", part.to_dict())
            _log.info(f"[{part.id[:8]}] Catalog part ready — {part.name}")
        else:
            part.error = result.exception or "Execution failed"
            part.status = "failed"
            self.emit("part.failed", part.to_dict())
            _log.warning(f"[{part.id[:8]}] Catalog part failed — {part.error}")

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

    async def _run_pipeline_with_plan(
        self, part_id: str, prompt: str, design_plan: Dict[str, Any]
    ) -> None:
        """Background task: run_with_plan and update part status via SSE."""
        part = self._state.get_part(part_id)
        if part is None:
            return

        try:
            result: PipelineResult = await asyncio.to_thread(
                self._pipeline.run_with_plan, prompt, design_plan
            )
        except Exception as exc:
            _log.error(f"[{part_id[:8]}] Unhandled run_with_plan exception: {exc}")
            self._finalise_part(part, success=False, result=None, error=str(exc))
            return

        self._finalise_part(part, success=result.success, result=result)

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
            # DesignPlan 저장 (치수 수정 재생성 지원)
            if result.design_plan is not None:
                part.design_plan = result.design_plan

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
