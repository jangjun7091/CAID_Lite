"""ArchitectAgent: converts a natural-language prompt into a DesignPlan."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from ..llm.base import LLMBackend
from ..llm.prompts import PromptBuilder
from ..logging.logger import get_logger
from .base import DesignPlan

_log = get_logger(__name__)

_DEFAULT_SYSTEM = """\
You are a mechanical CAD design architect. Convert the user's request into a
structured design plan.

Return a JSON object with EXACTLY these keys:
  "features"      : list of strings - geometric features to model in order
  "geometry_type" : string - primary shape category (plate/box/cylinder/bracket/etc.)
  "constraints"   : object - key/value pairs for critical numeric dimensions (mm)
  "notes"         : string - guidance for the code generator

Return ONLY the JSON object. No markdown fences, no explanation.
"""


def _parse_plan(text: str) -> DesignPlan:
    """Extract a DesignPlan from LLM output.

    Tries strict JSON parse first; if that fails, extracts the first
    JSON object found in the text.
    """
    text = text.strip()

    # Strip optional markdown code fences
    fenced = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        data: Dict[str, Any] = json.loads(text)
        return DesignPlan.from_dict(data)
    except json.JSONDecodeError:
        pass

    # Fallback: find first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return DesignPlan.from_dict(data)
        except json.JSONDecodeError:
            pass

    # Last resort: return a minimal plan with the raw text as notes
    _log.warning("ArchitectAgent: could not parse JSON plan; using fallback.")
    return DesignPlan(notes=text)


class ArchitectAgent:
    """Converts a natural-language prompt into a structured DesignPlan.

    Args:
        llm:         LLMBackend used for the planning call.
        prompts_dir: Optional path to prompt directory containing
                     ``system_architect.txt``.  Falls back to the
                     embedded default when absent.

    Example::

        agent = ArchitectAgent(llm=my_llm)
        plan  = agent.plan("a 50x40mm mounting bracket with four M4 holes")
        # plan.geometry_type -> "plate" or "bracket"
        # plan.features      -> ["rectangular body", "four M4 holes", ...]
    """

    def __init__(
        self,
        llm: LLMBackend,
        prompts_dir: Optional[object] = None,
    ) -> None:
        self._llm = llm
        self._prompt_builder = PromptBuilder(prompts_dir=prompts_dir)

    def plan(self, prompt: str) -> DesignPlan:
        """Generate a DesignPlan for the given user prompt.

        Args:
            prompt: Natural-language geometry description.

        Returns:
            DesignPlan populated from the LLM response.
        """
        system = self._prompt_builder._load(
            "system_architect.txt", _DEFAULT_SYSTEM
        )
        _log.debug(f"ArchitectAgent.plan: prompt={prompt!r}")
        raw = self._llm.generate(prompt, system)
        plan = _parse_plan(raw)
        _log.debug(f"ArchitectAgent.plan: plan={plan.to_dict()}")
        return plan
