"""ConstraintParserAgent: converts natural-language assembly instructions
into structured Constraint objects.

Architecture notes:
  - Structurally parallel to ArchitectAgent (agents/architect.py).
  - Accepts the list of parts currently in the assembly so the LLM can
    resolve part names to AssemblyPart.id values.
  - Returns a list of Constraint dicts (ready to be passed to
    AssemblyManager.add_constraint()).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..llm.base import LLMBackend
from ..logging.logger import get_logger

_log = get_logger(__name__)

_DEFAULT_SYSTEM = """\
You are a CAD assembly constraint expert.  Given a list of parts and a
natural-language assembly instruction, produce a list of CadQuery assembly
constraints.

Available constraint types:
  "Plane"     — align two faces coplanar (face-to-face mating)
  "Axis"      — align two axes coaxially (e.g. shaft inside hole)
  "Point"     — align two points
  "Fixed"     — fix a part to the world frame (no second part needed)
  "FixedPlane"— fix the plane of a face to the world XY/XZ/YZ plane
  "FixedAxis" — fix the axis of an edge to the world X/Y/Z axis

Face selectors (CadQuery syntax):
  ">Z"  top face (+Z)      "<Z"  bottom face (-Z)
  ">X"  right face (+X)    "<X"  left face (-X)
  ">Y"  front face (+Y)    "<Y"  back face (-Y)

Parts list format: [{"id": "<uuid>", "name": "<display name>"}, ...]

Return ONLY a JSON array of constraint objects.  Each object has:
  "type"       : string (one of the types above)
  "part_a"     : string (id from parts list)
  "selector_a" : string (face selector, e.g. ">Z")
  "part_b"     : string | null  (id from parts list, or null for Fixed)
  "selector_b" : string (face selector for part_b, or "" if part_b is null)
  "param"      : number (offset in mm, default 0)

No markdown fences, no explanation outside the JSON array.

Example output:
[
  {"type": "Fixed", "part_a": "abc123", "selector_a": "", "part_b": null, "selector_b": "", "param": 0},
  {"type": "Axis",  "part_a": "abc123", "selector_a": ">Z", "part_b": "def456", "selector_b": ">Z", "param": 0}
]
"""


def _parse_constraints(text: str) -> List[Dict[str, Any]]:
    """Extract a list of Constraint dicts from LLM output."""
    text = text.strip()

    # Strip optional markdown code fences
    fenced = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # Fallback: find first [...] block
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    _log.warning("ConstraintParserAgent: could not parse JSON list; returning empty.")
    return []


class ConstraintParserAgent:
    """Converts natural-language assembly instructions to Constraint dicts.

    Args:
        llm: LLMBackend used for the parsing call.

    Example::

        agent = ConstraintParserAgent(llm=my_llm)
        parts = [{"id": "abc", "name": "shaft"}, {"id": "def", "name": "bearing"}]
        constraints = agent.parse("Place the bearing coaxially on the shaft", parts)
    """

    def __init__(self, llm: LLMBackend) -> None:
        self._llm = llm

    def parse(
        self,
        message: str,
        parts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Parse a natural-language instruction into a list of Constraint dicts.

        Args:
            message: Natural-language instruction, e.g.
                     "Fix shaft to world, then place bearing coaxially on it".
            parts:   List of ``{"id": str, "name": str}`` dicts for all parts
                     currently in the assembly.

        Returns:
            List of constraint dicts ready for ``AssemblyManager.add_constraint()``.
        """
        parts_json = json.dumps(parts, ensure_ascii=False)
        user_prompt = (
            f"Parts in this assembly:\n{parts_json}\n\n"
            f"Assembly instruction:\n{message}"
        )
        _log.debug(f"ConstraintParserAgent.parse: {message!r}")
        raw = self._llm.generate(user_prompt, _DEFAULT_SYSTEM)
        constraints = _parse_constraints(raw)
        _log.debug(f"ConstraintParserAgent.parse: {len(constraints)} constraints")
        return constraints
