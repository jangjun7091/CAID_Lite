"""MockSandbox: deterministic fake executor for pipeline unit tests.

Because ``CADPipeline`` depends on ``Sandbox`` only through duck-typing (both
expose ``execute(code, run_id) -> ExecutionResult``), this mock can be
injected directly with no monkeypatching required.

Usage::

    from tests.fixtures.mock_sandbox import MockSandbox, make_success_sandbox
    from caid_lite.pipeline import CADPipeline
    from tests.fixtures.mock_llm import MockLLMBackend

    def test_pipeline_stores_exports():
        from pathlib import Path
        sandbox = make_success_sandbox(exports={"step": Path("out/a.step")})
        llm = MockLLMBackend(responses=["```python\\ndef build_model(): ...\\n```"])
        pipeline = CADPipeline(llm=llm, sandbox=sandbox)
        result = pipeline.run("a box")
        assert result.exports["step"] == Path("out/a.step")
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from caid_lite.executor.result import ExecutionResult


class MockSandbox:
    """Returns pre-set ``ExecutionResult`` responses in order.

    Args:
        results: Ordered list of ``ExecutionResult`` objects to return.
            Each call to ``execute()`` consumes the next entry.  If
            exhausted, ``AssertionError`` is raised immediately.

    Attributes:
        call_count: Total calls to ``execute()``.
        calls: ``[(code, run_id), ...]`` in call order, for assertion use.
    """

    def __init__(self, results: List[ExecutionResult]) -> None:
        if not results:
            raise ValueError("MockSandbox requires at least one ExecutionResult.")
        self._results_iter = iter(results)
        self.call_count: int = 0
        self.calls: List[Tuple[str, str]] = []

    # ------------------------------------------------------------------
    # Sandbox interface
    # ------------------------------------------------------------------

    def execute(self, code: str, run_id: str) -> ExecutionResult:
        self.call_count += 1
        self.calls.append((code, run_id))
        try:
            return next(self._results_iter)
        except StopIteration:
            raise AssertionError(
                f"MockSandbox ran out of results after {self.call_count} call(s). "
                "Add more ExecutionResult objects to the 'results' constructor argument."
            )

    def __repr__(self) -> str:
        return f"MockSandbox(calls_so_far={self.call_count})"


# ── Convenience factories ─────────────────────────────────────────────────────


def make_success_sandbox(
    exports: Optional[Dict[str, Path]] = None,
    run_id: str = "mock-run-id",
) -> MockSandbox:
    """Return a sandbox whose single result is a successful execution.

    Args:
        exports: Export paths to include in the result.  Defaults to empty
            (no files written) — sufficient for most pipeline unit tests.
        run_id: The ``run_id`` embedded in the returned ``ExecutionResult``.
    """
    return MockSandbox(
        results=[
            ExecutionResult(
                run_id=run_id,
                success=True,
                stdout='{"success": true, "exception": null, "exports": {}}',
                stderr="",
                exception=None,
                exports=exports or {},
                elapsed_s=0.01,
                timed_out=False,
            )
        ]
    )


def make_failure_sandbox(
    exception: str = "mock execution error",
    timed_out: bool = False,
    run_id: str = "mock-run-id",
) -> MockSandbox:
    """Return a sandbox whose single result is a failed execution."""
    return MockSandbox(
        results=[
            ExecutionResult(
                run_id=run_id,
                success=False,
                stdout="",
                stderr="",
                exception=exception,
                exports={},
                elapsed_s=0.01,
                timed_out=timed_out,
            )
        ]
    )
