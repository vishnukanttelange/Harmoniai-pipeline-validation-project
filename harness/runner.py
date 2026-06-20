"""
Batch validation harness.

Submits a batch of jobs to the mock pipeline service, polls each one to
completion (or timeout), compares the resulting output against a golden
fixture using tolerance-based comparison, and produces a structured report.

Usage (see also harness/run.py for the CLI):

    from harness.runner import TestCase, BatchValidator

    cases = [
        TestCase(name="img-1", input_type="image", input_ref="img-001.png",
                 expected_output={...}),
        ...
    ]
    validator = BatchValidator(base_url="http://localhost:8000")
    report = validator.run(cases)
    print(report.render_text())
"""

import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any

import requests

from .compare import compare_output, ComparisonResult


class Category(str, Enum):
    PASS = "pass"
    VALUE_MISMATCH = "value_mismatch"
    JOB_FAILED = "job_failed"          # pipeline itself reported failure
    TIMEOUT = "timeout"                # never reached a terminal state in time
    HTTP_ERROR = "http_error"          # submission/polling request itself errored
    LATE = "late_but_correct"          # completed correctly, but slower than `late_threshold_s`


@dataclass
class TestCase:
    name: str
    input_type: str
    input_ref: str
    expected_output: dict
    rel_tol: float = 1e-3
    abs_tol: float = 1e-6
    ignore_fields: Optional[List[str]] = None
    # Per-case override of how long to wait before declaring a timeout.
    timeout_s: float = 10.0


@dataclass
class CaseResult:
    case: TestCase
    category: Category
    job_id: Optional[str] = None
    final_status: Optional[str] = None
    comparison: Optional[ComparisonResult] = None
    latency_s: Optional[float] = None
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.category in (Category.PASS, Category.LATE)


@dataclass
class Report:
    results: List[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total) if self.total else 0.0

    def by_category(self) -> Dict[str, List[CaseResult]]:
        grouped: Dict[str, List[CaseResult]] = {}
        for r in self.results:
            grouped.setdefault(r.category.value, []).append(r)
        return grouped

    def latencies(self) -> List[float]:
        return [r.latency_s for r in self.results if r.latency_s is not None]

    def reliability_metrics(self) -> Dict[str, Any]:
        lats = self.latencies()
        metrics = {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 4),
        }
        if lats:
            sorted_lats = sorted(lats)
            metrics.update({
                "avg_latency_s": round(statistics.mean(lats), 3),
                "p50_latency_s": round(sorted_lats[len(sorted_lats) // 2], 3),
                "p95_latency_s": round(sorted_lats[min(len(sorted_lats) - 1, int(len(sorted_lats) * 0.95))], 3),
                "max_latency_s": round(max(lats), 3),
            })
        return metrics

    def render_text(self) -> str:
        lines = []
        lines.append("=" * 70)
        lines.append("BATCH VALIDATION REPORT")
        lines.append("=" * 70)

        lines.append("\nPer-input results:")
        for r in self.results:
            mark = "PASS" if r.passed else "FAIL"
            detail = ""
            if not r.passed:
                if r.error:
                    detail = f" ({r.error})"
                elif r.comparison:
                    detail = f" ({r.comparison.summary()})"
            lines.append(f"  [{mark}] {r.case.name:<20} category={r.category.value:<16} "
                          f"job_id={r.job_id}{detail}")

        lines.append("\nFailures grouped by category:")
        grouped = self.by_category()
        for cat, items in grouped.items():
            if cat == Category.PASS.value:
                continue
            lines.append(f"  {cat}: {len(items)}")
            for r in items:
                lines.append(f"    - {r.case.name}")

        lines.append("\nReliability metrics:")
        for k, v in self.reliability_metrics().items():
            lines.append(f"  {k}: {v}")

        lines.append("=" * 70)
        return "\n".join(lines)


class BatchValidator:
    def __init__(self, base_url: str, poll_interval_s: float = 0.1, session: Optional[requests.Session] = None):
        self.base_url = base_url.rstrip("/")
        self.poll_interval_s = poll_interval_s
        self.session = session or requests.Session()

    def submit(self, case: TestCase) -> Optional[str]:
        resp = self.session.post(
            f"{self.base_url}/jobs",
            json={"input_type": case.input_type, "input_ref": case.input_ref},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["job_id"]

    def poll(self, job_id: str, timeout_s: float) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        last = None
        while time.monotonic() < deadline:
            resp = self.session.get(f"{self.base_url}/jobs/{job_id}", timeout=10)
            resp.raise_for_status()
            last = resp.json()
            if last["status"] in ("completed", "failed"):
                return last
            time.sleep(self.poll_interval_s)
        return last or {"status": "timeout", "output": None}

    def _evaluate(self, case: TestCase, job_id: Optional[str], submit_start: float,
                   submit_error: Optional[str], late_threshold_s: float) -> CaseResult:
        if submit_error is not None:
            return CaseResult(case=case, category=Category.HTTP_ERROR, error=submit_error)

        try:
            final = self.poll(job_id, case.timeout_s)
        except requests.RequestException as e:
            return CaseResult(case=case, category=Category.HTTP_ERROR, job_id=job_id, error=str(e))

        latency = time.monotonic() - submit_start
        status = final.get("status")

        if status not in ("completed", "failed"):
            return CaseResult(case=case, category=Category.TIMEOUT, job_id=job_id,
                               final_status=status, latency_s=latency)

        if status == "failed":
            return CaseResult(case=case, category=Category.JOB_FAILED, job_id=job_id,
                               final_status=status, latency_s=latency,
                               error=final.get("error") or "job reported failed status")

        comparison = compare_output(
            case.expected_output, final.get("output"),
            rel_tol=case.rel_tol, abs_tol=case.abs_tol, ignore_fields=case.ignore_fields,
        )
        if not comparison.ok:
            return CaseResult(case=case, category=Category.VALUE_MISMATCH, job_id=job_id,
                               final_status=status, comparison=comparison, latency_s=latency)

        category = Category.LATE if latency > late_threshold_s else Category.PASS
        return CaseResult(case=case, category=category, job_id=job_id,
                           final_status=status, comparison=comparison, latency_s=latency)

    def run_one(self, case: TestCase, late_threshold_s: float = 1.0) -> CaseResult:
        """Submit + poll a single case to completion. Useful for ad-hoc/one-off checks."""
        start = time.monotonic()
        try:
            job_id = self.submit(case)
        except requests.RequestException as e:
            return self._evaluate(case, None, start, str(e), late_threshold_s)
        return self._evaluate(case, job_id, start, None, late_threshold_s)

    def run(self, cases: List[TestCase], late_threshold_s: float = 1.0, max_workers: int = 16) -> Report:
        """Submit the entire batch first (mirroring real-world async/parallel job
        submission), then poll all jobs concurrently. This matters: polling
        cases one-at-a-time would serialize what's actually a parallel
        pipeline and make the harness far slower / hide concurrency bugs.
        """
        n = len(cases)
        job_ids: List[Optional[str]] = [None] * n
        submit_errors: List[Optional[str]] = [None] * n
        submit_starts: List[float] = [0.0] * n

        # 1) Submit the whole batch (also in parallel, since real clients
        #    would not necessarily submit serially either).
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_idx = {}
            for i, case in enumerate(cases):
                submit_starts[i] = time.monotonic()
                future_to_idx[pool.submit(self.submit, case)] = i
            for fut in as_completed(future_to_idx):
                i = future_to_idx[fut]
                try:
                    job_ids[i] = fut.result()
                except requests.RequestException as e:
                    submit_errors[i] = str(e)

        # 2) Poll all submitted jobs concurrently to completion/timeout.
        results: List[Optional[CaseResult]] = [None] * n
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_idx = {
                pool.submit(self._evaluate, cases[i], job_ids[i], submit_starts[i],
                            submit_errors[i], late_threshold_s): i
                for i in range(n)
            }
            for fut in as_completed(future_to_idx):
                i = future_to_idx[fut]
                results[i] = fut.result()

        return Report(results=results)
