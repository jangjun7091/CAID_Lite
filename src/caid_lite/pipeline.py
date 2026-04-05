"""CADPipeline: top-level orchestrator for the NL → CadQuery → STEP/STL pipeline.

This class is intentionally **stateless** — it holds no session, GUI, or
per-request state.  All mutable session data lives in ``session.SessionManager``
(Phase 4).

Implemented stages (Phase 0–3):
  ✓ LLM code generation (Phase 1)
  ✓ Markdown fence stripping
  ✓ Sandbox subprocess execution (Phase 2)
  ✓ Geometry validation (Phase 3)
  ✓ LLM-guided repair loop (Phase 3)

Stub stages (wired in future phases):
  ✗ Session / API layer  → Phase 4
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .executor.result import ExecutionResult
from .executor.sandbox import Sandbox
from .llm.base import LLMBackend, LLMConfig
from .llm.factory import LLMFactory
from .llm.prompts import PromptBuilder
from .logging.logger import get_logger
from .repair.loop import RepairLoop, RepairResult
from .validator.geometry import GeometryValidator, ValidationResult
from .agents.base import CriticResult, DesignPlan
from .agents.architect import ArchitectAgent
from .agents.pattern_selector import PatternSelector
from .agents.designer import DesignerAgent
from .agents.critic import CriticAgent

_log = get_logger(__name__)


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class PipelineResult:
    """Everything the pipeline knows about a single generation run.

    Fields populated by phase:
      Phase 1: run_id, prompt, generated_code, elapsed_s
      Phase 2: success, exports, execution, error
      Phase 3: validation, repair
    """

    run_id: str
    success: bool
    prompt: str
    generated_code: str
    elapsed_s: float

    # Phase 2+ — execution details
    execution: Optional[ExecutionResult] = None
    exports: Dict[str, Path] = field(default_factory=dict)

    # Phase 3+ — validation and repair
    validation: Optional[ValidationResult] = None
    repair: Optional[Dict[str, Any]] = None

    # Multi-agent fields (populated only when agents are configured)
    design_plan: Optional[Dict[str, Any]] = None
    critic: Optional[Dict[str, Any]] = None

    # Human-readable failure reason; None on success
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict for logging and API responses."""
        return {
            "run_id": self.run_id,
            "success": self.success,
            "prompt": self.prompt,
            "generated_code": self.generated_code,
            "elapsed_s": self.elapsed_s,
            "execution": self.execution.to_dict() if self.execution else None,
            "exports": {k: str(v) for k, v in self.exports.items()},
            "validation": self.validation.to_dict() if self.validation else None,
            "repair": self.repair,
            "design_plan": self.design_plan,
            "critic": self.critic,
            "error": self.error,
        }


# ── Startup diagnostics ───────────────────────────────────────────────────────

_QWEN_DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

_PROVIDER_KEY_ENV: dict[str, tuple[str, str | None]] = {
    # provider → (api_key_env_var, api_base_env_var | None)
    "qwen":      ("QWEN_API_KEY",      "QWEN_API_BASE"),
    "openai":    ("OPENAI_API_KEY",    None),
    "anthropic": ("ANTHROPIC_API_KEY", None),
    "local":     ("LOCAL_API_KEY",     "LOCAL_API_BASE"),
}


def _log_provider_keys(provider: str, os_module) -> None:  # type: ignore[type-arg]
    """Emit INFO-level startup lines for the resolved provider.

    Shows which env vars are set and their effective values.  The API key
    itself is never logged — only whether it is set and a masked prefix.
    """
    key_var, base_var = _PROVIDER_KEY_ENV.get(provider, ("", None))

    if base_var:
        base_val = os_module.getenv(base_var)
        if base_val:
            _log.info(f"{base_var} : {base_val}")
        else:
            default = _QWEN_DEFAULT_BASE if provider == "qwen" else "(none)"
            _log.info(f"{base_var} : (not set, using default: {default})")

    if key_var:
        raw = os_module.getenv(key_var, "")
        if raw and raw not in ("none", "your_dashscope_key_here"):
            masked = raw[:4] + "*" * max(0, len(raw) - 4)
            _log.info(f"{key_var} : {masked}  [OK]")
        else:
            _log.warning(
                f"{key_var} : NOT SET - API calls will fail with 401. "
                f"Set the variable in .env or as a system/user environment variable."
            )


# ── Pipeline ──────────────────────────────────────────────────────────────────


class CADPipeline:
    """Orchestrates the NL → CadQuery → STEP/STL pipeline.

    The pipeline depends only on the ``LLMBackend`` protocol and duck-typed
    ``Sandbox`` / ``GeometryValidator`` / ``RepairLoop`` — all are injected,
    so tests can substitute mocks without any monkeypatching.

    Args:
        llm: Any object satisfying the ``LLMBackend`` protocol.
        sandbox: Sandbox instance for subprocess execution.  If ``None``,
            a default ``Sandbox()`` is created.
        validator: Geometry validator applied after successful execution.
            When ``None``, no geometry validation is performed.
        repair_loop: Repair loop invoked on execution or validation failure.
            When ``None``, failures are returned as-is without repair.
        prompts_dir: Optional path to custom prompt template files.

    Example (production)::

        pipeline = CADPipeline.from_config("config/default.yaml")
        result = pipeline.run("a 50x30x5mm mounting bracket with four M4 holes")

    Example (testing)::

        pipeline = CADPipeline(
            llm=MockLLMBackend(responses=["```python\\ndef build_model(): ...\\n```"]),
            sandbox=make_success_sandbox(),
        )
        result = pipeline.run("any prompt")
    """

    def __init__(
        self,
        llm: LLMBackend,
        sandbox: Optional[Sandbox] = None,
        validator: Optional[GeometryValidator] = None,
        repair_loop: Optional[RepairLoop] = None,
        prompts_dir: Optional[Path] = None,
        architect: Optional[ArchitectAgent] = None,
        pattern_selector: Optional[PatternSelector] = None,
        designer: Optional[DesignerAgent] = None,
        critic: Optional[CriticAgent] = None,
    ) -> None:
        self._llm = llm
        self._sandbox = sandbox if sandbox is not None else Sandbox()
        self._validator = validator
        self._repair_loop = repair_loop
        self._prompt_builder = PromptBuilder(prompts_dir=prompts_dir)
        self._architect = architect
        self._pattern_selector = pattern_selector
        self._designer = designer
        self._critic = critic

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls, config_path: str | Path = "config/default.yaml"
    ) -> "CADPipeline":
        """Build a fully-wired pipeline from a YAML config file.

        Creates ``Sandbox``, ``GeometryValidator``, and ``RepairLoop`` from
        the config.  The same ``llm`` and ``sandbox`` instances are shared
        between the pipeline and the repair loop.

        Args:
            config_path: Path to ``default.yaml`` (absolute or relative to CWD).

        Raises:
            FileNotFoundError: If the config file does not exist.
        """
        import os
        import yaml
        from dotenv import load_dotenv

        # Load .env (project root) if present.  By default load_dotenv() does
        # NOT override variables already set in the environment, so Windows /
        # shell env vars always take precedence over .env file values.
        load_dotenv()

        path = Path(config_path)
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path.resolve()}")

        data = yaml.safe_load(path.read_text(encoding="utf-8"))

        # Resolve provider + model (env vars applied on top of YAML defaults)
        # and log startup diagnostics *before* creating the backend so any
        # configuration problem is visible even if the first API call fails.
        resolved_cfg = LLMConfig.from_dict(data["llm"]).with_env_overrides()
        _log.info(f"LLM provider : {resolved_cfg.provider}")
        _log.info(f"LLM model    : {resolved_cfg.model}")
        _log_provider_keys(resolved_cfg.provider, os)

        llm = LLMFactory.from_yaml(data["llm"])
        sandbox = Sandbox.from_config(data)
        validator = GeometryValidator()

        max_attempts = int(
            data.get("repair", {}).get("max_repair_attempts", 3)
        )
        repair_loop = RepairLoop(
            llm=llm,
            sandbox=sandbox,
            validator=validator,
            max_iterations=max_attempts,
        )

        return cls(
            llm=llm,
            sandbox=sandbox,
            validator=validator,
            repair_loop=repair_loop,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, prompt: str) -> PipelineResult:
        """Execute the pipeline for a single natural language prompt.

        Phase 0–3 flow:
          1. Build generation prompt via PromptBuilder.
          2. Call LLMBackend.generate() to produce code.
          3. Strip markdown fences with _extract_code().
          4. Execute in Sandbox — enforces build_model() contract.
          5. Validate geometry metrics (if validator is present).
          6. Invoke repair loop on failure (if repair_loop is present).
          7. Return PipelineResult.

        Args:
            prompt: Natural language description of the desired geometry.

        Returns:
            PipelineResult with all available fields populated.
        """
        run_id = str(uuid.uuid4())
        start = time.monotonic()

        _log.info(f"[{run_id[:8]}] Pipeline run started")
        _log.debug(f"[{run_id[:8]}] Prompt: {prompt!r}")

        # ── Step 1: LLM code generation (single-LLM or multi-agent) ──────
        multi_agent = (
            self._architect is not None
            and self._pattern_selector is not None
            and self._designer is not None
            and self._critic is not None
        )

        design_plan_dict: Optional[Dict[str, Any]] = None
        critic_dict: Optional[Dict[str, Any]] = None
        plan: DesignPlan = DesignPlan()

        try:
            if multi_agent:
                # Stage 1a: Architect -- NL prompt -> DesignPlan
                _log.info(f"[{run_id[:8]}] Architect: planning")
                plan = self._architect.plan(prompt)  # type: ignore[union-attr]
                design_plan_dict = plan.to_dict()

                # Stage 1b: PatternSelector -- DesignPlan -> patterns
                patterns = self._pattern_selector.select(plan)  # type: ignore[union-attr]
                _log.info(
                    f"[{run_id[:8]}] PatternSelector: "
                    f"{len(patterns)} pattern(s) selected"
                )

                # Stage 1c: Designer -- plan + patterns -> raw LLM response
                _log.info(f"[{run_id[:8]}] Designer: generating code")
                raw_response = self._designer.generate(prompt, plan, patterns)  # type: ignore[union-attr]
            else:
                system_prompt, user_prompt = self._prompt_builder.build_generation_prompt(
                    prompt
                )
                _log.info(f"[{run_id[:8]}] Calling LLM ({self._llm!r})")
                raw_response = self._llm.generate(user_prompt, system_prompt)

        except Exception as exc:
            elapsed = time.monotonic() - start
            error_msg = f"LLM error: {type(exc).__name__}: {exc}"
            _log.error(f"[{run_id[:8]}] {error_msg}")
            return PipelineResult(
                run_id=run_id,
                success=False,
                prompt=prompt,
                generated_code="",
                elapsed_s=round(elapsed, 3),
                error=error_msg,
                design_plan=design_plan_dict,
            )

        # ── Step 2: Extract code from markdown response ───────────────
        code = self._extract_code(raw_response)
        _log.debug(f"[{run_id[:8]}] Extracted {len(code)} chars of code")

        # ── Step 1d (multi-agent): Critic review ──────────────────────────
        if multi_agent:
            try:
                _log.info(f"[{run_id[:8]}] Critic: reviewing code")
                critic_result = self._critic.review(prompt, plan, code)  # type: ignore[union-attr]
                critic_dict = critic_result.to_dict()
                if not critic_result.approved and critic_result.revised_code:
                    _log.info(
                        f"[{run_id[:8]}] Critic: code revised "
                        f"({critic_result.feedback[:80]})"
                    )
                    code = critic_result.revised_code
                elif not critic_result.approved:
                    _log.warning(
                        f"[{run_id[:8]}] Critic: issues found but no revision provided. "
                        f"Proceeding with original code."
                    )
            except Exception as exc:
                _log.warning(
                    f"[{run_id[:8]}] Critic failed ({exc}); proceeding with original code."
                )

        # ── Step 3: Execute in sandbox ────────────────────────────────
        _log.info(f"[{run_id[:8]}] Executing in sandbox")
        exec_result = self._sandbox.execute(code, run_id=run_id)

        # ── Step 4: Geometry validation ───────────────────────────────
        val_result: Optional[ValidationResult] = None
        if exec_result.success and self._validator:
            val_result = self._validator.validate(exec_result.validation_metrics)
            if val_result.valid:
                _log.info(f"[{run_id[:8]}] Geometry validation passed")
            else:
                _log.warning(
                    f"[{run_id[:8]}] Geometry validation failed: {val_result.errors}"
                )

        # ── Step 5: Repair loop ───────────────────────────────────────
        repair_result: Optional[RepairResult] = None
        needs_repair = not exec_result.success or (
            val_result is not None and not val_result.valid
        )

        if needs_repair and self._repair_loop:
            if val_result is not None and not val_result.valid:
                initial_error = val_result.format_errors()
            else:
                initial_error = exec_result.exception or "Unknown execution error."

            _log.info(f"[{run_id[:8]}] Starting repair loop")
            repair_result = self._repair_loop.run(
                prompt, code, initial_error, run_id_prefix=run_id
            )

            if repair_result.repaired and repair_result.final_exec_result:
                exec_result = repair_result.final_exec_result
                code = repair_result.final_code
                # Use validation from the successful repair attempt
                last = repair_result.history[-1]
                val_result = last.validation

        # ── Step 6: Assemble result ───────────────────────────────────
        elapsed = time.monotonic() - start

        final_success = exec_result.success and (
            val_result is None or val_result.valid
        )

        if not final_success:
            if val_result is not None and not val_result.valid:
                final_error: Optional[str] = val_result.format_errors()
            else:
                final_error = exec_result.exception
        else:
            final_error = None

        if final_success:
            _log.info(
                f"[{run_id[:8]}] Pipeline succeeded in {elapsed:.2f}s - "
                f"exports: {list(exec_result.exports.keys())}"
            )
        else:
            _log.warning(
                f"[{run_id[:8]}] Pipeline failed in {elapsed:.2f}s"
            )

        return PipelineResult(
            run_id=run_id,
            success=final_success,
            prompt=prompt,
            generated_code=code,
            elapsed_s=round(elapsed, 3),
            execution=exec_result,
            exports=exec_result.exports,
            validation=val_result,
            repair=repair_result.to_dict() if repair_result else None,
            design_plan=design_plan_dict,
            critic=critic_dict,
            error=final_error,
        )

    # ------------------------------------------------------------------
    # Code extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_code(response: str) -> str:
        """Strip markdown fences and return bare Python source.

        Handles:
        - ````python\\n...\\n```` (preferred)
        - `````\\n...\\n````` (no language tag)
        - Plain code with no fences at all

        When multiple code blocks are present, the first one wins.

        Args:
            response: Raw text returned by ``LLMBackend.generate()``.

        Returns:
            Python source string with leading/trailing whitespace stripped.
        """
        match = re.search(r"```(?:python)?\s*\n(.*?)```", response, re.DOTALL)
        if match:
            return match.group(1).strip()
        return response.strip()
