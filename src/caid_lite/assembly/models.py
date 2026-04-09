"""Assembly session state models.

These dataclasses define the runtime state for multi-part assemblies.
They are structurally parallel to session/models.py (PartEntry etc.)
and follow the same to_dict() → JSON-safe serialisation discipline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional


@dataclass
class Constraint:
    """A single positional/orientational constraint between two parts.

    For a "Fixed" constraint (fixes a part to the world frame), set
    ``part_b`` to ``None`` and leave ``selector_b`` empty.

    The ``selector_a`` / ``selector_b`` fields use CadQuery face-selector
    syntax, e.g. ``">Z"``, ``"<X"``.  The runner builds the full query
    string ``"{part_id}@faces@{selector}"`` automatically.
    """

    id: str
    type: Literal["Plane", "Axis", "Point", "FixedPlane", "FixedAxis", "Fixed"]
    part_a: str                  # AssemblyPart.id
    selector_a: str              # e.g. ">Z"
    part_b: Optional[str]        # None → world-fixed constraint
    selector_b: str = ""         # ignored when part_b is None
    param: float = 0.0           # offset/angle param for Plane, Axis constraints

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "part_a": self.part_a,
            "selector_a": self.selector_a,
            "part_b": self.part_b,
            "selector_b": self.selector_b,
            "param": self.param,
        }


@dataclass
class AssemblyPart:
    """A single part instance inside an AssemblySession.

    The part may originate from:
    - ``"generated"`` — a PartEntry from the single-part shelf.
    - ``"catalog"``   — directly generated from the ISO catalog.
    - ``"uploaded"``  — a STEP file supplied by the user.

    ``step_path`` is resolved at insertion time and must point to a
    valid STEP file.  ``stl_path`` is resolved when available (for
    Three.js preview).
    """

    id: str                # UUID within this assembly
    name: str
    source_type: Literal["generated", "catalog", "uploaded"]
    part_ref_id: str       # PartEntry.id / catalog key / upload filename
    step_path: str         # absolute path to STEP file
    stl_path: str = ""     # absolute path to STL file (optional, for preview)
    color: str = "#7ec8e3" # hex color for 3D viewer

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source_type": self.source_type,
            "part_ref_id": self.part_ref_id,
            "step_path": self.step_path,
            "stl_path": self.stl_path,
            "color": self.color,
        }


@dataclass
class AssemblySession:
    """Complete state for one assembly project.

    Lifecycle::

        draft → solving → solved
                        → failed
    """

    id: str
    name: str
    parts: List[AssemblyPart] = field(default_factory=list)
    constraints: List[Constraint] = field(default_factory=list)
    status: Literal["draft", "solving", "solved", "failed"] = "draft"
    exports: Dict[str, str] = field(default_factory=dict)   # {"step": abs_path}
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    solve_time_s: float = 0.0

    def get_part(self, part_id: str) -> Optional[AssemblyPart]:
        return next((p for p in self.parts if p.id == part_id), None)

    def get_constraint(self, constraint_id: str) -> Optional[Constraint]:
        return next((c for c in self.constraints if c.id == constraint_id), None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "parts": [p.to_dict() for p in self.parts],
            "constraints": [c.to_dict() for c in self.constraints],
            "status": self.status,
            "exports": self.exports,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "solve_time_s": self.solve_time_s,
        }
