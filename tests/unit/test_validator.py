"""Tests for GeometryValidator and ValidationResult.

All tests pass plain dicts to GeometryValidator.validate() — no CadQuery
installation required.
"""

from __future__ import annotations

import pytest

from caid_lite.validator.geometry import GeometryValidator, ValidationResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

_VALID_METRICS = {
    "is_valid": True,
    "is_solid": True,
    "body_count": 1,
    "volume": 1000.0,
    "face_count": 6,
    "bbox": [10.0, 10.0, 10.0],
    "surface_area": 600.0,
    "aspect_ratio": 1.0,
    "point_count": 120,
    "spread_cv": 0.35,
}


def _metrics(**overrides) -> dict:
    """Return a copy of _VALID_METRICS with the given fields overridden."""
    return {**_VALID_METRICS, **overrides}


@pytest.fixture
def validator() -> GeometryValidator:
    return GeometryValidator()


# ── ValidationResult ──────────────────────────────────────────────────────────


class TestValidationResult:
    def test_to_dict_contains_required_keys(self):
        r = ValidationResult(valid=True, errors=[], warnings=[], metrics=_VALID_METRICS)
        d = r.to_dict()
        for key in ("valid", "errors", "warnings", "metrics"):
            assert key in d

    def test_format_errors_joins_with_newlines(self):
        r = ValidationResult(valid=False, errors=["err1", "err2"], warnings=[], metrics={})
        assert r.format_errors() == "err1\nerr2"

    def test_format_errors_empty_string_when_valid(self):
        r = ValidationResult(valid=True, errors=[], warnings=[], metrics={})
        assert r.format_errors() == ""

    def test_to_dict_reflects_valid_flag(self):
        r = ValidationResult(valid=False, errors=["bad"], warnings=[], metrics={})
        assert r.to_dict()["valid"] is False


# ── GeometryValidator — happy path ────────────────────────────────────────────


class TestGeometryValidatorValid:
    def test_valid_metrics_returns_valid(self, validator):
        result = validator.validate(_VALID_METRICS)
        assert result.valid is True
        assert result.errors == []

    def test_valid_metrics_returns_no_warnings_for_normal_shape(self, validator):
        result = validator.validate(_VALID_METRICS)
        assert result.warnings == []

    def test_metrics_preserved_in_result(self, validator):
        result = validator.validate(_VALID_METRICS)
        assert result.metrics["volume"] == 1000.0


# ── GeometryValidator — hard checks ──────────────────────────────────────────


class TestGeometryValidatorHardChecks:
    def test_is_valid_false_fails(self, validator):
        result = validator.validate(_metrics(is_valid=False))
        assert result.valid is False
        assert any("isValid" in e for e in result.errors)

    def test_is_solid_false_fails(self, validator):
        result = validator.validate(_metrics(is_solid=False))
        assert result.valid is False
        assert any("solid" in e.lower() for e in result.errors)

    def test_zero_volume_fails(self, validator):
        result = validator.validate(_metrics(volume=0.0))
        assert result.valid is False
        assert any("volume" in e.lower() for e in result.errors)

    def test_near_zero_volume_fails(self, validator):
        result = validator.validate(_metrics(volume=1e-9))
        assert result.valid is False

    def test_volume_just_above_threshold_passes(self, validator):
        result = validator.validate(_metrics(volume=1e-5))
        assert result.valid is True

    def test_disconnected_bodies_fails(self, validator):
        result = validator.validate(_metrics(body_count=3))
        assert result.valid is False
        assert any("disconnected" in e for e in result.errors)

    def test_single_body_passes(self, validator):
        result = validator.validate(_metrics(body_count=1))
        assert result.valid is True
        assert not any("disconnected" in e for e in result.errors)

    def test_body_count_none_does_not_fail(self, validator):
        """body_count 필드가 없으면 (구버전 runner) 에러 없이 통과."""
        m = {k: v for k, v in _VALID_METRICS.items() if k != "body_count"}
        result = validator.validate(m)
        assert result.valid is True

    def test_multiple_hard_failures_all_reported(self, validator):
        result = validator.validate(_metrics(is_valid=False, is_solid=False, volume=0.0))
        assert result.valid is False
        assert len(result.errors) == 3

    def test_single_hard_failure_does_not_produce_warning(self, validator):
        # Errors and warnings are separate lists
        result = validator.validate(_metrics(is_valid=False))
        assert not any("isValid" in w for w in result.warnings)


# ── GeometryValidator — soft checks ──────────────────────────────────────────


class TestGeometryValidatorSoftChecks:
    def test_low_face_count_produces_warning(self, validator):
        result = validator.validate(_metrics(face_count=2))
        assert result.valid is True  # still valid
        assert len(result.warnings) >= 1
        assert any("face" in w.lower() for w in result.warnings)

    def test_degenerate_bbox_produces_warning(self, validator):
        result = validator.validate(_metrics(bbox=[0.0, 10.0, 10.0]))
        assert result.valid is True  # still valid
        assert len(result.warnings) >= 1
        assert any("bounding" in w.lower() or "bbox" in w.lower() or "dimension" in w.lower() for w in result.warnings)

    def test_warnings_do_not_make_result_invalid(self, validator):
        result = validator.validate(_metrics(face_count=1, bbox=[0.0, 5.0, 5.0]))
        assert result.valid is True

    def test_normal_shape_has_no_warnings(self, validator):
        result = validator.validate(_VALID_METRICS)
        assert result.warnings == []


# ── GeometryValidator — Compound solid (boolean ops) ─────────────────────────


class TestGeometryValidatorCompoundSolid:
    """Boolean operations (.hole(), .cut()) produce cq.Compound, not cq.Solid.

    The fixed runner sets is_solid=True whenever len(shape.Solids()) > 0,
    so these metrics must pass validation.
    """

    def test_compound_solid_metrics_passes(self, validator):
        # Simulates metrics from .box().hole() or .cylinder().hole() --
        # is_solid=True because shape.Solids() is non-empty even though
        # .val() returns cq.Compound after boolean subtraction.
        metrics = {
            "is_valid": True,
            "is_solid": True,
            "volume": 9800.0,   # box minus hole volume
            "face_count": 10,   # box faces + hole cylinder faces
            "bbox": [60.0, 40.0, 6.0],
        }
        result = validator.validate(metrics)
        assert result.valid is True
        assert result.errors == []

    def test_compound_zero_volume_still_fails(self, validator):
        # is_solid=True but volume=0 must still be rejected.
        metrics = {
            "is_valid": True,
            "is_solid": True,
            "volume": 0.0,
            "face_count": 10,
            "bbox": [60.0, 40.0, 6.0],
        }
        result = validator.validate(metrics)
        assert result.valid is False
        assert any("volume" in e.lower() for e in result.errors)

    def test_wire_compound_no_solid_fails(self, validator):
        # A Compound of wires or faces (e.g. an unclosed sketch) has no
        # cq.Solid children, so the fixed runner emits is_solid=False.
        # The validator must still reject it.
        metrics = {
            "is_valid": True,
            "is_solid": False,
            "volume": 0.0,
            "face_count": 1,
            "bbox": [10.0, 10.0, 0.0],
        }
        result = validator.validate(metrics)
        assert result.valid is False
        assert any("solid" in e.lower() for e in result.errors)


# ── GeometryValidator — missing / empty metrics ───────────────────────────────


class TestGeometryValidatorMissingMetrics:
    def test_none_metrics_returns_invalid(self, validator):
        result = validator.validate(None)
        assert result.valid is False
        assert len(result.errors) == 1

    def test_empty_dict_returns_invalid(self, validator):
        result = validator.validate({})
        assert result.valid is False

    def test_none_metrics_error_is_descriptive(self, validator):
        result = validator.validate(None)
        assert len(result.errors[0]) > 20


# ── GeometryValidator — parameter sanity checks ───────────────────────────────


class TestGeometryValidatorSanityChecks:
    """Dimension and parameter range sanity checks.

    Hard limit: any bbox dim > 10 000 mm (unit error)
    Soft limit: any bbox dim > 2 000 mm (suspicious)
    Soft limit: min nonzero bbox dim < 0.05 mm (too thin)
    Soft limit: aspect_ratio > 200 (very elongated)
    """

    def test_extreme_dimension_hard_failure(self, validator):
        # 15 000 mm = 15 m → must be a unit error
        result = validator.validate(_metrics(bbox=[15_000.0, 40.0, 10.0]))
        assert result.valid is False
        assert any("extreme dimension" in e.lower() or "10" in e for e in result.errors)

    def test_dimension_exactly_at_hard_limit_fails(self, validator):
        result = validator.validate(_metrics(bbox=[10_001.0, 10.0, 10.0]))
        assert result.valid is False

    def test_dimension_at_hard_limit_boundary_passes(self, validator):
        # Exactly 10 000 mm is the boundary — should NOT trigger the hard error
        result = validator.validate(_metrics(bbox=[10_000.0, 10.0, 10.0]))
        assert result.valid is True

    def test_large_dimension_warns(self, validator):
        # 2 500 mm is large but under 10 000 mm — warning only
        result = validator.validate(_metrics(bbox=[2_500.0, 40.0, 10.0]))
        assert result.valid is True
        assert any("large dimension" in w.lower() or "mm" in w for w in result.warnings)

    def test_normal_dimension_no_sanity_warning(self, validator):
        result = validator.validate(_VALID_METRICS)
        sanity_warns = [w for w in result.warnings if "dimension" in w.lower() or "aspect" in w.lower()]
        assert sanity_warns == []

    def test_very_thin_dimension_warns(self, validator):
        # 0.01 mm is extremely thin → soft warning
        result = validator.validate(_metrics(bbox=[100.0, 50.0, 0.01]))
        assert result.valid is True
        assert any("thin" in w.lower() or "0.01" in w for w in result.warnings)

    def test_dimension_just_above_thin_threshold_no_warn(self, validator):
        result = validator.validate(_metrics(bbox=[100.0, 50.0, 0.06]))
        thin_warns = [w for w in result.warnings if "thin" in w.lower()]
        assert thin_warns == []

    def test_high_aspect_ratio_warns(self, validator):
        # bbox [500, 1, 1] → aspect ratio 500 > 200
        result = validator.validate(_metrics(bbox=[500.0, 1.0, 1.0]))
        assert result.valid is True
        assert any("aspect ratio" in w.lower() for w in result.warnings)

    def test_acceptable_aspect_ratio_no_warn(self, validator):
        # bbox [200, 10, 5] → aspect ratio 40, fine
        result = validator.validate(_metrics(bbox=[200.0, 10.0, 5.0]))
        aspect_warns = [w for w in result.warnings if "aspect" in w.lower()]
        assert aspect_warns == []

    def test_multiple_sanity_issues_all_reported(self, validator):
        # Large dimension AND high aspect ratio
        result = validator.validate(_metrics(bbox=[3_000.0, 5.0, 5.0]))
        assert result.valid is True
        assert len(result.warnings) >= 2

    def test_metrics_without_aspect_ratio_key_no_crash(self, validator):
        m = {k: v for k, v in _VALID_METRICS.items() if k != "aspect_ratio"}
        result = validator.validate(m)
        assert result.valid is True  # should not crash


# ── GeometryValidator — surface distribution metrics ─────────────────────────


class TestGeometryValidatorSurfaceMetrics:
    """Point distribution (spread_cv) and surface area checks.

    spread_cv > 0.85 → soft warning (irregular surface)
    surface_area present → stored in metrics dict, no check required
    """

    def test_normal_spread_cv_no_warning(self, validator):
        result = validator.validate(_VALID_METRICS)
        spread_warns = [w for w in result.warnings if "spread" in w.lower() or "distribution" in w.lower()]
        assert spread_warns == []

    def test_high_spread_cv_produces_warning(self, validator):
        result = validator.validate(_metrics(spread_cv=0.92))
        assert result.valid is True   # soft check — does not block
        assert any("distribution" in w.lower() or "spread" in w.lower() for w in result.warnings)

    def test_spread_cv_at_threshold_no_warning(self, validator):
        # Exactly at 0.85 — should NOT warn
        result = validator.validate(_metrics(spread_cv=0.85))
        spread_warns = [w for w in result.warnings if "spread" in w.lower() or "distribution" in w.lower()]
        assert spread_warns == []

    def test_spread_cv_just_above_threshold_warns(self, validator):
        result = validator.validate(_metrics(spread_cv=0.86))
        assert any("spread" in w.lower() or "distribution" in w.lower() for w in result.warnings)

    def test_missing_spread_cv_no_crash(self, validator):
        m = {k: v for k, v in _VALID_METRICS.items() if k != "spread_cv"}
        result = validator.validate(m)
        assert result.valid is True

    def test_none_spread_cv_no_crash(self, validator):
        result = validator.validate(_metrics(spread_cv=None))
        assert result.valid is True

    def test_surface_area_preserved_in_metrics(self, validator):
        result = validator.validate(_VALID_METRICS)
        assert result.metrics.get("surface_area") == 600.0

    def test_point_count_preserved_in_metrics(self, validator):
        result = validator.validate(_VALID_METRICS)
        assert result.metrics.get("point_count") == 120

    def test_aspect_ratio_preserved_in_metrics(self, validator):
        result = validator.validate(_VALID_METRICS)
        assert result.metrics.get("aspect_ratio") == 1.0

    def test_full_metrics_with_all_new_fields_passes(self, validator):
        # Simulate realistic runner output for a 50x40x6 plate
        metrics = {
            "is_valid": True,
            "is_solid": True,
            "volume": 12_000.0,
            "face_count": 6,
            "bbox": [50.0, 40.0, 6.0],
            "surface_area": 5_080.0,
            "aspect_ratio": 8.33,
            "point_count": 240,
            "spread_cv": 0.42,
        }
        result = validator.validate(metrics)
        assert result.valid is True
        assert result.errors == []
