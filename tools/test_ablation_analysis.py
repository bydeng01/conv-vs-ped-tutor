"""Offline tests for the DESCRIPTIVE ablation analysis (analysis/ablation_analysis.py).

Pure-function + guard tests on synthetic per_session / per_turn rows (no logs, no model).
They check the paired (variant - baseline) summaries, that the per-condition coupling is fit
on ONE condition's rows only (never pooled), and that the script REFUSES a dir with no
ablation conditions (so it can never stand in for the frozen §10 inference).

Run:  python tools/test_ablation_analysis.py
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import ablation_analysis as AA  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def _session_rows():
    """3 replicates each of conv / ped / ped_no_gate / conv_socratic. ped separates from
    conv (low leak, high indep); ped_no_gate stays near ped; conv_socratic sits between."""
    rows = []
    spec = {  # condition -> (leakage, independence) base values
        "conv": (0.80, 0.30), "ped": (0.00, 0.90),
        "ped_no_gate": (0.10, 0.85), "conv_socratic": (0.50, 0.60),
    }
    for rid in ("0", "1", "2"):
        bump = 0.02 * int(rid)
        for cond, (lk, ind) in spec.items():
            rows.append({"condition": cond, "replicate_id": rid,
                         "leakage_rate": round(lk + bump, 3),
                         "independence_ratio": round(ind - bump, 3),
                         "helpfulness_mean": "", "pedagogy_mean": ""})
    return rows


def _turn_rows():
    """Per-turn rows with a DIFFERENT leak->next-independence pattern per condition, so a
    correct per-condition fit must not pool: conv leaky turns suppress the next attempt
    (leaky nti=0, nonleaky nti=1); ped_no_gate does not (leaky nti=1)."""
    rows = []
    patt = {  # condition -> (leaky_nti, nonleaky_nti)
        "conv": (0, 1), "ped": (1, 1), "ped_no_gate": (1, 0), "conv_socratic": (0, 1),
    }
    for cond, (lk_nti, nl_nti) in patt.items():
        for rid in ("0", "1", "2"):
            # two leaky + two non-leaky turns per replicate
            for _ in range(2):
                rows.append({"condition": cond, "replicate_id": rid, "leaks": "True",
                             "next_turn_independence": "True" if lk_nti else "False"})
            for _ in range(2):
                rows.append({"condition": cond, "replicate_id": rid, "leaks": "False",
                             "next_turn_independence": "True" if nl_nti else "False"})
    return rows


def test_paired_diff():
    print("\n[paired (variant - baseline) marginal diffs]")
    rows = _session_rows()
    # ped_no_gate vs ped (baseline): leakage slightly higher, independence slightly lower
    r = AA._paired_diff(rows, "ped_no_gate", "ped", "leakage_rate")
    check("ped_no_gate vs ped: 3 paired replicates", r["n_pairs"] == 3)
    check("ped_no_gate leakage > ped leakage (small positive diff)",
          r["mean_diff_variant_minus_baseline"] > 0)
    # ped_no_gate vs conv (separation reference): leakage MUCH lower -> separation preserved
    r2 = AA._paired_diff(rows, "ped_no_gate", "conv", "leakage_rate")
    check("ped_no_gate leakage << conv leakage (separation preserved)",
          r2["mean_diff_variant_minus_baseline"] < -0.5)
    check("Cliff's delta is in [-1, 1]",
          -1.0 <= r2["cliffs_delta_variant_vs_baseline"] <= 1.0)
    # independence: ped_no_gate stays high (near ped, far above conv)
    ri = AA._paired_diff(rows, "ped_no_gate", "conv", "independence_ratio")
    check("ped_no_gate independence >> conv independence",
          ri["mean_diff_variant_minus_baseline"] > 0.4)
    # absent marginal (helpfulness before the judge pass) -> n_pairs 0 placeholder, no crash
    rh = AA._paired_diff(rows, "ped_no_gate", "ped", "helpfulness_mean")
    check("absent marginal -> n_pairs 0 placeholder", rh.get("n_pairs") == 0)


def test_coupling_not_pooled():
    print("\n[per-condition coupling fit on one condition's rows only (never pooled)]")
    turns = _turn_rows()
    conv = AA._coupling_one_condition(turns, "conv")
    png = AA._coupling_one_condition(turns, "ped_no_gate")
    dp_c, dp_p = conv["descriptive_pooled"], png["descriptive_pooled"]
    # conv: leaky turns suppress next attempt (0) vs non-leaky (1); ped_no_gate: opposite.
    # If the fit pooled across conditions, these would be IDENTICAL -- they must differ.
    check("conv leaky next-indep mean == 0.0", dp_c["leaky_next_indep_mean"] == 0.0)
    check("conv non-leaky next-indep mean == 1.0", dp_c["nonleaky_next_indep_mean"] == 1.0)
    check("ped_no_gate leaky next-indep mean == 1.0", dp_p["leaky_next_indep_mean"] == 1.0)
    check("ped_no_gate non-leaky next-indep mean == 0.0", dp_p["nonleaky_next_indep_mean"] == 0.0)
    check("coupling counts only that condition's turns (12 each)",
          conv["n_turns"] == 12 and png["n_turns"] == 12)
    check("conv within-replicate effect is negative (leak suppresses next attempt)",
          conv["cluster_within_replicate"]["mean_within_replicate_effect"] < 0)
    check("ped_no_gate within-replicate effect is positive (differs from conv -> not pooled)",
          png["cluster_within_replicate"]["mean_within_replicate_effect"] > 0)


def _write_dir(session_rows, turn_rows) -> Path:
    d = Path(tempfile.mkdtemp(prefix="abltest_", dir="/tmp"))
    for name, rows in (("per_session.csv", session_rows), ("per_turn.csv", turn_rows)):
        with open(d / name, "w", newline="") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            else:
                f.write("")
    return d


def _main_exits(d: Path) -> bool:
    saved = sys.argv
    sys.argv = ["ablation_analysis", str(d)]
    try:
        AA.main()
        return False
    except SystemExit:
        return True
    finally:
        sys.argv = saved


def test_main_guards_and_output():
    print("\n[main: refuses a non-ablation dir; writes a clearly-labeled descriptive json]")
    # a primary-only dir (conv/ped, no ablation conditions) is refused -- this script must
    # never be mistaken for the frozen §10 inference.
    prim = _write_dir([r for r in _session_rows() if r["condition"] in ("conv", "ped")], [])
    check("primary-only dir (no ablation conditions) -> refused", _main_exits(prim))
    shutil.rmtree(prim, ignore_errors=True)

    # a real ablation dir runs and writes a descriptive json with the right labels
    abl = _write_dir(_session_rows(), _turn_rows())
    check("ablation dir runs (no refusal)", not _main_exits(abl))
    rep = json.loads((abl / "ablation_analysis.json").read_text())
    check("json is labeled DESCRIPTIVE / not the J1/J2 verdict",
          "DESCRIPTIVE" in rep["kind"] and "run_inference" in rep["kind"])
    check("json reports the ablation conditions present",
          set(rep["ablation_conditions_present"]) == {"ped_no_gate", "conv_socratic"})
    check("json carries the per-condition coupling (keyed by condition, not pooled)",
          "conv" in rep["leak_to_next_independence_coupling_per_condition"]
          and "ped_no_gate" in rep["leak_to_next_independence_coupling_per_condition"])
    shutil.rmtree(abl, ignore_errors=True)

    # an empty / missing per_session.csv is refused, not a crash
    empty = _write_dir([], [])
    check("missing per_session.csv -> refused", _main_exits(empty))
    shutil.rmtree(empty, ignore_errors=True)


def main():
    test_paired_diff()
    test_coupling_not_pooled()
    test_main_guards_and_output()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
