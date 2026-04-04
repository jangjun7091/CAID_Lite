"""Tests for CADPipeline (Phase 0–2).

All tests inject MockLLMBackend + MockSandbox — no API key or CadQuery
installation required.  Integration tests that exercise a real sandbox live
in tests/integration/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caid_lite.executor.result import ExecutionResult
from caid_lite.pipeline import CADPipeline, PipelineResult
from tests.fixtures.mock_llm import MockLLMBackend, make_mock_with_valid_code
from tests.fixtures.mock_sandbox import MockSandbox, make_success_sandbox, make_failure_sandbox


# ── Code fixtures ─────────────────────────────────────────────────────────────
# All examples follow the build_model() contract required from Phase 2.

_FENCED_CODE = """\
```python
import cadquery as cq


def build_model():
    width = 10.0
    return cq.Workplane("XY").box(width, width, width)
```"""

_PLAIN_CODE = (
    "import cadquery as cq\n\n"
    "def build_model():\n"
    "    return cq.Workplane('XY').box(1, 1, 1)\n"
)


# ── Shared fixture helpers ────────────────────────────────────────────────────


def _make_pipeline(
    llm_responses: list[str] | None = None,
    sandbox: MockSandbox | None = None,
) -> CADPipeline:
    llm = MockLLMBackend(responses=llm_responses or [_FENCED_CODE])
    sb = sandbox if sandbox is not None else make_success_sandbox()
    return CADPipeline(llm=llm, sandbox=sb)


# ── PipelineResult ────────────────────────────────────────────────────────────


class TestPipelineResult:
    def test_to_dict_contains_required_keys(self):
        r = PipelineResult(
            run_id="abc-123",
            success=True,
            prompt="test",
            generated_code="code",
            elapsed_s=1.0,
        )
        d = r.to_dict()
        for key in ("run_id", "success", "prompt", "generated_code", "elapsed_s"):
            assert key in d

    def test_to_dict_exports_as_strings(self):
        p = Path("outputs") / "abc" / "output.step"
        r = PipelineResult(
            run_id="x", success=True, prompt="p",
            generated_code="c", elapsed_s=0.1, exports={"step": p},
        )
        assert r.to_dict()["exports"]["step"] == str(p)

    def test_to_dict_execution_is_none_when_not_set(self):
        r = PipelineResult(
            run_id="x", success=True, prompt="p",
            generated_code="c", elapsed_s=0.1,
        )
        assert r.to_dict()["execution"] is None

    def test_to_dict_execution_is_dict_when_set(self):
        exec_r = ExecutionResult(
            run_id="x", success=True, stdout="", stderr="",
            exception=None, exports={}, elapsed_s=0.1,
        )
        r = PipelineResult(
            run_id="x", success=True, prompt="p",
            generated_code="c", elapsed_s=0.1, execution=exec_r,
        )
        assert isinstance(r.to_dict()["execution"], dict)


# ── CADPipeline construction ──────────────────────────────────────────────────


class TestCADPipelineConstruction:
    def test_default_sandbox_created_when_none(self):
        from caid_lite.executor.sandbox import Sandbox
        llm = MockLLMBackend(responses=[_FENCED_CODE])
        pipeline = CADPipeline(llm=llm)
        assert isinstance(pipeline._sandbox, Sandbox)

    def test_injected_sandbox_is_used(self):
        sandbox = make_success_sandbox()
        pipeline = _make_pipeline(sandbox=sandbox)
        pipeline.run("test")
        assert sandbox.call_count == 1


# ── CADPipeline.run — LLM interaction ────────────────────────────────────────


class TestCADPipelineRunLLM:
    def test_returns_pipeline_result_instance(self):
        result = _make_pipeline().run("a 10mm cube")
        assert isinstance(result, PipelineResult)

    def test_result_prompt_matches_input(self):
        result = _make_pipeline().run("a 10mm cube")
        assert result.prompt == "a 10mm cube"

    def test_result_has_non_empty_run_id(self):
        result = _make_pipeline().run("test")
        assert result.run_id and len(result.run_id) > 8

    def test_run_ids_are_unique_across_calls(self):
        llm = MockLLMBackend(responses=[_FENCED_CODE, _FENCED_CODE])
        sb = MockSandbox(results=[
            ExecutionResult(run_id="r1", success=True, stdout="", stderr="",
                            exception=None, exports={}, elapsed_s=0.01),
            ExecutionResult(run_id="r2", success=True, stdout="", stderr="",
                            exception=None, exports={}, elapsed_s=0.01),
        ])
        pipeline = CADPipeline(llm=llm, sandbox=sb)
        r1 = pipeline.run("p1")
        r2 = pipeline.run("p2")
        assert r1.run_id != r2.run_id

    def test_llm_called_exactly_once_per_run(self):
        llm = MockLLMBackend(responses=[_FENCED_CODE])
        pipeline = CADPipeline(llm=llm, sandbox=make_success_sandbox())
        pipeline.run("test")
        assert llm.call_count == 1

    def test_llm_user_prompt_contains_description(self):
        llm = MockLLMBackend(responses=[_FENCED_CODE])
        pipeline = CADPipeline(llm=llm, sandbox=make_success_sandbox())
        pipeline.run("a bracket with M4 holes")
        user_prompt, _ = llm.calls[0]
        assert "a bracket with M4 holes" in user_prompt

    def test_generated_code_has_fences_stripped(self):
        result = _make_pipeline(llm_responses=[_FENCED_CODE]).run("test")
        assert "```" not in result.generated_code
        assert "import cadquery" in result.generated_code

    def test_elapsed_s_is_non_negative(self):
        result = _make_pipeline().run("test")
        assert result.elapsed_s >= 0.0


# ── CADPipeline.run — executor integration ────────────────────────────────────


class TestCADPipelineRunExecutor:
    def test_sandbox_receives_extracted_code(self):
        sandbox = make_success_sandbox()
        _make_pipeline(sandbox=sandbox).run("test")
        executed_code, _ = sandbox.calls[0]
        assert "```" not in executed_code  # fences stripped before calling sandbox
        assert "build_model" in executed_code

    def test_sandbox_called_once_per_run(self):
        sandbox = make_success_sandbox()
        _make_pipeline(sandbox=sandbox).run("test")
        assert sandbox.call_count == 1

    def test_success_reflects_sandbox_result(self):
        result = _make_pipeline(sandbox=make_success_sandbox()).run("test")
        assert result.success is True

    def test_failure_reflects_sandbox_result(self):
        result = _make_pipeline(
            sandbox=make_failure_sandbox("NameError: build_model")
        ).run("test")
        assert result.success is False

    def test_error_is_none_on_success(self):
        result = _make_pipeline(sandbox=make_success_sandbox()).run("test")
        assert result.error is None

    def test_error_contains_exception_on_failure(self):
        result = _make_pipeline(
            sandbox=make_failure_sandbox("some exec error")
        ).run("test")
        assert result.error == "some exec error"

    def test_exports_propagated_from_sandbox(self):
        step = Path("outputs") / "run1" / "output.step"
        sandbox = make_success_sandbox(exports={"step": step})
        result = _make_pipeline(sandbox=sandbox).run("test")
        assert result.exports["step"] == step

    def test_execution_field_populated(self):
        result = _make_pipeline(sandbox=make_success_sandbox()).run("test")
        assert result.execution is not None
        assert isinstance(result.execution, ExecutionResult)

    def test_timed_out_propagated_from_sandbox(self):
        result = _make_pipeline(
            sandbox=make_failure_sandbox(
                exception="Execution timed out after 60.0s.",
                timed_out=True,
            )
        ).run("test")
        assert result.execution.timed_out is True


# ── CADPipeline._extract_code ─────────────────────────────────────────────────


class TestExtractCode:
    def test_strips_python_fenced_block(self):
        fenced = "```python\ndef build_model(): pass\n```"
        assert CADPipeline._extract_code(fenced) == "def build_model(): pass"

    def test_strips_plain_fenced_block(self):
        fenced = "```\ndef build_model(): pass\n```"
        assert CADPipeline._extract_code(fenced) == "def build_model(): pass"

    def test_returns_plain_code_unchanged(self):
        code = "def build_model(): pass"
        assert CADPipeline._extract_code(code) == code

    def test_multiline_code_preserved(self):
        inner = (
            "import cadquery as cq\n\n"
            "def build_model():\n"
            "    return cq.Workplane('XY').box(1, 1, 1)"
        )
        assert CADPipeline._extract_code(f"```python\n{inner}\n```") == inner

    def test_first_block_wins_when_multiple_present(self):
        response = (
            "```python\nfirst = True\n```\n\n"
            "```python\nsecond = True\n```"
        )
        result = CADPipeline._extract_code(response)
        assert "first" in result
        assert "second" not in result

    def test_strips_surrounding_whitespace(self):
        fenced = "```python\n   def build_model(): pass   \n```"
        assert CADPipeline._extract_code(fenced) == "def build_model(): pass"

    def test_handles_empty_response(self):
        assert CADPipeline._extract_code("") == ""

    def test_handles_response_with_preamble(self):
        response = "Here is your code:\n\n```python\ndef build_model(): pass\n```"
        assert CADPipeline._extract_code(response) == "def build_model(): pass"


# ── CADPipeline Phase 3 — validation ─────────────────────────────────────────


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


def _exec_result(success=True, exception=None, validation_metrics=None):
    return ExecutionResult(
        run_id="mock",
        success=success,
        stdout="",
        stderr="",
        exception=exception,
        exports={},
        elapsed_s=0.01,
        validation_metrics=validation_metrics,
    )


class TestCADPipelineValidation:
    def test_validation_populated_when_validator_present(self):
        from caid_lite.validator.geometry import GeometryValidator
        sandbox = MockSandbox(results=[_exec_result(validation_metrics=_VALID_METRICS)])
        pipeline = CADPipeline(
            llm=MockLLMBackend(responses=[_FENCED_CODE]),
            sandbox=sandbox,
            validator=GeometryValidator(),
        )
        result = pipeline.run("test")
        assert result.validation is not None
        assert result.validation.valid is True

    def test_validation_none_when_no_validator(self):
        result = _make_pipeline(sandbox=make_success_sandbox()).run("test")
        assert result.validation is None

    def test_geometry_failure_sets_success_false(self):
        from caid_lite.validator.geometry import GeometryValidator
        sandbox = MockSandbox(results=[_exec_result(validation_metrics=_INVALID_METRICS)])
        pipeline = CADPipeline(
            llm=MockLLMBackend(responses=[_FENCED_CODE]),
            sandbox=sandbox,
            validator=GeometryValidator(),
        )
        result = pipeline.run("test")
        assert result.success is False

    def test_geometry_failure_error_is_descriptive(self):
        from caid_lite.validator.geometry import GeometryValidator
        sandbox = MockSandbox(results=[_exec_result(validation_metrics=_INVALID_METRICS)])
        pipeline = CADPipeline(
            llm=MockLLMBackend(responses=[_FENCED_CODE]),
            sandbox=sandbox,
            validator=GeometryValidator(),
        )
        result = pipeline.run("test")
        assert result.error is not None
        assert len(result.error) > 10

    def test_validation_in_to_dict(self):
        from caid_lite.validator.geometry import GeometryValidator
        sandbox = MockSandbox(results=[_exec_result(validation_metrics=_VALID_METRICS)])
        pipeline = CADPipeline(
            llm=MockLLMBackend(responses=[_FENCED_CODE]),
            sandbox=sandbox,
            validator=GeometryValidator(),
        )
        result = pipeline.run("test")
        d = result.to_dict()
        assert "validation" in d
        assert isinstance(d["validation"], dict)


# ── CADPipeline Phase 3 — repair ──────────────────────────────────────────────


class TestCADPipelineRepair:
    def test_repair_triggered_on_execution_failure(self):
        from caid_lite.repair.loop import RepairLoop
        initial_sandbox = MockSandbox(results=[_exec_result(success=False, exception="err")])
        repair_sandbox = MockSandbox(results=[_exec_result(success=True)])
        llm = MockLLMBackend(responses=[_FENCED_CODE, _FENCED_CODE])
        repair_loop = RepairLoop(llm=llm, sandbox=repair_sandbox, max_iterations=1)
        pipeline = CADPipeline(llm=llm, sandbox=initial_sandbox, repair_loop=repair_loop)
        result = pipeline.run("test")
        assert result.success is True
        assert result.repair is not None
        assert result.repair["repaired"] is True

    def test_repair_triggered_on_validation_failure(self):
        from caid_lite.repair.loop import RepairLoop
        from caid_lite.validator.geometry import GeometryValidator
        initial_sandbox = MockSandbox(results=[_exec_result(validation_metrics=_INVALID_METRICS)])
        repair_sandbox = MockSandbox(results=[_exec_result(validation_metrics=_VALID_METRICS)])
        llm = MockLLMBackend(responses=[_FENCED_CODE, _FENCED_CODE])
        validator = GeometryValidator()
        repair_loop = RepairLoop(llm=llm, sandbox=repair_sandbox, validator=validator, max_iterations=1)
        pipeline = CADPipeline(llm=llm, sandbox=initial_sandbox, validator=validator, repair_loop=repair_loop)
        result = pipeline.run("test")
        assert result.success is True
        assert result.repair["repaired"] is True

    def test_no_repair_when_loop_not_injected(self):
        result = _make_pipeline(
            sandbox=make_failure_sandbox("some error")
        ).run("test")
        assert result.success is False
        assert result.repair is None

    def test_repair_dict_in_to_dict_when_triggered(self):
        from caid_lite.repair.loop import RepairLoop
        initial_sandbox = MockSandbox(results=[_exec_result(success=False, exception="err")])
        repair_sandbox = MockSandbox(results=[_exec_result(success=True)])
        llm = MockLLMBackend(responses=[_FENCED_CODE, _FENCED_CODE])
        repair_loop = RepairLoop(llm=llm, sandbox=repair_sandbox, max_iterations=1)
        pipeline = CADPipeline(llm=llm, sandbox=initial_sandbox, repair_loop=repair_loop)
        result = pipeline.run("test")
        d = result.to_dict()
        assert isinstance(d["repair"], dict)
        assert "history" in d["repair"]

    def test_repair_exhausted_result_is_failure(self):
        from caid_lite.repair.loop import RepairLoop
        initial_sandbox = MockSandbox(results=[_exec_result(success=False, exception="err")])
        repair_sandbox = MockSandbox(results=[_exec_result(success=False, exception="still broken")] * 2)
        llm = MockLLMBackend(responses=[_FENCED_CODE] * 3)
        repair_loop = RepairLoop(llm=llm, sandbox=repair_sandbox, max_iterations=2)
        pipeline = CADPipeline(llm=llm, sandbox=initial_sandbox, repair_loop=repair_loop)
        result = pipeline.run("test")
        assert result.success is False
        assert result.repair["repaired"] is False


# -- CADPipeline multi-agent path ---------------------------------------------


class TestCADPipelineMultiAgent:
    """Tests for the 4-agent (Architect+PatternSelector+Designer+Critic) path."""

    def _make_multi_agent_pipeline(
        self,
        architect_response: str,
        designer_response: str,
        critic_response: str,
        sandbox: "MockSandbox | None" = None,
    ) -> CADPipeline:
        from caid_lite.agents.architect import ArchitectAgent
        from caid_lite.agents.critic import CriticAgent
        from caid_lite.agents.designer import DesignerAgent
        from caid_lite.agents.pattern_selector import PatternSelector

        # Each agent gets its own LLM mock so call counts are isolated.
        architect_llm = MockLLMBackend(responses=[architect_response])
        designer_llm = MockLLMBackend(responses=[designer_response])
        critic_llm = MockLLMBackend(responses=[critic_response])

        return CADPipeline(
            llm=MockLLMBackend(responses=[designer_response]),  # fallback LLM (unused in multi-agent)
            sandbox=sandbox or make_success_sandbox(),
            architect=ArchitectAgent(llm=architect_llm),
            pattern_selector=PatternSelector(),
            designer=DesignerAgent(llm=designer_llm),
            critic=CriticAgent(llm=critic_llm),
        )

    _PLAN_JSON = json.dumps({
        "features": ["rectangular plate"],
        "geometry_type": "plate",
        "constraints": {"width_mm": 50},
        "notes": "",
    })

    def test_multi_agent_result_success(self):
        result = self._make_multi_agent_pipeline(
            architect_response=self._PLAN_JSON,
            designer_response=_FENCED_CODE,
            critic_response="APPROVED",
        ).run("a 50mm plate")
        assert result.success is True

    def test_design_plan_populated_in_result(self):
        result = self._make_multi_agent_pipeline(
            architect_response=self._PLAN_JSON,
            designer_response=_FENCED_CODE,
            critic_response="APPROVED",
        ).run("a plate")
        assert result.design_plan is not None
        assert result.design_plan["geometry_type"] == "plate"

    def test_critic_dict_populated_in_result(self):
        result = self._make_multi_agent_pipeline(
            architect_response=self._PLAN_JSON,
            designer_response=_FENCED_CODE,
            critic_response="APPROVED",
        ).run("a plate")
        assert result.critic is not None
        assert result.critic["approved"] is True

    def test_critic_revised_code_is_used(self):
        revised = (
            "import cadquery as cq\n\n"
            "def build_model():\n"
            "    return cq.Workplane('XY').box(60.0, 40.0, 8.0)\n"
        )
        critic_response = f"ISSUES: wrong size\n```python\n{revised}\n```"
        sandbox = make_success_sandbox()
        result = self._make_multi_agent_pipeline(
            architect_response=self._PLAN_JSON,
            designer_response=_FENCED_CODE,
            critic_response=critic_response,
            sandbox=sandbox,
        ).run("a 60mm plate")
        # The sandbox should have been called with the revised code
        executed_code, _ = sandbox.calls[0]
        assert "60.0" in executed_code

    def test_fallback_path_used_when_agents_absent(self):
        """Pipeline with no agents uses single-LLM path (existing behaviour)."""
        result = _make_pipeline(llm_responses=[_FENCED_CODE]).run("a cube")
        assert result.success is True
        assert result.design_plan is None
        assert result.critic is None
