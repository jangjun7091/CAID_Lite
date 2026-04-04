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
    "volume": 1000.0,
    "face_count": 6,
    "bbox": [10.0, 10.0, 10.0],
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
