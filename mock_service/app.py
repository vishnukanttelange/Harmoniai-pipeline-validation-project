"""
Mock pipeline service.

Endpoints (per the assignment contract):
  POST /jobs                -> { job_id, status: "queued" }
  GET  /jobs/{job_id}       -> { job_id, status, input_type, output }
  GET  /jobs?input_type=X   -> list of the above (bonus: needed by the
                                "filter by input_type" test case)
"""

from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import init_db, get_session, Job, JobStatus
from .worker import start_workers, enqueue


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_workers()
    yield


app = FastAPI(title="Mock Pipeline Service", lifespan=lifespan)


class CreateJobRequest(BaseModel):
    input_type: str
    input_ref: Optional[str] = None
    fault_overrides: Optional[dict] = None  # test-only determinism hook, see db.py


class JobResponse(BaseModel):
    job_id: str
    status: str
    input_type: Optional[str] = None
    output: Optional[dict] = None


@app.post("/jobs", response_model=JobResponse, status_code=201)
def create_job(req: CreateJobRequest, db: Session = Depends(get_session)):
    job = Job(input_type=req.input_type, input_ref=req.input_ref, status=JobStatus.QUEUED,
              fault_overrides=req.fault_overrides)
    db.add(job)
    db.commit()
    db.refresh(job)
    enqueue(job.job_id)
    return JobResponse(job_id=job.job_id, status=job.status.value, input_type=job.input_type)


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_session)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobResponse(**job.to_dict())


@app.get("/jobs", response_model=List[JobResponse])
def list_jobs(input_type: Optional[str] = None, db: Session = Depends(get_session)):
    q = db.query(Job)
    if input_type is not None:
        q = q.filter(Job.input_type == input_type)
    jobs = q.order_by(Job.created_at.desc()).all()
    return [JobResponse(**j.to_dict()) for j in jobs]
