"""
A tiny in-process async worker pool.

Real pipelines would have workers in separate processes/containers pulling
from a real queue (SQS, Celery, etc). For this mock, an in-process
ThreadPoolExecutor is enough to get genuine async/parallel behaviour
(multiple jobs "processing" concurrently, results landing out of submission
order) without bringing in infrastructure we'd just have to fake anyway.
"""

import queue
import threading
import logging

from .db import SessionLocal, Job, JobStatus
from .processing import run_pipeline

logger = logging.getLogger("mock_pipeline.worker")

NUM_WORKERS = 4
_job_queue: "queue.Queue[str]" = queue.Queue()
_started = False
_lock = threading.Lock()


def enqueue(job_id: str):
    _job_queue.put(job_id)


def _process_one(job_id: str):
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            logger.warning("worker: job %s vanished before processing", job_id)
            return

        job.status = JobStatus.PROCESSING
        db.commit()

        status, output, error, _delay = run_pipeline(
            job.input_type, job.input_ref or job_id, fault_config=job.fault_overrides
        )

        # Re-fetch in case of concurrent updates; keep it simple for a mock.
        job = db.get(Job, job_id)
        job.status = JobStatus.COMPLETED if status == "completed" else JobStatus.FAILED
        job.output = output
        job.error = error
        from datetime import datetime, timezone
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        logger.exception("worker: unhandled error processing job %s", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error = "internal worker error"
            db.commit()
    finally:
        db.close()


def _worker_loop():
    while True:
        job_id = _job_queue.get()
        try:
            _process_one(job_id)
        finally:
            _job_queue.task_done()


def start_workers():
    global _started
    with _lock:
        if _started:
            return
        for _ in range(NUM_WORKERS):
            t = threading.Thread(target=_worker_loop, daemon=True)
            t.start()
        _started = True
