"""AssemblyPipeline: executes cq.Assembly solve in an isolated subprocess.

Architecture notes:
  - Stateless: holds no session or run history.
  - Mirrors the Sandbox pattern from executor/sandbox.py.
  - Copies runner_assembly.py to a temp directory and spawns it as a fresh
    Python interpreter (same isolation principle as the CadQuery sandbox).
  - Returns AssemblyResult with all outcome data.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List

from ..logging.logger import get_logger
from .models import AssemblyPart, AssemblySession, Constraint

_log = get_logger(__name__)

_RUNNER_TEMPLATE = Path(__file__).resolve().parent / "runner_assembly.py"


class AssemblyResult:
    """Outcome of a single AssemblyPipeline.solve() call."""

    __slots__ = (
        "assembly_id", "success", "step_path", "stl_path",
        "solve_time_s", "elapsed_s", "timed_out", "error",
    )

    def __init__(
        self,
        assembly_id: str,
        success: bool,
        step_path: str | None = None,
        stl_path: str | None = None,
        solve_time_s: float = 0.0,
        elapsed_s: float = 0.0,
        timed_out: bool = False,
        error: str | None = None,
    ) -> None:
        self.assembly_id   = assembly_id
        self.success       = success
        self.step_path     = step_path
        self.stl_path      = stl_path
        self.solve_time_s  = solve_time_s
        self.elapsed_s     = elapsed_s
        self.timed_out     = timed_out
        self.error         = error


class AssemblyPipeline:
    """Runs cq.Assembly in an isolated subprocess with a hard timeout.

    Args:
        timeout_s:  Maximum wall-clock seconds before the subprocess is killed.
        output_dir: Root directory for assembly outputs.  Each solve gets its
                    own subdirectory: ``output_dir / assembly_id /``.
    """

    def __init__(
        self,
        timeout_s: float = 120.0,
        output_dir: Path = Path("outputs"),
    ) -> None:
        self.timeout_s  = timeout_s
        self.output_dir = Path(output_dir)

    @classmethod
    def from_config(cls, config: dict) -> "AssemblyPipeline":
        """Build from the top-level ``config/default.yaml`` dict."""
        executor_cfg = config.get("executor", {})
        exporter_cfg = config.get("exporter", {})
        return cls(
            timeout_s  = float(executor_cfg.get("timeout_s", 120.0)),
            output_dir = Path(exporter_cfg.get("output_dir", "outputs")),
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def solve(self, session: AssemblySession) -> AssemblyResult:
        """Solve the assembly constraints and export the result.

        Args:
            session: The AssemblySession to solve.  Only ``session.parts``
                     and ``session.constraints`` are read; the session object
                     is not mutated here.

        Returns:
            AssemblyResult with all outcome data.
        """
        asm_id      = session.id
        run_out_dir = self.output_dir / asm_id

        parts_payload = [
            {
                "id":        p.id,
                "name":      p.name,
                "step_path": p.step_path,
                "color":     p.color,
            }
            for p in session.parts
        ]
        constraints_payload = [c.to_dict() for c in session.constraints]

        parts_json       = json.dumps(parts_payload)
        constraints_json = json.dumps(constraints_payload)

        _log.debug(
            f"[{asm_id[:8]}] AssemblyPipeline.solve — "
            f"{len(parts_payload)} parts, {len(constraints_payload)} constraints"
        )

        with tempfile.TemporaryDirectory(prefix="caid_asm_") as _tmp:
            tmp_dir     = Path(_tmp)
            runner_path = tmp_dir / "_runner_assembly.py"
            shutil.copy2(_RUNNER_TEMPLATE, runner_path)

            cmd = [
                sys.executable,
                str(runner_path),
                str(run_out_dir),
                asm_id,
                parts_json,
                constraints_json,
            ]

            start = time.monotonic()
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.timeout_s,
                )
                elapsed = time.monotonic() - start
            except subprocess.TimeoutExpired as exc:
                elapsed = time.monotonic() - start
                _log.warning(
                    f"[{asm_id[:8]}] Assembly subprocess timed out "
                    f"after {self.timeout_s}s"
                )
                return AssemblyResult(
                    assembly_id=asm_id,
                    success=False,
                    elapsed_s=round(elapsed, 3),
                    timed_out=True,
                    error=f"Assembly solve timed out after {self.timeout_s:.1f}s.",
                )

            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            _log.debug(
                f"[{asm_id[:8]}] Subprocess exited "
                f"(rc={proc.returncode}, elapsed={elapsed:.2f}s)"
            )

            if not stdout:
                return AssemblyResult(
                    assembly_id=asm_id,
                    success=False,
                    elapsed_s=round(elapsed, 3),
                    error=(
                        f"Runner exited without producing output "
                        f"(exit code {proc.returncode})."
                        + (f"\nstderr: {stderr}" if stderr else "")
                    ),
                )

            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                return AssemblyResult(
                    assembly_id=asm_id,
                    success=False,
                    elapsed_s=round(elapsed, 3),
                    error=f"Runner produced non-JSON output:\n{stdout[:500]}",
                )

            return AssemblyResult(
                assembly_id  = asm_id,
                success      = bool(data.get("success", False)),
                step_path    = data.get("step_path"),
                stl_path     = data.get("stl_path"),
                solve_time_s = float(data.get("solve_time_s", 0.0)),
                elapsed_s    = round(elapsed, 3),
                error        = data.get("exception"),
            )
