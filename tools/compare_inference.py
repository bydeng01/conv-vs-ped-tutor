"""Compare scientific result blocks in two inference.json files."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

RESULT_BLOCKS = ("verdict", "j1", "j2", "accuracy", "cost_normalized")

# Pre-rendered prose inside the verdict block ("mixed coef -0.313 95% CI [...]"). These are
# STRINGS built from numbers that this comparator already checks numerically, under
# j2.*.mixed_effects and j1.*. Compared as strings they are exact-match, so a third-decimal
# platform difference reads as a categorical mismatch. --science-only drops the rendering
# and keeps the source numbers; `claim` and `verdict` -- the actual conclusions -- are always
# compared exactly.
RENDERED_VERDICT_FIELDS = ("effect", "ci", "p")

# Everything a crossed mixed-effects fit produces -- coef, se, ci95, p, and the random-effect
# variance components -- comes out of the same iterative optimizer and is not bit-portable
# across BLAS/toolchain/Python-ABI combinations. Relative tolerance is the wrong instrument
# for small-magnitude leaves here (a small absolute wobble is a large relative one near
# zero), so under --science-only the whole mixed_effects sub-tree gets an absolute allowance
# instead of pure rel_tol. Observed drift so far, all scientifically inert (no verdict
# changed, no significance call flipped):
#   - variance components: same pinned deps, macOS/Accelerate vs Linux/OpenBLAS, up to 0.0072
#     absolute (one boundary variance moved 1.1e-10 -> 6.5e-3).
#   - gemini leak_to_helpfulness (docker run, exact pinned deps): coef/ci95/p all shifted;
#     largest was p at 0.018 absolute (0.129 -> 0.147; not significant on either side).
#   - sonnet leak_to_next_independence.se (GitHub Actions, py3.11, floating requirements.txt,
#     py3.12 clean): 0.0035 absolute, ~6% relative -- enough to clear rel_tol=0.05 alone,
#     which is what originally caught this before mixed_effects leaves were covered here.
# This cannot hide a real conclusion flip: verdict[...]'s claim/significance fields are a
# separate part of the JSON and are always compared exactly (see RENDERED_VERDICT_FIELDS
# above), never touched by this. The `converged`/`available` booleans and the `model` string
# inside mixed_effects are also always exact -- bools and strings never reach the numeric
# tolerance branch below.
MIXED_EFFECTS_KEY = "mixed_effects"
VARIANCE_KEY = "variance_components"


def _compare(left, right, path: str, failures: list[str], abs_tol: float, rel_tol: float,
             skip_rendered: bool = False, variance_abs_tol: float = 0.0) -> None:
    if isinstance(left, bool) or isinstance(right, bool):
        if left != right:
            failures.append(f"{path}: {left!r} != {right!r}")
        return
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        tol = abs_tol
        if variance_abs_tol and (VARIANCE_KEY in path or MIXED_EFFECTS_KEY in path):
            tol = max(tol, variance_abs_tol)
        if not math.isclose(float(left), float(right), rel_tol=rel_tol, abs_tol=tol):
            failures.append(f"{path}: {left!r} != {right!r}")
        return
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            failures.append(f"{path}: keys differ")
            return
        for key in sorted(left):
            if (skip_rendered and key in RENDERED_VERDICT_FIELDS
                    and path.startswith("verdict")):
                continue
            _compare(left[key], right[key], f"{path}.{key}", failures, abs_tol, rel_tol,
                     skip_rendered, variance_abs_tol)
        return
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            failures.append(f"{path}: lengths differ")
            return
        for index, (a, b) in enumerate(zip(left, right)):
            _compare(a, b, f"{path}[{index}]", failures, abs_tol, rel_tol, skip_rendered,
                     variance_abs_tol)
        return
    if left != right:
        failures.append(f"{path}: {left!r} != {right!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    parser.add_argument("--abs-tol", type=float, default=1e-8)
    parser.add_argument("--rel-tol", type=float, default=1e-2)
    parser.add_argument(
        "--science-only", action="store_true",
        help="compare the conclusions and the numbers behind them, not the pre-rendered "
             "verdict prose. Use this when the rerun is on a different OS/CPU than the "
             "packaged reference: crossed mixed models are not bit-portable across BLAS "
             "implementations, so coefficients move in the third decimal while every "
             "verdict label, sign, and significance call is unchanged.")
    parser.add_argument(
        "--variance-abs-tol", type=float, default=0.03,
        help="absolute allowance for mixed-effects fit outputs (coef/se/ci95/p and "
             "random-effect variance components) under --science-only. Default 0.03; the "
             "largest cross-platform drift observed on any of those fields so far is 0.018 "
             "(a p-value, gemini leak_to_helpfulness). Ignored without --science-only.")
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text())
    actual = json.loads(args.actual.read_text())
    failures: list[str] = []
    for block in RESULT_BLOCKS:
        _compare(expected[block], actual[block], block, failures, args.abs_tol, args.rel_tol,
                 args.science_only,
                 args.variance_abs_tol if args.science_only else 0.0)
    if failures:
        print(f"FAIL: {len(failures)} scientific-result differences")
        for failure in failures[:30]:
            print(f"  {failure}")
        raise SystemExit(1)
    mode = " [science-only: verdict prose not compared]" if args.science_only else ""
    print(
        "PASS inference: verdict, J1, J2, accuracy, and cost-normalized blocks match "
        f"(numeric abs_tol={args.abs_tol:g}, rtol={args.rel_tol:g}){mode}"
    )


if __name__ == "__main__":
    main()
