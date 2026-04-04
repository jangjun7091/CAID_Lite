"""ExecutionResult: structured output from a single Sandbox.execute() call."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class ExecutionResult:
    """Everything the sandbox knows about a single subprocess execution.

    Populated by ``Sandbox.execute()`` and stored on ``PipelineResult``.
    All fields are set regardless of success/failure so callers can always
    log the full picture.

    Attributes:
        run_id: The run UUID passed into ``Sandbox.execute()``; links this
            result back to the parent ``PipelineResult``.
        success: True only when the subprocess ran, ``build_model()`` returned
            a valid ``cq.Workplane``, and all exports completed without error.
        stdout: Full stdout captured from the subprocess.
        stderr: Full stderr captured from the subprocess.
        exception: Human-readable error description when ``success=False``.
            ``None`` on success.
        exports: Mapping from format name to absolute ``Path`` of the output
            file.  Partial on export failure.
        elapsed_s: Wall-clock time from subprocess spawn to return, in seconds.
        timed_out: True when the subprocess was killed by the timeout.
        validation_metrics: Raw geometry metrics collected by the runner after
            a successful ``build_model()`` call.  ``None`` when execution failed
            before metrics could be collected, or if CadQuery is not installed.
            Keys: ``is_valid``, ``is_solid``, ``volume``, ``face_count``, ``bbox``.
    """

    run_id: str
    success: bool
    stdout: str
    stderr: str
    exception: Optional[str]
    exports: Dict[str, Path]
    elapsed_s: float
    timed_out: bool = False
    validation_metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict for logging and API responses."""
        return {
            "run_id": self.run_id,
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exception": self.exception,
            "exports": {k: str(v) for k, v in self.exports.items()},
            "elapsed_s": self.elapsed_s,
            "timed_out": self.timed_out,
            "validation_metrics": self.validation_metrics,
        }
