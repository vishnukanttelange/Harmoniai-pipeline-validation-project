"""
Regenerates harness/fixtures/golden.json.

In a real system, golden/expected outputs would come from a trusted oracle
(e.g. manually verified results, or a previous known-good pipeline run) -
not from the same code path being tested. Here, since the mock pipeline's
"true" (uncorrupted) values are a pure deterministic function of
(input_type, input_ref), we can generate golden fixtures once and check
them into the repo, then treat them as fixed ground truth from then on.

Run from the repo root:
    python3 -m harness.fixtures.generate_golden
"""

import json
import os

from mock_service.processing import true_measurements, PIPELINE_VERSION

CASES = [
    ("image", "img-001.png"),
    ("image", "img-002.png"),
    ("audio", "a1.wav"),
    ("audio", "a2.wav"),
    ("log", "server-2024-01-01.log"),
    ("log", "server-2024-01-02.log"),
    ("image", "img-003.png"),
    ("video", "clip-001.mp4"),
]

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "golden.json")


def main():
    golden = []
    for input_type, input_ref in CASES:
        measurements = true_measurements(input_type, input_ref)
        golden.append({
            "name": f"{input_type}:{input_ref}",
            "input_type": input_type,
            "input_ref": input_ref,
            "expected_output": {
                "measurements": measurements,
                "metadata": {"input_type": input_type, "pipeline_version": PIPELINE_VERSION},
            },
        })

    with open(OUTPUT_PATH, "w") as f:
        json.dump(golden, f, indent=2)
    print(f"wrote {len(golden)} fixtures to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
