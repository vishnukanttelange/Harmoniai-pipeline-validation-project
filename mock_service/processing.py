"""
Simulates the "real" multi-stage pipeline's numeric output.

This is intentionally a stand-in for whatever the real pipeline does. Given an
input_type + input_ref, it deterministically derives a "true" set of
measurements (so the harness's golden files can predict them), then -
depending on injected fault config - may:
  - return the correct output (most common case)
  - return output with one or more fields nudged outside tolerance ("wrong")
  - take an unusually long time ("late")
  - raise / return a failure ("failed")

Determinism: the "true" values are derived from a stable hash of
(input_type, input_ref) so that a golden/expected fixture can be computed
once and reused across test runs, instead of needing a live oracle.
"""

import hashlib
import random
import time


PIPELINE_VERSION = "mock-1.0.0"

# Fault-injection rates. Tunable via env/config for different test scenarios.
DEFAULT_FAULT_CONFIG = {
    "fail_rate": 0.05,       # job fails outright
    "wrong_rate": 0.10,      # job completes but with bad numeric values
    "late_rate": 0.10,       # job takes much longer than normal
    "min_delay_s": 0.05,
    "max_delay_s": 0.4,
    "late_extra_s": 1.0,
}


def _seed_for(input_type: str, input_ref: str) -> int:
    digest = hashlib.sha256(f"{input_type}:{input_ref}".encode()).hexdigest()
    return int(digest[:8], 16)


def true_measurements(input_type: str, input_ref: str) -> dict:
    """Deterministically-derived 'correct' measurements for a given input.

    This is what a golden/expected fixture should contain for the harness
    to compare against.
    """
    rng = random.Random(_seed_for(input_type, input_ref))
    base = {
        "score": round(rng.uniform(0, 100), 3),
        "confidence": round(rng.uniform(0.5, 1.0), 4),
        "duration_ms": round(rng.uniform(10, 500), 1),
    }
    return base


def run_pipeline(input_type: str, input_ref: str, fault_config: dict | None = None):
    """Simulate running the job. Returns (status, output_dict_or_None, error_or_None, processing_seconds).

    status is one of "completed" / "failed".
    """
    cfg = {**DEFAULT_FAULT_CONFIG, **(fault_config or {})}
    rng = random.Random(_seed_for(input_type, input_ref) ^ 0xA5A5A5A5)

    delay = rng.uniform(cfg["min_delay_s"], cfg["max_delay_s"])
    is_late = rng.random() < cfg["late_rate"]
    if is_late:
        delay += cfg["late_extra_s"]

    time.sleep(delay)

    if rng.random() < cfg["fail_rate"]:
        return "failed", None, "pipeline stage 2 (transform) raised an internal error", delay

    measurements = true_measurements(input_type, input_ref)

    if rng.random() < cfg["wrong_rate"]:
        # Corrupt one field well outside any reasonable tolerance.
        field = rng.choice(list(measurements.keys()))
        measurements = dict(measurements)
        measurements[field] = measurements[field] * rng.choice([0, 3.5, -1])

    output = {
        "measurements": measurements,
        "metadata": {
            "input_type": input_type,
            "pipeline_version": PIPELINE_VERSION,
        },
    }
    return "completed", output, None, delay
