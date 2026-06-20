"""
A genuine end-to-end async test: submit -> poll -> completed, going through
the real background worker (not a direct DB insert like in
test_job_lifecycle.py). Uses `fault_overrides` to force a deterministic,
always-succeeds outcome - otherwise this test would be flaky against the
mock's default ~5% fail / ~10% wrong-value injection rates, which violates
the "passes reliably when run repeatedly" requirement.
"""

import time


def _poll(client, job_id, timeout_s=5.0, interval_s=0.05):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(f"/jobs/{job_id}")
        body = resp.json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(interval_s)
    raise AssertionError(f"job {job_id} did not reach a terminal state within {timeout_s}s")


def test_job_progresses_from_queued_to_completed_via_real_worker(client):
    resp = client.post("/jobs", json={
        "input_type": "image",
        "input_ref": "deterministic-success.png",
        "fault_overrides": {"fail_rate": 0.0, "wrong_rate": 0.0, "late_rate": 0.0,
                             "min_delay_s": 0.01, "max_delay_s": 0.05},
    })
    assert resp.status_code == 201
    job_id = resp.json()["job_id"]

    final = _poll(client, job_id)

    assert final["status"] == "completed"
    assert final["output"] is not None
    assert "measurements" in final["output"]
    assert "score" in final["output"]["measurements"]


def test_job_can_be_forced_to_fail_deterministically(client):
    resp = client.post("/jobs", json={
        "input_type": "log",
        "input_ref": "deterministic-failure.log",
        "fault_overrides": {"fail_rate": 1.0, "min_delay_s": 0.01, "max_delay_s": 0.02},
    })
    job_id = resp.json()["job_id"]

    final = _poll(client, job_id)

    assert final["status"] == "failed"
    assert final["output"] is None
