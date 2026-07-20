# -*- coding: utf-8 -*-
"""Runs every test_*.py in this directory as a separate subprocess (they're standalone
scripts, not pytest) and reports a pass/fail summary. Each gets its own fresh, isolated
STATS_DIR via _bootstrap.py, so tests never interfere with each other or touch the real
stats.json. Exits non-zero if any test fails, for CI.

    python3 tests/run_all.py
"""
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

def main() -> int:
    test_files = sorted(TESTS_DIR.glob("test_*.py"))
    if not test_files:
        print("No test_*.py files found.")
        return 1

    failures = []
    for path in test_files:
        print(f"=== {path.name} ===", flush=True)
        result = subprocess.run([sys.executable, str(path)])
        if result.returncode != 0:
            failures.append(path.name)
        print()

    print("=" * 60)
    print(f"{len(test_files) - len(failures)}/{len(test_files)} test files passed")
    if failures:
        print("FAILED:")
        for name in failures:
            print(f"  - {name}")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
