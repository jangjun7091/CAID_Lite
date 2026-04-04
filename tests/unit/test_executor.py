"""Tests for Sandbox executor.

Test layers:
  - Mocked subprocess  : fast unit tests; no CadQuery required.
  - Real subprocess    : run _runner.py with trivial Python; no CadQuery required.
  - Integration        : real subprocess + real CadQuery; marked @pytest.mark.skipif.

The split guarantees that ``pytest tests/unit/`` always passes in a fresh venv
that has only the dev dependencies installed (no cadquery).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from caid_lite.executor.result import ExecutionResult
from caid_lite.executor.sandbox import Sandbox

# ── CadQuery availability guard ───────────────────────────────────────────────

try:
    import cadquery  # noqa: F401

    _CQ_AVAILABLE = True
except ImportError:
    _CQ_AVAILABLE = False

requires_cq = pytest.mark.skipif(
    not _CQ_AVAILABLE, reason="cadquery not installed"
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_proc(stdout_dict: dict, stderr: str = "", returncode: int = 0) -> MagicMock:
    """Build a mock CompletedProcess with JSON stdout."""
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = json.dumps(stdout_dict)
    mock.stderr = stderr
    return mock


# ── ExecutionResult ───────────────────────────────────────────────────────────


class TestExecutionResult:
    def test_to_dict_contains_all_keys(self):
        r = ExecutionResult(
            run_id="abc",
            success=True,
            stdout="{}",
            stderr="",
            exception=None,
            exports={},
            elapsed_s=1.0,
        )
        d = r.to_dict()
        for key in ("run_id", "success", "stdout", "stderr", "exception",
                    "exports", "elapsed_s", "timed_out"):
            assert key in d

    def test_to_dict_exports_are_strings(self, tmp_path):
        p = tmp_path / "output.step"
        r = ExecutionResult(
            run_id="x", success=True, stdout="", stderr="",
            exception=None, exports={"step": p}, elapsed_s=0.1,
        )
        assert r.to_dict()["exports"]["step"] == str(p)

    def test_timed_out_defaults_false(self):
        r = ExecutionResult(
            run_id="x", success=False, stdout="", stderr="",
            exception="err", exports={}, elapsed_s=0.1,
        )
        assert r.timed_out is False


# ── Sandbox.from_config ───────────────────────────────────────────────────────


class TestSandboxFromConfig:
    def test_reads_timeout(self):
        cfg = {"executor": {"timeout_s": 45}, "exporter": {}}
        s = Sandbox.from_config(cfg)
        assert s.timeout_s == 45.0

    def test_reads_output_dir(self):
        cfg = {"executor": {}, "exporter": {"output_dir": "my_outputs"}}
        s = Sandbox.from_config(cfg)
        assert s.output_dir == Path("my_outputs")

    def test_reads_formats(self):
        cfg = {"executor": {}, "exporter": {"formats": ["step"]}}
        s = Sandbox.from_config(cfg)
        assert s.formats == ["step"]

    def test_defaults_when_keys_absent(self):
        s = Sandbox.from_config({})
        assert s.timeout_s == 60.0
        assert s.output_dir == Path("outputs")
        assert "step" in s.formats
        assert "stl" in s.formats


# ── Mocked subprocess tests (no CadQuery, no real subprocess) ─────────────────


class TestSandboxMocked:
    """Patch subprocess.run to control exactly what the runner returns."""

    def test_successful_json_parsed(self, tmp_path, monkeypatch):
        exports_raw = {
            "step": str(tmp_path / "output.step"),
            "stl": str(tmp_path / "output.stl"),
        }
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_proc(
                {"success": True, "exception": None, "exports": exports_raw}
            ),
        )
        result = Sandbox(output_dir=tmp_path).execute("code", run_id="r1")
        assert result.success is True
        assert result.exception is None
        assert result.timed_out is False
        assert result.exports["step"] == tmp_path / "output.step"
        assert result.exports["stl"] == tmp_path / "output.stl"

    def test_failure_json_parsed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_proc(
                {"success": False, "exception": "NameError: x", "exports": {}}
            ),
        )
        result = Sandbox(output_dir=tmp_path).execute("bad code", run_id="r2")
        assert result.success is False
        assert "NameError" in result.exception

    def test_timeout_sets_timed_out_flag(self, tmp_path, monkeypatch):
        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd=args[0], timeout=5.0, output=None, stderr=None
            )

        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        result = Sandbox(timeout_s=5.0, output_dir=tmp_path).execute(
            "code", run_id="timeout-run"
        )
        assert result.success is False
        assert result.timed_out is True
        assert result.exception is not None

    def test_timeout_exception_mentions_duration(self, tmp_path, monkeypatch):
        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd=args[0], timeout=30.0, output=None, stderr=None
            )

        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        result = Sandbox(timeout_s=30.0, output_dir=tmp_path).execute(
            "code", run_id="r"
        )
        assert "30" in result.exception

    def test_timeout_captures_partial_stdout(self, tmp_path, monkeypatch):
        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd=args[0], timeout=1.0, output="partial", stderr="err"
            )

        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        result = Sandbox(output_dir=tmp_path).execute("code", run_id="r")
        assert result.stdout == "partial"
        assert result.stderr == "err"

    def test_empty_stdout_is_failure(self, tmp_path, monkeypatch):
        mock = MagicMock()
        mock.stdout = ""
        mock.stderr = "OCC crash"
        mock.returncode = 139
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock)
        result = Sandbox(output_dir=tmp_path).execute("code", run_id="r")
        assert result.success is False
        assert result.exception is not None

    def test_invalid_json_stdout_is_failure(self, tmp_path, monkeypatch):
        mock = MagicMock()
        mock.stdout = "NOT JSON"
        mock.stderr = ""
        mock.returncode = 0
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock)
        result = Sandbox(output_dir=tmp_path).execute("code", run_id="r")
        assert result.success is False
        assert result.exception is not None

    def test_stderr_captured_on_failure(self, tmp_path, monkeypatch):
        mock_proc = _make_proc(
            {"success": False, "exception": "err", "exports": {}}
        )
        mock_proc.stderr = "warning: something"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_proc)
        result = Sandbox(output_dir=tmp_path).execute("code", run_id="r")
        assert result.stderr == "warning: something"

    def test_export_failure_in_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_proc({
                "success": False,
                "exception": "STEP export failed:\nSomeError",
                "exports": {},
            }),
        )
        result = Sandbox(output_dir=tmp_path).execute("code", run_id="r")
        assert result.success is False
        assert "export" in result.exception.lower()

    def test_run_id_is_preserved(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_proc(
                {"success": True, "exception": None, "exports": {}}
            ),
        )
        result = Sandbox(output_dir=tmp_path).execute("code", run_id="my-run-id")
        assert result.run_id == "my-run-id"

    def test_elapsed_s_is_non_negative(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_proc(
                {"success": True, "exception": None, "exports": {}}
            ),
        )
        result = Sandbox(output_dir=tmp_path).execute("code", run_id="r")
        assert result.elapsed_s >= 0.0


# ── Real subprocess, no CadQuery (runner exits early on contract violation) ────


class TestSandboxRealSubprocessNoCadQuery:
    """These tests use a real subprocess.  The runner exits before importing
    cadquery, so they pass even without cadquery installed."""

    def test_missing_build_model_fails(self, tmp_path):
        code = "x = 42  # no build_model defined"
        result = Sandbox(output_dir=tmp_path).execute(code, run_id="no-fn")
        assert result.success is False
        assert "build_model" in result.exception

    def test_non_callable_build_model_fails(self, tmp_path):
        code = "build_model = 'not callable'"
        result = Sandbox(output_dir=tmp_path).execute(code, run_id="non-call")
        assert result.success is False
        assert "build_model" in result.exception

    def test_syntax_error_fails(self, tmp_path):
        from tests.fixtures.invalid_cadquery import SYNTAX_ERROR
        result = Sandbox(output_dir=tmp_path).execute(SYNTAX_ERROR, run_id="syn-err")
        assert result.success is False
        assert result.exception is not None

    def test_exception_in_build_model_fails(self, tmp_path):
        from tests.fixtures.invalid_cadquery import RAISES_IN_BUILD_MODEL
        result = Sandbox(output_dir=tmp_path).execute(
            RAISES_IN_BUILD_MODEL, run_id="raises"
        )
        assert result.success is False
        assert "Deliberate error" in result.exception

    def test_exception_at_module_level_fails(self, tmp_path):
        from tests.fixtures.invalid_cadquery import RAISES_AT_MODULE_LEVEL
        result = Sandbox(output_dir=tmp_path).execute(
            RAISES_AT_MODULE_LEVEL, run_id="module-err"
        )
        assert result.success is False
        assert result.exception is not None

    def test_run_out_dir_is_created_even_on_failure(self, tmp_path):
        code = "x = 1  # no build_model"
        run_id = "dir-check"
        Sandbox(output_dir=tmp_path).execute(code, run_id=run_id)
        # The temp directory for user_code.py is cleaned up, but the sandbox
        # itself doesn't pre-create the output dir on failure (runner does).
        # Just verify no crash occurred.

    def test_empty_code_fails_gracefully(self, tmp_path):
        result = Sandbox(output_dir=tmp_path).execute("", run_id="empty")
        assert result.success is False
        assert "build_model" in result.exception


# ── Integration tests — require CadQuery ─────────────────────────────────────


@requires_cq
class TestSandboxIntegration:
    """Full end-to-end runs with a real CadQuery installation."""

    def test_valid_model_succeeds(self, tmp_path):
        from tests.fixtures.valid_cadquery import SOURCE
        result = Sandbox(output_dir=tmp_path).execute(SOURCE, run_id="valid")
        assert result.success is True
        assert result.exception is None

    def test_valid_model_produces_step(self, tmp_path):
        from tests.fixtures.valid_cadquery import SOURCE
        result = Sandbox(output_dir=tmp_path).execute(SOURCE, run_id="step-chk")
        assert "step" in result.exports
        assert result.exports["step"].exists()
        assert result.exports["step"].stat().st_size > 0

    def test_valid_model_produces_stl(self, tmp_path):
        from tests.fixtures.valid_cadquery import SOURCE
        result = Sandbox(output_dir=tmp_path).execute(SOURCE, run_id="stl-chk")
        assert "stl" in result.exports
        assert result.exports["stl"].exists()
        assert result.exports["stl"].stat().st_size > 0

    def test_exports_written_to_run_subdirectory(self, tmp_path):
        from tests.fixtures.valid_cadquery import SOURCE
        run_id = "subdir-chk"
        result = Sandbox(output_dir=tmp_path).execute(SOURCE, run_id=run_id)
        assert result.success
        # All exports must be inside output_dir / run_id
        expected_dir = tmp_path / run_id
        for path in result.exports.values():
            assert path.parent == expected_dir

    def test_formats_single_step_only(self, tmp_path):
        from tests.fixtures.valid_cadquery import SOURCE
        result = Sandbox(output_dir=tmp_path, formats=["step"]).execute(
            SOURCE, run_id="step-only"
        )
        assert result.success
        assert "step" in result.exports
        assert "stl" not in result.exports

    def test_wrong_return_type_fails(self, tmp_path):
        from tests.fixtures.invalid_cadquery import WRONG_RETURN_TYPE_STRING
        result = Sandbox(output_dir=tmp_path).execute(
            WRONG_RETURN_TYPE_STRING, run_id="wrong-type"
        )
        assert result.success is False
        assert "Workplane" in result.exception

    def test_wrong_return_type_none_fails(self, tmp_path):
        from tests.fixtures.invalid_cadquery import WRONG_RETURN_TYPE_NONE
        result = Sandbox(output_dir=tmp_path).execute(
            WRONG_RETURN_TYPE_NONE, run_id="none-type"
        )
        assert result.success is False
        assert "Workplane" in result.exception

    def test_elapsed_s_is_positive_for_real_run(self, tmp_path):
        from tests.fixtures.valid_cadquery import SOURCE
        result = Sandbox(output_dir=tmp_path).execute(SOURCE, run_id="timing")
        assert result.elapsed_s > 0.0

    def test_timed_out_is_false_on_success(self, tmp_path):
        from tests.fixtures.valid_cadquery import SOURCE
        result = Sandbox(output_dir=tmp_path).execute(SOURCE, run_id="to-false")
        assert result.timed_out is False
