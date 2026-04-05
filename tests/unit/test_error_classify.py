"""Tests for repair error classification and error-type-aware repair prompts.

No API key, no CadQuery, no subprocess required.
"""

from __future__ import annotations

import pytest

from caid_lite.repair.loop import (
    classify_error,
    ERROR_GEOMETRY_CONSTRUCTION,
    ERROR_MISSING_BUILD_MODEL,
    ERROR_WRONG_RETURN_TYPE,
    ERROR_SYNTAX,
    ERROR_IMPORT,
    ERROR_VALIDATION_FAILURE,
    ERROR_UNIT,
    ERROR_UNKNOWN,
)
from caid_lite.llm.prompts import PromptBuilder


# ── classify_error ────────────────────────────────────────────────────────────


class TestClassifyError:
    def test_brepadaptor_is_geometry_construction(self):
        assert classify_error("BRepAdaptor_Curve::No geometry") == ERROR_GEOMETRY_CONSTRUCTION

    def test_wire_keyword_is_geometry_construction(self):
        assert classify_error("TypeError: expected Solid, got Wire") == ERROR_GEOMETRY_CONSTRUCTION

    def test_makespline_is_geometry_construction(self):
        assert classify_error("cq.Wire.makeSpline failed") == ERROR_GEOMETRY_CONSTRUCTION

    def test_nullobject_is_geometry_construction(self):
        assert classify_error("Standard_NullObject raised") == ERROR_GEOMETRY_CONSTRUCTION

    def test_nameerror_build_model_is_missing_build_model(self):
        assert classify_error("NameError: name 'build_model' is not defined") == ERROR_MISSING_BUILD_MODEL

    def test_not_callable_is_missing_build_model(self):
        assert classify_error("build_model is not callable") == ERROR_MISSING_BUILD_MODEL

    def test_workplane_return_type(self):
        assert classify_error("build_model() must return a cq.Workplane object, got NoneType") == ERROR_WRONG_RETURN_TYPE

    def test_syntaxerror_is_syntax(self):
        assert classify_error("SyntaxError: invalid syntax") == ERROR_SYNTAX

    def test_indentationerror_is_syntax(self):
        assert classify_error("IndentationError: unexpected indent") == ERROR_SYNTAX

    def test_importerror_is_import(self):
        assert classify_error("ImportError: No module named 'cadquery'") == ERROR_IMPORT

    def test_modulenotfound_is_import(self):
        assert classify_error("ModuleNotFoundError: No module named 'occ'") == ERROR_IMPORT

    def test_extreme_dimension_is_unit_error(self):
        assert classify_error("Shape has an extreme dimension of 15000.0 mm") == ERROR_UNIT

    def test_volume_failure_is_validation(self):
        assert classify_error("Shape has zero or near-zero volume (0.0 mm³)") == ERROR_VALIDATION_FAILURE

    def test_solid_body_failure_is_validation(self):
        assert classify_error("build_model() did not produce a solid body.") == ERROR_VALIDATION_FAILURE

    def test_isvalid_failure_is_validation(self):
        assert classify_error("isValid() returned False") == ERROR_VALIDATION_FAILURE

    def test_empty_string_is_unknown(self):
        assert classify_error("") == ERROR_UNKNOWN

    def test_generic_error_is_unknown(self):
        assert classify_error("something completely unrecognised happened") == ERROR_UNKNOWN

    def test_case_insensitive(self):
        assert classify_error("BREPADAPTOR_CURVE::NO GEOMETRY") == ERROR_GEOMETRY_CONSTRUCTION

    def test_multiline_traceback_geometry(self):
        tb = (
            "Traceback (most recent call last):\n"
            "  File 'user_code.py', line 55, in build_model\n"
            "    solid = wire.extrude(10)\n"
            "OCP.OCP.Standard.Standard_NullObject: BRepAdaptor_Curve::No geometry"
        )
        assert classify_error(tb) == ERROR_GEOMETRY_CONSTRUCTION


# ── PromptBuilder error-type hint injection ───────────────────────────────────


class TestPromptBuilderErrorTypeHints:
    def _build(self, error_type: str) -> str:
        pb = PromptBuilder()
        _, user = pb.build_repair_prompt(
            original_description="a box",
            failed_code="bad code",
            error_message="some error",
            iteration=0,
            error_type=error_type,
        )
        return user

    def test_geometry_hint_injected(self):
        user = self._build(ERROR_GEOMETRY_CONSTRUCTION)
        assert "GEOMETRY_CONSTRUCTION" in user
        assert "polyline" in user.lower()

    def test_missing_build_model_hint_injected(self):
        user = self._build(ERROR_MISSING_BUILD_MODEL)
        assert "MISSING_BUILD_MODEL" in user
        assert "build_model" in user

    def test_wrong_return_type_hint_injected(self):
        user = self._build(ERROR_WRONG_RETURN_TYPE)
        assert "WRONG_RETURN_TYPE" in user
        assert "cq.Workplane" in user

    def test_syntax_hint_injected(self):
        user = self._build(ERROR_SYNTAX)
        assert "SYNTAX_ERROR" in user

    def test_import_hint_injected(self):
        user = self._build(ERROR_IMPORT)
        assert "IMPORT_ERROR" in user
        assert "import cadquery" in user.lower()

    def test_unit_hint_injected(self):
        user = self._build(ERROR_UNIT)
        assert "UNIT_ERROR" in user
        assert "millimeter" in user.lower()

    def test_validation_hint_injected(self):
        user = self._build(ERROR_VALIDATION_FAILURE)
        assert "VALIDATION_FAILURE" in user

    def test_unknown_type_no_hint_block(self):
        user = self._build(ERROR_UNKNOWN)
        assert "TARGETED FIX" not in user

    def test_error_message_always_present(self):
        user = self._build(ERROR_SYNTAX)
        assert "some error" in user

    def test_original_description_always_present(self):
        pb = PromptBuilder()
        _, user = pb.build_repair_prompt(
            original_description="a 50mm bracket",
            failed_code="bad",
            error_message="err",
            error_type=ERROR_SYNTAX,
        )
        assert "50mm bracket" in user

    def test_default_error_type_is_unknown(self):
        pb = PromptBuilder()
        _, user = pb.build_repair_prompt("a box", "bad", "err")
        assert "TARGETED FIX" not in user

    def test_iteration_shown_in_prompt(self):
        pb = PromptBuilder()
        _, user = pb.build_repair_prompt("a box", "bad", "err", iteration=2)
        assert "attempt 3" in user


# ── RepairLoop passes error_type through ─────────────────────────────────────


class TestRepairLoopErrorTypePassthrough:
    """Verify the loop classifies errors and injects the hint into LLM calls."""

    def test_geometry_error_type_hint_reaches_llm(self):
        from caid_lite.repair.loop import RepairLoop
        from caid_lite.executor.result import ExecutionResult
        from tests.fixtures.mock_llm import MockLLMBackend
        from tests.fixtures.mock_sandbox import MockSandbox

        fenced = "```python\ndef build_model(): pass\n```"
        exec_ok = ExecutionResult(
            run_id="r", success=True, stdout="", stderr="",
            exception=None, exports={}, elapsed_s=0.01,
        )
        llm = MockLLMBackend(responses=[fenced])
        sandbox = MockSandbox(results=[exec_ok])
        loop = RepairLoop(llm=llm, sandbox=sandbox, max_iterations=1)

        loop.run("a gear", "bad code", "BRepAdaptor_Curve::No geometry")

        user_prompt, _ = llm.calls[0]
        assert "GEOMETRY_CONSTRUCTION" in user_prompt
        assert "polyline" in user_prompt.lower()

    def test_unknown_error_no_hint(self):
        from caid_lite.repair.loop import RepairLoop
        from caid_lite.executor.result import ExecutionResult
        from tests.fixtures.mock_llm import MockLLMBackend
        from tests.fixtures.mock_sandbox import MockSandbox

        fenced = "```python\ndef build_model(): pass\n```"
        exec_ok = ExecutionResult(
            run_id="r", success=True, stdout="", stderr="",
            exception=None, exports={}, elapsed_s=0.01,
        )
        llm = MockLLMBackend(responses=[fenced])
        sandbox = MockSandbox(results=[exec_ok])
        loop = RepairLoop(llm=llm, sandbox=sandbox, max_iterations=1)

        loop.run("a box", "bad code", "something totally random")

        user_prompt, _ = llm.calls[0]
        assert "TARGETED FIX" not in user_prompt
