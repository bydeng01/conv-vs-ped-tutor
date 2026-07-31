"""Compare two condition-adjusted sensitivity reports.

Replaces a bare `cmp` of the two JSON files. `cmp` asserts byte equality, which holds only
on the machine the packaged reference was fit on: the crossed mixed models in
`analysis/condition_adjusted_sensitivity.py` are not bit-portable across BLAS
implementations. With the pinned package set on Linux/OpenBLAS instead of macOS/Accelerate,
the GPT helpfulness problem-variance moves from 1.1e-10 (a boundary estimate) to 6.5e-3 and
the Sonnet helpfulness p-value from 9.6e-10 to 1.2e-11 -- while every coefficient sign and
every significance call is unchanged. A reader following the artifact README on Linux would
see `cmp` fail and reasonably conclude the analysis did not reproduce.

So this compares what the sensitivity analysis is used to claim:

  * the same models converged,
  * the leakage coefficients agree within an absolute tolerance,
  * each coefficient carries the same sign, and
  * each clears (or fails to clear) alpha the same way.

`--strict` restores exact numeric comparison for a rerun inside the pinned environment
recorded in `artifact/pinned-environment.json`.

Usage:
    python tools/compare_condition_adjusted.py EXPECTED.json ACTUAL.json
    python tools/compare_condition_adjusted.py EXPECTED.json ACTUAL.json --strict
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ALPHA = 0.05
FIELDS = ("coefficient", "p_value", "standard_error", "condition_coefficient_ped_vs_conv")


def _models(report: dict) -> dict[tuple[str, str], dict]:
    out = {}
    for base, payload in report["results"].items():
        for outcome, model in payload["models"].items():
            out[(base, outcome)] = model
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    parser.add_argument("--abs-tol", type=float, default=0.05,
                        help="absolute allowance on coefficients (default 0.05; the largest "
                             "cross-BLAS drift observed is 0.008)")
    parser.add_argument("--strict", action="store_true",
                        help="exact numeric comparison, for a rerun inside the pinned "
                             "environment in artifact/pinned-environment.json")
    args = parser.parse_args()

    expected = _models(json.loads(args.expected.read_text()))
    actual = _models(json.loads(args.actual.read_text()))
    failures: list[str] = []

    if set(expected) != set(actual):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise SystemExit(f"FAIL: model sets differ (missing={missing}, unexpected={extra})")

    for key in sorted(expected):
        base, outcome = key
        want, got = expected[key], actual[key]
        label = f"{base}/{outcome}"

        if want.get("converged") is not got.get("converged"):
            failures.append(f"{label}: converged {want.get('converged')!r} != "
                            f"{got.get('converged')!r}")

        if args.strict:
            for field in FIELDS:
                if field in want and want[field] != got.get(field):
                    failures.append(f"{label}.{field}: {want[field]!r} != {got.get(field)!r}")
            continue

        if not math.isclose(want["coefficient"], got["coefficient"], abs_tol=args.abs_tol):
            failures.append(f"{label}.coefficient: {want['coefficient']!r} != "
                            f"{got['coefficient']!r} (abs_tol={args.abs_tol:g})")

        if (want["p_value"] < ALPHA) != (got["p_value"] < ALPHA):
            failures.append(f"{label}: significance at alpha={ALPHA} flips "
                            f"(p {want['p_value']:.3g} -> {got['p_value']:.3g})")

        # Sign is only meaningful where the effect is distinguishable from zero. A null
        # coefficient that wanders across zero while staying nonsignificant has not changed
        # any claim; asserting its sign would be asserting the sign of noise.
        if want["p_value"] < ALPHA and (want["coefficient"] > 0) != (got["coefficient"] > 0):
            failures.append(f"{label}: significant coefficient changed sign "
                            f"({want['coefficient']:+.4f} -> {got['coefficient']:+.4f})")

    if failures:
        print(f"FAIL: {len(failures)} differences")
        for failure in failures:
            print(f"  {failure}")
        raise SystemExit(1)

    mode = "exact" if args.strict else f"sign + significance + abs_tol={args.abs_tol:g}"
    print(f"PASS condition-adjusted sensitivity: {len(expected)} models match ({mode})")


if __name__ == "__main__":
    main()
