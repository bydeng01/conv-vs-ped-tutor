"""Post hoc policy-adjusted sensitivity analysis for the three tutor bases.

This analysis is additive to the pre-registered pooled J2 models in
``analysis/inferential.py``.  It never writes any base's ``inference.json``.  For each
base and outcome it fits the same crossed-random-intercept linear mixed model as J2,
adding tutoring condition as a fixed effect:

    outcome ~ leaks_i + C(condition)

Only answer-phase ConvTutor and PedTutor rows are eligible.  Replicate and problem are
crossed variance components over one dummy group, maximum likelihood is used, and the
frozen J2 optimizer sequence is passed to statsmodels unchanged.

Usage:
  python analysis/condition_adjusted_sensitivity.py
  python analysis/condition_adjusted_sensitivity.py --output /tmp/sensitivity.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis.inferential import J2_OPTIMIZERS  # noqa: E402

FORMULA_TEMPLATE = "{outcome} ~ leaks_i + C(condition)"
VC_FORMULA = {
    "replicate": "0 + C(replicate_id)",
    "problem": "0 + C(problem_id)",
}
ELIGIBLE_CONDITIONS = ("conv", "ped")
OUTCOMES = {
    "helpfulness": {"column": "helpfulness", "predicted_sign": None},
    "next_turn_independence": {"column": "indep_i", "predicted_sign": -1},
}
BASE_INPUTS = {
    "sonnet": Path("results/confirmatory/per_turn.csv"),
    "gpt": Path("results/confirmatory_gpt/per_turn.csv"),
    "gemini": Path("results/confirmatory_gemini/per_turn.csv"),
}
DEFAULT_OUTPUT = Path("results/condition_adjusted_sensitivity/analysis.json")
DEFAULT_LATEX_OUTPUT = Path("results/condition_adjusted_sensitivity/values.tex")
REQUIRED_COLUMNS = {
    "condition",
    "replicate_id",
    "problem_id",
    "leaks",
    "helpfulness",
    "next_turn_independence",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _repo_rel(path: Path) -> str:
    """Repo-relative path string for provenance -- never an absolute or home path.

    Matches analysis/run_inference.py and analysis/ablation_analysis.py, which both fall
    back to the bare name. Without the fallback an --output outside the repo raised
    ValueError from the final progress line, AFTER the report had been written: the work
    succeeded and the process still exited non-zero."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return path.name


def _binary(series: pd.Series, name: str) -> pd.Series:
    """Convert strict bool-like values to 0/1; reject missing or unfamiliar values."""
    mapping = {
        True: 1.0,
        False: 0.0,
        1: 1.0,
        0: 0.0,
        "true": 1.0,
        "false": 0.0,
        "True": 1.0,
        "False": 0.0,
        "1": 1.0,
        "0": 0.0,
    }
    converted = series.map(mapping)
    bad = converted.isna()
    if bad.any():
        values = sorted({repr(v) for v in series[bad].tolist()})
        raise ValueError(f"{name} contains missing or non-binary values: {values}")
    return converted.astype(float)


def prepare_data(frame: pd.DataFrame, *, source: str = "<dataframe>") -> tuple[pd.DataFrame, dict]:
    """Validate the input and return only complete ConvTutor/PedTutor rows.

    Cold rows are deliberately excluded before fitting.  Missing required values in an
    eligible row are an error rather than silently changing the analysis sample.
    """
    missing_columns = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing_columns:
        raise ValueError(f"{source} is missing required columns: {missing_columns}")

    raw_missing = frame[sorted(REQUIRED_COLUMNS)].isna().sum()
    raw_missing = {k: int(v) for k, v in raw_missing.items() if int(v)}
    if raw_missing:
        raise ValueError(f"{source} has missing required values: {raw_missing}")

    condition = frame["condition"].astype("string").str.lower()
    eligible_mask = condition.isin(ELIGIBLE_CONDITIONS)
    eligible = frame.loc[eligible_mask].copy()
    eligible["condition"] = condition.loc[eligible_mask]
    if eligible.empty:
        raise ValueError(f"{source} has no ConvTutor/PedTutor rows")

    eligible["leaks_i"] = _binary(eligible["leaks"], "leaks")
    eligible["indep_i"] = _binary(
        eligible["next_turn_independence"], "next_turn_independence"
    )
    eligible["helpfulness"] = pd.to_numeric(eligible["helpfulness"], errors="coerce")
    if eligible["helpfulness"].isna().any():
        raise ValueError(f"{source} has non-numeric helpfulness values in eligible rows")
    eligible["_grp"] = 1

    counts = {k: int(v) for k, v in eligible["condition"].value_counts().items()}
    if set(counts) != set(ELIGIBLE_CONDITIONS):
        raise ValueError(
            f"{source} must contain both eligible conditions; observed {sorted(counts)}"
        )
    excluded = condition.loc[~eligible_mask].value_counts(dropna=False)
    audit = {
        "rows_read": int(frame.shape[0]),
        "rows_analyzed": int(eligible.shape[0]),
        "condition_counts": {k: counts[k] for k in ELIGIBLE_CONDITIONS},
        "excluded_condition_counts": {str(k): int(v) for k, v in excluded.items()},
        "n_replicates": int(eligible["replicate_id"].nunique()),
        "n_problems": int(eligible["problem_id"].nunique()),
    }
    return eligible, audit


def _selected_optimizer(captured_warnings: list[str]) -> str:
    """Infer the successful method from statsmodels' documented retry warnings.

    MixedLM.fit stores final iteration history but not the optimizer name.  It emits
    ``Retrying MixedLM optimization with <method>`` before each fallback, so the last
    retry names the method that produced the returned result.  With no retry, the first
    requested method produced it.
    """
    selected = J2_OPTIMIZERS[0]
    retry = re.compile(r"Retrying MixedLM optimization with ([A-Za-z0-9_-]+)")
    for message in captured_warnings:
        match = retry.search(message)
        if match:
            selected = match.group(1)
    return selected


def fit_policy_adjusted(frame: pd.DataFrame, outcome: str) -> dict:
    """Fit one policy-adjusted crossed MixedLM and serialize its leakage coefficient."""
    if outcome not in {spec["column"] for spec in OUTCOMES.values()}:
        raise ValueError(f"unsupported outcome: {outcome}")
    import statsmodels.formula.api as smf

    formula = FORMULA_TEMPLATE.format(outcome=outcome)
    model = smf.mixedlm(
        formula,
        frame,
        groups="_grp",
        re_formula="0",
        vc_formula=VC_FORMULA,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fit = model.fit(reml=False, method=J2_OPTIMIZERS, full_output=True)
    warning_messages = [str(w.message) for w in caught]
    ci = fit.conf_int().loc["leaks_i"]
    variance_components = {
        name: float(value)
        for name, value in zip(sorted(VC_FORMULA), np.atleast_1d(fit.vcomp))
    }
    variance_components["residual"] = float(fit.scale)
    return {
        "formula": formula,
        "model": (
            "linear mixed model; crossed replicate and problem random intercepts "
            "as variance components over one dummy group; maximum likelihood"
        ),
        "reml": False,
        "groups": "single dummy group (_grp = 1)",
        "re_formula": "0",
        "vc_formula": dict(VC_FORMULA),
        "optimizer_sequence": list(J2_OPTIMIZERS),
        "selected_optimizer": _selected_optimizer(warning_messages),
        "converged": bool(fit.converged),
        "optimizer_history": json.loads(json.dumps(fit.hist, default=_json_default)),
        "warnings": warning_messages,
        "coefficient": float(fit.params["leaks_i"]),
        "standard_error": float(fit.bse["leaks_i"]),
        "confidence_interval_95": [float(ci.iloc[0]), float(ci.iloc[1])],
        "p_value": float(fit.pvalues["leaks_i"]),
        "condition_coefficient_ped_vs_conv": float(fit.params["C(condition)[T.ped]"]),
        "variance_components": variance_components,
        "n_obs": int(fit.nobs),
    }


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


def analyze(inputs: dict[str, Path] | None = None) -> dict:
    """Run all six adjusted models and return a machine-readable report."""
    import scipy
    import statsmodels

    inputs = inputs or BASE_INPUTS
    results = {}
    input_records = []
    for base, relative in inputs.items():
        path = relative if relative.is_absolute() else REPO_ROOT / relative
        frame = pd.read_csv(path)
        prepared, audit = prepare_data(frame, source=_repo_rel(path))
        models = {}
        for label, spec in OUTCOMES.items():
            models[label] = fit_policy_adjusted(prepared, spec["column"])
        results[base] = {"sample": audit, "models": models}
        input_records.append(
            {
                "base": base,
                "path": _repo_rel(path),
                "sha256": _sha256(path),
            }
        )

    return {
        "analysis": "condition-adjusted leakage sensitivity",
        "epistemic_status": "post hoc sensitivity analysis",
        "relationship_to_preregistered_j2": (
            "additive; the pre-registered pooled J2 analyses and inference.json files "
            "remain primary and unchanged"
        ),
        "eligible_conditions": list(ELIGIBLE_CONDITIONS),
        "inputs": input_records,
        "results": results,
        "provenance": {
            "script": "analysis/condition_adjusted_sensitivity.py",
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "statsmodels": statsmodels.__version__,
            "optimizer_policy_source": "analysis.inferential.J2_OPTIMIZERS",
        },
    }


def _latex_p(value: float) -> str:
    if value < 0.001:
        exponent = int(np.floor(np.log10(value)))
        mantissa = value / (10 ** exponent)
        return f"{mantissa:.1f}{{\\times}}10^{{{exponent}}}"
    return f"{value:.3f}".lstrip("0")


def write_latex_values(report: dict, path: Path) -> None:
    """Write the manuscript-facing adjusted coefficients from the JSON report."""
    base_names = {"sonnet": "Sonnet", "gpt": "GPT", "gemini": "Gemini"}
    outcome_names = {
        "helpfulness": "AdjHelp",
        "next_turn_independence": "AdjIndep",
    }
    lines = [
        "% Generated by analysis/condition_adjusted_sensitivity.py; do not hand edit.",
        "% Values are from the post hoc policy-adjusted sensitivity analysis.",
    ]
    for base, base_name in base_names.items():
        for outcome, prefix in outcome_names.items():
            result = report["results"][base]["models"][outcome]
            coefficient = result["coefficient"]
            coef_text = f"{{+}}{coefficient:.3f}" if coefficient >= 0 else f"{{-}}{abs(coefficient):.3f}"
            p_text = _latex_p(result["p_value"])
            lines.extend(
                [
                    f"\\newcommand{{\\{prefix}{base_name}Result}}{{%",
                    f"  \\ensuremath{{{coef_text}}} (\\ensuremath{{p{{=}}{p_text}}})}}",
                ]
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"machine-readable output (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--latex-output",
        type=Path,
        default=DEFAULT_LATEX_OUTPUT,
        help=f"generated manuscript values (default: {DEFAULT_LATEX_OUTPUT})",
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    latex_output = (
        args.latex_output if args.latex_output.is_absolute() else REPO_ROOT / args.latex_output
    )
    report = analyze()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n")
    write_latex_values(report, latex_output)
    print(f"wrote {_repo_rel(output)}")
    print(f"wrote {_repo_rel(latex_output)}")
    for base, result in report["results"].items():
        help_model = result["models"]["helpfulness"]
        indep_model = result["models"]["next_turn_independence"]
        print(
            f"{base:7s} n={result['sample']['rows_analyzed']:3d} | "
            f"helpfulness {help_model['coefficient']:+.7f}, p={help_model['p_value']:.6g} | "
            f"independence {indep_model['coefficient']:+.7f}, p={indep_model['p_value']:.6g}"
        )


if __name__ == "__main__":
    main()
