"""AssemblyManager: manages assembly sessions and dispatches solve jobs.

Architecture notes:
  - Structurally parallel to SessionManager (session/manager.py).
  - Holds an in-memory dict of AssemblySession objects.
  - Shares the SSE event channel via an injected emit_fn (from SessionManager).
  - Dispatches AssemblyPipeline.solve() via asyncio.to_thread (non-blocking).
  - AssemblyManager is a singleton instantiated alongside SessionManager in
    server.py's lifespan and injected into routes via Depends.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..llm.base import LLMBackend
from ..logging.logger import get_logger
from ..session.manager import SessionManager
from .models import AssemblyPart, AssemblySession, Constraint
from .pipeline import AssemblyPipeline

_log = get_logger(__name__)

# Part colors cycle for visual distinction
_PART_COLORS = [
    "#7ec8e3",  # light blue
    "#7ecd7e",  # light green
    "#f4d66a",  # light yellow
    "#f4a67a",  # light orange
    "#c87ef4",  # light purple
    "#f47ec8",  # light pink
    "#7ef4e3",  # teal
    "#f4f47e",  # lime
]


class AssemblyManager:
    """Manages all assembly sessions for one server instance.

    Args:
        pipeline:   A fully-wired AssemblyPipeline instance.
        session_manager: The main SessionManager (used for STEP path lookup
                         and shared SSE emit channel).
    """

    def __init__(
        self,
        pipeline: AssemblyPipeline,
        session_manager: SessionManager,
        llm: Optional[LLMBackend] = None,
    ) -> None:
        self._pipeline = pipeline
        self._session_mgr = session_manager
        self._llm = llm
        self._sessions: Dict[str, AssemblySession] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Delegate SSE emission to the shared SessionManager channel."""
        self._session_mgr.emit(event_type, payload)

    def _next_color(self, session: AssemblySession) -> str:
        return _PART_COLORS[len(session.parts) % len(_PART_COLORS)]

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def list_sessions(self) -> List[AssemblySession]:
        return list(self._sessions.values())

    def get_session(self, asm_id: str) -> Optional[AssemblySession]:
        return self._sessions.get(asm_id)

    def create_session(self, name: str = "") -> AssemblySession:
        asm_id = str(uuid.uuid4())
        name   = name.strip() or f"Assembly {len(self._sessions) + 1}"
        session = AssemblySession(id=asm_id, name=name)
        self._sessions[asm_id] = session
        _log.info(f"[{asm_id[:8]}] Assembly session created — '{name}'")
        return session

    def delete_session(self, asm_id: str) -> bool:
        if asm_id not in self._sessions:
            return False
        del self._sessions[asm_id]
        _log.info(f"[{asm_id[:8]}] Assembly session deleted")
        return True

    # ------------------------------------------------------------------
    # Part management
    # ------------------------------------------------------------------

    def add_part_from_shelf(self, asm_id: str, part_ref_id: str) -> AssemblyPart:
        """Add a part from the single-part shelf to the assembly.

        Resolves the STEP/STL paths from the existing PartEntry.

        Raises:
            ValueError: Session or part not found, or part not ready.
        """
        session = self._sessions.get(asm_id)
        if session is None:
            raise ValueError(f"Assembly session '{asm_id}' not found.")

        part_entry = self._session_mgr.get_part(part_ref_id)
        if part_entry is None:
            raise ValueError(f"Part '{part_ref_id}' not found on shelf.")
        if part_entry.status != "ready":
            raise ValueError(
                f"Part '{part_ref_id}' is not ready (status={part_entry.status})."
            )
        if not part_entry.exports.get("step"):
            raise ValueError(f"Part '{part_ref_id}' has no STEP export.")

        asm_part = AssemblyPart(
            id           = str(uuid.uuid4()),
            name         = part_entry.name,
            source_type  = "generated",
            part_ref_id  = part_ref_id,
            step_path    = part_entry.exports["step"],
            stl_path     = part_entry.exports.get("stl", ""),
            color        = self._next_color(session),
        )
        session.parts.append(asm_part)
        self._emit("assembly.updated", session.to_dict())
        _log.info(
            f"[{asm_id[:8]}] Part added from shelf: '{asm_part.name}' "
            f"(ref={part_ref_id[:8]})"
        )
        return asm_part

    def add_part_from_catalog(
        self,
        asm_id: str,
        step_path: str,
        stl_path: str,
        name: str,
        part_ref_id: str,
    ) -> AssemblyPart:
        """Add a catalog-generated part to the assembly.

        The caller (route) is responsible for generating the STEP first
        via the catalog system and providing the paths.

        Raises:
            ValueError: Session not found.
        """
        session = self._sessions.get(asm_id)
        if session is None:
            raise ValueError(f"Assembly session '{asm_id}' not found.")

        asm_part = AssemblyPart(
            id           = str(uuid.uuid4()),
            name         = name,
            source_type  = "catalog",
            part_ref_id  = part_ref_id,
            step_path    = step_path,
            stl_path     = stl_path,
            color        = self._next_color(session),
        )
        session.parts.append(asm_part)
        self._emit("assembly.updated", session.to_dict())
        _log.info(f"[{asm_id[:8]}] Catalog part added: '{name}'")
        return asm_part

    def add_part_from_upload(
        self,
        asm_id: str,
        step_path: str,
        name: str,
    ) -> AssemblyPart:
        """Add an uploaded STEP file to the assembly.

        Raises:
            ValueError: Session not found or file does not exist.
        """
        session = self._sessions.get(asm_id)
        if session is None:
            raise ValueError(f"Assembly session '{asm_id}' not found.")
        if not Path(step_path).is_file():
            raise ValueError(f"STEP file not found: {step_path}")

        asm_part = AssemblyPart(
            id          = str(uuid.uuid4()),
            name        = name,
            source_type = "uploaded",
            part_ref_id = Path(step_path).name,
            step_path   = step_path,
            color       = self._next_color(session),
        )
        session.parts.append(asm_part)
        self._emit("assembly.updated", session.to_dict())
        _log.info(f"[{asm_id[:8]}] Uploaded part added: '{name}'")
        return asm_part

    def remove_part(self, asm_id: str, part_id: str) -> bool:
        """Remove a part and any constraints that reference it."""
        session = self._sessions.get(asm_id)
        if session is None:
            return False
        initial_count = len(session.parts)
        session.parts = [p for p in session.parts if p.id != part_id]
        # Remove dangling constraints
        session.constraints = [
            c for c in session.constraints
            if c.part_a != part_id and c.part_b != part_id
        ]
        changed = len(session.parts) < initial_count
        if changed:
            self._emit("assembly.updated", session.to_dict())
        return changed

    def update_part_color(self, asm_id: str, part_id: str, color: str) -> bool:
        """Update a part's display color."""
        session = self._sessions.get(asm_id)
        if session is None:
            return False
        part = session.get_part(part_id)
        if part is None:
            return False
        part.color = color
        self._emit("assembly.updated", session.to_dict())
        return True

    # ------------------------------------------------------------------
    # Constraint management
    # ------------------------------------------------------------------

    def add_constraint(
        self,
        asm_id: str,
        constraint_type: str,
        part_a: str,
        selector_a: str,
        part_b: Optional[str] = None,
        selector_b: str = "",
        param: float = 0.0,
    ) -> Constraint:
        """Add a constraint to the assembly session.

        Raises:
            ValueError: Session or referenced parts not found.
        """
        session = self._sessions.get(asm_id)
        if session is None:
            raise ValueError(f"Assembly session '{asm_id}' not found.")
        if session.get_part(part_a) is None:
            raise ValueError(f"Part '{part_a}' not in assembly.")
        if part_b is not None and session.get_part(part_b) is None:
            raise ValueError(f"Part '{part_b}' not in assembly.")

        con = Constraint(
            id         = str(uuid.uuid4()),
            type       = constraint_type,
            part_a     = part_a,
            selector_a = selector_a,
            part_b     = part_b,
            selector_b = selector_b,
            param      = param,
        )
        session.constraints.append(con)
        self._emit("assembly.updated", session.to_dict())
        _log.info(
            f"[{asm_id[:8]}] Constraint added: {constraint_type} "
            f"({part_a}@{selector_a} ↔ {part_b}@{selector_b})"
        )
        return con

    def remove_constraint(self, asm_id: str, constraint_id: str) -> bool:
        """Remove a constraint by id."""
        session = self._sessions.get(asm_id)
        if session is None:
            return False
        initial = len(session.constraints)
        session.constraints = [c for c in session.constraints if c.id != constraint_id]
        changed = len(session.constraints) < initial
        if changed:
            self._emit("assembly.updated", session.to_dict())
        return changed

    # ------------------------------------------------------------------
    # NL constraint parsing (Phase 2)
    # ------------------------------------------------------------------

    def parse_nl_constraints(
        self,
        asm_id: str,
        message: str,
    ) -> List[Constraint]:
        """Parse a NL instruction and add the resulting constraints.

        Raises:
            ValueError: Session not found, no LLM configured, or no parts.
        """
        from .constraint_parser import ConstraintParserAgent

        session = self._sessions.get(asm_id)
        if session is None:
            raise ValueError(f"Assembly session '{asm_id}' not found.")
        if self._llm is None:
            raise ValueError("No LLM backend configured for NL constraint parsing.")
        if not session.parts:
            raise ValueError("Assembly has no parts. Add parts before using NL constraints.")

        parts_info = [{"id": p.id, "name": p.name} for p in session.parts]
        agent = ConstraintParserAgent(self._llm)
        raw_constraints = agent.parse(message, parts_info)

        added: List[Constraint] = []
        for raw in raw_constraints:
            try:
                con = self.add_constraint(
                    asm_id          = asm_id,
                    constraint_type = raw["type"],
                    part_a          = raw["part_a"],
                    selector_a      = raw.get("selector_a", ""),
                    part_b          = raw.get("part_b"),
                    selector_b      = raw.get("selector_b", ""),
                    param           = float(raw.get("param", 0.0)),
                )
                added.append(con)
            except (KeyError, ValueError) as exc:
                _log.warning(f"[{asm_id[:8]}] Skipping invalid NL constraint: {exc}")

        return added

    # ------------------------------------------------------------------
    # Solve dispatch
    # ------------------------------------------------------------------

    async def solve(self, asm_id: str) -> None:
        """Start an async assembly solve and update session state via SSE.

        Raises:
            ValueError: Session not found or no parts to assemble.
        """
        session = self._sessions.get(asm_id)
        if session is None:
            raise ValueError(f"Assembly session '{asm_id}' not found.")
        if not session.parts:
            raise ValueError("Assembly has no parts. Add at least one part before solving.")

        session.status = "solving"
        session.error  = None
        session.exports = {}
        self._emit("assembly.status_changed", {"id": asm_id, "status": "solving"})

        asyncio.create_task(self._run_solve(session))

    async def _run_solve(self, session: AssemblySession) -> None:
        """Background task: run AssemblyPipeline.solve() and emit result."""
        asm_id = session.id
        try:
            result = await asyncio.to_thread(self._pipeline.solve, session)
        except Exception as exc:
            _log.error(f"[{asm_id[:8]}] Unhandled solve exception: {exc}")
            session.status = "failed"
            session.error  = str(exc)
            self._emit("assembly.failed", session.to_dict())
            return

        if result.success:
            session.status       = "solved"
            session.solve_time_s = result.solve_time_s
            session.exports      = {}
            if result.step_path:
                session.exports["step"] = result.step_path
            if result.stl_path:
                session.exports["stl"] = result.stl_path
            self._emit("assembly.solved", session.to_dict())
            _log.info(
                f"[{asm_id[:8]}] Assembly solved in "
                f"{result.solve_time_s:.2f}s (total {result.elapsed_s:.2f}s)"
            )
        else:
            session.status = "failed"
            session.error  = result.error or "Solve failed."
            self._emit("assembly.failed", session.to_dict())
            _log.warning(f"[{asm_id[:8]}] Assembly solve failed: {session.error}")
