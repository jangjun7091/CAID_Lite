"""agents/ -- Multi-agent CAD generation layer.

Agents are optional pipeline components that enrich code generation when all
four are provided to CADPipeline:

  ArchitectAgent    - converts a user prompt to a structured DesignPlan
  PatternSelector   - maps a DesignPlan to relevant YAML patterns (no LLM)
  DesignerAgent     - generates CadQuery code from plan + patterns
  CriticAgent       - reviews generated code before execution

When any agent is absent the pipeline falls back to the single-LLM path.
"""

from .base import DesignPlan, CriticResult
from .architect import ArchitectAgent
from .pattern_selector import PatternSelector
from .designer import DesignerAgent
from .critic import CriticAgent

__all__ = [
    "DesignPlan",
    "CriticResult",
    "ArchitectAgent",
    "PatternSelector",
    "DesignerAgent",
    "CriticAgent",
]
