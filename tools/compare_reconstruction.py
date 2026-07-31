"""Compare released and reconstructed metric CSVs.

Small differences in numeric formatting are allowed.

Run:
  python tools/compare_reconstruction.py results/confirmatory_gpt reproduced/gpt
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

TABLES = ("per_turn.csv", "per_session.csv", "per_replicate.csv")


def _numeric(value: str) -> float | None:
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def compare_csv(expected: Path, actual: Path, *, abs_tol: float) -> list[str]:
    with expected.open(newline="") as f:
        expected_rows = list(csv.DictReader(f))
    with actual.open(newline="") as f:
        actual_rows = list(csv.DictReader(f))
    failures = []
    if len(expected_rows) != len(actual_rows):
        return [f"row count: expected {len(expected_rows)}, observed {len(actual_rows)}"]
    if not expected_rows and not actual_rows:
        return failures
    if list(expected_rows[0]) != list(actual_rows[0]):
        return [f"column order differs: {list(expected_rows[0])} != {list(actual_rows[0])}"]
    for row_index, (left, right) in enumerate(zip(expected_rows, actual_rows), start=2):
        for column in left:
            if left[column] == right[column]:
                continue
            left_number, right_number = _numeric(left[column]), _numeric(right[column])
            if (left_number is not None and right_number is not None
                    and math.isclose(left_number, right_number, rel_tol=0.0, abs_tol=abs_tol)):
                continue
            failures.append(
                f"row {row_index} column {column}: {left[column]!r} != {right[column]!r}"
            )
            if len(failures) >= 20:
                return failures
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    parser.add_argument("--abs-tol", type=float, default=1e-12)
    args = parser.parse_args()
    failed = False
    for table in TABLES:
        failures = compare_csv(args.expected / table, args.actual / table, abs_tol=args.abs_tol)
        if failures:
            failed = True
            print(f"FAIL {table}")
            for failure in failures:
                print(f"  {failure}")
        else:
            print(f"PASS {table}: exact non-numeric fields; numeric abs_tol={args.abs_tol:g}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
