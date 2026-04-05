"""DesignerAgent: generates CadQuery code from a DesignPlan + patterns."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..llm.base import LLMBackend
from ..llm.prompts import PromptBuilder
from ..logging.logger import get_logger
from .base import DesignPlan

_log = get_logger(__name__)

_DEFAULT_SYSTEM = """\
You are an expert CadQuery programmer. Generate Python code for the described
3D geometry.

Rules:
- Always start with: import cadquery as cq
- Define a function: def build_model() -> no arguments, returns cq.Workplane
- The function must be named exactly build_model
- Do NOT call cq.exporters, open files, or perform any I/O
- Do NOT use print() or any logging statements
- Use named parametric variables with millimeter units
- Return ONLY the Python code inside a ```python code block
"""


def _format_plan(plan: DesignPlan) -> str:
    """Render a DesignPlan as a compact text block for the user prompt."""
    lines = [
        f"Geometry type: {plan.geometry_type}",
        f"Features: {', '.join(plan.features) if plan.features else 'none specified'}",
    ]
    if plan.constraints:
        pairs = ", ".join(f"{k}={v}" for k, v in plan.constraints.items())
        lines.append(f"Constraints: {pairs}")
    if plan.notes:
        lines.append(f"Notes: {plan.notes}")
    if plan.operations:
        lines.append("Operation sequence (implement in this order):")
        for i, op in enumerate(plan.operations, 1):
            op_type = op.get("op", "?")
            details = ", ".join(
                f"{k}={v}" for k, v in op.items() if k != "op"
            )
            lines.append(f"  Step {i}: {op_type}" + (f" ({details})" if details else ""))
    return "\n".join(lines)


def _format_patterns(patterns: List[Dict[str, Any]]) -> str:
    """Render selected patterns as a reference block for the prompt."""
    if not patterns:
        return ""
    sections: List[str] = ["--- Relevant patterns ---"]
    for p in patterns:
        name = p.get("name", "?")
        purpose = p.get("purpose", "")
        idiom = p.get("idiom", "")
        avoid = p.get("avoid", [])
        sections.append(f"\nPattern: {name}  ({purpose})")
        if idiom:
            sections.append(f"Preferred idiom:\n{idiom.rstrip()}")
        if avoid:
            avoid_str = "\n  - ".join(avoid)
            sections.append(f"Avoid:\n  - {avoid_str}")
    return "\n".join(sections)


class DesignerAgent:
    """Generates CadQuery source code from a DesignPlan and pattern hints.

    Args:
        llm:         LLMBackend used for code generation.
        prompts_dir: Optional path to a directory containing
                     ``system_generate.txt``.  Falls back to the
                     embedded default when absent.

    Example::

        agent = DesignerAgent(llm=my_llm)
        code  = agent.generate(
            prompt="a bracket",
            plan=design_plan,
            patterns=[plate_pattern, hole_pattern],
        )
    """

    def __init__(
        self,
        llm: LLMBackend,
        prompts_dir: Optional[Path] = None,
    ) -> None:
        self._llm = llm
        self._prompt_builder = PromptBuilder(prompts_dir=prompts_dir)

    def generate(
        self,
        prompt: str,
        plan: DesignPlan,
        patterns: List[Dict[str, Any]],
    ) -> str:
        """Generate CadQuery code for the given plan.

        Args:
            prompt:   Original user NL prompt (provides intent context).
            plan:     DesignPlan from ArchitectAgent.
            patterns: Relevant pattern dicts from PatternSelector.

        Returns:
            Raw LLM response string (may contain markdown fences --
            the pipeline strips them via CADPipeline._extract_code).
        """
        # Use system_generate.txt if present; otherwise the embedded default.
        system = self._prompt_builder._load("system_generate.txt", _DEFAULT_SYSTEM)

        plan_block = _format_plan(plan)
        pattern_block = _format_patterns(patterns)

        user = (
            f"User request: {prompt}\n\n"
            f"Design plan:\n{plan_block}"
        )
        if pattern_block:
            user += f"\n\n{pattern_block}"

        _log.debug("DesignerAgent.generate: calling LLM")
        return self._llm.generate(user, system)
