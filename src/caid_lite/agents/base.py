"""Shared dataclasses for the multi-agent layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DesignPlan:
    """Structured interpretation of a user prompt produced by ArchitectAgent.

    Fields:
        features:      Ordered list of geometric features to model
                       (e.g. ["rectangular body", "four M4 through-holes"]).
        geometry_type: High-level shape category (e.g. "plate", "enclosure").
        constraints:   Key/value pairs for critical dimensions and clearances
                       (e.g. {"width_mm": 50, "thickness_mm": 5}).
        notes:         Free-form guidance for the Designer
                       (e.g. "use fillets on outer edges").
    """

    features: List[str] = field(default_factory=list)
    geometry_type: str = ""
    constraints: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "features": self.features,
            "geometry_type": self.geometry_type,
            "constraints": self.constraints,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DesignPlan":
        return cls(
            features=data.get("features", []),
            geometry_type=data.get("geometry_type", ""),
            constraints=data.get("constraints", {}),
            notes=data.get("notes", ""),
        )


@dataclass
class CriticResult:
    """Verdict produced by CriticAgent after reviewing generated code.

    Fields:
        approved:     True when the code may proceed to execution unchanged.
        revised_code: Optional replacement code from the Critic.  When set
                      the pipeline uses this code instead of the original.
        feedback:     Human-readable explanation of any issues found or
                      confirmation that the code is correct.
    """

    approved: bool
    revised_code: Optional[str] = None
    feedback: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "revised_code": self.revised_code,
            "feedback": self.feedback,
        }
