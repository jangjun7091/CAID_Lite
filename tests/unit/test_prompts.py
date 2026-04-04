"""Tests for PromptBuilder.

All tests use the embedded defaults — no config/prompts/ files are required.
"""

from __future__ import annotations

import pytest

from caid_lite.llm.prompts import PromptBuilder


@pytest.fixture
def builder() -> PromptBuilder:
    """PromptBuilder using embedded defaults (no file I/O)."""
    return PromptBuilder(prompts_dir=None)


# ── build_generation_prompt ───────────────────────────────────────────────────


class TestBuildGenerationPrompt:
    def test_returns_two_strings(self, builder):
        result = builder.build_generation_prompt("a simple box")
        assert isinstance(result, tuple)
        assert len(result) == 2
        system, user = result
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_user_prompt_is_the_description(self, builder):
        _, user = builder.build_generation_prompt("a 50mm bracket")
        assert user == "a 50mm bracket"

    def test_system_prompt_mentions_cadquery(self, builder):
        system, _ = builder.build_generation_prompt("anything")
        assert "cadquery" in system.lower() or "cq" in system.lower()

    def test_system_prompt_specifies_build_model_function(self, builder):
        system, _ = builder.build_generation_prompt("anything")
        assert "build_model" in system

    def test_system_prompt_forbids_io(self, builder):
        system, _ = builder.build_generation_prompt("anything")
        # Should explicitly restrict file I/O or exporters
        assert "export" in system.lower() or "I/O" in system or "i/o" in system.lower()

    def test_system_prompt_requests_code_block(self, builder):
        system, _ = builder.build_generation_prompt("anything")
        assert "```" in system or "code block" in system.lower()

    def test_empty_description_still_works(self, builder):
        system, user = builder.build_generation_prompt("")
        assert isinstance(system, str)
        assert user == ""

    def test_multiline_description_preserved(self, builder):
        desc = "a bracket\nwith holes\non the sides"
        _, user = builder.build_generation_prompt(desc)
        assert user == desc


# ── build_repair_prompt ───────────────────────────────────────────────────────


class TestBuildRepairPrompt:
    def test_returns_two_strings(self, builder):
        result = builder.build_repair_prompt("a box", "import cq", "NameError")
        assert isinstance(result, tuple) and len(result) == 2

    def test_user_contains_original_description(self, builder):
        _, user = builder.build_repair_prompt(
            original_description="a box with holes",
            failed_code="import cadquery as cq",
            error_message="some error",
        )
        assert "a box with holes" in user

    def test_user_contains_failed_code(self, builder):
        code = "import cadquery as cq\nx = broken_call()"
        _, user = builder.build_repair_prompt("desc", code, "error")
        assert code in user

    def test_user_contains_error_message(self, builder):
        _, user = builder.build_repair_prompt(
            "desc", "code", "NameError: name 'result' is not defined"
        )
        assert "NameError: name 'result' is not defined" in user

    def test_iteration_zero_shows_attempt_1(self, builder):
        _, user = builder.build_repair_prompt("desc", "code", "err", iteration=0)
        assert "attempt 1" in user

    def test_iteration_two_shows_attempt_3(self, builder):
        _, user = builder.build_repair_prompt("desc", "code", "err", iteration=2)
        assert "attempt 3" in user

    def test_system_prompt_mentions_build_model_function(self, builder):
        system, _ = builder.build_repair_prompt("desc", "code", "error")
        assert "build_model" in system

    def test_system_prompt_forbids_io(self, builder):
        system, _ = builder.build_repair_prompt("desc", "code", "error")
        assert "export" in system.lower() or "I/O" in system or "i/o" in system.lower()

    def test_default_iteration_is_zero(self, builder):
        # Calling without iteration kwarg should not raise
        _, user = builder.build_repair_prompt("desc", "code", "error")
        assert "attempt 1" in user

    def test_user_requests_code_block_output(self, builder):
        _, user = builder.build_repair_prompt("desc", "code", "error")
        assert "```python" in user or "code block" in user.lower()


# ── File-based override ───────────────────────────────────────────────────────


class TestPromptFileOverride:
    def test_custom_prompts_dir_overrides_generate(self, tmp_path):
        custom_system = "CUSTOM GENERATE SYSTEM PROMPT"
        (tmp_path / "system_generate.txt").write_text(custom_system, encoding="utf-8")
        builder = PromptBuilder(prompts_dir=tmp_path)
        system, _ = builder.build_generation_prompt("test")
        assert system == custom_system

    def test_custom_prompts_dir_overrides_repair(self, tmp_path):
        custom_system = "CUSTOM REPAIR SYSTEM PROMPT"
        (tmp_path / "system_repair.txt").write_text(custom_system, encoding="utf-8")
        builder = PromptBuilder(prompts_dir=tmp_path)
        system, _ = builder.build_repair_prompt("desc", "code", "error")
        assert system == custom_system

    def test_missing_file_falls_back_to_default(self, tmp_path):
        # prompts_dir exists but the file is absent
        builder = PromptBuilder(prompts_dir=tmp_path)
        system, _ = builder.build_generation_prompt("test")
        # Should be the embedded default, not empty
        assert len(system) > 20
        assert "build_model" in system
