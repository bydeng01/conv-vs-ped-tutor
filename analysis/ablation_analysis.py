"""DESCRIPTIVE ablation analysis (#5; decisions-log.md 2026-06-30) — SEPARATE from the
frozen §10 inference, and NEVER part of the J1/J2 verdict.

It reads a compute_metrics output dir that contains BOTH the ablation conditions and the
reused primary baselines (conv / ped / cold) — produced by:

  python analysis/compute_metrics.py logs/abl-s0-* logs/conf-s0-conv-r* logs/conf-s0-ped-r* \
      logs/conf-s0-cold-r* --out results/ablation --judge-helpfulness --judge-pedagogy

and characterizes, for each ablation variant, how its leakage / independence / helpfulness /
pedagogy compare to the minimal-ConvTutor and frozen-PedTutor baselines, plus the per-turn
leakage -> next-turn-independence coupling FIT SEPARATELY PER CONDITION (never pooled across
conditions). All of it is DESCRIPTIVE — paired conv/ped-style differences, Cliff's delta,
bootstrap CIs — exactly the §4 S-style descriptive treatment, with no NHST verdict.

WHY THIS IS A SEPARATE SCRIPT (and never analysis/run_inference.py): the frozen §10 J1/J2
path is variant-UNSAFE — `j1`/`_paired` pair only conv-vs-ped, accuracy loops cold/conv/ped,
and `j2` POOLS every per-turn row it is given with no condition covariate. Feeding ablation
rows (or an ablation out dir) to it would contaminate the frozen verdict. This script imports
ONLY the two PURE statistics primitives (`bootstrap_ci`, `cliffs_delta`) — never `j1`/`j2`/
`verdict`/`accuracy` — and fits the coupling on one condition's rows at a time.

Usage:
  python analysis/ablation_analysis.py results/ablation
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ONLY the pure stats primitives — NOT j1/j2/verdict/accuracy (the frozen §10 orchestration).
from analysis.inferential import ALPHA, bootstrap_ci, cliffs_delta  # noqa: E402


def _repo_rel(p: Path) -> str:
    """Repo-relative path string for provenance -- never an absolute or home path."""
    try:
        return str(p.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return p.name


def _scrub_paths(s: str) -> str:
    """Redact the user segment of any absolute home path in the serialized output,
    so a regenerated file never leaks a local username."""
    return re.sub(r'(/Users/|/home/)[^/\s"]+', r'\1<user>', s)


# Which primary baseline each ablation variant is contrasted against, and the "separation"
# reference (the opposite primary — the contrast that DEFINES the leakage/independence gap).
PRIMARY = ("cold", "conv", "ped")
BASELINE = {  # variant -> (its baseline, the separation reference)
    "conv_socratic":        ("conv", "ped"),
    "conv_no_final_answer": ("conv", "ped"),
    "ped_no_gate":          ("ped", "conv"),
    "ped_no_tracker":       ("ped", "conv"),
    "ped_no_cascade":       ("ped", "conv"),
}
ABLATION_CONDITIONS = tuple(BASELINE)
# Per-session marginals compared (descriptive). Orientation only: for a PedTutor variant the
# separation is "low leakage, high independence"; for a ConvTutor variant the question is
# whether a prompt-only change moves it toward that. No significance verdict is emitted.
MARGINALS = ("leakage_rate", "independence_ratio", "helpfulness_mean", "pedagogy_mean")


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.open()))


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v   # drop NaN


def _b(x):
    s = str(x).strip().lower()
    return True if s == "true" else (False if s == "false" else None)


def _paired(rows: list[dict], cond_a: str, cond_b: str, col: str):
    """Aligned (variant, baseline) arrays over replicate ids present + non-null in both."""
    by = {}
    for r in rows:
        v = _f(r.get(col))
        if v is None:
            continue
        by.setdefault(r["replicate_id"], {})[r["condition"]] = v
    a, b, rids = [], [], []
    for rid in sorted(by, key=lambda x: (len(str(x)), str(x))):
        d = by[rid]
        if cond_a in d and cond_b in d:
            a.append(d[cond_a]); b.append(d[cond_b]); rids.append(rid)
    return a, b, rids


def _paired_diff(rows, variant, baseline, col) -> dict:
    """Descriptive paired (variant - baseline) summary on a per-session marginal. None-safe:
    a marginal absent for both (e.g. helpfulness before the judge pass) -> n=0 placeholder."""
    a, b, rids = _paired(rows, variant, baseline, col)
    if not a:
        return {"n_pairs": 0, "note": f"{col} absent / unpaired for {variant} vs {baseline}"}
    a, b = np.asarray(a, float), np.asarray(b, float)
    diffs = a - b
    return {
        "n_pairs": int(diffs.size),
        "variant_mean": float(np.mean(a)),
        "baseline_mean": float(np.mean(b)),
        "mean_diff_variant_minus_baseline": float(np.mean(diffs)),
        "median_diff": float(np.median(diffs)),
        "diff_ci95": bootstrap_ci(diffs),
        "cliffs_delta_variant_vs_baseline": cliffs_delta(a, b),
        "n_variant_gt_baseline": int(np.sum(diffs > 0)),
        "n_variant_lt_baseline": int(np.sum(diffs < 0)),
    }


def _coupling_one_condition(per_turn: list[dict], cond: str) -> dict:
    """Per-turn leakage -> next-turn-independence coupling fit on ONE condition's rows ONLY
    (NEVER pooled across conditions, so it cannot contaminate or be contaminated by another
    variant). Descriptive: the pooled leaky-vs-nonleaky next-independence means, plus a
    two-stage conversation-clustered effect (within each replicate, leaky-minus-nonleaky
    next-independence; signed-rank across replicates). The frozen §10 J2 is NOT called."""
    rows = [r for r in per_turn if r.get("condition") == cond]
    leaky, nonl = [], []
    by_rep: dict = {}
    for r in rows:
        lk = _b(r.get("leaks"))
        nti = _b(r.get("next_turn_independence"))
        if lk is None or nti is None:
            continue
        (leaky if lk else nonl).append(1.0 if nti else 0.0)
        by_rep.setdefault(r["replicate_id"], {"lk": [], "nl": []})
        by_rep[r["replicate_id"]]["lk" if lk else "nl"].append(1.0 if nti else 0.0)
    effs = [np.mean(d["lk"]) - np.mean(d["nl"])
            for d in by_rep.values() if d["lk"] and d["nl"]]
    effs = np.asarray(effs, float)
    if effs.size and (effs != 0).any():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            W, p = stats.wilcoxon(effs, alternative="two-sided", zero_method="wilcox")
        W, p = float(W), float(p)
    else:
        W, p = float("nan"), 1.0
    return {
        "n_turns": len(rows),
        "descriptive_pooled": {
            "leaky_next_indep_mean": float(np.mean(leaky)) if leaky else None,
            "nonleaky_next_indep_mean": float(np.mean(nonl)) if nonl else None,
            "n_leaky": len(leaky), "n_nonleaky": len(nonl),
        },
        "cluster_within_replicate": {
            "mean_within_replicate_effect": float(np.mean(effs)) if effs.size else None,
            "effect_ci95": bootstrap_ci(effs) if effs.size else (None, None),
            "n_replicates_used": int(effs.size),
            "wilcoxon_W": W, "p_two_sided": p,
            "note": "leaky-minus-nonleaky next-turn independence within each replicate, "
                    "signed-rank across replicates; predicted sign is negative if leakage "
                    "suppresses the next student attempt. DESCRIPTIVE, fit per condition.",
        },
    }


def _fmt(x, pct=False):
    if x is None:
        return "  n/a"
    return f"{x:6.1%}" if pct else f"{x:+.3f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir", help="a compute_metrics out dir with ablation + baseline rows")
    args = ap.parse_args()
    d = Path(args.results_dir)
    if not d.is_absolute():
        d = REPO_ROOT / d

    per_session = _read_csv(d / "per_session.csv")
    per_turn = _read_csv(d / "per_turn.csv")
    if not per_session:
        raise SystemExit(f"no per_session.csv in {d} — run compute_metrics into this dir first.")

    present = sorted({r["condition"] for r in per_session})
    abl_present = [c for c in ABLATION_CONDITIONS if c in present]
    if not abl_present:
        raise SystemExit(
            f"no ablation conditions in {d} (found {present}). This DESCRIPTIVE script is for "
            f"the ablation out dir (results/ablation), not the primary; it never runs the frozen "
            f"§10 inference. Point it at a dir that contains ablation cells.")

    marginals: dict = {}
    for v in abl_present:
        baseline, ref = BASELINE[v]
        block = {"baseline": baseline, "separation_reference": ref,
                 "vs_baseline": {}, "vs_separation_reference": {}}
        for col in MARGINALS:
            block["vs_baseline"][col] = _paired_diff(per_session, v, baseline, col)
            block["vs_separation_reference"][col] = _paired_diff(per_session, v, ref, col)
        marginals[v] = block

    # Per-condition coupling: every ablation variant AND its baselines, each fit separately.
    coupling_conditions = sorted(set(abl_present) | {b for v in abl_present for b in BASELINE[v][:1]}
                                 | {BASELINE[v][1] for v in abl_present})
    coupling = {c: _coupling_one_condition(per_turn, c) for c in coupling_conditions if per_turn}

    report = {
        "results_dir": _repo_rel(d),
        "kind": "DESCRIPTIVE ablation extension (#5). NOT the primary; NOT part of the §10 "
                "J1/J2 verdict; NEVER fed to analysis/run_inference.py.",
        "alpha_for_reference_only": ALPHA,
        "conditions_present": present,
        "ablation_conditions_present": abl_present,
        "per_session_marginals_variant_minus_baseline": marginals,
        "leak_to_next_independence_coupling_per_condition": coupling,
        "note": "Paired by replicate id (variant - baseline). Cliff's delta + percentile "
                "bootstrap CIs are descriptive effect sizes, no NHST verdict. The coupling is "
                "fit SEPARATELY per condition and never pooled across conditions. 'No node "
                "collapses the leakage/independence separation' is an allowed, reportable result.",
    }
    (d / "ablation_analysis.json").write_text(_scrub_paths(json.dumps(report, indent=2, default=str)))

    # ----- console -----
    print("\n=== ablation marginals (per-session; DESCRIPTIVE; variant - baseline, paired by "
          "replicate) ===")
    print("  (leakage/independence reported as the variant mean; diff vs each baseline below)")
    for v in abl_present:
        b = marginals[v]
        print(f"\n  {v}  [baseline={b['baseline']}, separation ref={b['separation_reference']}]")
        for col in MARGINALS:
            r1 = b["vs_baseline"][col]
            r2 = b["vs_separation_reference"][col]
            if r1.get("n_pairs", 0) == 0 and r2.get("n_pairs", 0) == 0:
                print(f"    {col:20s} (absent — e.g. needs the judge pass)")
                continue
            vm = r1.get("variant_mean")
            pct = col in ("leakage_rate", "independence_ratio")
            seg = f"variant {(_fmt(vm, pct) if vm is not None else 'n/a')}"
            if r1.get("n_pairs"):
                seg += (f" | vs {b['baseline']}: diff {_fmt(r1['mean_diff_variant_minus_baseline'])} "
                        f"δ {r1['cliffs_delta_variant_vs_baseline']:+.2f} (n={r1['n_pairs']})")
            if r2.get("n_pairs"):
                seg += (f" | vs {b['separation_reference']}: diff "
                        f"{_fmt(r2['mean_diff_variant_minus_baseline'])} "
                        f"δ {r2['cliffs_delta_variant_vs_baseline']:+.2f}")
            print(f"    {col:20s} {seg}")

    if coupling:
        print("\n=== leak -> next-turn independence coupling (per condition; fit SEPARATELY, "
              "never pooled) ===")
        for c in coupling_conditions:
            cp = coupling.get(c)
            if not cp:
                continue
            dp = cp["descriptive_pooled"]; cl = cp["cluster_within_replicate"]
            lm, nm, eff = (dp["leaky_next_indep_mean"], dp["nonleaky_next_indep_mean"],
                           cl["mean_within_replicate_effect"])
            lm_s = "n/a" if lm is None else f"{lm:.3f}"
            nm_s = "n/a" if nm is None else f"{nm:.3f}"
            eff_s = "n/a" if eff is None else f"{eff:+.3f}"
            print(f"  {c:22s} leaky next-indep {lm_s} (n={dp['n_leaky']}) vs non-leaky "
                  f"{nm_s} (n={dp['n_nonleaky']}) | within-rep effect {eff_s} "
                  f"(n_rep={cl['n_replicates_used']}, p={cl['p_two_sided']:.3f})")

    print(f"\nwrote {d}/ablation_analysis.json")
    print("DESCRIPTIVE ablation extension — reported regardless of outcome (§11). NOT the "
          "primary, NOT the J1/J2 verdict; the frozen §10 inference is untouched.")


if __name__ == "__main__":
    main()
