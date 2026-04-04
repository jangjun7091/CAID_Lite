"""Sandbox: executes LLM-generated CadQuery code in an isolated subprocess.

Design principles:
  - Isolation: each execution spawns a fresh Python interpreter, so an OCC
    crash or infinite loop cannot kill the parent process.
  - Timeout: the subprocess is killed after ``timeout_s`` seconds.
  - No side-effects: user code is written to a temporary directory that is
    cleaned up automatically; only the exported STEP/STL files persist.
  - Decoupled: Sandbox has no knowledge of sessions, GUI, or the LLM layer.
    It speaks only ``str`` (code) → ``ExecutionResult``.

Code contract enforced by the runner:
  - Generated code must define ``build_model()`` with no arguments.
  - ``build_model()`` must return a ``cq.Workplane`` object.
  - Generated code must NOT call ``cq.exporters`` or any file I/O directly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from .result import ExecutionResult
from ..logging.logger import get_logger

_log = get_logger(__name__)

# Resolved once at import time so Sandbox.execute() never needs __file__ logic.
_RUNNER_TEMPLATE = Path(__file__).resolve().parent / "runner_template.py"


class Sandbox:
    """Runs generated CadQuery code in a child subprocess with a hard timeout.

    Args:
        timeout_s: Maximum wall-clock time (seconds) before the subprocess is
            killed.  Defaults to 60 s; set lower for test speed.
        output_dir: Root directory for persistent run outputs.  Each run gets
            its own subdirectory: ``output_dir / run_id / output.{step,stl}``.
        formats: List of export formats to produce.  The runner passes these
            to ``cq.exporters.export()``.  Defaults to ``["step", "stl"]``.

    Example::

        sandbox = Sandbox(timeout_s=30, output_dir=Path("outputs"))
        result = sandbox.execute(code_string, run_id="abc123")
        if result.success:
            print(result.exports["step"])
    """

    def __init__(
        self,
        timeout_s: float = 60.0,
        output_dir: Path = Path("outputs"),
        formats: Optional[List[str]] = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.output_dir = Path(output_dir)
        self.formats = formats or ["step", "stl"]

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: dict) -> "Sandbox":
        """Build from the top-level ``config/default.yaml`` dict.

        Reads ``config["executor"]["timeout_s"]``,
        ``config["exporter"]["output_dir"]``, and
        ``config["exporter"]["formats"]``.
        """
        executor_cfg = config.get("executor", {})
        exporter_cfg = config.get("exporter", {})
        return cls(
            timeout_s=float(executor_cfg.get("timeout_s", 60.0)),
            output_dir=Path(exporter_cfg.get("output_dir", "outputs")),
            formats=exporter_cfg.get("formats", ["step", "stl"]),
        )

    # ------------------------------------------------------------------
    # Main execution method
    # ------------------------------------------------------------------

    def execute(self, code: str, run_id: str) -> ExecutionResult:
        """Execute ``code`` in an isolated subprocess and return the result.

        The method:
          1. Writes ``code`` to a temporary ``user_code.py``.
          2. Copies the runner template alongside it.
          3. Spawns a fresh Python interpreter with a hard timeout.
          4. Parses the JSON printed to stdout by the runner.
          5. Returns an ``ExecutionResult`` regardless of success or failure.

        The temporary directory is always cleaned up; only files written to
        ``output_dir / run_id /`` persist beyond this call.

        Args:
            code: Python source that must define ``build_model()``.
            run_id: Unique identifier for this run; used as the output
                subdirectory name.

        Returns:
            ``ExecutionResult`` with all fields populated.
        """
        run_out_dir = self.output_dir / run_id
        _log.debug(f"[{run_id[:8]}] Sandbox.execute - out_dir={run_out_dir}")

        with tempfile.TemporaryDirectory(prefix="caid_lite_") as _tmp:
            tmp_dir = Path(_tmp)

            # ── Prepare temp directory ────────────────────────────────────
            (tmp_dir / "user_code.py").write_text(code, encoding="utf-8")
            runner_path = tmp_dir / "_runner.py"
            shutil.copy2(_RUNNER_TEMPLATE, runner_path)

            cmd: List[str] = [
                sys.executable,
                str(runner_path),
                str(run_out_dir),
                run_id,
                ",".join(self.formats),
            ]

            # ── Spawn subprocess ──────────────────────────────────────────
            _log.debug(
                f"[{run_id[:8]}] Spawning: {sys.executable} _runner.py "
                f"(timeout={self.timeout_s}s, formats={self.formats})"
            )
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
                    f"[{run_id[:8]}] Subprocess timed out after {self.timeout_s}s"
                )
                return ExecutionResult(
                    run_id=run_id,
                    success=False,
                    stdout=exc.stdout or "",
                    stderr=exc.stderr or "",
                    exception=f"Execution timed out after {self.timeout_s:.1f}s.",
                    exports={},
                    elapsed_s=round(elapsed, 3),
                    timed_out=True,
                )

            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()

            _log.debug(
                f"[{run_id[:8]}] Subprocess exited "
                f"(rc={proc.returncode}, elapsed={elapsed:.2f}s)"
            )

            # ── Handle empty stdout (runner crashed before printing) ──────
            if not stdout:
                return ExecutionResult(
                    run_id=run_id,
                    success=False,
                    stdout="",
                    stderr=stderr,
                    exception=(
                        f"Runner exited without producing output "
                        f"(exit code {proc.returncode})."
                        + (f"\nstderr: {stderr}" if stderr else "")
                    ),
                    exports={},
                    elapsed_s=round(elapsed, 3),
                )

            # ── Parse JSON from stdout ────────────────────────────────────
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                return ExecutionResult(
                    run_id=run_id,
                    success=False,
                    stdout=stdout,
                    stderr=stderr,
                    exception=(
                        "Runner produced non-JSON output — this is a bug in "
                        f"runner_template.py.\nstdout: {stdout[:500]}"
                    ),
                    exports={},
                    elapsed_s=round(elapsed, 3),
                )

            # ── Build result ──────────────────────────────────────────────
            exports = {k: Path(v) for k, v in data.get("exports", {}).items()}

            return ExecutionResult(
                run_id=run_id,
                success=bool(data.get("success", False)),
                stdout=stdout,
                stderr=stderr,
                exception=data.get("exception"),
                exports=exports,
                elapsed_s=round(elapsed, 3),
                validation_metrics=data.get("validation_metrics"),
            )
