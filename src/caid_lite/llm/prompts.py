"""PromptBuilder: assembles prompts for the two LLM call sites in the pipeline.

Prompts are sourced in priority order:
  1. ``config/prompts/`` files (discovered relative to CWD — customisable).
  2. Embedded string defaults in this module (no file system required,
     tests work out of the box without any config directory present).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


# ── Embedded default prompts ──────────────────────────────────────────────────
# Kept in sync with config/prompts/*.txt.  The file-based versions take
# precedence when present, allowing prompt iteration without code changes.

_DEFAULT_SYSTEM_GENERATE = """\
You are an expert CadQuery programmer. Generate Python code that creates 3D \
geometry using the CadQuery library.

Rules:
- Always start with: import cadquery as cq
- Assign the final geometry to a variable named exactly `result` of type \
cq.Workplane
- Do NOT call cq.exporters, open files, or perform any I/O
- Do NOT use print() or any logging statements
- Use named parametric variables (e.g., width, height, thickness) with \
millimeter units
- Produce clean, concise code that generates a valid, watertight solid
- Return ONLY the Python code inside a ```python code block — no explanation \
outside the block
"""

_DEFAULT_SYSTEM_REPAIR = """\
You are an expert CadQuery programmer. Fix the broken CadQuery Python code \
provided.

Rules:
- The final geometry MUST be assigned to a variable named exactly `result` \
of type cq.Workplane
- Do NOT call cq.exporters, open files, or perform any I/O
- Do NOT use print() or any logging statements
- Fix ONLY the errors described — preserve the original design intent
- Return ONLY the corrected Python code inside a ```python code block — no \
explanation outside the block
"""



_DEFAULT_SYSTEM_ARCHITECT = """You are a mechanical CAD design architect. Convert the user's request into a
structured JSON design plan with keys: features, geometry_type, constraints, notes.
Return ONLY the JSON object.
"""

_DEFAULT_SYSTEM_CRITIC = """You are a CadQuery code reviewer. If the code is correct respond APPROVED.
If it has issues respond: ISSUES: <summary> then a ```python block with fixed code.
"""
class PromptBuilder:
    """Builds (system_prompt, user_prompt) tuples for each LLM call site.

    Args:
        prompts_dir: Optional explicit path to a directory containing
            ``system_generate.txt`` and ``system_repair.txt``.  When *None*
            the builder looks for ``config/prompts/`` relative to the current
            working directory, then falls back to the embedded defaults above.

    Example::

        builder = PromptBuilder()
        system, user = builder.build_generation_prompt("a 50mm bracket")
        code = llm.generate(user, system)
    """

    def __init__(self, prompts_dir: Optional[Path] = None) -> None:
        self._prompts_dir = prompts_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_generation_prompt(
        self, user_description: str
    ) -> tuple[str, str]:
        """Return ``(system_prompt, user_prompt)`` for initial code generation.

        Args:
            user_description: Natural language geometry description from the
                user (e.g. "a mounting bracket with four M4 holes").

        Returns:
            ``(system_prompt, user_prompt)`` ready to pass to
            ``LLMBackend.generate(user_prompt, system_prompt)``.
        """
        system = self._load("system_generate.txt", _DEFAULT_SYSTEM_GENERATE)
        return system, user_description

    # ── Error-type specific hint blocks ──────────────────────────────────────
    _ERROR_HINTS: dict[str, str] = {
        "GEOMETRY_CONSTRUCTION": (
            "TARGETED FIX (GEOMETRY_CONSTRUCTION): "
            "The error is caused by invalid OCC Wire/BSpline construction. "
            "Replace the failing geometry entirely using safe CadQuery primitives:\n"
            "  - For tooth/gear profiles: use .polyline([(x,y),...]).close().extrude(h)\n"
            "  - Do NOT import from OCC.Core or use cq.Wire.makeSpline()\n"
            "  - All polyline points must be 2-tuples (x, y) in the XY plane"
        ),
        "MISSING_BUILD_MODEL": (
            "TARGETED FIX (MISSING_BUILD_MODEL): "
            "The file must define exactly: def build_model():\n"
            "  - No arguments, no default parameters\n"
            "  - Must return a cq.Workplane object\n"
            "  - Do NOT assign geometry to a top-level variable"
        ),
        "WRONG_RETURN_TYPE": (
            "TARGETED FIX (WRONG_RETURN_TYPE): "
            "build_model() must return the cq.Workplane object directly.\n"
            "  - Do NOT return None, a solid, or a tuple\n"
            "  - The final chain must end with a cq.Workplane method\n"
            "  - Example: return cq.Workplane('XY').box(w, h, t)"
        ),
        "SYNTAX_ERROR": (
            "TARGETED FIX (SYNTAX_ERROR): "
            "The code has a Python syntax error. Check:\n"
            "  - Matching parentheses and brackets\n"
            "  - Consistent 4-space indentation (no tabs)\n"
            "  - No trailing commas inside function calls unless in a list/tuple"
        ),
        "IMPORT_ERROR": (
            "TARGETED FIX (IMPORT_ERROR): "
            "A required module is missing. Ensure:\n"
            "  - First line: import cadquery as cq\n"
            "  - import math  (if trigonometry is needed)\n"
            "  - Do NOT import from OCC.Core, OCC.Display, or any non-stdlib module"
        ),
        "UNIT_ERROR": (
            "TARGETED FIX (UNIT_ERROR): "
            "Dimensions appear to use wrong units (cm or m instead of mm).\n"
            "  - All dimensions must be in millimeters\n"
            "  - Typical ranges: thickness 2-50 mm, width/height 10-500 mm\n"
            "  - Convert: 1 cm = 10 mm, 1 m = 1000 mm"
        ),
        "VALIDATION_FAILURE": (
            "TARGETED FIX (VALIDATION_FAILURE): "
            "Geometry was produced but failed quality checks. Verify:\n"
            "  - build_model() returns a closed solid (not a 2D sketch or wire)\n"
            "  - Volume must be > 0: ensure the model is fully extruded\n"
            "  - Boolean ops (.hole(), .cut()) on an existing solid are valid and produce cq.Compound"
        ),
    }

    def build_repair_prompt(
        self,
        original_description: str,
        failed_code: str,
        error_message: str,
        iteration: int = 0,
        error_type: str = "UNKNOWN",
    ) -> tuple[str, str]:
        """Return ``(system_prompt, user_prompt)`` for a repair attempt.

        The user prompt embeds the original NL intent, the failed code, the
        exact error, and a targeted hint block selected by ``error_type`` so
        the LLM receives focused repair guidance instead of generic instructions.

        Args:
            original_description: The user's original NL geometry description.
            failed_code: The CadQuery code that failed or produced invalid geometry.
            error_message: Python traceback or validation error strings.
            iteration: Zero-based attempt index (shown in the prompt so the
                model knows how many attempts have been made).
            error_type: Coarse error category from ``repair.loop.classify_error()``.
                One of the ``ERROR_*`` constants.  Defaults to ``"UNKNOWN"``.

        Returns:
            ``(system_prompt, user_prompt)`` ready to pass to
            ``LLMBackend.generate(user_prompt, system_prompt)``.
        """
        system = self._load("system_repair.txt", _DEFAULT_SYSTEM_REPAIR)

        hint = self._ERROR_HINTS.get(error_type, "")
        hint_block = f"\n{hint}\n" if hint else ""

        user = (
            f"ORIGINAL REQUEST:\n{original_description}\n\n"
            f"FAILED CODE (attempt {iteration + 1}):\n"
            f"```python\n{failed_code}\n```\n\n"
            f"ERROR:\n{error_message}\n"
            f"{hint_block}\n"
            "Return ONLY the corrected Python code inside a ```python block."
        )
        return system, user

    def build_architect_prompt(
        self, user_description: str
    ) -> tuple[str, str]:
        """Return ``(system_prompt, user_prompt)`` for the Architect agent.

        Args:
            user_description: Natural language geometry description.

        Returns:
            ``(system_prompt, user_prompt)`` for ``LLMBackend.generate()``.
        """
        system = self._load("system_architect.txt", _DEFAULT_SYSTEM_ARCHITECT)
        return system, user_description

    def build_critic_prompt(
        self,
        original_description: str,
        plan_summary: str,
        code: str,
    ) -> tuple[str, str]:
        """Return ``(system_prompt, user_prompt)`` for the Critic agent.

        Args:
            original_description: The user's original NL geometry description.
            plan_summary:         Short text rendering of the DesignPlan.
            code:                 Generated CadQuery code to review.

        Returns:
            ``(system_prompt, user_prompt)`` for ``LLMBackend.generate()``.
        """
        system = self._load("system_critic.txt", _DEFAULT_SYSTEM_CRITIC)
        user = (
            f"ORIGINAL REQUEST:\n{original_description}\n\n"
            f"DESIGN PLAN:\n{plan_summary}\n\n"
            f"CODE TO REVIEW:\n```python\n{code}\n```"
        )
        return system, user

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self, filename: str, default: str) -> str:
        """Load a prompt file, falling back to the embedded default."""
        # 1. Explicit prompts_dir passed to __init__
        if self._prompts_dir is not None:
            candidate = self._prompts_dir / filename
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")

        # 2. config/prompts/ relative to CWD
        cwd_candidate = Path("config") / "prompts" / filename
        if cwd_candidate.is_file():
            return cwd_candidate.read_text(encoding="utf-8")

        # 3. Embedded default
        return default
