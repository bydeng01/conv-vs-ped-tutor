"""Confirmatory inferential analysis (paper-plan.md §10) — the FROZEN analysis plan, run
post-hoc over the compute_metrics output tables (per_replicate.csv, per_session.csv,
per_turn.csv). Nothing here changes a frozen metric, window, or rubric; it only runs the
pre-registered tests on the already-computed conversation summaries.

Implements §10 exactly:
  - J1: paired Wilcoxon signed-rank (two-tailed, alpha=0.05, paired by replicate id) on
    leakage (conv>ped), annotator-perceived helpfulness (conv>ped — the live test, P2),
    and independence (ped>conv); Cliff's delta effect size; conversation-level bootstrap
    95% CIs; the joint verdict (§11: P1 & P3 separate, P2 significant, J2 holds).
  - J2: the frozen §10 mixed-effects coupling (leakage -> helpfulness; leakage ->
    next-turn independence) with CROSSED replicate AND problem random intercepts
    (paper-plan §10; metric-amendment §3). A conversation-clustered two-stage
    signed-rank is also reported as a dependency-light robustness check.
  - Accuracy (secondary): per-condition per-role means + CIs, NO NHST (§4 S1).
  - Cost-normalized sensitivity: the J1 contrasts on per-1k-tutor-token outcomes; a
    marginal whose direction/significance flips under normalization is flagged (§10).

Outcome interpretation follows paper-plan.md §11.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats

ALPHA = 0.05
# Predicted sign of the paired conv-ped difference for each marginal.
PREDICTED = {"leakage_rate": +1, "helpfulness_mean": +1, "independence_ratio": -1}
ROLE_ACCURACY = ("acc_immediate", "acc_delayed", "acc_transfer")


# ------------------------------------------------------------------ primitives
def cliffs_delta(a, b) -> float:
    """Cliff's delta between groups a and b: (#a>b - #a<b) / (|a|*|b|). In [-1, 1]."""
    a, b = list(a), list(b)
    if not a or not b:
        return float("nan")
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (len(a) * len(b))


def bootstrap_ci(values, stat=np.mean, n_boot: int = 10000, alpha: float = ALPHA,
                 seed: int = 0):
    """Percentile bootstrap CI for `stat` over `values` (conversation-level, §10)."""
    v = np.asarray([x for x in values if x is not None and not np.isnan(x)], float)
    if v.size == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    boots = [stat(rng.choice(v, size=v.size, replace=True)) for _ in range(n_boot)]
    lo, hi = np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return (float(lo), float(hi))


def paired_test(conv, ped, predicted_sign: int) -> dict:
    """Paired conv-ped comparison on conversation summaries: two-sided Wilcoxon
    signed-rank (exact for small n with no ties), Cliff's delta on the two groups, and a
    bootstrap CI on the mean paired difference. `predicted_sign` is +1 (conv>ped) or -1
    (ped>conv). 'significant' = two-sided p<alpha AND the observed direction matches."""
    conv = np.asarray(conv, float)
    ped = np.asarray(ped, float)
    diffs = conv - ped
    nz = diffs[diffs != 0]
    if nz.size >= 1:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            W, p = stats.wilcoxon(conv, ped, alternative="two-sided",
                                  zero_method="wilcox")
        W, p = float(W), float(p)
    else:
        W, p = float("nan"), 1.0
    mean_diff = float(np.mean(diffs))
    direction_ok = (np.sign(mean_diff) == predicted_sign) if mean_diff != 0 else False
    return {
        "n": int(diffs.size),
        "n_conv_gt_ped": int(np.sum(diffs > 0)),
        "n_ped_gt_conv": int(np.sum(diffs < 0)),
        "conv_mean": float(np.mean(conv)),
        "ped_mean": float(np.mean(ped)),
        "mean_diff_conv_minus_ped": mean_diff,
        "median_diff": float(np.median(diffs)),
        "diff_ci95": bootstrap_ci(diffs),
        "wilcoxon_W": W,
        "p_two_sided": p,
        "cliffs_delta_conv_vs_ped": cliffs_delta(conv, ped),
        "predicted_sign": predicted_sign,
        "direction_matches_prediction": bool(direction_ok),
        "significant_in_predicted_direction": bool(p < ALPHA and direction_ok),
    }


# ------------------------------------------------------------------ loaders
def _paired(rows: list[dict], col: str):
    """Aligned conv/ped arrays over replicate ids present (and non-null) in both."""
    by = {}
    for r in rows:
        v = r.get(col)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        by.setdefault(r["replicate_id"], {})[r["condition"]] = v
    conv, ped, rids = [], [], []
    for rid in sorted(by, key=lambda x: (len(str(x)), str(x))):
        d = by[rid]
        if "conv" in d and "ped" in d:
            conv.append(d["conv"]); ped.append(d["ped"]); rids.append(rid)
    return conv, ped, rids


# ------------------------------------------------------------------ J1
def j1(per_replicate: list[dict]) -> dict:
    """The three paired marginals + the §11 joint verdict."""
    out = {}
    label = {"leakage_rate": "P1_leakage", "helpfulness_mean": "P2_helpfulness",
             "independence_ratio": "P3_independence"}
    for col, sign in PREDICTED.items():
        conv, ped, rids = _paired(per_replicate, col)
        res = paired_test(conv, ped, sign)
        res["n_replicates"] = len(rids)
        out[label[col]] = res
    p1, p2, p3 = out["P1_leakage"], out["P2_helpfulness"], out["P3_independence"]
    # §11: joint coupling J1 is supported only if P1 & P3 separate (manipulation checks)
    # AND P2 is significant in the predicted direction. (J2 is added by the caller.)
    out["joint_J1"] = {
        "P1_separates": p1["significant_in_predicted_direction"],
        "P3_separates": p3["significant_in_predicted_direction"],
        "P2_significant_conv_gt_ped": p2["significant_in_predicted_direction"],
        "J1_marginal_supported": bool(
            p1["significant_in_predicted_direction"]
            and p3["significant_in_predicted_direction"]
            and p2["significant_in_predicted_direction"]),
    }
    return out


# ------------------------------------------------------------------ J2
def _cluster_summary(df: pd.DataFrame, outcome: str, predicted_sign: int,
                     group: str = "replicate_id") -> dict:
    """Two-stage conversation-clustered test (scipy-only): within each replicate compute
    the leaky-minus-non-leaky effect on `outcome`, then a two-sided Wilcoxon signed-rank
    across the replicate-level effects. The replicate (conversation) is the unit — no turn
    pooling (§10). Predicted sign is on (leaky - nonleaky): helpfulness +1, next-turn
    independence -1. Robust and dependency-light; reported as the operative J2 test when
    the canonical statsmodels mixed model can't run here."""
    effs = []
    for _, sub in df.groupby(group):
        lk = sub[sub["leaks_i"] == 1][outcome]
        nl = sub[sub["leaks_i"] == 0][outcome]
        if len(lk) >= 1 and len(nl) >= 1:
            effs.append(float(lk.mean() - nl.mean()))
    effs = np.asarray(effs, float)
    if effs.size and (effs != 0).any():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            W, p = stats.wilcoxon(effs, alternative="two-sided", zero_method="wilcox")
        W, p = float(W), float(p)
    else:
        W, p = float("nan"), 1.0
    mean_eff = float(np.mean(effs)) if effs.size else float("nan")
    dir_ok = (np.sign(mean_eff) == predicted_sign) if (effs.size and mean_eff != 0) else False
    return {"method": "two-stage cluster-summary (within-replicate leaky-minus-nonleaky; "
                      "signed-rank across replicates)",
            "n_replicates_used": int(effs.size),
            "mean_within_replicate_effect": mean_eff,
            "effect_ci95": bootstrap_ci(effs) if effs.size else (None, None),
            "wilcoxon_W": W, "p_two_sided": p, "predicted_sign": predicted_sign,
            "direction_matches_prediction": bool(dir_ok),
            "significant_in_predicted_direction": bool(p < ALPHA and dir_ok)}


# The frozen §10 / metric-amendment §3 J2 model uses CROSSED random intercepts for
# replicate AND problem. statsmodels expresses crossed REs as variance components over a
# single dummy group. A short optimizer sequence is tried so a variance component pinned
# at the zero boundary (common with the binary independence outcome) still yields a
# converged fit. The pinned analysis passes this fixed sequence to statsmodels, which
# tries the methods in order until convergence. Exact estimates can vary slightly across
# optimizers; in separately checked GPT fits, the coefficient's sign and inferential
# conclusion were unchanged.
J2_OPTIMIZERS = ["lbfgs", "bfgs", "cg", "powell"]


def _crossed_mixedlm(df: pd.DataFrame, outcome: str, predicted_sign: int) -> dict:
    """Canonical §10 J2 mixed-effects model: `outcome ~ leaks_i` with crossed replicate
    AND problem random intercepts. Returns an availability note instead of raising if
    statsmodels can't import (so the rest of the analysis still runs; the operative test
    then falls back to the conversation-clustered signed-rank)."""
    try:
        import statsmodels.formula.api as smf
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": f"statsmodels import failed: {type(e).__name__}: {e}"}
    try:
        d = df[["replicate_id", "problem_id", "leaks_i", outcome]].dropna().copy()
        d["_grp"] = 1  # single dummy group; crossed REs live in vc_formula
        vc = {"replicate": "0 + C(replicate_id)", "problem": "0 + C(problem_id)"}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = smf.mixedlm(f"{outcome} ~ leaks_i", d, groups="_grp",
                              re_formula="0", vc_formula=vc).fit(reml=False, method=J2_OPTIMIZERS)
        ci = fit.conf_int().loc["leaks_i"]
        coef, p = float(fit.params["leaks_i"]), float(fit.pvalues["leaks_i"])
        # statsmodels sorts vc names alphabetically; pair the sorted names with vcomp.
        vcomp = {name: float(v) for name, v in zip(sorted(vc), np.atleast_1d(fit.vcomp))}
        vcomp["residual"] = float(fit.scale)
        return {"available": True,
                "model": "mixedlm: outcome ~ leaks_i; crossed RE = replicate + problem "
                         "(variance components over a dummy group); ML, "
                         f"optimizer tried in order {J2_OPTIMIZERS}",
                "coef": coef, "se": float(fit.bse["leaks_i"]), "p": p,
                "ci95": [float(ci[0]), float(ci[1])],
                "converged": bool(fit.converged),
                "variance_components": vcomp,
                "n_obs": int(d.shape[0]),
                "n_replicates": int(d["replicate_id"].nunique()),
                "n_problems": int(d["problem_id"].nunique()),
                "predicted_sign": predicted_sign,
                "significant_in_predicted_direction": bool(p < ALPHA and np.sign(coef) == predicted_sign)}
    except Exception as e:  # noqa: BLE001
        return {"available": True, "error": f"fit failed: {type(e).__name__}: {e}"}


def _leg(df: pd.DataFrame, outcome: str, predicted_sign: int) -> dict:
    sub = df[["replicate_id", "problem_id", "leaks_i", outcome]].dropna()
    cluster = _cluster_summary(sub, outcome, predicted_sign)
    mixed = _crossed_mixedlm(sub, outcome, predicted_sign)
    mixed_ran = mixed.get("available") and "coef" in mixed
    leaky = sub[sub["leaks_i"] == 1][outcome]
    nonl = sub[sub["leaks_i"] == 0][outcome]
    desc = {"leaky_mean": float(leaky.mean()) if len(leaky) else None,
            "nonleaky_mean": float(nonl.mean()) if len(nonl) else None,
            "n_leaky": int(len(leaky)), "n_nonleaky": int(len(nonl))}
    operative = (mixed["significant_in_predicted_direction"] if mixed_ran
                 else cluster["significant_in_predicted_direction"])
    return {"predicted_sign": predicted_sign,
            "operative_method": "mixed_effects" if mixed_ran else "cluster_summary",
            "operative_significant_in_predicted_direction": bool(operative),
            "cluster_summary": cluster, "mixed_effects": mixed, "descriptive_pooled": desc}


def j2(per_turn: list[dict]) -> dict:
    """Per-turn coupling J2: leakage -> helpfulness (predicted +) and leakage -> next-turn
    independence (predicted -). Operative test is the conversation-clustered two-stage
    signed-rank; the canonical §10 mixed-effects model is also attempted and reported when
    statsmodels is importable."""
    df = pd.DataFrame(per_turn)
    def _b(x):
        s = str(x).lower()
        return 1.0 if s == "true" else (0.0 if s == "false" else np.nan)
    df["leaks_i"] = df["leaks"].map(_b)
    df["helpfulness"] = pd.to_numeric(df["helpfulness"], errors="coerce")
    df["nti"] = df["next_turn_independence"].map(_b)
    out = {"n_turns": int(df.shape[0])}
    out["leak_to_helpfulness"] = _leg(df.dropna(subset=["leaks_i", "helpfulness"]), "helpfulness", +1)
    out["leak_to_next_independence"] = _leg(df.dropna(subset=["leaks_i", "nti"]), "nti", -1)
    out["J2_supported"] = bool(
        out["leak_to_helpfulness"]["operative_significant_in_predicted_direction"]
        and out["leak_to_next_independence"]["operative_significant_in_predicted_direction"])
    out["mixed_effects_available"] = bool(out["leak_to_helpfulness"]["mixed_effects"].get("available")
                                          and "coef" in out["leak_to_helpfulness"]["mixed_effects"])
    # §10 forbids re-spec'ing to move a p-value; concerns are disclosed, not re-modeled.
    out["limitations"] = [
        "leak_to_next_independence outcome is BINARY; the mixed model is a linear "
        "probability model, so its fixed effect is a risk-difference, not a log-odds. A "
        "logistic GLMM is a defensible alternative deliberately NOT substituted post-hoc "
        "(frozen §10 names a mixed-effects model, family unspecified; the linear family "
        "matches the helpfulness leg and the committed spec).",
        "J2 pools conv and ped tutor turns; leakage correlates with condition, so the "
        "fixed effect blends within- and between-condition variation. Per frozen §10 "
        "condition is NOT added as a covariate; a condition-stratified check is noted as "
        "a limitation, not run as a re-spec.",
    ]
    return out


# ------------------------------------------------------------------ accuracy (no NHST)
def accuracy(per_replicate: list[dict]) -> dict:
    out = {}
    for cond in ("cold", "conv", "ped"):
        rows = [r for r in per_replicate if r["condition"] == cond]
        out[cond] = {}
        for col in ROLE_ACCURACY:
            vals = []
            for r in rows:
                try:
                    vals.append(float(r[col]))
                except (TypeError, ValueError, KeyError):
                    pass
            out[cond][col] = {"mean": float(np.mean(vals)) if vals else None,
                              "ci95": bootstrap_ci(vals) if vals else (None, None),
                              "n": len(vals)}
    out["note"] = "secondary/descriptive (S1, expected to saturate); no significance test (§4, §10)."
    return out


# ------------------------------------------------------------------ cost-normalized
def cost_normalized(per_session: list[dict], j1_result: dict) -> dict:
    """Re-run the count-based marginals per 1k tutor tokens (§10 compute-fairness). Flag a
    marginal whose significance/direction differs from the raw J1."""
    out = {}
    spec = {"leaky_turns_per_1k_tutor_tok": ("P1_leakage", +1),
            "independent_turns_per_1k_tutor_tok": ("P3_independence", -1)}
    for col, (raw_key, sign) in spec.items():
        conv, ped, rids = _paired(per_session, col)
        if not conv:
            out[col] = {"note": "column absent"}
            continue
        res = paired_test(conv, ped, sign)
        raw_sig = j1_result[raw_key]["significant_in_predicted_direction"]
        out[col] = {**res,
                    "raw_was_significant": raw_sig,
                    "flips_under_normalization": bool(raw_sig != res["significant_in_predicted_direction"])}
    return out


# ------------------------------------------------------------------ §11 verdict roll-up
def _leg_effect(leg: dict) -> tuple[str, float | None]:
    """Effect string + p for a J2 leg: the canonical mixed model when it ran, else the
    conversation-clustered signed-rank (so the table never silently drops a leg)."""
    me = leg["mixed_effects"]
    if me.get("available") and "coef" in me:
        return (f"mixed coef {me['coef']:+.3f} 95% CI [{me['ci95'][0]:+.3f}, {me['ci95'][1]:+.3f}]",
                me["p"])
    cs = leg["cluster_summary"]
    return (f"cluster within-rep effect {cs['mean_within_replicate_effect']:+.3f} "
            f"(statsmodels unavailable)", cs["p_two_sided"])


def verdict(j1_result: dict, j2_result: dict | None) -> list[dict]:
    """The §11 plain-language verdict for every pre-registered claim, reported regardless
    of outcome (no file-drawer). Manipulation checks (P1, P3) that fail to separate are
    'inconclusive' (uninterpretable, not falsified — §11); the live test P2 that is
    null/reversed is 'not supported' (the §11 negative result); J1 needs all three
    directions with P2 significant; J2 (headline) needs both coupling legs. Effect sizes
    and CIs are carried through verbatim — nothing is re-derived here."""
    def marg(key, claim, manip):
        r = j1_result[key]
        sig = r["significant_in_predicted_direction"]
        # a failed manipulation check is 'inconclusive'; a failed live test is 'not supported'
        v = "supported" if sig else ("inconclusive" if manip else "not supported")
        return {"claim": claim, "verdict": v,
                "effect": f"Cliff's delta {r['cliffs_delta_conv_vs_ped']:+.2f}",
                "ci": f"diff(conv-ped) {r['mean_diff_conv_minus_ped']:+.3f} "
                      f"95% CI [{r['diff_ci95'][0]:+.3f}, {r['diff_ci95'][1]:+.3f}]",
                "p": r["p_two_sided"]}
    rows = [
        marg("P1_leakage", "P1 leakage (conv>ped; manipulation check)", manip=True),
        marg("P2_helpfulness", "P2 annotator-perceived helpfulness (conv>ped; LIVE test)", manip=False),
        marg("P3_independence", "P3 independence (ped>conv; manipulation check)", manip=True),
    ]
    j1_ok = bool(j1_result["joint_J1"]["J1_marginal_supported"])
    rows.append({"claim": "J1 joint marginal coupling (all 3 directions + P2 significant)",
                 "verdict": "supported" if j1_ok else "not supported",
                 "effect": "conjunction of P1/P2/P3", "ci": "—", "p": None})
    if j2_result and "leak_to_helpfulness" in j2_result:
        he, hp = _leg_effect(j2_result["leak_to_helpfulness"])
        ne, npv = _leg_effect(j2_result["leak_to_next_independence"])
        j2_ok = bool(j2_result.get("J2_supported"))
        rows.append({"claim": "J2 per-turn coupling (HEADLINE): leak->helpfulness +, leak->next-indep -",
                     "verdict": "supported" if j2_ok else "not supported",
                     "effect": f"helpfulness {he}; independence {ne}", "ci": "(in effect)",
                     "p": f"help p={hp:.2e}; indep p={npv:.2e}"})
    return rows
