"""CadQuery sandbox runner — executed as a subprocess by Sandbox.

DO NOT import this module directly. Sandbox copies it to a temporary
directory and runs it as ``python _runner.py <out_dir> <run_id> <formats>``.

Contract enforced on user-supplied code:
  - Must define a callable ``build_model()`` that takes no arguments.
  - ``build_model()`` must return a ``cq.Workplane`` object.
  - Must NOT call ``cq.exporters`` or perform any file I/O.

Communication protocol:
  stdout  — exactly one JSON line: ``{"success": bool, "exception": str|null,
            "exports": {format: path}, "validation_metrics": dict|null}``
  stderr  — captured but not parsed; contains CadQuery / OCC diagnostics
  exit code — always 0; errors are reported via JSON, not the exit code
"""

from __future__ import annotations

import json
import sys
import traceback
import pathlib

# ── Runtime arguments ─────────────────────────────────────────────────────────
_here = pathlib.Path(__file__).resolve().parent
_out_dir = pathlib.Path(sys.argv[1])
_run_id = sys.argv[2] if len(sys.argv) > 2 else "unknown"
_formats = sys.argv[3].split(",") if len(sys.argv) > 3 else ["step", "stl"]


# ── Runner ────────────────────────────────────────────────────────────────────

def _run() -> dict:
    """Execute the pipeline contract and return a JSON-serialisable result."""

    # ── Step 1: Read user code ────────────────────────────────────────────────
    code_path = _here / "user_code.py"
    try:
        code = code_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "success": False,
            "exception": f"Failed to read user_code.py: {exc}",
            "exports": {},
            "validation_metrics": None,
        }

    # ── Step 2: Compile and exec user code ────────────────────────────────────
    namespace: dict = {}
    try:
        exec(compile(code, str(code_path), "exec"), namespace)
    except Exception:
        return {
            "success": False,
            "exception": traceback.format_exc(),
            "exports": {},
            "validation_metrics": None,
        }

    # ── Step 3: Verify build_model() is defined and callable ─────────────────
    build_fn = namespace.get("build_model")
    if not callable(build_fn):
        return {
            "success": False,
            "exception": (
                "Generated code must define a callable build_model() function.\n\n"
                "Example:\n\n"
                "def build_model():\n"
                "    return cq.Workplane('XY').box(1, 1, 1)"
            ),
            "exports": {},
            "validation_metrics": None,
        }

    # ── Step 4: Call build_model() ────────────────────────────────────────────
    try:
        model = build_fn()
    except Exception:
        return {
            "success": False,
            "exception": traceback.format_exc(),
            "exports": {},
            "validation_metrics": None,
        }

    # ── Step 5: Import CadQuery and validate return type ─────────────────────
    try:
        import cadquery as cq
    except ImportError:
        return {
            "success": False,
            "exception": (
                "cadquery is not installed in this Python environment.\n"
                "Install with: pip install cadquery"
            ),
            "exports": {},
            "validation_metrics": None,
        }

    if not isinstance(model, cq.Workplane):
        return {
            "success": False,
            "exception": (
                f"build_model() must return a cq.Workplane object, "
                f"got {type(model).__qualname__!r} instead."
            ),
            "exports": {},
            "validation_metrics": None,
        }

    # ── Step 6: Collect geometry metrics ─────────────────────────────────────
    validation_metrics: dict | None = None
    try:
        shape = model.val()
        bb = shape.BoundingBox()
        validation_metrics = {
            "is_valid": shape.isValid(),
            "is_solid": isinstance(shape, (cq.Solid, cq.Compound)) and len(shape.Solids()) > 0,
            "volume": shape.Volume(),
            "face_count": len(shape.Faces()),
            "bbox": [bb.xlen, bb.ylen, bb.zlen],
        }
    except Exception:
        # Non-fatal: export can still proceed even if metrics collection fails.
        validation_metrics = None

    # ── Step 7: Export requested formats ─────────────────────────────────────
    exports: dict = {}
    _out_dir.mkdir(parents=True, exist_ok=True)

    for fmt in _formats:
        out_path = _out_dir / f"output.{fmt}"
        try:
            cq.exporters.export(model, str(out_path))
            exports[fmt] = str(out_path)
        except Exception:
            return {
                "success": False,
                "exception": f"{fmt.upper()} export failed:\n{traceback.format_exc()}",
                "exports": exports,
                "validation_metrics": validation_metrics,
            }

    return {
        "success": True,
        "exception": None,
        "exports": exports,
        "validation_metrics": validation_metrics,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = _run()
    print(json.dumps(result))
