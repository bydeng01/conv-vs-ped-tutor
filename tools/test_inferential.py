"""Offline tests for the Week-3 inferential analysis (analysis/inferential.py).

Checks the pure primitives (Cliff's delta, bootstrap determinism, the paired Wilcoxon
wrapper + verdict logic), the J1 joint-verdict rule on synthetic conversation summaries,
and that J2's mixed-effects legs recover a planted coupling's sign/significance. No API
key or network needed.

Run:  python tools/test_inferential.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import inferential as I  # noqa: E402

_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}")


def approx(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol


# ----------------------------------------------------------------- primitives
def test_cliffs_delta():
    print("\n[cliffs_delta]")
    check("fully a>b -> +1", approx(I.cliffs_delta([3, 4, 5], [0, 1, 2]), 1.0))
    check("fully a<b -> -1", approx(I.cliffs_delta([0, 1], [5, 6]), -1.0))
    check("identical -> 0", approx(I.cliffs_delta([1, 2, 3], [1, 2, 3]), 0.0))


def test_bootstrap():
    print("\n[bootstrap_ci]")
    vals = [4.0, 4.2, 4.5, 4.1, 4.3, 4.4, 3.9, 4.6, 4.0, 4.2]
    lo1, hi1 = I.bootstrap_ci(vals, seed=0)
    lo2, hi2 = I.bootstrap_ci(vals, seed=0)
    check("deterministic for a fixed seed", approx(lo1, lo2) and approx(hi1, hi2))
    check("CI brackets the sample mean", lo1 <= sum(vals) / len(vals) <= hi1)
    check("CI is an interval", lo1 <= hi1)


def test_paired_test():
    print("\n[paired_test]")
    # conv uniformly above ped -> significant in predicted (+1) direction
    conv = [0.50, 0.55, 0.60, 0.45, 0.52, 0.58, 0.49, 0.61, 0.47, 0.53]
    ped = [0.10, 0.12, 0.08, 0.05, 0.11, 0.09, 0.07, 0.13, 0.06, 0.10]
    r = I.paired_test(conv, ped, predicted_sign=+1)
    check("clean separation is significant (conv>ped)", r["significant_in_predicted_direction"])
    check("direction matches +1", r["direction_matches_prediction"])
    check("Cliff's delta ~ +1", r["cliffs_delta_conv_vs_ped"] > 0.9)
    check("counts conv>ped on every replicate", r["n_conv_gt_ped"] == 10)
    # same data, but the PREDICTION was conv<ped -> not significant in predicted dir
    r2 = I.paired_test(conv, ped, predicted_sign=-1)
    check("wrong predicted direction -> not significant_in_predicted_direction",
          not r2["significant_in_predicted_direction"])
    # near-tie, mixed signs -> not significant
    a = [4.70, 4.89, 5.00, 5.00, 4.56, 4.44, 4.53, 4.74, 4.06, 5.00]
    b = [4.85, 4.91, 4.96, 4.63, 4.78, 4.87, 4.58, 4.79, 4.62, 4.99]
    r3 = I.paired_test(a, b, predicted_sign=+1)
    check("reversed/near-tie P2-like -> not significant in predicted dir",
          not r3["significant_in_predicted_direction"])


def test_wilcoxon_known_p():
    print("\n[paired_test — hand-computed Wilcoxon p (conversation unit)]")
    # n=6 paired replicates, every conv>ped -> two-sided EXACT signed-rank p = 2/2^6.
    conv = [0.60, 0.70, 0.80, 0.50, 0.90, 0.65]
    ped = [0.10, 0.20, 0.15, 0.05, 0.30, 0.12]
    r = I.paired_test(conv, ped, predicted_sign=+1)
    check("n=6 all-positive -> p == 0.03125 (hand-computed 2/2^6)",
          approx(r["p_two_sided"], 0.03125, tol=1e-12))
    check("unit is the PAIR/replicate count n=6 (not pooled turns)", r["n"] == 6)
    check("Wilcoxon W == 0 when one sign is unanimous", approx(r["wilcoxon_W"], 0.0))
    # n=8 all-positive -> 2/2^8 = 0.0078125
    a8 = [1, 2, 3, 4, 5, 6, 7, 8]
    b8 = [x - 0.5 for x in a8]
    r8 = I.paired_test(a8, b8, predicted_sign=+1)
    check("n=8 all-positive -> p == 0.0078125 (hand-computed 2/2^8)",
          approx(r8["p_two_sided"], 0.0078125, tol=1e-12))


# ----------------------------------------------------------------- J1 verdict
def _per_rep(cond, rid, leak, indep, help_):
    return {"condition": cond, "replicate_id": str(rid), "leakage_rate": leak,
            "independence_ratio": indep, "helpfulness_mean": help_,
            "acc_immediate": 1.0, "acc_delayed": 1.0, "acc_transfer": 1.0}


def test_j1_verdict():
    print("\n[J1 joint verdict]")
    # all three separate cleanly AND P2 (helpfulness) significant conv>ped -> supported
    rows = []
    for r in range(10):
        rows.append(_per_rep("conv", r, 0.50 + 0.01 * r, 0.30 + 0.01 * r, 4.6 + 0.01 * r))
        rows.append(_per_rep("ped", r, 0.05 + 0.005 * r, 0.70 + 0.01 * r, 4.0 + 0.01 * r))
    out = I.j1(rows)
    check("P1 separates (conv>ped)", out["P1_leakage"]["significant_in_predicted_direction"])
    check("P3 separates (ped>conv)", out["P3_independence"]["significant_in_predicted_direction"])
    check("P2 significant (conv>ped)", out["P2_helpfulness"]["significant_in_predicted_direction"])
    check("J1 marginal SUPPORTED when all hold", out["joint_J1"]["J1_marginal_supported"])

    # P1/P3 separate but P2 REVERSED (ped>conv) -> J1 not supported
    rows2 = []
    for r in range(10):
        rows2.append(_per_rep("conv", r, 0.50, 0.30, 4.0 + 0.01 * r))
        rows2.append(_per_rep("ped", r, 0.05, 0.70, 4.3 + 0.01 * r))  # ped more helpful
    out2 = I.j1(rows2)
    check("P2 reversed -> P2 not significant in predicted dir",
          not out2["P2_helpfulness"]["significant_in_predicted_direction"])
    check("J1 marginal NOT supported when P2 reversed",
          not out2["joint_J1"]["J1_marginal_supported"])


# ----------------------------------------------------------------- J2 legs
def _planted_turns():
    """Synthetic per-turn rows with a planted coupling: leaky turns are rated higher and
    are followed by lower next-turn independence.

    The independence leg is planted at CONCORDANCE, not at 1.0. A deterministic
    leaky <-> not-independent mapping is perfectly separable: the binary mixed model fits a
    boundary solution whose standard error collapses to zero, so the p-value comes back nan
    (or 0.0, depending on the linear-algebra backend) and
    `significant_in_predicted_direction` is not well defined. That made this check pass on
    macOS/Accelerate and fail on Linux/OpenBLAS while testing nothing either way. At 0.90 the
    planted effect is unambiguous (coef ~ -0.77, p ~ 1e-118) and the fit is well posed, so
    the assertion is now about signal recovery rather than about which backend happens to
    divide by a zero standard error."""
    rows = []
    rng = __import__("random").Random(0)
    concordance = 0.90
    for rep in range(10):
        for prob in range(6):
            for t in range(6):
                leaky = (t % 2 == 0)
                help_ = (5.0 if leaky else 4.0) + rng.uniform(-0.2, 0.2)
                independent = (not leaky) if rng.random() < concordance else leaky
                nti = "True" if independent else "False"
                rows.append({"condition": "conv", "replicate_id": str(rep),
                             "problem_id": f"train-{prob}", "turn_index": t,
                             "leaks": "True" if leaky else "False",
                             "helpfulness": round(help_, 3),
                             "next_turn_independence": nti})
    return rows


def test_j2_recovers_signal():
    print("\n[J2 coupling — recovers a planted signal]")
    out = I.j2(_planted_turns())
    h, n = out["leak_to_helpfulness"], out["leak_to_next_independence"]
    hc, nc = h["cluster_summary"], n["cluster_summary"]
    # cluster-summary is scipy-only and always runs (no statsmodels needed)
    check("leak->helpfulness within-replicate effect positive",
          hc["mean_within_replicate_effect"] > 0)
    check("leak->helpfulness significant in predicted (+) dir (operative)",
          h["operative_significant_in_predicted_direction"])
    check("leak->next-independence within-replicate effect negative",
          nc["mean_within_replicate_effect"] < 0)
    check("leak->next-independence significant in predicted (-) dir (operative)",
          n["operative_significant_in_predicted_direction"])
    check("J2 supported (both legs) on planted signal", out["J2_supported"])
    check("descriptive anchor present", h["descriptive_pooled"]["n_leaky"] > 0)
    # statsmodels is a required dependency (requirements.txt); the crossed model must run.
    me = h["mixed_effects"]
    check("crossed mixed model ran (statsmodels required dep)",
          me.get("available") and "coef" in me)
    check("mixed-effects coef agrees in predicted (+) sign", me["coef"] > 0)
    check("mixed model reports BOTH crossed factors (replicate + problem)",
          me.get("n_replicates") == 10 and me.get("n_problems") == 6)
    check("operative J2 test is the mixed model when it runs",
          h["operative_method"] == "mixed_effects")


def _planted_crossed(beta):
    """Per-turn rows with genuine replicate AND problem random intercepts plus a known
    fixed effect `beta` of leakage on the (continuous) helpfulness outcome, so the crossed
    mixed model has a hand-set target estimate to recover (not just a sign)."""
    rng = __import__("random").Random(1)
    rep_eff = {r: rng.gauss(0, 0.5) for r in range(10)}
    prob_eff = {q: rng.gauss(0, 0.3) for q in range(6)}
    rows = []
    for rep in range(10):
        for prob in range(6):
            for t in range(6):
                leaky = (t % 2 == 0)
                y = 2.0 + beta * (1 if leaky else 0) + rep_eff[rep] + prob_eff[prob] + rng.gauss(0, 0.2)
                rows.append({"condition": "conv", "replicate_id": str(rep),
                             "problem_id": f"train-{prob}", "turn_index": t,
                             "leaks": "True" if leaky else "False",
                             "helpfulness": round(y, 4),
                             "next_turn_independence": "False" if leaky else "True"})
    return rows


def test_j2_mixed_recovers_estimate():
    print("\n[J2 crossed mixed model — recovers a KNOWN estimate, not just a sign]")
    out = I.j2(_planted_crossed(beta=1.0))
    me = out["leak_to_helpfulness"]["mixed_effects"]
    check("crossed mixed model ran", me.get("available") and "coef" in me)
    check("recovers planted fixed effect beta ~ +1.0 (|coef-1| < 0.15)",
          abs(me["coef"] - 1.0) < 0.15)
    check("95% CI brackets the planted beta = 1.0", me["ci95"][0] <= 1.0 <= me["ci95"][1])
    check("converged on a well-structured crossed design", me.get("converged") is True)
    check("significant in predicted (+) direction", me["significant_in_predicted_direction"])
    check("reports replicate AND problem variance components",
          set(me["variance_components"]) == {"replicate", "problem", "residual"})


def _planted_binary_crossed(delta):
    """Per-turn rows with a BINARY next_turn_independence outcome carrying a known risk
    difference `delta` for leaky turns (plus replicate+problem variation), so the crossed
    linear-probability mixed model has a hand-set target to recover on the binary leg
    (mirrors _planted_crossed, which pins the continuous helpfulness leg). helpfulness is
    set deterministically here so it consumes no RNG draw and does not perturb the
    Bernoulli sequence that defines the binary outcome."""
    rng = __import__("random").Random(3)
    rep_eff = {r: rng.uniform(-0.10, 0.10) for r in range(10)}
    prob_eff = {q: rng.uniform(-0.08, 0.08) for q in range(6)}
    rows = []
    for rep in range(10):
        for prob in range(6):
            for t in range(6):
                leaky = (t % 2 == 0)
                base = 0.70 + rep_eff[rep] + prob_eff[prob]
                p = min(max(base + (delta if leaky else 0.0), 0.02), 0.98)
                y = 1 if rng.random() < p else 0
                rows.append({"condition": "conv", "replicate_id": str(rep),
                             "problem_id": f"train-{prob}", "turn_index": t,
                             "leaks": "True" if leaky else "False",
                             "helpfulness": 4.5 if leaky else 4.0,
                             "next_turn_independence": "True" if y else "False"})
    return rows


def test_j2_mixed_recovers_binary_estimate():
    print("\n[J2 crossed mixed model — recovers a KNOWN binary risk difference]")
    out = I.j2(_planted_binary_crossed(delta=-0.40))
    me = out["leak_to_next_independence"]["mixed_effects"]
    check("crossed mixed model ran on the binary leg", me.get("available") and "coef" in me)
    check("recovers planted risk difference ~ -0.40 (|coef+0.40| < 0.15)",
          abs(me["coef"] - (-0.40)) < 0.15)
    check("95% CI brackets the planted risk difference -0.40",
          me["ci95"][0] <= -0.40 <= me["ci95"][1])
    check("significant in predicted (-) direction", me["significant_in_predicted_direction"])
    check("converged on the binary crossed design", me.get("converged") is True)


def test_verdict_mapping():
    print("\n[§11 verdict mapping — no negative is silently dropped]")
    rng = __import__("random").Random(2)
    rows = []
    for r in range(10):
        # P1: conv leaks much more (clean separation -> supported)
        # P2 (live): helpfulness near-tie / slightly reversed (-> not supported)
        # P3 (manip check): independence near-tie (-> inconclusive)
        rows.append(_per_rep("conv", r, 0.50 + 0.01 * r, 0.50 + rng.uniform(-0.08, 0.08),
                             4.50 + rng.uniform(-0.10, 0.10)))
        rows.append(_per_rep("ped", r, 0.05 + 0.005 * r, 0.50 + rng.uniform(-0.08, 0.08),
                             4.55 + rng.uniform(-0.10, 0.10)))
    j1 = I.j1(rows)
    j2 = I.j2(_planted_turns())  # a supported coupling
    V = {row["claim"].split(" ")[0]: row["verdict"] for row in I.verdict(j1, j2)}
    check("P1 clean separation -> supported", V["P1"] == "supported")
    check("P2 (LIVE) null/reversed -> NOT supported (the §11 negative)", V["P2"] == "not supported")
    check("P3 (manip check) n.s. -> inconclusive (not falsified)", V["P3"] == "inconclusive")
    check("J1 -> not supported when P2 fails", V["J1"] == "not supported")
    check("J2 -> supported on the planted coupling", V["J2"] == "supported")


def main():
    test_cliffs_delta()
    test_bootstrap()
    test_paired_test()
    test_wilcoxon_known_p()
    test_j1_verdict()
    test_j2_recovers_signal()
    test_j2_mixed_recovers_estimate()
    test_j2_mixed_recovers_binary_estimate()
    test_verdict_mapping()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
