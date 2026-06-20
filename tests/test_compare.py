"""
Pure unit tests for harness/compare.py - no DB, no HTTP, no async.
These should be the fastest, most deterministic tests in the suite.
"""

from harness.compare import numbers_close, compare_output, compare_values, FieldMismatch


# ---- numbers_close ----

def test_numbers_close_exact_match():
    assert numbers_close(10.0, 10.0)


def test_numbers_close_within_relative_tolerance():
    # 0.1% default relative tolerance
    assert numbers_close(1000.0, 1000.5)


def test_numbers_close_outside_relative_tolerance():
    assert not numbers_close(1000.0, 1010.0)


def test_numbers_close_near_zero_uses_absolute_tolerance():
    assert numbers_close(0.0, 0.0000001)
    assert not numbers_close(0.0, 0.01)


def test_numbers_close_custom_tolerance():
    assert numbers_close(100.0, 105.0, rel_tol=0.1)
    assert not numbers_close(100.0, 105.0, rel_tol=0.01)


# ---- compare_output: happy paths ----

def test_compare_output_identical_matches():
    expected = {"measurements": {"score": 42.0, "confidence": 0.9}}
    actual = {"measurements": {"score": 42.0, "confidence": 0.9}}
    result = compare_output(expected, actual)
    assert result.ok
    assert result.mismatches == []


def test_compare_output_within_tolerance_matches():
    expected = {"score": 100.0}
    actual = {"score": 100.05}
    result = compare_output(expected, actual)
    assert result.ok


# ---- compare_output: failure modes ----

def test_compare_output_numeric_mismatch_outside_tolerance():
    expected = {"score": 100.0}
    actual = {"score": 150.0}
    result = compare_output(expected, actual)
    assert not result.ok
    assert len(result.mismatches) == 1
    assert result.mismatches[0].path == "$.score"


def test_compare_output_missing_field_is_a_mismatch():
    expected = {"score": 1.0, "confidence": 0.5}
    actual = {"score": 1.0}
    result = compare_output(expected, actual)
    assert not result.ok
    assert any("missing field" in m.reason for m in result.mismatches)


def test_compare_output_actual_none_is_a_mismatch():
    result = compare_output({"score": 1.0}, None)
    assert not result.ok
    assert result.mismatches[0].path == "$"


def test_compare_output_nested_dict_mismatch_reports_full_path():
    expected = {"measurements": {"nested": {"value": 10.0}}}
    actual = {"measurements": {"nested": {"value": 999.0}}}
    result = compare_output(expected, actual)
    assert not result.ok
    assert result.mismatches[0].path == "$.measurements.nested.value"


def test_compare_output_list_length_mismatch():
    result = compare_output({"items": [1, 2, 3]}, {"items": [1, 2]})
    assert not result.ok
    assert "list length mismatch" in result.mismatches[0].reason


def test_compare_output_list_elementwise_tolerance():
    expected = {"items": [1.0, 2.0, 3.0]}
    actual = {"items": [1.0001, 2.0001, 3.0001]}
    assert compare_output(expected, actual).ok


def test_compare_output_string_field_exact_match_required():
    assert compare_output({"label": "cat"}, {"label": "cat"}).ok
    assert not compare_output({"label": "cat"}, {"label": "dog"}).ok


# ---- ignore_fields ----

def test_compare_output_ignore_fields_skips_listed_paths():
    expected = {"measurements": {"score": 1.0}, "metadata": {"pipeline_version": "v1"}}
    actual = {"measurements": {"score": 1.0}, "metadata": {"pipeline_version": "v2-different"}}
    result = compare_output(expected, actual, ignore_fields=["$.metadata.pipeline_version"])
    assert result.ok


def test_compare_output_ignore_fields_does_not_suppress_other_mismatches():
    expected = {"measurements": {"score": 1.0}, "metadata": {"pipeline_version": "v1"}}
    actual = {"measurements": {"score": 999.0}, "metadata": {"pipeline_version": "v2"}}
    result = compare_output(expected, actual, ignore_fields=["$.metadata.pipeline_version"])
    assert not result.ok
    assert all(m.path != "$.metadata.pipeline_version" for m in result.mismatches)


# ---- compare_values directly ----

def test_compare_values_type_mismatch_dict_vs_other():
    mismatches: list = []
    compare_values({"a": 1}, "not a dict", "$", 1e-3, 1e-6, mismatches)
    assert len(mismatches) == 1
    assert "expected object" in mismatches[0].reason
