"""
CLI entrypoint for the batch validation harness.

Usage:
    python3 -m harness.run --base-url http://localhost:8000 \
        --fixtures harness/fixtures/golden.json

Exit code is 0 if all cases passed, 1 otherwise (so it plugs into CI).
"""

import argparse
import json
import sys

from .runner import BatchValidator, TestCase


def load_cases(fixtures_path: str) -> list:
    with open(fixtures_path) as f:
        raw = json.load(f)
    cases = []
    for item in raw:
        cases.append(TestCase(
            name=item["name"],
            input_type=item["input_type"],
            input_ref=item["input_ref"],
            expected_output=item["expected_output"],
            rel_tol=item.get("rel_tol", 1e-3),
            abs_tol=item.get("abs_tol", 1e-6),
            ignore_fields=item.get("ignore_fields"),
            timeout_s=item.get("timeout_s", 10.0),
        ))
    return cases


def main():
    parser = argparse.ArgumentParser(description="Batch validation harness for the mock pipeline service")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--fixtures", default="harness/fixtures/golden.json")
    parser.add_argument("--late-threshold-s", type=float, default=1.0)
    parser.add_argument("--json-report", help="optional path to also dump a JSON report")
    args = parser.parse_args()

    cases = load_cases(args.fixtures)
    validator = BatchValidator(base_url=args.base_url)
    report = validator.run(cases, late_threshold_s=args.late_threshold_s)

    print(report.render_text())

    if args.json_report:
        payload = {
            "metrics": report.reliability_metrics(),
            "results": [
                {
                    "name": r.case.name,
                    "category": r.category.value,
                    "job_id": r.job_id,
                    "latency_s": r.latency_s,
                    "passed": r.passed,
                    "error": r.error,
                    "mismatches": [m.__dict__ for m in (r.comparison.mismatches if r.comparison else [])],
                }
                for r in report.results
            ],
        }
        with open(args.json_report, "w") as f:
            json.dump(payload, f, indent=2)

    sys.exit(0 if report.failed == 0 else 1)


if __name__ == "__main__":
    main()
