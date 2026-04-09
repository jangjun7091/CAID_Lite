"""CadQuery assembly runner — executed as a subprocess by AssemblyPipeline.

DO NOT import this module directly.  AssemblyPipeline copies it to a temporary
directory and runs it as:

    python runner_assembly.py <out_dir> <assembly_id> <parts_json> <constraints_json>

Contract:
  - Loads each part's STEP file via ``cq.importers.importStep()``.
  - Builds a ``cq.Assembly`` tree, applies constraints, and calls ``asm.solve()``.
  - Exports the assembled compound as a single STEP file.

Communication protocol:
  stdout  — exactly one JSON line:
            {
              "success": bool,
              "exception": str | null,
              "step_path": str | null,
              "stl_path": str | null,
              "solve_time_s": float
            }
  stderr  — captured but not parsed; contains CadQuery / OCC diagnostics
  exit code — always 0; errors are reported via JSON, not the exit code
"""

from __future__ import annotations

import json
import sys
import time
import traceback
import pathlib

# ── Runtime arguments ─────────────────────────────────────────────────────────
_out_dir      = pathlib.Path(sys.argv[1])
_assembly_id  = sys.argv[2] if len(sys.argv) > 2 else "unknown"
_parts_json   = sys.argv[3] if len(sys.argv) > 3 else "[]"
_constraints_json = sys.argv[4] if len(sys.argv) > 4 else "[]"


# ── Face-selector wrapper ─────────────────────────────────────────────────────

def _make_query(part_id: str, selector: str) -> str:
    """Build a CadQuery assembly query string.

    Returns ``"<part_id>@faces@<selector>"`` for normal face queries.
    """
    return f"{part_id}@faces@{selector}"


# ── Runner ────────────────────────────────────────────────────────────────────

def _run() -> dict:
    """Execute the assembly pipeline and return a JSON-serialisable result."""

    try:
        parts = json.loads(_parts_json)
        constraints = json.loads(_constraints_json)
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "exception": f"Failed to parse arguments: {exc}",
            "step_path": None,
            "stl_path": None,
            "solve_time_s": 0.0,
        }

    # ── Step 1: Import CadQuery ───────────────────────────────────────────────
    try:
        import cadquery as cq
    except ImportError:
        return {
            "success": False,
            "exception": (
                "cadquery is not installed in this Python environment.\n"
                "Install with: pip install cadquery"
            ),
            "step_path": None,
            "stl_path": None,
            "solve_time_s": 0.0,
        }

    # ── Step 2: Load each STEP into a cq.Workplane ───────────────────────────
    workplanes: dict = {}
    for part in parts:
        pid   = part["id"]
        spath = part["step_path"]
        color = part.get("color", "#7ec8e3")
        try:
            wp = cq.importers.importStep(spath)
            workplanes[pid] = (wp, color)
        except Exception:
            return {
                "success": False,
                "exception": (
                    f"Failed to import STEP for part '{part['name']}' "
                    f"(id={pid}):\n{traceback.format_exc()}"
                ),
                "step_path": None,
                "stl_path": None,
                "solve_time_s": 0.0,
            }

    # ── Step 3: Build cq.Assembly ─────────────────────────────────────────────
    # Color list cycles for visual distinction when no explicit color is set.
    _COLORS = [
        cq.Color("lightblue"),
        cq.Color("lightgreen"),
        cq.Color("lightyellow"),
        cq.Color("lightpink"),
        cq.Color("lightgray"),
    ]

    asm = cq.Assembly()
    for idx, part in enumerate(parts):
        pid  = part["id"]
        wp, hex_color = workplanes[pid]
        try:
            r = int(hex_color[1:3], 16) / 255.0
            g = int(hex_color[3:5], 16) / 255.0
            b = int(hex_color[5:7], 16) / 255.0
            part_color = cq.Color(r, g, b)
        except Exception:
            part_color = _COLORS[idx % len(_COLORS)]

        asm.add(wp, name=pid, color=part_color)

    # ── Step 4: Add constraints ───────────────────────────────────────────────
    for con in constraints:
        kind    = con["type"]
        part_a  = con["part_a"]
        sel_a   = con.get("selector_a", "")
        part_b  = con.get("part_b")      # None for world-fixed constraints
        sel_b   = con.get("selector_b", "")
        param   = con.get("param", 0.0)

        try:
            if kind == "Fixed" or part_b is None:
                # Single-part world-fixed constraint
                asm.constrain(part_a, "Fixed")
            elif sel_a and sel_b:
                q1 = _make_query(part_a, sel_a)
                q2 = _make_query(part_b, sel_b)
                if param:
                    asm.constrain(q1, q2, kind, param=param)
                else:
                    asm.constrain(q1, q2, kind)
            else:
                # No selectors — use part-level constraint
                asm.constrain(part_a, part_b, kind)
        except Exception:
            return {
                "success": False,
                "exception": (
                    f"Failed to add constraint (type={kind}, "
                    f"part_a={part_a}, part_b={part_b}):\n"
                    f"{traceback.format_exc()}"
                ),
                "step_path": None,
                "stl_path": None,
                "solve_time_s": 0.0,
            }

    # ── Step 5: Solve ─────────────────────────────────────────────────────────
    t_start = time.monotonic()
    try:
        asm.solve()
    except Exception:
        return {
            "success": False,
            "exception": f"Assembly.solve() failed:\n{traceback.format_exc()}",
            "step_path": None,
            "stl_path": None,
            "solve_time_s": round(time.monotonic() - t_start, 3),
        }
    solve_time_s = round(time.monotonic() - t_start, 3)

    # ── Step 6: Export ────────────────────────────────────────────────────────
    _out_dir.mkdir(parents=True, exist_ok=True)
    step_path = str(_out_dir / "assembly.step")
    stl_path  = str(_out_dir / "assembly.stl")

    try:
        cq.exporters.export(asm, step_path)
    except Exception:
        return {
            "success": False,
            "exception": f"STEP export failed:\n{traceback.format_exc()}",
            "step_path": None,
            "stl_path": None,
            "solve_time_s": solve_time_s,
        }

    try:
        cq.exporters.export(asm, stl_path)
    except Exception:
        # STL export failure is non-fatal; STEP succeeded
        stl_path = None

    return {
        "success": True,
        "exception": None,
        "step_path": step_path,
        "stl_path": stl_path,
        "solve_time_s": solve_time_s,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = _run()
    print(json.dumps(result))
