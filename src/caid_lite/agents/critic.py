"""CriticAgent: reviews generated CadQuery code before execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..llm.base import LLMBackend
from ..llm.prompts import PromptBuilder
from ..logging.logger import get_logger
from .base import CriticResult, DesignPlan

_log = get_logger(__name__)

_DEFAULT_SYSTEM = """\
You are a CadQuery code reviewer. Review the provided code against the design
plan and identify any issues.

If the code is correct, respond with:
  APPROVED

If the code has issues, respond with:
  ISSUES: <brief description>
  ```python
  <corrected complete code>
  ```

Rules for review:
- Check that build_model() is defined and returns cq.Workplane
- Check that key dimensions match the design plan constraints
- Check that no forbidden patterns are used (no cq.exporters, no print, no file I/O)
- Check that the primary geometry type matches the plan
- Do NOT rewrite working code just to change style
"""


def _parse_critic_response(text: str) -> CriticResult:
    """Parse the Critic's textual response into a CriticResult."""
    import re

    stripped = text.strip()

    # Check for explicit approval
    if stripped.upper().startswith("APPROVED"):
        return CriticResult(approved=True, feedback=stripped)

    # Look for a corrected code block
    code_match = re.search(r"```(?:python)?\s*\n(.*?)```", stripped, re.DOTALL)
    revised = code_match.group(1).strip() if code_match else None

    # Extract the feedback line(s) before the code block
    if code_match:
        feedback = stripped[: code_match.start()].strip()
    else:
        feedback = stripped

    # If ISSUES tag is present the Critic found problems
    has_issues = "ISSUES" in stripped.upper() or "ERROR" in stripped.upper()

    if has_issues and revised:
        return CriticResult(approved=False, revised_code=revised, feedback=feedback)
    if has_issues:
        # Identified issues but gave no corrected code -- still not approved;
        # the pipeline will proceed with the original code and rely on repair.
        return CriticResult(approved=False, feedback=feedback)

    # Ambiguous response: treat as approved to avoid unnecessary repair cycles.
    _log.debug("CriticAgent: ambiguous response, treating as approved.")
    return CriticResult(approved=True, feedback=stripped)


class CriticAgent:
    """Reviews CadQuery code and optionally provides a corrected version.

    Args:
        llm:         LLMBackend used for the review call.
        prompts_dir: Optional path to a directory containing
                     ``system_critic.txt``.  Falls back to embedded default.

    Example::

        agent = CriticAgent(llm=my_llm)
        result = agent.review(
            prompt="a bracket",
            plan=design_plan,
            code=generated_code,
        )
        if not result.approved and result.revised_code:
            use_code = result.revised_code
    """

    def __init__(
        self,
        llm: LLMBackend,
        prompts_dir: Optional[Path] = None,
    ) -> None:
        self._llm = llm
        self._prompt_builder = PromptBuilder(prompts_dir=prompts_dir)

    def review(
        self,
        prompt: str,
        plan: DesignPlan,
        code: str,
    ) -> CriticResult:
        """Review generated code against the design plan.

        Args:
            prompt: Original user NL prompt.
            plan:   DesignPlan from ArchitectAgent.
            code:   CadQuery code to review (fences already stripped).

        Returns:
            CriticResult with approval verdict and optional revised code.
        """
        system = self._prompt_builder._load("system_critic.txt", _DEFAULT_SYSTEM)

        constraints_str = (
            ", ".join(f"{k}={v}" for k, v in plan.constraints.items())
            if plan.constraints
            else "none"
        )
        user = (
            f"User request: {prompt}\n\n"
            f"Design plan:\n"
            f"  Geometry type: {plan.geometry_type}\n"
            f"  Features: {', '.join(plan.features)}\n"
            f"  Constraints: {constraints_str}\n\n"
            f"Generated code to review:\n"
            f"```python\n{code}\n```"
        )

        _log.debug("CriticAgent.review: calling LLM")
        raw = self._llm.generate(user, system)
        result = _parse_critic_response(raw)
        _log.debug(
            f"CriticAgent.review: approved={result.approved}, "
            f"revised={'yes' if result.revised_code else 'no'}"
        )
        return result
