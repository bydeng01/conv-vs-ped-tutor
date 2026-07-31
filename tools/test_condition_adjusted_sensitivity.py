"""Regression and guardrail tests for the post hoc policy-adjusted sensitivity.

Run:  python tools/test_condition_adjusted_sensitivity.py
"""
from __future__ import annotations

import json
import math
import platform
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import condition_adjusted_sensitivity as S  # noqa: E402

EXPECTED = {
    "sonnet": {
        "helpfulness": (0.5002182459393254, 9.643784879152811e-10),
        "next_turn_independence": (-0.3015182405213561, 7.424513053934483e-06),
    },
    "gpt": {
        "helpfulness": (-0.04058210052078997, 0.5635118854628991),
        "next_turn_independence": (-0.29475489235139385, 1.6650724920614195e-06),
    },
    "gemini": {
        "helpfulness": (0.053163645061076265, 0.20803433427545726),
        "next_turn_independence": (-0.6036559999755627, 1.9883126786598337e-19),
    },
}

ALPHA = 0.05

_passed = _failed = _skipped = 0


def check(name: str, condition: bool) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}")


def skip(name: str, why: str) -> None:
    """A check that does not APPLY here. Tallied separately -- a skip is not a pass."""
    global _skipped
    _skipped += 1
    print(f"  SKIP  {name}\n          ({why})")


def _pinned_environment() -> tuple[bool, str]:
    """(is_pinned, why_not) for the environment recorded in artifact/pinned-environment.json.

    The checkpoints in EXPECTED are exact fits of crossed mixed models. Those are not
    portable across BLAS implementations: identical package versions on Linux/OpenBLAS and
    macOS/Accelerate land on different variance-component optima (one boundary estimate
    moves from 1.1e-10 to 6.5e-3), which is why the OS and CPU are part of the pin and not
    just the package set. Pip pinning alone does not reproduce these numbers."""
    recorded = json.loads((REPO_ROOT / "artifact" / "pinned-environment.json").read_text())
    want_os = recorded["analysis_hardware"]["operating_system"]
    if not (platform.system() == "Darwin" and platform.machine() == "arm64"):
        return False, (f"checkpoints were fit on {want_os}; this is "
                       f"{platform.system()} {platform.machine()} with a different BLAS")
    want_py = recorded["python"]
    have_py = platform.python_version()
    if have_py != want_py:
        return False, f"Python {want_py} pinned, running {have_py}"
    import importlib.metadata as md
    for name, want in sorted(recorded["packages"].items()):
        try:
            have = md.version(name)
        except md.PackageNotFoundError:
            return False, f"{name} not installed (pinned {want})"
        if have != want:
            return False, f"{name} {want} pinned, running {have}"
    return True, ""


def _minimal_frame() -> pd.DataFrame:
    rows = []
    for condition in ("conv", "ped"):
        for replicate in (0, 1):
            for problem in ("p1", "p2"):
                rows.append(
                    {
                        "condition": condition,
                        "replicate_id": replicate,
                        "problem_id": problem,
                        "leaks": replicate == 0,
                        "helpfulness": 4.0,
                        "next_turn_independence": replicate == 1,
                    }
                )
    return pd.DataFrame(rows)


def test_formula_and_model_structure_are_frozen() -> None:
    print("\n[formula and structure]")
    check("formula includes the policy fixed effect",
          S.FORMULA_TEMPLATE == "{outcome} ~ leaks_i + C(condition)")
    check("variance components are replicate and problem",
          S.VC_FORMULA == {"replicate": "0 + C(replicate_id)",
                           "problem": "0 + C(problem_id)"})
    check("only ConvTutor and PedTutor are eligible", S.ELIGIBLE_CONDITIONS == ("conv", "ped"))
    check("pinned optimizer policy reused",
          S.J2_OPTIMIZERS == ["lbfgs", "bfgs", "cg", "powell"])


def test_cold_rows_are_excluded_not_fit() -> None:
    print("\n[cold exclusion]")
    frame = _minimal_frame()
    cold = frame.iloc[[0]].copy()
    cold["condition"] = "cold"
    prepared, audit = S.prepare_data(pd.concat([frame, cold], ignore_index=True))
    check("cold absent from model frame", set(prepared["condition"]) == {"conv", "ped"})
    check("eligible row count unchanged", len(prepared) == len(frame))
    check("cold exclusion audited", audit["excluded_condition_counts"] == {"cold": 1})


def test_missing_required_values_are_rejected() -> None:
    print("\n[missing-data tripwires]")
    for column in sorted(S.REQUIRED_COLUMNS):
        frame = _minimal_frame()
        frame[column] = frame[column].astype(object)
        frame.loc[0, column] = None
        try:
            S.prepare_data(frame)
        except ValueError:
            rejected = True
        else:
            rejected = False
        check(f"missing {column} rejected", rejected)


def test_regression_checkpoints_portable() -> None:
    """The load-bearing claims, asserted at a tolerance that survives a BLAS change.

    What the sensitivity analysis is used for is the SIGN of the leakage coefficient and
    whether it clears alpha -- not its sixth decimal. Those hold on every platform tried;
    the sixth decimal does not. This check runs everywhere and is the one CI enforces."""
    print("\n[numerical regression -- portable]")
    report = S.analyze()
    for base, models in EXPECTED.items():
        for outcome, (coefficient, p_value) in models.items():
            actual = report["results"][base]["models"][outcome]
            check(f"{base} {outcome} converged", actual["converged"] is True)
            check(f"{base} {outcome} coefficient within abs_tol=0.05 ({coefficient:+.4f})",
                  math.isclose(actual["coefficient"], coefficient, abs_tol=0.05))
            check(f"{base} {outcome} same significance verdict at alpha={ALPHA}",
                  (actual["p_value"] < ALPHA) == (p_value < ALPHA))
            if p_value < ALPHA:
                check(f"{base} {outcome} coefficient sign preserved",
                      (actual["coefficient"] > 0) == (coefficient > 0))


def test_regression_checkpoints_in_pinned_environment() -> None:
    print("\n[numerical regression -- exact, pinned environment only]")
    pinned, why = _pinned_environment()
    if not pinned:
        skip("exact mixed-model checkpoints (abs_tol=1e-6)", why)
        return
    report = S.analyze()
    for base, models in EXPECTED.items():
        for outcome, (coefficient, p_value) in models.items():
            actual = report["results"][base]["models"][outcome]
            check(
                f"{base} {outcome} coefficient abs_tol=1e-6",
                math.isclose(actual["coefficient"], coefficient, abs_tol=1e-6),
            )
            check(
                f"{base} {outcome} p-value rtol=1e-3 abs_tol=1e-12",
                math.isclose(actual["p_value"], p_value, rel_tol=1e-3, abs_tol=1e-12),
            )


def test_output_is_additive() -> None:
    print("\n[additive output]")
    check("default output is the dedicated sensitivity result",
          S.DEFAULT_OUTPUT == Path("results/condition_adjusted_sensitivity/analysis.json"))
    check("default output is not inference.json", S.DEFAULT_OUTPUT.name != "inference.json")
    check("default output is outside confirmatory dirs",
          "confirmatory" not in S.DEFAULT_OUTPUT.parts)
    check("manuscript values have a dedicated generated path",
          S.DEFAULT_LATEX_OUTPUT == Path("results/condition_adjusted_sensitivity/values.tex"))


def main() -> None:
    test_formula_and_model_structure_are_frozen()
    test_cold_rows_are_excluded_not_fit()
    test_missing_required_values_are_rejected()
    test_regression_checkpoints_portable()
    test_regression_checkpoints_in_pinned_environment()
    test_output_is_additive()
    print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
    raise SystemExit(1 if _failed else 0)


if __name__ == "__main__":
    main()
