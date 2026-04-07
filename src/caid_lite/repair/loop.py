"""RepairLoop: iterative LLM-guided correction of failed CadQuery code.

The loop receives the failed code and error from the pipeline, asks the LLM
to fix it, re-executes in the sandbox, and optionally validates geometry.
It runs up to ``max_iterations`` times and returns a full attempt history.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..executor.result import ExecutionResult
from ..llm.base import LLMBackend
from ..llm.prompts import PromptBuilder
from ..logging.logger import get_logger
from ..validator.geometry import GeometryValidator, ValidationResult

_log = get_logger(__name__)

# ── Error type constants ──────────────────────────────────────────────────────

ERROR_GEOMETRY_CONSTRUCTION = "GEOMETRY_CONSTRUCTION"
ERROR_MISSING_BUILD_MODEL   = "MISSING_BUILD_MODEL"
ERROR_WRONG_RETURN_TYPE     = "WRONG_RETURN_TYPE"
ERROR_SYNTAX                = "SYNTAX_ERROR"
ERROR_IMPORT                = "IMPORT_ERROR"
ERROR_VALIDATION_FAILURE    = "VALIDATION_FAILURE"
ERROR_UNIT                  = "UNIT_ERROR"
ERROR_INT_CAST              = "INT_CAST_ERROR"
ERROR_UNKNOWN               = "UNKNOWN"


def classify_error(error: str) -> str:
    """Classify a repair error string into a coarse error type.

    The returned type string is used by ``RepairLoop`` to inject targeted
    repair guidance into the LLM prompt via ``PromptBuilder``.

    Args:
        error: Python traceback, CadQuery error message, or validation
               failure string produced by ``ValidationResult.format_errors()``.

    Returns:
        One of the ``ERROR_*`` module-level constants.
    """
    if not error:
        return ERROR_UNKNOWN

    lower = error.lower()

    # OCC / Wire / BRep geometry construction errors
    if any(kw in lower for kw in (
        "brepadaptor", "no geometry", "makespline", "bspline",
        "breplib_findsurface", "nullobject", "standard_nullobject",
        "brepcheck", "topods",
    )):
        return ERROR_GEOMETRY_CONSTRUCTION
    # Wire-only check — requires accompanying OCC context; raw "wire" is too broad
    if "wire" in lower and any(kw in lower for kw in ("occ", "solid", "shape", "topology")):
        return ERROR_GEOMETRY_CONSTRUCTION

    # Return type wrong — check BEFORE build_model so "must return" wins
    if "must return a cq.workplane" in lower or (
        "must return" in lower and "workplane" in lower
    ):
        return ERROR_WRONG_RETURN_TYPE
    # Also catch the runner's type-check message
    if "build_model() must return" in lower:
        return ERROR_WRONG_RETURN_TYPE

    # Validation failure messages that mention build_model — check BEFORE
    # MISSING_BUILD_MODEL so "did not produce" wins
    if "did not produce" in lower or "solid body" in lower:
        return ERROR_VALIDATION_FAILURE

    # build_model() missing or not callable
    if any(kw in lower for kw in (
        "not callable", "nameerror",
    )):
        return ERROR_MISSING_BUILD_MODEL
    if "build_model" in lower and ("not defined" in lower or "not found" in lower):
        return ERROR_MISSING_BUILD_MODEL

    # Return type wrong (broader fallback)
    if any(kw in lower for kw in ("typeerror",)) and "workplane" in lower:
        return ERROR_WRONG_RETURN_TYPE

    # Python syntax / indentation
    if any(kw in lower for kw in (
        "syntaxerror", "indentationerror", "unexpected indent",
        "invalid syntax", "eol while scanning",
    )):
        return ERROR_SYNTAX

    # Missing imports
    if any(kw in lower for kw in (
        "importerror", "modulenotfounderror", "no module named",
    )):
        return ERROR_IMPORT

    # Validation failures from GeometryValidator (unit / dimension error)
    if any(kw in lower for kw in (
        "extreme dimension", "wrong unit", "millimeter",
    )):
        return ERROR_UNIT

    # Validation failures (volume, solid, valid)
    if any(kw in lower for kw in (
        "volume", "solid body", "isvalid", "bounding box",
        "face_count", "validation",
    )):
        return ERROR_VALIDATION_FAILURE

    # rarray int/float argument order error
    if "cannot be interpreted as an integer" in lower or (
        "typeerror" in lower
        and "float" in lower
        and any(kw in lower for kw in ("int", "rarray", "range"))
    ):
        return ERROR_INT_CAST

    return ERROR_UNKNOWN


def _extract_code(response: str) -> str:
    """Strip markdown fences from an LLM response (first block wins)."""
    match = re.search(r"```(?:python)?\s*\n(.*?)```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return response.strip()


@dataclass
class RepairAttempt:
    """Record of a single repair iteration.

    Attributes:
        iteration: 0-indexed attempt number.
        code: The code submitted for this attempt (after fence stripping).
        error: The error string that was fed to the LLM for this attempt.
        exec_result: Execution outcome for this attempt.
        validation: Geometry validation outcome, if a validator is present
            and execution succeeded.
    """

    iteration: int
    code: str
    error: str
    exec_result: ExecutionResult
    validation: Optional[ValidationResult] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration,
            "code": self.code,
            "error": self.error,
            "exec_result": self.exec_result.to_dict(),
            "validation": self.validation.to_dict() if self.validation else None,
        }


@dataclass
class RepairResult:
    """Outcome of a full repair loop run.

    Attributes:
        repaired: True if any attempt produced valid, exportable geometry.
        iterations: Number of attempts made (1-indexed; 0 means loop not run).
        final_code: The code from the last attempt (successful or not).
        history: One ``RepairAttempt`` per iteration, in order.
        final_exec_result: ``ExecutionResult`` from the last attempt.
    """

    repaired: bool
    iterations: int
    final_code: str
    history: List[RepairAttempt] = field(default_factory=list)
    final_exec_result: Optional[ExecutionResult] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repaired": self.repaired,
            "iterations": self.iterations,
            "final_code": self.final_code,
            "history": [a.to_dict() for a in self.history],
        }


class RepairLoop:
    """Iteratively fixes failed CadQuery code via the LLM.

    Each iteration:
      1. Builds a repair prompt from the original description, current code,
         and the current error message.
      2. Calls ``LLMBackend.generate()`` to get a corrected version.
      3. Strips markdown fences.
      4. Executes the new code in the sandbox.
      5. Optionally validates geometry metrics.
      6. Returns immediately on the first successful, valid result.

    Args:
        llm: LLM backend for generating repair code.
        sandbox: Sandbox for executing repair candidates.
        validator: Optional geometry validator applied after successful
            execution.  When ``None``, any successful execution is accepted.
        max_iterations: Maximum repair attempts before giving up.
        prompts_dir: Optional path to custom prompt template files.
    """

    def __init__(
        self,
        llm: LLMBackend,
        sandbox: Any,  # duck-typed Sandbox
        validator: Optional[GeometryValidator] = None,
        max_iterations: int = 3,
        prompts_dir: Optional[Path] = None,
    ) -> None:
        self._llm = llm
        self._sandbox = sandbox
        self._validator = validator
        self._max_iterations = max_iterations
        self._prompt_builder = PromptBuilder(prompts_dir=prompts_dir)

    def run(
        self,
        original_prompt: str,
        failed_code: str,
        error: str,
        run_id_prefix: str = "",
    ) -> RepairResult:
        """Attempt to fix ``failed_code`` up to ``max_iterations`` times.

        Args:
            original_prompt: The user's original NL description.
            failed_code: The most recent code that failed (execution or validation).
            error: Error message to feed to the LLM (traceback or validation
                failure string from ``ValidationResult.format_errors()``).
            run_id_prefix: Prefix for repair run IDs (typically the original
                ``run_id``).  Each attempt appends ``-r{i}``.

        Returns:
            ``RepairResult`` with ``repaired=True`` if any attempt succeeded.
        """
        history: List[RepairAttempt] = []
        current_code = failed_code
        current_error = error

        for i in range(self._max_iterations):
            prefix_short = run_id_prefix[:8] if run_id_prefix else "repair"

            error_type = classify_error(current_error)
            _log.info(
                f"[{prefix_short}] Repair attempt {i + 1}/{self._max_iterations} "
                f"[error_type={error_type}]"
            )

            system, user = self._prompt_builder.build_repair_prompt(
                original_prompt, current_code, current_error,
                iteration=i, error_type=error_type,
            )
            raw = self._llm.generate(user, system)
            new_code = _extract_code(raw)

            repair_run_id = (
                f"{run_id_prefix}-r{i}" if run_id_prefix else f"repair-{i}"
            )
            exec_result = self._sandbox.execute(new_code, run_id=repair_run_id)

            val_result: Optional[ValidationResult] = None
            if exec_result.success and self._validator:
                val_result = self._validator.validate(exec_result.validation_metrics)

            attempt = RepairAttempt(
                iteration=i,
                code=new_code,
                error=current_error,
                exec_result=exec_result,
                validation=val_result,
            )
            history.append(attempt)

            # Success: execution worked and geometry is valid (or no validator)
            if exec_result.success and (val_result is None or val_result.valid):
                _log.info(f"[{prefix_short}] Repair succeeded on attempt {i + 1}")
                return RepairResult(
                    repaired=True,
                    iterations=i + 1,
                    final_code=new_code,
                    history=history,
                    final_exec_result=exec_result,
                )

            # Set up next iteration's error
            if not exec_result.success:
                current_error = exec_result.exception or "Unknown execution error."
            elif val_result is not None and not val_result.valid:
                current_error = val_result.format_errors()
            current_code = new_code

        _log.warning(
            f"[{prefix_short}] Repair exhausted {self._max_iterations} "
            "attempt(s) without success"
        )
        return RepairResult(
            repaired=False,
            iterations=self._max_iterations,
            final_code=current_code,
            history=history,
            final_exec_result=history[-1].exec_result if history else None,
        )
