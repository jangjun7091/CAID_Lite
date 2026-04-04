"""Tests for the multi-agent layer (agents/).

All tests use MockLLMBackend and require no API key or CadQuery installation.
"""

from __future__ import annotations

import json

import pytest

from caid_lite.agents.base import CriticResult, DesignPlan
from caid_lite.agents.architect import ArchitectAgent, _parse_plan
from caid_lite.agents.pattern_selector import PatternSelector
from caid_lite.agents.designer import DesignerAgent, _format_plan, _format_patterns
from caid_lite.agents.critic import CriticAgent, _parse_critic_response
from tests.fixtures.mock_llm import MockLLMBackend


# -- DesignPlan ----------------------------------------------------------------


class TestDesignPlan:
    def test_default_fields(self):
        plan = DesignPlan()
        assert plan.features == []
        assert plan.geometry_type == ""
        assert plan.constraints == {}
        assert plan.notes == ""

    def test_to_dict_round_trip(self):
        plan = DesignPlan(
            features=["a box", "four holes"],
            geometry_type="plate",
            constraints={"width_mm": 50},
            notes="use fillets",
        )
        d = plan.to_dict()
        restored = DesignPlan.from_dict(d)
        assert restored.features == plan.features
        assert restored.geometry_type == plan.geometry_type
        assert restored.constraints == plan.constraints
        assert restored.notes == plan.notes

    def test_from_dict_partial(self):
        plan = DesignPlan.from_dict({"geometry_type": "bracket"})
        assert plan.geometry_type == "bracket"
        assert plan.features == []

    def test_to_dict_keys(self):
        d = DesignPlan().to_dict()
        assert set(d.keys()) == {"features", "geometry_type", "constraints", "notes"}


# -- CriticResult --------------------------------------------------------------


class TestCriticResult:
    def test_approved_result(self):
        r = CriticResult(approved=True, feedback="Looks good.")
        assert r.approved is True
        assert r.revised_code is None

    def test_rejected_with_revision(self):
        r = CriticResult(approved=False, revised_code="fixed code", feedback="Fixed X.")
        assert r.approved is False
        assert r.revised_code == "fixed code"

    def test_to_dict_keys(self):
        d = CriticResult(approved=True).to_dict()
        assert set(d.keys()) == {"approved", "revised_code", "feedback"}

    def test_to_dict_values(self):
        r = CriticResult(approved=False, revised_code="code", feedback="msg")
        d = r.to_dict()
        assert d["approved"] is False
        assert d["revised_code"] == "code"
        assert d["feedback"] == "msg"


# -- ArchitectAgent ------------------------------------------------------------


_VALID_PLAN_JSON = json.dumps({
    "features": ["rectangular plate", "four M4 holes"],
    "geometry_type": "plate",
    "constraints": {"width_mm": 60, "height_mm": 40},
    "notes": "corner holes only",
})


class TestArchitectAgent:
    def test_returns_design_plan(self):
        llm = MockLLMBackend(responses=[_VALID_PLAN_JSON])
        agent = ArchitectAgent(llm=llm)
        plan = agent.plan("a 60x40 plate with holes")
        assert isinstance(plan, DesignPlan)

    def test_plan_fields_populated(self):
        llm = MockLLMBackend(responses=[_VALID_PLAN_JSON])
        agent = ArchitectAgent(llm=llm)
        plan = agent.plan("a 60x40 plate with holes")
        assert plan.geometry_type == "plate"
        assert "rectangular plate" in plan.features
        assert plan.constraints["width_mm"] == 60

    def test_llm_called_once(self):
        llm = MockLLMBackend(responses=[_VALID_PLAN_JSON])
        agent = ArchitectAgent(llm=llm)
        agent.plan("test")
        assert llm.call_count == 1

    def test_prompt_passed_to_llm(self):
        llm = MockLLMBackend(responses=[_VALID_PLAN_JSON])
        agent = ArchitectAgent(llm=llm)
        agent.plan("a bracket with holes")
        user_prompt, _ = llm.calls[0]
        assert "bracket" in user_prompt

    def test_fallback_on_invalid_json(self):
        llm = MockLLMBackend(responses=["not valid json at all"])
        agent = ArchitectAgent(llm=llm)
        plan = agent.plan("some prompt")
        assert isinstance(plan, DesignPlan)
        # Fallback plan should have the raw text in notes
        assert len(plan.notes) > 0

    def test_parse_plan_with_fenced_json(self):
        fenced = f"```json\n{_VALID_PLAN_JSON}\n```"
        plan = _parse_plan(fenced)
        assert plan.geometry_type == "plate"


# -- PatternSelector -----------------------------------------------------------


class TestPatternSelector:
    def test_returns_list(self):
        selector = PatternSelector()
        plan = DesignPlan(geometry_type="plate", features=["a flat slab"])
        result = selector.select(plan)
        assert isinstance(result, list)

    def test_plate_plan_matches_plate_pattern(self):
        selector = PatternSelector()
        plan = DesignPlan(geometry_type="plate", features=["rectangular body"])
        patterns = selector.select(plan)
        names = [p.get("name") for p in patterns]
        assert "plate" in names

    def test_bracket_plan_matches_bracket_patterns(self):
        selector = PatternSelector()
        plan = DesignPlan(geometry_type="bracket", features=["L-shaped body"])
        patterns = selector.select(plan)
        names = [p.get("name") for p in patterns]
        # Should match at least one bracket-related pattern
        assert any("bracket" in n or "plate" in n for n in names)

    def test_max_patterns_limit(self):
        selector = PatternSelector()
        # Many overlapping keywords
        plan = DesignPlan(
            geometry_type="bracket plate mounting",
            features=["hole", "slot", "boss", "fillet", "chamfer"],
        )
        patterns = selector.select(plan)
        from caid_lite.agents.pattern_selector import _MAX_PATTERNS
        assert len(patterns) <= _MAX_PATTERNS

    def test_empty_plan_returns_empty_or_minimal(self):
        selector = PatternSelector()
        plan = DesignPlan()
        result = selector.select(plan)
        assert isinstance(result, list)

    def test_patterns_are_dicts_with_name_key(self):
        selector = PatternSelector()
        plan = DesignPlan(geometry_type="cylinder", features=["solid cylinder"])
        patterns = selector.select(plan)
        for p in patterns:
            assert isinstance(p, dict)
            assert "name" in p

    def test_custom_patterns_dir_used_when_provided(self, tmp_path):
        import yaml
        # Create a minimal pattern file in a temp directory
        pattern = {
            "name": "test_widget",
            "category": "solid",
            "purpose": "Test widget",
            "when_to_use": "Testing only.",
            "idiom": "cq.Workplane('XY').box(1,1,1)",
            "avoid": [],
            "parameters": {},
            "example": "import cadquery as cq\ndef build_model():\n    return cq.Workplane('XY').box(1,1,1)\n",
            "repair_hints": [],
        }
        (tmp_path / "test_widget.yaml").write_text(
            yaml.dump(pattern), encoding="utf-8"
        )
        selector = PatternSelector(patterns_dir=tmp_path)
        plan = DesignPlan(geometry_type="widget", features=["widget"])
        # Should load without error; patterns dict should be populated
        library = selector._load_library()
        assert "test_widget" in library


# -- DesignerAgent -------------------------------------------------------------


_FENCED_CODE = """\
```python
import cadquery as cq


def build_model():
    return cq.Workplane("XY").box(50.0, 40.0, 8.0)
```"""


class TestDesignerAgent:
    def test_returns_string(self):
        llm = MockLLMBackend(responses=[_FENCED_CODE])
        agent = DesignerAgent(llm=llm)
        result = agent.generate(
            prompt="a plate",
            plan=DesignPlan(geometry_type="plate"),
            patterns=[],
        )
        assert isinstance(result, str)

    def test_llm_called_once(self):
        llm = MockLLMBackend(responses=[_FENCED_CODE])
        agent = DesignerAgent(llm=llm)
        agent.generate("plate", DesignPlan(geometry_type="plate"), [])
        assert llm.call_count == 1

    def test_user_prompt_contains_original_prompt(self):
        llm = MockLLMBackend(responses=[_FENCED_CODE])
        agent = DesignerAgent(llm=llm)
        agent.generate("a 50mm bracket", DesignPlan(geometry_type="bracket"), [])
        user_prompt, _ = llm.calls[0]
        assert "50mm bracket" in user_prompt

    def test_user_prompt_contains_geometry_type(self):
        llm = MockLLMBackend(responses=[_FENCED_CODE])
        agent = DesignerAgent(llm=llm)
        plan = DesignPlan(geometry_type="flange", features=["disc body"])
        agent.generate("a flange", plan, [])
        user_prompt, _ = llm.calls[0]
        assert "flange" in user_prompt

    def test_pattern_idiom_included_in_prompt(self):
        llm = MockLLMBackend(responses=[_FENCED_CODE])
        agent = DesignerAgent(llm=llm)
        pattern = {
            "name": "plate",
            "purpose": "flat slab",
            "idiom": "cq.Workplane('XY').box(w, h, t)",
            "avoid": ["never use sphere"],
        }
        plan = DesignPlan(geometry_type="plate")
        agent.generate("a plate", plan, [pattern])
        user_prompt, _ = llm.calls[0]
        assert "cq.Workplane" in user_prompt

    def test_format_plan_includes_features(self):
        plan = DesignPlan(
            geometry_type="box",
            features=["outer shell", "lid"],
            constraints={"width_mm": 30},
        )
        text = _format_plan(plan)
        assert "box" in text
        assert "outer shell" in text
        assert "width_mm=30" in text

    def test_format_patterns_empty_list(self):
        assert _format_patterns([]) == ""

    def test_format_patterns_non_empty(self):
        p = {"name": "plate", "purpose": "flat slab", "idiom": "box()", "avoid": []}
        text = _format_patterns([p])
        assert "plate" in text
        assert "box()" in text


# -- CriticAgent ---------------------------------------------------------------


class TestCriticAgent:
    def test_approved_response(self):
        llm = MockLLMBackend(responses=["APPROVED"])
        agent = CriticAgent(llm=llm)
        result = agent.review("a box", DesignPlan(geometry_type="box"), "def build_model(): ...")
        assert isinstance(result, CriticResult)
        assert result.approved is True

    def test_rejected_with_revision(self):
        revised = "import cadquery as cq\ndef build_model():\n    return cq.Workplane('XY').box(1,1,1)"
        response = f"ISSUES: missing import\n```python\n{revised}\n```"
        llm = MockLLMBackend(responses=[response])
        agent = CriticAgent(llm=llm)
        result = agent.review("a box", DesignPlan(geometry_type="box"), "broken code")
        assert result.approved is False
        assert result.revised_code is not None
        assert "build_model" in result.revised_code

    def test_rejected_no_revision(self):
        response = "ISSUES: result variable not defined"
        llm = MockLLMBackend(responses=[response])
        agent = CriticAgent(llm=llm)
        result = agent.review("a box", DesignPlan(geometry_type="box"), "bad code")
        assert result.approved is False
        assert result.revised_code is None

    def test_llm_called_once(self):
        llm = MockLLMBackend(responses=["APPROVED"])
        agent = CriticAgent(llm=llm)
        agent.review("test", DesignPlan(), "code")
        assert llm.call_count == 1

    def test_parse_approved(self):
        r = _parse_critic_response("APPROVED")
        assert r.approved is True

    def test_parse_issues_with_code(self):
        response = "ISSUES: wrong shape\n```python\nfixed_code\n```"
        r = _parse_critic_response(response)
        assert r.approved is False
        assert r.revised_code == "fixed_code"

    def test_parse_issues_no_code(self):
        r = _parse_critic_response("ISSUES: some problem")
        assert r.approved is False
        assert r.revised_code is None

    def test_parse_ambiguous_treated_as_approved(self):
        r = _parse_critic_response("The code looks fine to me.")
        assert r.approved is True
