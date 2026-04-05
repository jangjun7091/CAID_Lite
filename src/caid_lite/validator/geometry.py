"""GeometryValidator: inspects runner-produced metrics for shape correctness.

Accepts the raw ``validation_metrics`` dict from ``ExecutionResult`` and
applies hard (blocking) and soft (warning-only) checks.  No CadQuery import
is required — all logic operates on plain Python dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ValidationResult:
    """Outcome of a single geometry validation pass.

    Attributes:
        valid: True only when all hard checks passed.  Soft warnings do not
            affect this flag.
        errors: Hard-failure descriptions.  Non-empty → ``valid=False``;
            these strings are fed verbatim into the repair prompt.
        warnings: Soft-issue descriptions.  Logged but do not block export.
        metrics: The raw metrics dict that was validated.
    """

    valid: bool
    errors: List[str]
    warnings: List[str]
    metrics: Dict[str, Any] = field(default_factory=dict)

    def format_errors(self) -> str:
        """Return all hard errors as a single newline-separated string."""
        return "\n".join(self.errors)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


class GeometryValidator:
    """Validates geometry metrics emitted by the executor runner.

    Hard checks trigger a repair attempt; soft checks produce warnings only.

    Hard checks:
        - ``is_valid``: shape passed BRep validity check
        - ``is_solid``: result contains at least one closed solid body (not a bare
          shell, wire, or empty Compound)
        - ``volume > 0``: shape has non-trivial volume

    Soft checks (warnings, non-blocking):
        - ``face_count >= 4``: minimum for a closed solid
        - ``bbox`` dimensions all > 0: no degenerate bounding box
    """

    _MIN_VOLUME: float = 1e-6
    _MIN_FACES: int = 4

    def validate(self, metrics: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate a metrics dict and return a ``ValidationResult``.

        Args:
            metrics: The ``validation_metrics`` dict from ``ExecutionResult``.
                ``None`` or empty → immediate hard failure.

        Returns:
            ``ValidationResult`` with ``valid=True`` iff all hard checks pass.
        """
        if not metrics:
            return ValidationResult(
                valid=False,
                errors=[
                    "No geometry metrics available — the runner did not produce "
                    "shape data. This usually means execution failed before "
                    "build_model() could be called successfully."
                ],
                warnings=[],
                metrics={},
            )

        errors: List[str] = []
        warnings: List[str] = []

        # ── Hard checks ───────────────────────────────────────────────────────

        if not metrics.get("is_valid", False):
            errors.append(
                "Shape failed the BRep validity check (isValid() returned False). "
                "The geometry has internal errors and cannot be exported reliably."
            )

        if not metrics.get("is_solid", False):
            errors.append(
                "build_model() did not produce a solid body. "
                "The result contains no closed solid geometry. "
                "Build a solid base first (.box(), .cylinder(), .extrude(), etc.) "
                "before applying features. Boolean operations like .hole() and .cut() "
                "are valid on an existing solid."
            )

        volume = float(metrics.get("volume") or 0.0)
        if volume <= self._MIN_VOLUME:
            errors.append(
                f"Shape has zero or near-zero volume ({volume:.6g} mm³). "
                "Check that the model is not a 2D surface or an empty Workplane."
            )

        # ── Soft checks ───────────────────────────────────────────────────────

        face_count = int(metrics.get("face_count") or 0)
        if face_count < self._MIN_FACES:
            warnings.append(
                f"Shape has only {face_count} face(s); "
                f"a closed solid typically has at least {self._MIN_FACES}."
            )

        bbox = metrics.get("bbox") or []
        if bbox and any(d <= 0 for d in bbox):
            dims = ", ".join(f"{d:.3g}" for d in bbox)
            warnings.append(
                f"Bounding box has a zero or negative dimension: [{dims}] mm."
            )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            metrics=dict(metrics),
        )
