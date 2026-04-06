"""Session state model shared between the API layer and the GUI.

These dataclasses are the single source of truth for what a "part" and a
"conversation message" look like at runtime.  They are populated by
``SessionManager`` (Phase 4) and serialised to JSON by the FastAPI routes.

Defined here in Phase 0 so that all downstream modules can import them
without circular dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional


@dataclass
class PartEntry:
    """A single CAD part tracked in the parts shelf.

    Lifecycle::

        generating → validating → repairing (0..N) → ready
                                                    → failed
    """

    id: str
    name: str
    prompt: str
    status: Literal["generating", "validating", "repairing", "ready", "failed"]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Populated progressively as the pipeline advances
    code: Optional[str] = None
    validation: Optional[Dict[str, Any]] = None   # ValidationResult dict (Phase 2)
    exports: Dict[str, str] = field(default_factory=dict)  # {"step": path, "stl": path}
    thumbnail_url: Optional[str] = None
    repair_iterations: int = 0
    error: Optional[str] = None
    design_plan: Optional[Dict[str, Any]] = None   # DesignPlan.to_dict() — multi-agent 시에만

    def is_terminal(self) -> bool:
        """Return True if this part has reached a final (non-transitional) state."""
        return self.status in ("ready", "failed")

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "code": self.code,
            "validation": self.validation,
            "exports": self.exports,
            "thumbnail_url": self.thumbnail_url,
            "repair_iterations": self.repair_iterations,
            "error": self.error,
            "design_plan": self.design_plan,
        }


@dataclass
class ChatMessage:
    """A single turn in the AI chat panel conversation."""

    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Set when the message triggered or describes a generation result
    code_block: Optional[str] = None   # extracted CadQuery snippet, if any
    part_id: Optional[str] = None      # linked PartEntry.id, if applicable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "code_block": self.code_block,
            "part_id": self.part_id,
        }


@dataclass
class SessionState:
    """Complete in-memory state for a single CAID Lite session.

    Owned and mutated exclusively by ``SessionManager`` (Phase 4).
    Read-only snapshots are served to the GUI via the API routes.
    """

    parts: List[PartEntry] = field(default_factory=list)
    active_part_id: Optional[str] = None
    chat_history: List[ChatMessage] = field(default_factory=list)

    def get_part(self, part_id: str) -> Optional[PartEntry]:
        """Return the PartEntry with the given id, or None."""
        return next((p for p in self.parts if p.id == part_id), None)

    def add_part(self, part: PartEntry) -> None:
        self.parts.append(part)

    def add_message(self, message: ChatMessage) -> None:
        self.chat_history.append(message)
