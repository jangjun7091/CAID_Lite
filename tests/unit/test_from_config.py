"""Tests for CADPipeline.from_config() — agent wiring and config parsing.

Uses a temporary YAML config so no real API key is needed and the production
config/default.yaml is never touched.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_config(tmp_path: Path, agents_section: dict | None = None) -> Path:
    """Write a minimal default.yaml to tmp_path and return its path."""
    cfg: dict = {
        "llm": {
            "provider": "qwen",
            "model": "test-model",
            "temperature": 0.2,
            "max_tokens": 512,
        },
        "executor": {"timeout_s": 10},
        "repair": {"max_repair_attempts": 1},
        "exporter": {"formats": ["step"], "output_dir": str(tmp_path / "outputs")},
        "logging": {"log_dir": str(tmp_path / "logs"), "console_level": "WARNING"},
    }
    if agents_section is not None:
        cfg["agents"] = agents_section

    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml.dump(cfg), encoding="utf-8")
    return config_file


def _set_placeholder_key(monkeypatch):
    """Set a fake (but non-placeholder) API key so QwenBackend doesn't error."""
    monkeypatch.setenv("QWEN_API_KEY", "sk-test-fake-key-for-unit-tests")
    monkeypatch.setenv("QWEN_API_BASE", "http://localhost:9999/v1")  # unreachable — never called


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestFromConfigAgentWiring:
    """from_config() must wire agents when agents.enabled=true (the default)."""

    def test_agents_enabled_by_default_no_section(self, tmp_path, monkeypatch):
        """When no 'agents' key exists in the YAML, agents are created."""
        _set_placeholder_key(monkeypatch)
        from caid_lite.pipeline import CADPipeline
        config = _write_config(tmp_path)  # no agents section
        pipeline = CADPipeline.from_config(config)

        assert pipeline._architect is not None
        assert pipeline._pattern_selector is not None
        assert pipeline._designer is not None
        assert pipeline._critic is not None

    def test_agents_enabled_explicitly_true(self, tmp_path, monkeypatch):
        """agents.enabled=true creates all four agents."""
        _set_placeholder_key(monkeypatch)
        from caid_lite.pipeline import CADPipeline
        config = _write_config(tmp_path, agents_section={"enabled": True})
        pipeline = CADPipeline.from_config(config)

        assert pipeline._architect is not None
        assert pipeline._designer is not None
        assert pipeline._critic is not None
        assert pipeline._pattern_selector is not None

    def test_agents_disabled_returns_none_agents(self, tmp_path, monkeypatch):
        """agents.enabled=false leaves all agents as None (single-LLM path)."""
        _set_placeholder_key(monkeypatch)
        from caid_lite.pipeline import CADPipeline
        config = _write_config(tmp_path, agents_section={"enabled": False})
        pipeline = CADPipeline.from_config(config)

        assert pipeline._architect is None
        assert pipeline._designer is None
        assert pipeline._critic is None
        assert pipeline._pattern_selector is None

    def test_agents_are_correct_types(self, tmp_path, monkeypatch):
        """from_config() creates the right agent class instances."""
        _set_placeholder_key(monkeypatch)
        from caid_lite.pipeline import CADPipeline
        from caid_lite.agents.architect import ArchitectAgent
        from caid_lite.agents.designer import DesignerAgent
        from caid_lite.agents.critic import CriticAgent
        from caid_lite.agents.pattern_selector import PatternSelector

        config = _write_config(tmp_path)
        pipeline = CADPipeline.from_config(config)

        assert isinstance(pipeline._architect, ArchitectAgent)
        assert isinstance(pipeline._designer, DesignerAgent)
        assert isinstance(pipeline._critic, CriticAgent)
        assert isinstance(pipeline._pattern_selector, PatternSelector)

    def test_multi_agent_run_uses_agents(self, tmp_path, monkeypatch):
        """With agents wired, run() takes the multi-agent code path."""
        _set_placeholder_key(monkeypatch)
        import json
        from caid_lite.pipeline import CADPipeline

        config = _write_config(tmp_path)
        pipeline = CADPipeline.from_config(config)

        # Replace agent internals with mocks post-construction
        from tests.fixtures.mock_llm import MockLLMBackend
        from tests.fixtures.mock_sandbox import make_success_sandbox

        _PLAN = json.dumps({
            "features": ["box"],
            "geometry_type": "box",
            "constraints": {},
            "notes": "",
        })
        _CODE = (
            "```python\n"
            "import cadquery as cq\n\n"
            "def build_model():\n"
            "    return cq.Workplane('XY').box(50, 40, 30)\n"
            "```"
        )

        pipeline._architect._llm = MockLLMBackend(responses=[_PLAN])
        pipeline._designer._llm = MockLLMBackend(responses=[_CODE])
        pipeline._critic._llm = MockLLMBackend(responses=["APPROVED"])
        pipeline._sandbox = make_success_sandbox()
        pipeline._repair_loop = None

        result = pipeline.run("a simple box")
        assert result.design_plan is not None
        assert result.critic is not None
        assert result.design_plan["geometry_type"] == "box"
