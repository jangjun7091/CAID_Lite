# validator/ — Geometry Validator

## Purpose
Inspect a `cq.Workplane` returned by `build_model()` for hard geometry faults (block export)
and soft warnings (logged but non-blocking). Not yet implemented — stub only.

## Planned interface
```python
@dataclass
class ValidationResult:
    valid: bool
    errors: List[str]       # hard failures; non-empty → trigger repair loop
    warnings: List[str]     # soft issues; logged, do not block export
    metrics: Dict[str, Any] # volume, bbox, face_count, is_solid

class GeometryValidator:
    def validate(self, model: "cq.Workplane") -> ValidationResult: ...
```

## Hard checks (failure → repair loop)
- `solid.isValid()` via `BRepCheck_Analyzer`
- `len(model.val().Solids()) > 0`  (accepts cq.Solid and cq.Compound wrapping solids;
  rejects bare Wire/Face compounds from unclosed 2-D sketches)
- `solid.Volume() > 1e-6`
- `model.val() is not None`

NOTE: Boolean operations like `.hole()` and `.cut()` return `cq.Compound`, not `cq.Solid`.
The `is_solid` check uses `.Solids()` rather than `isinstance(..., cq.Solid)` so that any
geometry containing at least one closed solid body passes, regardless of the OCC container type.

## Soft checks (warnings only)
- All bounding box dimensions > 0
- `len(solid.Faces()) >= 4`
- Center of mass within bounding box

## Architecture rules
- `GeometryValidator` operates on the `cq.Workplane` object returned by the runner.
  It does **not** re-execute user code.
- Validation runs inside the parent process (not a subprocess) — CadQuery must be installed.
- `ValidationResult.errors` strings are passed verbatim into the repair prompt so the LLM
  understands exactly what geometric property failed.
- Guard all imports of `cadquery` behind `TYPE_CHECKING` or lazy import — the validator
  module must be importable in environments without CadQuery installed.

## Dependency constraints
- `cadquery` at runtime only (optional extra).
- No imports from `llm`, `executor`, `repair`, `session`, or `api`.
