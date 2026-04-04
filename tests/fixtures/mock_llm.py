"""MockLLMBackend: deterministic fake for offline pipeline testing.

Because ``CADPipeline`` and ``RepairLoop`` depend only on the ``LLMBackend``
protocol, this mock can be injected directly — no monkeypatching required.

Usage::

    from tests.fixtures.mock_llm import MockLLMBackend
    from caid_lite.pipeline import CADPipeline

    CODE = \"\"\"
    ```python
    import cadquery as cq
    result = cq.Workplane("XY").box(10, 10, 10)
    ```
    \"\"\"

    def test_pipeline_calls_llm_once():
        llm = MockLLMBackend(responses=[CODE])
        pipeline = CADPipeline(llm=llm)
        result = pipeline.run("a 10mm cube")
        assert llm.call_count == 1
        assert "import cadquery" in result.generated_code
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import List, Tuple


class MockLLMBackend:
    """Returns pre-set string responses in order, one per ``generate()`` call.

    Args:
        responses: Ordered list of strings the mock will return.  Each call
            to ``generate()`` consumes the next item.  If the list is
            exhausted an ``AssertionError`` is raised immediately, which makes
            missing-response bugs obvious in test output.

    Attributes:
        call_count: Total number of times ``generate()`` has been called.
        calls: List of ``(user_prompt, system_prompt)`` tuples in call order,
            useful for asserting that the correct prompts were sent.
    """

    def __init__(self, responses: List[str]) -> None:
        if not responses:
            raise ValueError("MockLLMBackend requires at least one response.")
        self._responses: Iterator[str] = iter(responses)
        self.call_count: int = 0
        self.calls: List[Tuple[str, str]] = []

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        """Return the next pre-set response.

        Args:
            user_prompt: Recorded in ``self.calls`` for assertion use.
            system_prompt: Recorded in ``self.calls`` for assertion use.

        Returns:
            The next string from the ``responses`` list.

        Raises:
            AssertionError: If all responses have been consumed.
        """
        self.call_count += 1
        self.calls.append((user_prompt, system_prompt))
        try:
            return next(self._responses)
        except StopIteration:
            raise AssertionError(
                f"MockLLMBackend ran out of responses after {self.call_count} call(s). "
                "Add more strings to the 'responses' constructor argument."
            )

    def __repr__(self) -> str:
        return f"MockLLMBackend(calls_so_far={self.call_count})"


# ── Convenience factory functions ─────────────────────────────────────────────


def make_mock_with_valid_code(code: str | None = None) -> MockLLMBackend:
    """Return a mock that yields a single well-formed CadQuery response.

    Args:
        code: Optional custom CadQuery source.  Defaults to a minimal valid
            box geometry.

    Returns:
        ``MockLLMBackend`` pre-loaded with one fenced Python code block.
    """
    if code is None:
        code = (
            "import cadquery as cq\n\n"
            "result = cq.Workplane('XY').box(10.0, 10.0, 10.0)\n"
        )
    return MockLLMBackend(responses=[f"```python\n{code}\n```"])


def make_mock_failing_then_valid(
    error_response: str, valid_code: str | None = None
) -> MockLLMBackend:
    """Return a mock that fails once then succeeds — for repair loop tests.

    Args:
        error_response: The first (broken) code response.
        valid_code: Optional valid code for the second response.

    Returns:
        ``MockLLMBackend`` with two responses: broken then valid.
    """
    second = valid_code or (
        "import cadquery as cq\n"
        "result = cq.Workplane('XY').box(10.0, 10.0, 10.0)\n"
    )
    return MockLLMBackend(responses=[error_response, f"```python\n{second}\n```"])
