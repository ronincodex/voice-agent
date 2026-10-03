"""Phase 6 integration test orchestrator.

Runs all Phase 6 unit tests in sequence. Each test is a standalone
Python script that exits non-zero on failure.
"""

import subprocess
import sys

TESTS = [
    ("tests/unit/test_barge_in.py", "Barge-in defense and merger behavior"),
]


def main() -> None:
    failed: list[str] = []
    for path, label in TESTS:
        result = subprocess.run(
            [sys.executable, path],
            capture_output=True,
            text=True,
        )
        status = "PASS" if result.returncode == 0 else "FAIL"
        print(f"[{status}] {label} ({path})")
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            failed.append(path)

    if failed:
        print(f"\n{len(failed)} test(s) failed")
        sys.exit(1)
    print("\nAll Phase 6 integration tests passed")


if __name__ == "__main__":
    main()
