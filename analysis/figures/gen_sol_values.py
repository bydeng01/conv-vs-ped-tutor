#!/usr/bin/env python3
"""Generate AI4EDU/values_sol.tex: LaTeX value macros for the cross-judge
(GPT-5.6 Sol) robustness audit and the Opus pedagogy contrasts, sourced only
from the authoritative frozen result artifacts. No number is hand-entered.

Sources (read, never re-fitted except the two deterministic recomputations
explicitly noted):
  results/confirmatory{,_gpt,_gemini}/inference.json     Opus session + J2
  results/confirmatory{,_gpt,_gemini}/per_replicate.csv  Opus pedagogy contrast
  results/judge_robustness/gpt-5.6-sol/<base>/judge_inference.json   Sol session
  results/judge_robustness/gpt-5.6-sol/<base>/policy_adjusted.json   Sol adj slope
  results/judge_robustness/gpt-5.6-sol/comparison/comparison.json    interaction,
                                                          agreement, ceiling

The pedagogy session contrast under Opus is recomputed here from the frozen
per_replicate.csv with the same paired two-sided Wilcoxon signed-rank + Cliff's
delta the confirmatory pipeline uses; every other value is copied from JSON.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "results"
SOL = R / "judge_robustness/gpt-5.6-sol"

BASES = [("sonnet", "confirmatory", "Sonnet"),
         ("gpt", "confirmatory_gpt", "GPT"),
         ("gemini", "confirmatory_gemini", "Gemini")]


def load(p):
    return json.loads(Path(p).read_text())


# ----------------------------------------------------------------- formatting
def num(x, dp=3):
    """Signed fixed-decimal in LaTeX math braces, real minus: {+}0.115 / {-}1.240."""
    s = f"{abs(x):.{dp}f}"
    return ("{+}" if x >= 0 else "{-}") + s


def dlt(x):
    """Cliff's delta: signed, leading zero stripped, |d|=1 -> 1.00."""
    s = f"{abs(x):.2f}"
    if not math.isclose(abs(x), 1.0):
        s = s.lstrip("0")
    return ("{+}" if x >= 0 else "{-}") + s


def pv(p):
    if p < 1e-3:
        e = int(math.floor(math.log10(p)))
        m = p / (10 ** e)
        return f"{m:.1f}{{\\times}}10^{{{e}}}"
    if p >= 1.0:
        return "1.0"
    s = (f"{p:.4f}" if p < 0.1 else f"{p:.3f}")
    return s.lstrip("0")


def cliffs_delta(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    gt = int(np.sum(a[:, None] > b[None, :]))
    lt = int(np.sum(a[:, None] < b[None, :]))
    return (gt - lt) / (a.size * b.size)


def holm(pvals):
    """Holm step-down adjusted p-values for a dict {key: p}."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out = {}
    running = 0.0
    for i, (k, p) in enumerate(items):
        adj = min(1.0, (m - i) * p)
        running = max(running, adj)
        out[k] = running
    return out


# ----------------------------------------------------------------- gather
macros = {}


def put(name, body):
    macros[name] = body


raw_int = {}
for key, cdir, Name in BASES:
    inf = load(R / cdir / "inference.json")
    ji = load(SOL / key / "judge_inference.json")
    pa = load(SOL / key / "policy_adjusted.json")

    # ---- Opus session helpfulness contrast (conv - ped) ----
    p2 = inf["j1"]["P2_helpfulness"]
    put(f"OpusHelp{Name}", num(p2["mean_diff_conv_minus_ped"]))
    put(f"OpusHelp{Name}D", dlt(p2["cliffs_delta_conv_vs_ped"]))
    put(f"OpusHelp{Name}P", pv(p2["p_two_sided"]))

    # ---- Opus session pedagogy contrast: recompute from per_replicate.csv ----
    df = pd.read_csv(R / cdir / "per_replicate.csv")
    conv = df[df.condition == "conv"].sort_values("replicate_id")
    ped = df[df.condition == "ped"].sort_values("replicate_id")
    cv = conv["pedagogy_mean"].to_numpy(float)
    pv_ = ped["pedagogy_mean"].to_numpy(float)
    diff = cv - pv_
    W, pW = wilcoxon(cv, pv_, alternative="two-sided", zero_method="wilcox",
                     mode="exact")
    d_ped = cliffs_delta(cv, pv_)
    put(f"OpusPed{Name}", num(float(diff.mean())))
    put(f"OpusPed{Name}D", dlt(d_ped))
    put(f"OpusPed{Name}P", pv(float(pW)))
    put(f"OpusPedConv{Name}", f"{cv.mean():.3f}")
    put(f"OpusPedPed{Name}", f"{pv_.mean():.3f}")

    # ---- Opus pooled + J2 deterministic legs ----
    j2 = inf["j2"]
    ph = j2["leak_to_helpfulness"]["mixed_effects"]
    pi = j2["leak_to_next_independence"]["mixed_effects"]
    put(f"OpusPoolHelp{Name}", num(ph["coef"]))
    put(f"OpusPoolHelp{Name}P", pv(ph["p"]))
    put(f"DetIndep{Name}", num(pi["coef"]))
    put(f"DetIndep{Name}P", pv(pi["p"]))
    # ---- deterministic P1 leakage ----
    p1 = inf["j1"]["P1_leakage"]
    put(f"DetLeakConv{Name}", f"{p1['conv_mean']:.3f}")
    put(f"DetLeakPed{Name}", f"{p1['ped_mean']:.3f}")
    put(f"DetLeak{Name}D", dlt(p1["cliffs_delta_conv_vs_ped"]))
    put(f"DetLeak{Name}P", pv(p1["p_two_sided"]))
    put(f"Nturn{Name}", str(int(j2["n_turns"])))

    # ---- Sol session contrasts ----
    sh = ji["session_helpfulness_contrast"]
    sp = ji["session_pedagogy_contrast_manipulation_check"]
    put(f"SolHelp{Name}", num(sh["mean_diff_conv_minus_ped"]))
    put(f"SolHelp{Name}D", dlt(sh["cliffs_delta_conv_vs_ped"]))
    put(f"SolHelp{Name}P", pv(sh["p_two_sided"]))
    put(f"SolPed{Name}", num(sp["mean_diff_conv_minus_ped"]))
    put(f"SolPed{Name}D", dlt(sp["cliffs_delta_conv_vs_ped"]))
    put(f"SolPed{Name}P", pv(sp["p_two_sided"]))
    put(f"SolPedConv{Name}", f"{sh['conv_mean']:.3f}")  # placeholder overwritten below
    put(f"SolPedConv{Name}", f"{sp['conv_mean']:.3f}")
    put(f"SolPedPed{Name}", f"{sp['ped_mean']:.3f}")

    # ---- Sol pooled + policy-adjusted leak->helpfulness ----
    tlh = ji["turn_leak_to_helpfulness"]
    put(f"SolPoolHelp{Name}", num(tlh["coef"]))
    put(f"SolPoolHelp{Name}P", pv(tlh["p"]))
    adj = pa["models"]["helpfulness"]
    put(f"SolAdjHelp{Name}", num(adj["coefficient"]))
    put(f"SolAdjHelp{Name}P", pv(adj["p_value"]))

# ---- comparison.json: interaction (Holm), agreement, ceiling ----
comp = load(SOL / "comparison/comparison.json")
for key, cdir, Name in BASES:
    raw_int[key] = comp["per_base"][key]["instruments"]["helpfulness"][
        "interaction"]["raw"]["judge_x_policy_condition_ped"]["p"]
holm_int = holm(raw_int)
for key, cdir, Name in BASES:
    put(f"HolmHelp{Name}", pv(holm_int[key]))
    put(f"RawIntHelp{Name}", pv(raw_int[key]))

opd = comp["overall_pooled_descriptive"]
put("AgreeHelpRho", f"{opd['helpfulness']['agreement']['spearman_of_per_turn_means']:.3f}".lstrip("0"))
put("AgreeHelpKappa", f"{opd['helpfulness']['agreement']['quadratic_weighted_kappa_on_medians']:.3f}".lstrip("0"))
put("AgreePedRho", f"{opd['pedagogy']['agreement']['spearman_of_per_turn_means']:.3f}".lstrip("0"))
put("AgreePedKappa", f"{opd['pedagogy']['agreement']['quadratic_weighted_kappa_on_medians']:.3f}".lstrip("0"))
put("CeilOpus", str(int(opd["helpfulness"]["agreement"]["opus_median_distribution"]["5"])))
put("CeilSol", str(int(opd["helpfulness"]["agreement"]["gpt_median_distribution"]["5"])))
NT = int(opd["helpfulness"]["agreement"]["n_turns"])
put("NturnTotal", str(NT))
put("NratingTotal", str(NT * 2 * 3))

# ---- per-base agreement: the pooled ordering does not hold per base (B2) ----
for key, cdir, Name in BASES:
    ag_h = comp["per_base"][key]["instruments"]["helpfulness"]["agreement"]
    ag_p = comp["per_base"][key]["instruments"]["pedagogy"]["agreement"]
    put(f"AgreeHelpRho{Name}",
        f"{ag_h['spearman_of_per_turn_means']:.3f}".lstrip("0"))
    put(f"AgreePedRho{Name}",
        f"{ag_p['spearman_of_per_turn_means']:.3f}".lstrip("0"))
put("AgreePedExact",
    f"{opd['pedagogy']['agreement']['exact_agreement_on_medians'] * 100:.1f}")

# ---- primary-base probe-accuracy envelope over ALL THREE conditions (B3) ----
_acc = load(R / "confirmatory/inference.json")["accuracy"]
_cells = [v["mean"] for c, d in _acc.items() if c != "note" for v in d.values()]
put("AccMinSonnet", f"{min(_cells):.2f}")
put("AccMaxSonnet", f"{max(_cells):.2f}")

# ----------------------------------------------------------------- emit
lines = ["% GENERATED by analysis/figures/gen_sol_values.py -- do not hand edit.",
         "% Cross-judge (GPT-5.6 Sol) robustness values + Opus pedagogy contrasts,",
         "% sourced from frozen results/ artifacts. See that script for provenance.",
         ""]
for name in sorted(macros):
    body = macros[name]
    lines.append(f"\\newcommand{{\\{name}}}{{\\ensuremath{{{body}}}}}")
out = ROOT / "AI4EDU/values_sol.tex"
out.write_text("\n".join(lines) + "\n")

# QA ledger to stdout
print("== values_sol.tex QA ==")
for key, cdir, Name in BASES:
    print(f"[{Name}] Opus help {macros[f'OpusHelp{Name}']} d={macros[f'OpusHelp{Name}D']} p={macros[f'OpusHelp{Name}P']}"
          f" | Sol help {macros[f'SolHelp{Name}']} d={macros[f'SolHelp{Name}D']} p={macros[f'SolHelp{Name}P']}")
    print(f"        Opus ped  {macros[f'OpusPed{Name}']} d={macros[f'OpusPed{Name}D']} p={macros[f'OpusPed{Name}P']}"
          f" ({macros[f'OpusPedConv{Name}']}/{macros[f'OpusPedPed{Name}']})"
          f" | Sol ped {macros[f'SolPed{Name}']} d={macros[f'SolPed{Name}D']} p={macros[f'SolPed{Name}P']}"
          f" ({macros[f'SolPedConv{Name}']}/{macros[f'SolPedPed{Name}']})")
    print(f"        Holm(jxpolicy help)={macros[f'HolmHelp{Name}']} (raw {macros[f'RawIntHelp{Name}']})"
          f" | Sol adj-help {macros[f'SolAdjHelp{Name}']} p={macros[f'SolAdjHelp{Name}P']}"
          f" | det leak->indep {macros[f'DetIndep{Name}']} p={macros[f'DetIndep{Name}P']}")
print(f"agree help rho={macros['AgreeHelpRho']} kappa={macros['AgreeHelpKappa']}"
      f" | ped rho={macros['AgreePedRho']} kappa={macros['AgreePedKappa']}")
print(f"ceiling opus={macros['CeilOpus']} sol={macros['CeilSol']} / {macros['NturnTotal']} ; ratings={macros['NratingTotal']}")
print(f"n turns per base: {macros['NturnSonnet']}/{macros['NturnGPT']}/{macros['NturnGemini']}")
print(f"wrote {out} with {len(macros)} macros")
