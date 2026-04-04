"""Tests for RepairLoop, RepairResult, and RepairAttempt.

All tests use MockLLMBackend + MockSandbox — no API key or CadQuery required.
"""

from __future__ import annotations

import pytest

from caid_lite.executor.result import ExecutionResult
from caid_lite.repair.loop import RepairAttempt, RepairLoop, RepairResult
from caid_lite.validator.geometry import GeometryValidator
from tests.fixtures.mock_llm import MockLLMBackend
from tests.fixtures.mock_sandbox import MockSandbox


# ── Code fixtures ─────────────────────────────────────────────────────────────

_FENCED_CODE = "```python\ndef build_model(): pass\n```"
_PLAIN_CODE = "def build_model(): pass"

_VALID_METRICS = {
    "is_valid": True,
    "is_solid": True,
    "volume": 1000.0,
    "face_count": 6,
    "bbox": [10.0, 10.0, 10.0],
}

_INVALID_METRICS = {
    "is_valid": False,
    "is_solid": True,
    "volume": 1000.0,
    "face_count": 6,
    "bbox": [10.0, 10.0, 10.0],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _exec(success=True, exception=None, run_id="r", validation_metrics=None):
    return ExecutionResult(
        run_id=run_id,
        success=success,
        stdout="",
        stderr="",
        exception=exception,
        exports={},
        elapsed_s=0.01,
        validation_metrics=validation_metrics,
    )


def _make_loop(responses, sandbox, validator=None, max_iterations=3):
    llm = MockLLMBackend(responses=responses)
    return RepairLoop(
        llm=llm,
        sandbox=sandbox,
        validator=validator,
        max_iterations=max_iterations,
    ), llm


# ── RepairResult ──────────────────────────────────────────────────────────────


class TestRepairResult:
    def test_to_dict_contains_required_keys(self):
        r = RepairResult(repaired=True, iterations=1, final_code="code", history=[])
        d = r.to_dict()
        for key in ("repaired", "iterations", "final_code", "history"):
            assert key in d

    def test_to_dict_history_is_list(self):
        r = RepairResult(repaired=False, iterations=2, final_code="code", history=[])
        assert isinstance(r.to_dict()["history"], list)


# ── RepairAttempt ─────────────────────────────────────────────────────────────


class TestRepairAttempt:
    def test_to_dict_contains_required_keys(self):
        attempt = RepairAttempt(
            iteration=0, code="code", error="err",
            exec_result=_exec(), validation=None,
        )
        d = attempt.to_dict()
        for key in ("iteration", "code", "error", "exec_result", "validation"):
            assert key in d

    def test_to_dict_validation_is_none_when_not_set(self):
        attempt = RepairAttempt(iteration=0, code="c", error="e", exec_result=_exec())
        assert attempt.to_dict()["validation"] is None


# ── Successful repair ─────────────────────────────────────────────────────────


class TestRepairLoopSuccess:
    def test_succeeds_on_first_attempt(self):
        sandbox = MockSandbox(results=[_exec(success=True)])
        loop, _ = _make_loop([_FENCED_CODE], sandbox)
        result = loop.run("a box", "bad code", "SomeError")
        assert result.repaired is True
        assert result.iterations == 1

    def test_succeeds_on_second_attempt(self):
        sandbox = MockSandbox(results=[_exec(success=False, exception="err"), _exec(success=True)])
        loop, _ = _make_loop([_FENCED_CODE, _FENCED_CODE], sandbox)
        result = loop.run("a box", "bad code", "SomeError")
        assert result.repaired is True
        assert result.iterations == 2

    def test_history_length_equals_iterations_on_success(self):
        sandbox = MockSandbox(results=[_exec(success=False, exception="err"), _exec(success=True)])
        loop, _ = _make_loop([_FENCED_CODE, _FENCED_CODE], sandbox)
        result = loop.run("a box", "bad code", "SomeError")
        assert len(result.history) == 2

    def test_final_code_has_fences_stripped(self):
        sandbox = MockSandbox(results=[_exec(success=True)])
        loop, _ = _make_loop([_FENCED_CODE], sandbox)
        result = loop.run("a box", "bad code", "err")
        assert "```" not in result.final_code
        assert "build_model" in result.final_code

    def test_final_exec_result_populated_on_success(self):
        exec_r = _exec(success=True, run_id="repair-run")
        sandbox = MockSandbox(results=[exec_r])
        loop, _ = _make_loop([_FENCED_CODE], sandbox)
        result = loop.run("a box", "bad code", "err")
        assert result.final_exec_result is not None
        assert result.final_exec_result.success is True


# ── Exhausted repair ──────────────────────────────────────────────────────────


class TestRepairLoopExhausted:
    def test_repaired_false_when_all_attempts_fail(self):
        sandbox = MockSandbox(results=[_exec(success=False, exception="err")] * 3)
        loop, _ = _make_loop([_FENCED_CODE] * 3, sandbox, max_iterations=3)
        result = loop.run("a box", "bad code", "SomeError")
        assert result.repaired is False

    def test_iterations_equals_max_when_all_fail(self):
        sandbox = MockSandbox(results=[_exec(success=False, exception="err")] * 2)
        loop, _ = _make_loop([_FENCED_CODE] * 2, sandbox, max_iterations=2)
        result = loop.run("a box", "bad code", "SomeError")
        assert result.iterations == 2

    def test_history_has_entry_per_attempt(self):
        sandbox = MockSandbox(results=[_exec(success=False, exception="err")] * 3)
        loop, _ = _make_loop([_FENCED_CODE] * 3, sandbox, max_iterations=3)
        result = loop.run("a box", "bad code", "SomeError")
        assert len(result.history) == 3

    def test_final_exec_result_populated_on_exhaustion(self):
        sandbox = MockSandbox(results=[_exec(success=False, exception="err")] * 1)
        loop, _ = _make_loop([_FENCED_CODE], sandbox, max_iterations=1)
        result = loop.run("a box", "bad code", "err")
        assert result.final_exec_result is not None


# ── LLM interaction ───────────────────────────────────────────────────────────


class TestRepairLoopLLMCalls:
    def test_llm_called_once_per_attempt(self):
        sandbox = MockSandbox(results=[_exec(success=False, exception="err")] * 2)
        loop, llm = _make_loop([_FENCED_CODE] * 2, sandbox, max_iterations=2)
        loop.run("a box", "bad code", "SomeError")
        assert llm.call_count == 2

    def test_original_error_passed_to_first_llm_call(self):
        sandbox = MockSandbox(results=[_exec(success=True)])
        loop, llm = _make_loop([_FENCED_CODE], sandbox)
        loop.run("a box", "bad code", "MySpecificError")
        first_user_prompt, _ = llm.calls[0]
        assert "MySpecificError" in first_user_prompt

    def test_execution_error_passed_to_next_llm_call(self):
        err_msg = "NameError: build_model not found"
        sandbox = MockSandbox(results=[
            _exec(success=False, exception=err_msg),
            _exec(success=True),
        ])
        loop, llm = _make_loop([_FENCED_CODE, _FENCED_CODE], sandbox, max_iterations=2)
        loop.run("a box", "bad code", "initial error")
        second_user_prompt, _ = llm.calls[1]
        assert err_msg in second_user_prompt

    def test_original_prompt_in_every_llm_call(self):
        sandbox = MockSandbox(results=[_exec(success=False, exception="e"), _exec(success=True)])
        loop, llm = _make_loop([_FENCED_CODE, _FENCED_CODE], sandbox, max_iterations=2)
        loop.run("a mounting bracket", "bad code", "err")
        for user_prompt, _ in llm.calls:
            assert "a mounting bracket" in user_prompt


# ── With geometry validator ───────────────────────────────────────────────────


class TestRepairLoopWithValidator:
    def test_accepts_execution_with_valid_geometry(self):
        exec_r = _exec(success=True, validation_metrics=_VALID_METRICS)
        sandbox = MockSandbox(results=[exec_r])
        loop, _ = _make_loop([_FENCED_CODE], sandbox, validator=GeometryValidator())
        result = loop.run("a box", "bad code", "err")
        assert result.repaired is True

    def test_rejects_execution_with_invalid_geometry(self):
        exec_invalid = _exec(success=True, validation_metrics=_INVALID_METRICS)
        exec_valid = _exec(success=True, validation_metrics=_VALID_METRICS)
        sandbox = MockSandbox(results=[exec_invalid, exec_valid])
        loop, _ = _make_loop([_FENCED_CODE, _FENCED_CODE], sandbox, validator=GeometryValidator(), max_iterations=3)
        result = loop.run("a box", "bad code", "err")
        assert result.repaired is True
        assert result.iterations == 2

    def test_geometry_error_passed_to_next_llm_call(self):
        exec_invalid = _exec(success=True, validation_metrics=_INVALID_METRICS)
        exec_valid = _exec(success=True, validation_metrics=_VALID_METRICS)
        sandbox = MockSandbox(results=[exec_invalid, exec_valid])
        loop, llm = _make_loop([_FENCED_CODE, _FENCED_CODE], sandbox, validator=GeometryValidator(), max_iterations=3)
        loop.run("a box", "bad code", "err")
        second_user_prompt, _ = llm.calls[1]
        assert "isValid" in second_user_prompt or "valid" in second_user_prompt.lower()

    def test_validation_stored_in_attempt_history(self):
        exec_r = _exec(success=True, validation_metrics=_VALID_METRICS)
        sandbox = MockSandbox(results=[exec_r])
        loop, _ = _make_loop([_FENCED_CODE], sandbox, validator=GeometryValidator())
        result = loop.run("a box", "bad code", "err")
        assert result.history[0].validation is not None
        assert result.history[0].validation.valid is True

    def test_no_validation_when_execution_fails(self):
        exec_r = _exec(success=False, exception="err")
        sandbox = MockSandbox(results=[exec_r])
        loop, _ = _make_loop([_FENCED_CODE], sandbox, validator=GeometryValidator(), max_iterations=1)
        result = loop.run("a box", "bad code", "err")
        assert result.history[0].validation is None
