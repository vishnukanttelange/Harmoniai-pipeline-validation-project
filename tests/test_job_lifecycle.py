"""
Integration tests against the mock service + its Postgres database.

These hit the real FastAPI app (in-process) and the real `jobs` table -
no mocking of the DB layer - per the assignment's requirement to test
"the mock service and its Postgres database".
"""

from datetime import datetime, timezone

from mock_service.db import Job, JobStatus


def test_submitting_a_job_creates_expected_row_and_initial_state(client, db_session):
    resp = client.post("/jobs", json={"input_type": "image", "input_ref": "t1.png"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "queued"
    assert body["input_type"] == "image"
    job_id = body["job_id"]

    # Verify the row actually exists in Postgres with the right shape.
    row = db_session.get(Job, job_id)
    assert row is not None
    assert row.input_type == "image"
    assert row.input_ref == "t1.png"
    assert row.output is None
    # The background worker may have already picked it up by the time we
    # check, so the only guarantee we can make is "queued or processing" -
    # asserting strictly "queued" here would be flaky depending on
    # scheduling, and the assignment explicitly calls out flake-free tests.
    assert row.status in (JobStatus.QUEUED, JobStatus.PROCESSING)


def test_completed_job_returns_its_output_on_retrieval(client, db_session):
    # Insert a completed job directly, bypassing the async worker/fault
    # injection entirely. This isolates exactly what the test name says:
    # "does GET return the output for a completed job" - not "does the
    # pipeline eventually succeed", which is covered separately by the
    # harness against fixtures.
    job = Job(
        job_id="11111111-1111-1111-1111-111111111111",
        input_type="audio",
        input_ref="known.wav",
        status=JobStatus.COMPLETED,
        output={"measurements": {"score": 50.0, "confidence": 0.9, "duration_ms": 120.0},
                "metadata": {"input_type": "audio", "pipeline_version": "mock-1.0.0"}},
        completed_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    db_session.commit()

    resp = client.get(f"/jobs/{job.job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["output"]["measurements"]["score"] == 50.0
    assert body["output"]["metadata"]["input_type"] == "audio"


def test_get_unknown_job_returns_404(client):
    resp = client.get("/jobs/does-not-exist")
    assert resp.status_code == 404


def test_filtering_jobs_by_input_type_returns_only_matching_ones(client, db_session):
    jobs = [
        Job(job_id=f"type-test-{i}", input_type=t, input_ref=f"ref-{i}", status=JobStatus.QUEUED)
        for i, t in enumerate(["image", "audio", "image", "log", "image"])
    ]
    db_session.add_all(jobs)
    db_session.commit()

    resp = client.get("/jobs", params={"input_type": "image"})
    assert resp.status_code == 200
    body = resp.json()

    assert len(body) == 3
    assert all(j["input_type"] == "image" for j in body)
    returned_ids = {j["job_id"] for j in body}
    expected_ids = {j.job_id for j in jobs if j.input_type == "image"}
    assert returned_ids == expected_ids


def test_filtering_by_input_type_with_no_matches_returns_empty_list(client, db_session):
    db_session.add(Job(job_id="solo-job", input_type="video", input_ref="x", status=JobStatus.QUEUED))
    db_session.commit()

    resp = client.get("/jobs", params={"input_type": "nonexistent-type"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_unfiltered_list_returns_all_jobs(client, db_session):
    db_session.add_all([
        Job(job_id="all-1", input_type="image", input_ref="a", status=JobStatus.QUEUED),
        Job(job_id="all-2", input_type="audio", input_ref="b", status=JobStatus.QUEUED),
    ])
    db_session.commit()

    resp = client.get("/jobs")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
