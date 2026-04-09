"""STEP/STL import runner — executed as a subprocess by the import route.

DO NOT import this module directly.

argv: <out_dir> <part_id> <source_path> <source_format>

  source_format: "step" | "stl"

Responsibilities:
  - For STEP: importStep() → validate → export STEP + STL
  - For STL:  load directly → export STL only (no STEP regeneration)

Communication protocol:
  stdout  — exactly one JSON line:
            {
              "success": bool,
              "exception": str | null,
              "step_path": str | null,
              "stl_path":  str | null,
              "validation_metrics": dict | null
            }
  exit code — always 0
"""

from __future__ import annotations

import json
import pathlib
import sys
import traceback

_out_dir       = pathlib.Path(sys.argv[1])
_part_id       = sys.argv[2] if len(sys.argv) > 2 else "unknown"
_source_path   = sys.argv[3] if len(sys.argv) > 3 else ""
_source_format = sys.argv[4].lower() if len(sys.argv) > 4 else "step"


def _run() -> dict:
    try:
        import cadquery as cq
    except ImportError:
        return {
            "success": False,
            "exception": "cadquery is not installed.",
            "step_path": None, "stl_path": None, "validation_metrics": None,
        }

    _out_dir.mkdir(parents=True, exist_ok=True)
    step_path = str(_out_dir / "output.step")
    stl_path  = str(_out_dir / "output.stl")

    # ── Import ────────────────────────────────────────────────────────────────
    if _source_format == "step":
        try:
            model = cq.importers.importStep(_source_path)
        except Exception:
            return {
                "success": False,
                "exception": f"Failed to import STEP:\n{traceback.format_exc()}",
                "step_path": None, "stl_path": None, "validation_metrics": None,
            }

        # ── Validation metrics ────────────────────────────────────────────────
        validation_metrics = None
        try:
            import math as _math
            shape = model.val()
            bb    = shape.BoundingBox()
            bbox_dims = [bb.xlen, bb.ylen, bb.zlen]
            max_dim   = max(bbox_dims) if bbox_dims else 0.0
            nonzero   = [d for d in bbox_dims if d > 1e-9]
            min_dim   = min(nonzero) if nonzero else 0.0
            aspect    = round(max_dim / min_dim, 2) if min_dim > 0 else None
            try:
                surface_area = round(shape.Area(), 4)
            except Exception:
                surface_area = None
            validation_metrics = {
                "is_valid":     shape.isValid(),
                "is_solid":     isinstance(shape, (cq.Solid, cq.Compound))
                                and len(shape.Solids()) > 0,
                "body_count":   len(shape.Solids()),
                "volume":       shape.Volume(),
                "face_count":   len(shape.Faces()),
                "bbox":         bbox_dims,
                "surface_area": surface_area,
                "aspect_ratio": aspect,
                "point_count":  None,
                "spread_cv":    None,
            }
        except Exception:
            validation_metrics = None

        # ── Export STEP + STL ─────────────────────────────────────────────────
        try:
            cq.exporters.export(model, step_path)
        except Exception:
            return {
                "success": False,
                "exception": f"STEP export failed:\n{traceback.format_exc()}",
                "step_path": None, "stl_path": None, "validation_metrics": validation_metrics,
            }
        try:
            cq.exporters.export(model, stl_path)
        except Exception:
            stl_path = None

        return {
            "success": True, "exception": None,
            "step_path": step_path, "stl_path": stl_path,
            "validation_metrics": validation_metrics,
        }

    elif _source_format == "stl":
        # STL: just copy to output dir; no STEP available
        import shutil
        try:
            shutil.copy2(_source_path, stl_path)
        except Exception:
            return {
                "success": False,
                "exception": f"Failed to copy STL:\n{traceback.format_exc()}",
                "step_path": None, "stl_path": None, "validation_metrics": None,
            }
        return {
            "success": True, "exception": None,
            "step_path": None, "stl_path": stl_path,
            "validation_metrics": None,
        }

    else:
        return {
            "success": False,
            "exception": f"Unsupported format: {_source_format!r}",
            "step_path": None, "stl_path": None, "validation_metrics": None,
        }


if __name__ == "__main__":
    result = _run()
    print(json.dumps(result))
