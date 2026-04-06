"""GeometryValidator: inspects runner-produced metrics for shape correctness.

Accepts the raw ``validation_metrics`` dict from ``ExecutionResult`` and
applies hard (blocking) and soft (warning-only) checks.  No CadQuery import
is required — all logic operates on plain Python dicts.

Metrics produced by runner_template.py
---------------------------------------
Core (always present when runner succeeds):
    is_valid     bool   — BRep validity check (BRepCheck_Analyzer)
    is_solid     bool   — shape contains at least one closed Solid body
    volume       float  — total volume in mm³
    face_count   int    — number of topological faces
    bbox         list   — [xlen, ylen, zlen] bounding box dimensions in mm

Surface / distribution (best-effort; may be None):
    surface_area  float  — total surface area in mm²
    aspect_ratio  float  — max_bbox_dim / min_bbox_dim; None if degenerate
    point_count   int    — number of tessellation vertices sampled
    spread_cv     float  — stddev / mean of vertex distances from centroid;
                           near 0 = uniform, > 0.8 = irregular distribution
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

    Hard checks (block export):
        - ``is_valid``:          shape passed BRep validity check
        - ``is_solid``:          result contains at least one closed solid body
        - ``volume > 0``:        shape has non-trivial volume
        - ``max_dim <= 10000``:  no single dimension exceeds 10 m
                                 (guards against LLM using metres or centimetres)

    Soft checks (warnings, non-blocking):
        - ``face_count >= 4``:   minimum for a closed solid
        - bbox dims all > 0:     no degenerate bounding box
        - max dim <= 2000 mm:    suspicious if larger (possible unit error)
        - min nonzero dim >= 0.05 mm:  extremely thin features may fail export
        - aspect_ratio <= 200:   extremely elongated shapes
        - spread_cv <= 0.85:     irregular surface point distribution
    """

    # ── Thresholds ────────────────────────────────────────────────────────────
    _MIN_VOLUME: float = 1e-6          # mm³

    _MIN_FACES: int = 4

    # Dimension sanity
    _MAX_DIM_HARD: float = 10_000.0   # mm  — hard error (unit mistake)
    _MAX_DIM_WARN: float = 2_000.0    # mm  — soft warning
    _MIN_DIM_WARN: float = 0.05       # mm  — soft warning (too thin)

    # Shape regularity
    _MAX_ASPECT_RATIO: float = 200.0  # soft warning
    _MAX_SPREAD_CV: float = 0.85      # soft warning

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

        bbox: list = metrics.get("bbox") or []

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

        body_count = metrics.get("body_count")
        if body_count is not None and body_count > 1:
            errors.append(
                f"Model has {body_count} disconnected solid bodies (expected 1). "
                "All parts must be joined into a single solid with .union(). "
                "Ensure each body's .translate() offset positions it flush against "
                "the adjacent body (sharing a face) before calling .union()."
            )

        volume = float(metrics.get("volume") or 0.0)
        if volume <= self._MIN_VOLUME:
            errors.append(
                f"Shape has zero or near-zero volume ({volume:.6g} mm\u00b3). "
                "Check that the model is not a 2D surface or an empty Workplane."
            )

        # Parameter sanity — hard: dimension exceeds 10 m (likely unit error)
        if bbox:
            max_dim = max(bbox)
            if max_dim > self._MAX_DIM_HARD:
                errors.append(
                    f"Shape has an extreme dimension of {max_dim:.1f} mm "
                    f"({max_dim / 1000:.2f} m). This almost certainly means "
                    "dimensions were specified in the wrong unit. "
                    "All dimensions must be in millimeters. "
                    f"Maximum allowed: {self._MAX_DIM_HARD:.0f} mm."
                )

        # ── Soft checks ───────────────────────────────────────────────────────

        face_count = int(metrics.get("face_count") or 0)
        if face_count < self._MIN_FACES:
            warnings.append(
                f"Shape has only {face_count} face(s); "
                f"a closed solid typically has at least {self._MIN_FACES}."
            )

        if bbox and any(d <= 0 for d in bbox):
            dims = ", ".join(f"{d:.3g}" for d in bbox)
            warnings.append(
                f"Bounding box has a zero or negative dimension: [{dims}] mm."
            )

        # Parameter sanity — soft: large dimension (suspicious unit)
        if bbox:
            max_dim = max(bbox)
            if self._MAX_DIM_WARN < max_dim <= self._MAX_DIM_HARD:
                warnings.append(
                    f"Shape has a large dimension of {max_dim:.1f} mm. "
                    "Verify that all dimensions are in millimeters, not centimeters "
                    "or meters."
                )

        # Parameter sanity — soft: extremely thin feature
        if bbox:
            nonzero = [d for d in bbox if d > 0]
            if nonzero:
                min_dim = min(nonzero)
                if min_dim < self._MIN_DIM_WARN:
                    warnings.append(
                        f"Shape has a very thin dimension of {min_dim:.4g} mm. "
                        "Features thinner than 0.05 mm may cause STEP/STL export "
                        "failures or mesh errors."
                    )

        # Shape regularity — soft: extreme aspect ratio
        # Computed from bbox directly (validator is authoritative; runner value is informational).
        if bbox:
            nonzero = [d for d in bbox if d > 1e-9]
            if len(nonzero) >= 2:
                computed_ar = max(nonzero) / min(nonzero)
                if computed_ar > self._MAX_ASPECT_RATIO:
                    warnings.append(
                        f"Shape has a high aspect ratio of {computed_ar:.1f}:1. "
                        "The geometry is very elongated or needle-like; verify dimensions."
                    )

        # Surface distribution — soft: irregular point spread
        spread_cv = metrics.get("spread_cv")
        if spread_cv is not None and spread_cv > self._MAX_SPREAD_CV:
            warnings.append(
                f"Surface point distribution is irregular (spread_cv={spread_cv:.3f}). "
                "The tessellated surface has highly uneven vertex density, which may "
                "indicate geometry with extreme concavities or near-degenerate faces."
            )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            metrics=dict(metrics),
        )
