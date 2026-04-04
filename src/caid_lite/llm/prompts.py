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

    def build_repair_prompt(
        self,
        original_description: str,
        failed_code: str,
        error_message: str,
        iteration: int = 0,
    ) -> tuple[str, str]:
        """Return ``(system_prompt, user_prompt)`` for a repair attempt.

        The user prompt embeds the original NL intent, the failed code, and
        the exact error so the LLM has full context to fix the problem without
        drifting from the design intent.

        Args:
            original_description: The user's original NL geometry description.
            failed_code: The CadQuery code that failed or produced invalid geometry.
            error_message: Python traceback or validation error strings.
            iteration: Zero-based attempt index (shown in the prompt so the
                model knows how many attempts have been made).

        Returns:
            ``(system_prompt, user_prompt)`` ready to pass to
            ``LLMBackend.generate(user_prompt, system_prompt)``.
        """
        system = self._load("system_repair.txt", _DEFAULT_SYSTEM_REPAIR)
        user = (
            f"ORIGINAL REQUEST:\n{original_description}\n\n"
            f"FAILED CODE (attempt {iteration + 1}):\n"
            f"```python\n{failed_code}\n```\n\n"
            f"ERROR:\n{error_message}\n\n"
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
