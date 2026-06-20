"""
Comparison logic: compares an actual pipeline output against a golden/expected
result, using numeric tolerance instead of exact equality.

Kept as a standalone, dependency-free module (no DB/HTTP) so it can be unit
tested in isolation and reused by the harness.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


# Default tolerances, can be overridden per-field by the caller.
DEFAULT_REL_TOL = 1e-3   # 0.1% relative tolerance
DEFAULT_ABS_TOL = 1e-6   # floor for values near zero


@dataclass
class FieldMismatch:
    path: str
    expected: Any
    actual: Any
    reason: str


@dataclass
class ComparisonResult:
    ok: bool
    mismatches: list = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return "match"
        return "; ".join(f"{m.path}: {m.reason}" for m in self.mismatches)


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def numbers_close(expected: float, actual: float, rel_tol: float = DEFAULT_REL_TOL,
                   abs_tol: float = DEFAULT_ABS_TOL) -> bool:
    """True if `actual` is within tolerance of `expected`.

    Uses combined relative+absolute tolerance (similar to math.isclose) so
    that both very small and very large values are handled sensibly:
    |actual - expected| <= max(abs_tol, rel_tol * max(|expected|, |actual|))
    """
    diff = abs(actual - expected)
    threshold = max(abs_tol, rel_tol * max(abs(expected), abs(actual)))
    return diff <= threshold


def compare_values(expected: Any, actual: Any, path: str, rel_tol: float, abs_tol: float,
                    mismatches: list) -> None:
    if _is_number(expected) and _is_number(actual):
        if not numbers_close(expected, actual, rel_tol, abs_tol):
            mismatches.append(FieldMismatch(
                path=path, expected=expected, actual=actual,
                reason=f"numeric mismatch (expected={expected}, actual={actual}, "
                       f"rel_tol={rel_tol}, abs_tol={abs_tol})",
            ))
        return

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            mismatches.append(FieldMismatch(path, expected, actual, "expected object, got different type"))
            return
        for key, exp_val in expected.items():
            if key not in actual:
                mismatches.append(FieldMismatch(f"{path}.{key}", exp_val, None, "missing field"))
                continue
            compare_values(exp_val, actual[key], f"{path}.{key}", rel_tol, abs_tol, mismatches)
        return

    if isinstance(expected, list):
        if not isinstance(actual, list):
            mismatches.append(FieldMismatch(path, expected, actual, "expected list, got different type"))
            return
        if len(expected) != len(actual):
            mismatches.append(FieldMismatch(path, len(expected), len(actual), "list length mismatch"))
            return
        for i, (e, a) in enumerate(zip(expected, actual)):
            compare_values(e, a, f"{path}[{i}]", rel_tol, abs_tol, mismatches)
        return

    # Fallback: exact equality for strings/bools/None/etc.
    if expected != actual:
        mismatches.append(FieldMismatch(path, expected, actual, "value mismatch"))


def compare_output(expected: dict, actual: Optional[dict], rel_tol: float = DEFAULT_REL_TOL,
                    abs_tol: float = DEFAULT_ABS_TOL, ignore_fields: Optional[list] = None) -> ComparisonResult:
    """Compare an actual job output against the golden/expected output.

    `ignore_fields` is a list of dotted paths (e.g. "metadata.pipeline_version")
    to skip entirely - useful for fields like timestamps or version strings
    that legitimately vary run-to-run.
    """
    ignore_fields = set(ignore_fields or [])
    mismatches: list = []

    if actual is None:
        return ComparisonResult(ok=False, mismatches=[
            FieldMismatch("$", expected, None, "actual output is missing (job not completed?)")
        ])

    compare_values(expected, actual, "$", rel_tol, abs_tol, mismatches)
    mismatches = [m for m in mismatches if m.path not in ignore_fields
                  and not any(m.path.startswith(f"{f}.") or m.path == f for f in ignore_fields)]

    return ComparisonResult(ok=len(mismatches) == 0, mismatches=mismatches)
