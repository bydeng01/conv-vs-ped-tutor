"""Cross-judge comparison: Claude Opus 4.8 (frozen primary) vs GPT-5.6 Sol (robustness).

EPISTEMIC STATUS: prospectively specified post hoc cross-judge robustness analysis over
frozen transcripts. This module NEVER averages the two instruments into a consensus
headline -- both judges are reported separately, and disagreement is a RESULT, not noise to
be smoothed away. A two-model panel can support "replicated across Opus and GPT-5.6 Sol",
"directionally consistent across two specified judges", or "judge-contingent"; it can NEVER
support "generalizable across LLM judges", "judge-independent", or any human-validity claim.

Alignment is by EXACT turn identity (base, run_id, condition, replicate_id, problem_id,
turn_index). Repetition indices are arbitrary within-model samples, so rep 0 is NEVER paired
with rep 0; the comparison is over per-turn aggregates (means) and each judge's median
integer rating over its three reps.

For each instrument (helpfulness, pedagogy), by tutor base and overall:
  - Spearman of per-turn means + conversation-clustered bootstrap 95% CI
  - quadratic-weighted Cohen's kappa on median integer ratings + clustered CI
  - mean signed diff (GPT - Opus), mean absolute diff, exact agreement, within-one agreement
  - score distributions, valid-repetition rates, within-turn repetition variance per judge
Correlation is NOT agreement: a systematic scale shift is reported even when Spearman is high.

Judge-interaction analysis (per base): score_difference = GPT mean - Opus mean, fit
`score_difference ~ leaks_i + C(condition)` with crossed replicate+problem random intercepts
(reusing the frozen condition-adjusted fitting logic). leaks_i is the judge x leakage
interaction; C(condition) is the judge x tutoring-policy interaction. A within-judge/base
standardized refit is the scale-use sensitivity. At the replicate level,
[(Conv-Ped)_GPT - (Conv-Ped)_Opus] is reported with its ten values, mean, bootstrap CI, and
paired signed-rank. The GPT-judge/GPT-tutor arm is flagged same-family; a sensitivity summary
restricted to Sonnet+Gemini is added. Holm adjustment is applied WITHIN three declared
families (3 policy-adjusted leakage slopes; 3 judge x leakage interactions; 3 judge x
condition interactions); a nonsignificant interaction is NOT read as equivalence.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import inferential as I  # noqa: E402  bootstrap_ci, J2_OPTIMIZERS
from analysis import condition_adjusted_sensitivity as S  # noqa: E402  VC_FORMULA

INSTRUMENTS = ("helpfulness", "pedagogy")
MIN_RATING, MAX_RATING = 1, 5
ALPHA = 0.05
ALLOWED_NAMESPACE = ("results", "judge_robustness")
# Each declared Holm family is THREE tests (one per tutor base). The family size is a property
# of the declared analysis, not of how many tests happened to succeed: a degraded run must not
# shrink its own multiplicity denominator into significance.
DECLARED_FAMILY_SIZE = 3
RUN_STATE_FILE = "run_state.json"
# The ROBUSTNESS judge (GPT-5.6 Sol) shares a model family with the GPT-5.5 tutor on the
# `gpt` base -- the arm the Sonnet+Gemini-only sensitivity removes.
SAME_FAMILY_BASE = "gpt"
# Symmetric disclosure: the PRIMARY judge (Claude Opus 4.8) ALSO shares a model family with
# its tutor on the `sonnet` base (Claude Sonnet 4.6). This is a property of the original
# confirmatory study, not introduced here, but it is disclosed so the same-family caveat is
# not read as applying only to the GPT arm. The Sonnet+Gemini-only sensitivity removes the
# GPT-judge family confound; the Sonnet base still carries this primary-judge overlap.
PRIMARY_JUDGE_FAMILY_BASE = "sonnet"

DEFAULT_PAIRS = [
    ("sonnet", "results/confirmatory", "results/judge_robustness/gpt-5.6-sol/sonnet"),
    ("gpt", "results/confirmatory_gpt", "results/judge_robustness/gpt-5.6-sol/gpt"),
    ("gemini", "results/confirmatory_gemini", "results/judge_robustness/gpt-5.6-sol/gemini"),
]
DEFAULT_OUT = "results/judge_robustness/gpt-5.6-sol/comparison"


# -------------------------------------------------------------------- guards
def _enforce_namespace(out_dir: Path) -> None:
    """Refuse to write the comparison anywhere but results/judge_robustness/... (the same
    guard the scoring runner uses; never a canonical/frozen results dir)."""
    try:
        rel = out_dir.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        raise SystemExit(f"--out must be inside results/judge_robustness/: {out_dir}")
    if rel.parts[:2] != ALLOWED_NAMESPACE:
        raise SystemExit(
            f"REFUSING to write the cross-judge comparison to {rel}: only "
            "results/judge_robustness/ is allowed (never results/confirmatory*, "
            "results/ablation, or results/condition_adjusted_sensitivity).")


def _assert_reportable(detail_path: Path, blob: dict) -> None:
    """Refuse to compare a MOCK/synthetic GPT detail as if it were a real judge pass.
    A live/offline-cache-only detail is fine; backend=='mock' or a do-not-report score_source
    aborts (the mock backend exists only for offline plumbing)."""
    backend = str(blob.get("backend", "")).lower()
    score_source = str(blob.get("score_source", ""))
    if backend == "mock" or any(s in score_source.upper() for s in ("MOCK", "DO NOT REPORT")) \
            or "synthetic" in score_source.lower():
        raise SystemExit(
            f"{detail_path}: this GPT detail is MOCK/synthetic (backend={backend!r}, "
            f"score_source={score_source!r}) -- refusing to build a reportable cross-judge "
            "comparison from do-not-report scores. Run the live GPT judge pass first.")


# -------------------------------------------------------------------- loading + alignment
def _assert_current_complete(base: str, gpt_dir: Path, instrument: str, blob: dict) -> None:
    """Refuse to compare GPT outputs that are not the CURRENT, complete, promoted set.

    The runner promotes a scoring attempt atomically and records `run_state.json` last. Before
    that existed, an incomplete rerun left the previous run's detail files, CSVs, inference and
    provenance in place next to a new partial cache, and this comparator -- which only checked
    file presence -- would happily report them. Now the comparison requires:

      * `run_state.json` with state == "complete" and complete is True;
      * the promoted run's recorded cache stamp for this instrument to equal the stamp embedded
        in `<instrument>_detail.json`;
      * the on-disk per-rep cache (when packaged) to carry that same stamp, so a cache that was
        re-scored after these outputs were promoted is caught rather than reported.
    """
    state_path = gpt_dir / RUN_STATE_FILE
    if not state_path.is_file():
        raise SystemExit(
            f"{base}/{instrument}: no {RUN_STATE_FILE} in {gpt_dir}. The GPT outputs are not a "
            "verifiably complete promoted set (they predate transactional promotion, or the run "
            "never finished). Re-run analysis/run_cross_judge_audit.py for this base.")
    state = json.loads(state_path.read_text())
    if state.get("state") != "complete" or state.get("complete") is not True:
        raise SystemExit(
            f"{base}/{instrument}: {state_path} reports state={state.get('state')!r} "
            f"complete={state.get('complete')!r}. These outputs were invalidated by a later "
            "scoring attempt that did not complete; refusing to compare stale results.")
    want = (state.get("cache_stamps") or {}).get(instrument)
    got = blob.get("stamp")
    if want is None:
        raise SystemExit(
            f"{base}/{instrument}: {state_path} records no cache stamp for this instrument; "
            "the promoted set cannot be tied to the scores it came from.")
    if got != want:
        raise SystemExit(
            f"{base}/{instrument}: the stamp in {instrument}_detail.json does not match the "
            f"stamp recorded when this output set was promoted. The detail file and the "
            "promoted run disagree about which scoring run produced it; refusing to compare.")
    cache_path = gpt_dir / "cache" / f"{instrument}_cache.json"
    if cache_path.is_file():
        cached = json.loads(cache_path.read_text())
        if (cached or {}).get("stamp") != want:
            raise SystemExit(
                f"{base}/{instrument}: the on-disk per-rep cache {cache_path} carries a "
                "different stamp from the promoted outputs -- the cache was re-scored after "
                "these results were published. Refusing to compare results against a cache "
                "that no longer produced them.")


def _detail_turns(detail_path: Path, assert_reportable: bool = False, on_blob=None) -> dict:
    """{(run_id, problem_id, turn_index): turn} from a *_detail.json (Opus or GPT)."""
    blob = json.loads(detail_path.read_text())
    if assert_reportable:
        _assert_reportable(detail_path, blob)
    if on_blob is not None:
        on_blob(blob)
    out = {}
    for run in blob.get("runs", []):
        for t in run["turns"]:
            out[(t["run_id"], t["problem_id"], t["turn_index"])] = t
    return out


def _leaks_by_turn(opus_dir: Path) -> dict:
    """{(condition, replicate_id, problem_id, turn_index): leaks_bool} from the frozen Opus
    per_turn.csv. Leakage is DETERMINISTIC (judge-invariant), so it is read once here."""
    out = {}
    for r in pd.read_csv(opus_dir / "per_turn.csv").to_dict("records"):
        key = (str(r["condition"]), str(r["replicate_id"]), str(r["problem_id"]),
               int(r["turn_index"]))
        out[key] = 1.0 if str(r["leaks"]).lower() == "true" else 0.0
    return out


def _manifest_dialogue_hashes(base: str, instrument: str, gpt_dir: Path) -> dict:
    """{(run_id, problem_id, turn_index): dialogue_sha256} from the base's frozen
    input_manifest.jsonl, used to prove the GPT scores were produced from the planned dialogue
    text.

    The manifest is REQUIRED. It was previously optional ("absent for synthetic fixtures"), and
    an absent manifest degraded to an empty hash map -- which, combined with a hash check that
    only fired when both sides were truthy, meant deleting one gitignore-adjacent file silently
    removed the entire dialogue binding while the comparison still published. Being unable to
    check the binding is not the same as the binding holding."""
    path = gpt_dir / "input_manifest.jsonl"
    if not path.is_file():
        raise SystemExit(
            f"{base}/{instrument}: no input_manifest.jsonl in {path.parent}. This file is the "
            "only thing tying the GPT ratings to the frozen dialogue text they were supposed "
            "to be produced from; without it the comparison cannot show the scores came from "
            "the planned inputs at all. Refusing to publish an unbound comparison. Re-run "
            "analysis/run_cross_judge_audit.py --manifest-only for this base, or restore the "
            "manifest frozen at plan time.")
    out = {}
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            key = (r["run_id"], r["problem_id"], r["turn_index"])
            digest = r["dialogue_sha256"]
        except (ValueError, KeyError, TypeError) as e:
            raise SystemExit(
                f"{base}/{instrument}: {path}:{lineno} is not a usable manifest record "
                f"({type(e).__name__}: {e}). A damaged manifest must not be read as a weaker "
                "binding; refusing to compare.") from e
        if not digest:
            raise SystemExit(
                f"{base}/{instrument}: {path}:{lineno} records an empty dialogue_sha256 for "
                f"{key}. An empty expected hash cannot bind anything; refusing to compare.")
        out[key] = digest
    return out


def _median_int(values) -> float | None:
    vals = [v for v in (values or []) if v is not None]
    return float(statistics.median(vals)) if vals else None


def load_aligned(base: str, opus_dir: str, gpt_dir: str, instrument: str) -> list[dict]:
    """Aligned per-turn records for one base+instrument. Requires EXACT turn-identity
    equality between the Opus and GPT surfaces (raises on any mismatch)."""
    opus_dir, gpt_dir = REPO_ROOT / opus_dir, REPO_ROOT / gpt_dir
    opus = _detail_turns(opus_dir / f"{instrument}_detail.json")
    gpt = _detail_turns(
        gpt_dir / f"{instrument}_detail.json", assert_reportable=True,
        on_blob=lambda b: _assert_current_complete(base, gpt_dir, instrument, b))
    if set(opus) != set(gpt):
        only_o, only_g = set(opus) - set(gpt), set(gpt) - set(opus)
        raise SystemExit(f"{base}/{instrument}: turn-identity mismatch Opus vs GPT "
                         f"(opus-only {list(only_o)[:3]}, gpt-only {list(only_g)[:3]})")
    leaks = _leaks_by_turn(opus_dir)
    manifest_hashes = _manifest_dialogue_hashes(base, instrument, gpt_dir)
    # The manifest must cover EXACTLY the scored turns. A manifest that merely overlaps would
    # leave the uncovered turns unbound while the run still looked hash-checked.
    if set(manifest_hashes) != set(gpt):
        only_m = sorted(set(manifest_hashes) - set(gpt))[:3]
        only_g = sorted(set(gpt) - set(manifest_hashes))[:3]
        raise SystemExit(
            f"{base}/{instrument}: the frozen input manifest and the GPT detail describe "
            f"different turn sets ({len(manifest_hashes)} manifest vs {len(gpt)} scored; "
            f"manifest-only {only_m}, scored-only {only_g}). Every scored turn must be bound "
            "to a planned dialogue; refusing to compare a partially-bound set.")
    records, id_mismatch, hash_mismatch, missing_hash, missing_leaks = [], [], [], [], []
    for key in sorted(opus):
        o, g = opus[key], gpt[key]
        run_id, problem_id, turn_index = key
        cond, rep = str(o["condition"]), str(o["replicate_id"])
        # (a) FULL identity equality, not just the (run_id, problem_id, turn_index) join key
        if (str(g.get("condition")) != cond) or (str(g.get("replicate_id")) != rep):
            id_mismatch.append((key, (cond, rep),
                                (str(g.get("condition")), str(g.get("replicate_id")))))
        # (b) dialogue-hash equality against the frozen input manifest. Unconditional: an
        # ABSENT hash on the GPT side used to skip the check silently, so stripping the field
        # after scoring bought the same free pass as deleting the manifest.
        g_hash = g.get("dialogue_sha256")
        want_hash = manifest_hashes.get(key)
        if not g_hash:
            missing_hash.append(key)
        elif g_hash != want_hash:
            hash_mismatch.append((key, want_hash[:12], g_hash[:12]))
        lk = leaks.get((cond, rep, str(problem_id), int(turn_index)))
        if lk is None:
            missing_leaks.append(key)
        records.append({
            "base": base, "run_id": run_id, "condition": cond, "replicate_id": rep,
            "problem_id": problem_id, "turn_index": turn_index, "leaks_i": lk,
            "opus_mean": o["overall_mean"], "gpt_mean": g["overall_mean"],
            "opus_median": _median_int(o.get("overall_values")),
            "gpt_median": _median_int(g.get("overall_values")),
            "opus_var": o.get("overall_var"), "gpt_var": g.get("overall_var"),
            "opus_n_valid": o.get("n_valid"), "gpt_n_valid": g.get("n_valid"),
            "opus_values": o.get("overall_values"), "gpt_values": g.get("overall_values"),
        })
    # Fail loudly: a mislabelled or corrupted GPT detail, or an unjoinable leakage row, must
    # never be silently dropped into the comparison (the amendment promises EXACT identity and
    # dialogue-hash agreement with the Opus surfaces).
    if id_mismatch:
        raise SystemExit(
            f"{base}/{instrument}: {len(id_mismatch)} turn(s) disagree on condition/replicate_id "
            f"between Opus and GPT (e.g. {id_mismatch[:3]}). Refusing to compare mislabelled units.")
    if missing_hash:
        raise SystemExit(
            f"{base}/{instrument}: {len(missing_hash)} scored turn(s) carry no dialogue_sha256 "
            f"(e.g. {missing_hash[:3]}), so they cannot be checked against the frozen input "
            "manifest. A turn with no recorded input hash is unbound, not verified; refusing "
            "to compare.")
    if hash_mismatch:
        raise SystemExit(
            f"{base}/{instrument}: {len(hash_mismatch)} turn(s) have a GPT dialogue_sha256 that "
            f"differs from the frozen input manifest (e.g. {hash_mismatch[:3]}). The GPT scores "
            "were produced from different dialogue text; refusing to compare.")
    if missing_leaks:
        raise SystemExit(
            f"{base}/{instrument}: no leakage row joined for {len(missing_leaks)} turn(s) "
            f"(e.g. {missing_leaks[:3]}). leaks_i drives the judge x leakage interaction; "
            "refusing to silently drop these turns.")
    return records


# -------------------------------------------------------------------- agreement stats
def quadratic_weighted_kappa(a: list[int], b: list[int],
                             lo: int = MIN_RATING, hi: int = MAX_RATING) -> float | None:
    """Quadratic-weighted Cohen's kappa on two integer rating vectors over [lo, hi]."""
    a = [int(round(x)) for x in a]
    b = [int(round(x)) for x in b]
    if not a:
        return None
    n_cat = hi - lo + 1
    O = np.zeros((n_cat, n_cat))
    for x, y in zip(a, b):
        O[x - lo, y - lo] += 1
    W = np.zeros((n_cat, n_cat))
    for i in range(n_cat):
        for j in range(n_cat):
            W[i, j] = (i - j) ** 2 / (n_cat - 1) ** 2
    hist_a = O.sum(axis=1)
    hist_b = O.sum(axis=0)
    E = np.outer(hist_a, hist_b) / O.sum()
    denom = (W * E).sum()
    if denom == 0:
        return 1.0  # no expected disagreement (both constant + identical) -> perfect
    return float(1.0 - (W * O).sum() / denom)


def _clustered_bootstrap(records: list[dict], stat_fn, n_boot: int = 2000,
                         seed: int = 0) -> tuple[float | None, float | None]:
    """Percentile 95% CI resampling whole CONVERSATIONS (run_id) with replacement, so the
    within-conversation dependence among turns is respected."""
    by_run: dict[str, list[dict]] = {}
    for r in records:
        by_run.setdefault(r["run_id"], []).append(r)
    runs = list(by_run)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        chosen = rng.choice(len(runs), size=len(runs), replace=True)
        sample = [rec for idx in chosen for rec in by_run[runs[idx]]]
        v = stat_fn(sample)
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            boots.append(v)
    if not boots:
        return (None, None)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return (float(lo), float(hi))


def _spearman(records: list[dict]) -> float | None:
    x = [r["opus_mean"] for r in records if r["opus_mean"] is not None and r["gpt_mean"] is not None]
    y = [r["gpt_mean"] for r in records if r["opus_mean"] is not None and r["gpt_mean"] is not None]
    if len(x) < 3:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rho, _ = stats.spearmanr(x, y)
    return float(rho) if rho == rho else None


def _qwk(records: list[dict]) -> float | None:
    pairs = [(r["opus_median"], r["gpt_median"]) for r in records
             if r["opus_median"] is not None and r["gpt_median"] is not None]
    if not pairs:
        return None
    return quadratic_weighted_kappa([p[0] for p in pairs], [p[1] for p in pairs])


def _distribution(values) -> dict:
    counts = {str(k): 0 for k in range(MIN_RATING, MAX_RATING + 1)}
    for v in values:
        if v is None:
            continue
        iv = int(round(v))
        if MIN_RATING <= iv <= MAX_RATING:
            counts[str(iv)] += 1
    return counts


def agreement_metrics(records: list[dict], instrument: str, seed: int = 0) -> dict:
    both = [r for r in records if r["opus_mean"] is not None and r["gpt_mean"] is not None]
    n = len(both)
    signed = [r["gpt_mean"] - r["opus_mean"] for r in both]
    med_pairs = [(r["opus_median"], r["gpt_median"]) for r in both
                 if r["opus_median"] is not None and r["gpt_median"] is not None]
    exact = sum(1 for a, b in med_pairs if a == b)
    within1 = sum(1 for a, b in med_pairs if abs(a - b) <= 1)
    rho = _spearman(both)
    qwk = _qwk(both)
    return {
        "instrument": instrument, "n_turns": n,
        "spearman_of_per_turn_means": rho,
        "spearman_clustered_ci95": list(_clustered_bootstrap(both, _spearman, seed=seed)),
        "quadratic_weighted_kappa_on_medians": qwk,
        "kappa_clustered_ci95": list(_clustered_bootstrap(both, _qwk, seed=seed + 1)),
        "mean_signed_diff_gpt_minus_opus": float(np.mean(signed)) if signed else None,
        "mean_absolute_diff": float(np.mean(np.abs(signed))) if signed else None,
        "exact_agreement_on_medians": (exact / len(med_pairs)) if med_pairs else None,
        "within_one_agreement_on_medians": (within1 / len(med_pairs)) if med_pairs else None,
        "opus_median_distribution": _distribution([r["opus_median"] for r in both]),
        "gpt_median_distribution": _distribution([r["gpt_median"] for r in both]),
        "opus_mean_of_per_turn_means": float(np.mean([r["opus_mean"] for r in both])) if both else None,
        "gpt_mean_of_per_turn_means": float(np.mean([r["gpt_mean"] for r in both])) if both else None,
        "valid_rep_rate_opus": _valid_rate(records, "opus_n_valid"),
        "valid_rep_rate_gpt": _valid_rate(records, "gpt_n_valid"),
        "within_turn_rep_variance_opus": _mean_var(records, "opus_var"),
        "within_turn_rep_variance_gpt": _mean_var(records, "gpt_var"),
        "note": "Correlation is not agreement; the mean signed diff reports any systematic "
                "scale shift even when Spearman is high.",
    }


def _valid_rate(records, key) -> float | None:
    xs = [r[key] for r in records if r[key] is not None]
    return (sum(1 for x in xs if x == 3) / len(xs)) if xs else None


def _mean_var(records, key) -> float | None:
    xs = [r[key] for r in records if r[key] is not None]
    return float(np.mean(xs)) if xs else None


# -------------------------------------------------------------------- interaction models
def _fit_crossed(df: pd.DataFrame, outcome: str) -> dict:
    """Fit `outcome ~ leaks_i + C(condition)` with crossed replicate+problem random
    intercepts (the frozen condition-adjusted spec, generalized to an arbitrary continuous
    outcome). Returns the leaks_i (judge x leakage) and C(condition)[T.ped] (judge x policy)
    terms with coef/se/ci/p, convergence, optimizer, and cell counts."""
    try:
        import statsmodels.formula.api as smf
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": f"statsmodels import failed: {e}"}
    d = df[["replicate_id", "problem_id", "condition", "leaks_i", outcome]].dropna().copy()
    d["_grp"] = 1
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fit = smf.mixedlm(f"{outcome} ~ leaks_i + C(condition)", d, groups="_grp",
                              re_formula="0", vc_formula=S.VC_FORMULA).fit(
                                  reml=False, method=I.J2_OPTIMIZERS)
        warns = [str(w.message) for w in caught]

        def term(name):
            ci = fit.conf_int().loc[name]
            return {"coef": float(fit.params[name]), "se": float(fit.bse[name]),
                    "p": float(fit.pvalues[name]),
                    "ci95": [float(ci.iloc[0]), float(ci.iloc[1])]}
        vc = {name: float(v) for name, v in zip(sorted(S.VC_FORMULA), np.atleast_1d(fit.vcomp))}
        vc["residual"] = float(fit.scale)
        return {"available": True, "formula": f"{outcome} ~ leaks_i + C(condition)",
                "model": "crossed replicate+problem RE (variance components over one dummy "
                         "group); ML; " + f"optimizers {I.J2_OPTIMIZERS}",
                "converged": bool(fit.converged),
                "judge_x_leakage_leaks_i": term("leaks_i"),
                "judge_x_policy_condition_ped": term("C(condition)[T.ped]"),
                "variance_components": vc, "warnings": warns,
                "n_obs": int(d.shape[0]),
                "n_replicates": int(d["replicate_id"].nunique()),
                "n_problems": int(d["problem_id"].nunique()),
                "n_leaky": int((d["leaks_i"] == 1).sum()),
                "n_nonleaky": int((d["leaks_i"] == 0).sum())}
    except Exception as e:  # noqa: BLE001
        return {"available": True, "error": f"fit failed: {type(e).__name__}: {e}"}


def interaction_models(records: list[dict], instrument: str) -> dict:
    """Raw and within-judge/base standardized judge-interaction fits on score_difference."""
    df = pd.DataFrame([r for r in records if r["opus_mean"] is not None
                       and r["gpt_mean"] is not None and r["leaks_i"] is not None])
    if df.empty:
        return {"available": False, "error": "no complete rows"}
    df["score_difference"] = df["gpt_mean"] - df["opus_mean"]
    # scale-use sensitivity: standardize each judge's per-turn means within this base, then
    # difference the z-scores (removes a pure additive/scale shift between the two judges).
    def _z(col):
        s = df[col]
        sd = s.std(ddof=0)
        return (s - s.mean()) / sd if sd > 0 else s * 0.0
    df["score_difference_std"] = _z("gpt_mean") - _z("opus_mean")
    return {"instrument": instrument,
            "raw": _fit_crossed(df, "score_difference"),
            "standardized_within_judge_and_base": _fit_crossed(df, "score_difference_std")}


# -------------------------------------------------------------------- difference-of-differences
def difference_of_differences(records: list[dict], instrument: str, seed: int = 0) -> dict:
    """Replicate-level [(Conv-Ped)_GPT - (Conv-Ped)_Opus]: ten values, mean, bootstrap CI,
    paired two-sided signed-rank."""
    by_rep: dict[str, dict] = {}
    for r in records:
        if r["opus_mean"] is None or r["gpt_mean"] is None:
            continue
        d = by_rep.setdefault(r["replicate_id"], {"conv": {"o": [], "g": []},
                                                  "ped": {"o": [], "g": []}})
        if r["condition"] in ("conv", "ped"):
            d[r["condition"]]["o"].append(r["opus_mean"])
            d[r["condition"]]["g"].append(r["gpt_mean"])
    values, rids = [], []
    for rid in sorted(by_rep, key=lambda x: (len(str(x)), str(x))):
        d = by_rep[rid]
        if not (d["conv"]["o"] and d["ped"]["o"]):
            continue
        opus_cmp = np.mean(d["conv"]["o"]) - np.mean(d["ped"]["o"])
        gpt_cmp = np.mean(d["conv"]["g"]) - np.mean(d["ped"]["g"])
        values.append(float(gpt_cmp - opus_cmp))
        rids.append(rid)
    arr = np.asarray(values, float)
    if arr.size and (arr != 0).any():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            W, p = stats.wilcoxon(arr, alternative="two-sided", zero_method="wilcox")
        W, p = float(W), float(p)
    else:
        W, p = float("nan"), 1.0
    return {"instrument": instrument, "n_replicates": len(values),
            "replicate_ids": rids, "dod_values": values,
            "mean_dod": float(np.mean(arr)) if arr.size else None,
            "dod_ci95": list(I.bootstrap_ci(arr)) if arr.size else [None, None],
            "wilcoxon_W": W, "p_two_sided": p,
            "interpretation": "(Conv-Ped)_GPT - (Conv-Ped)_Opus per replicate; a non-zero mean "
                              "means the two judges disagree about the ConvTutor-PedTutor gap."}


# -------------------------------------------------------------------- Holm
def holm(pairs: list[tuple[str, float]], family_name: str = "family",
         family_size: int | None = None) -> list[dict]:
    """Holm-Bonferroni step-down within a DECLARED family. `pairs` = [(label, p), ...].
    Returns each with its raw and adjusted p, in the input order.

    The multiplicity denominator is the DECLARED family size, not the number of tests that
    happened to return a p-value. Previously this dropped missing/nonfinite p-values and used
    only the survivors as the denominator, so a degraded run shrank its own correction: a
    declared three-test family in which two fits failed reported the one available p=.04 as
    Holm-adjusted .04 (m=1) and called it significant, when the declared analysis was simply
    incomplete. A missing p is now a blocking analysis error, never a smaller family.
    """
    m = DECLARED_FAMILY_SIZE if family_size is None else family_size
    if len(pairs) != m:
        raise SystemExit(
            f"{family_name}: declared as {m} tests but {len(pairs)} were supplied "
            f"({[lab for lab, _ in pairs]}). The family size is fixed by the declared analysis; "
            "refusing to publish a comparison over a different number of tests.")
    missing = [lab for lab, p in pairs
               if p is None or not isinstance(p, (int, float)) or isinstance(p, bool)
               or not math.isfinite(float(p))]
    if missing:
        raise SystemExit(
            f"{family_name}: no finite p-value for {missing}. This family declares {m} tests and "
            "every one must produce a finite p from an available, converged fit. Refusing to "
            "publish: dropping the missing tests would shrink the Holm denominator and could "
            "turn a degraded run into a significant reported result.")
    order = sorted(range(len(pairs)), key=lambda i: pairs[i][1])
    adj = {}
    running = 0.0
    for rank, i in enumerate(order):
        lab, p = pairs[i]
        a = min(1.0, (m - rank) * float(p))
        running = max(running, a)  # enforce monotonic non-decreasing adjusted p
        adj[lab] = running
    return [{"label": lab, "p_raw": p, "p_holm": adj.get(lab),
             "family_size": m,
             "significant_holm_0.05": (adj.get(lab) is not None and adj[lab] <= ALPHA)}
            for lab, p in pairs]


# -------------------------------------------------------------------- driver
def _policy_adjusted_help_p(base: str, gpt_dir: str) -> float:
    """The GPT policy-adjusted leak->helpfulness p (from the base's policy_adjusted.json).

    A declared member of Holm family A. A missing file, a missing model, or a non-finite p is a
    BLOCKING analysis error: it means the declared three-test family is incomplete, and silently
    returning None would shrink the multiplicity denominator instead."""
    path = REPO_ROOT / gpt_dir / "policy_adjusted.json"
    if not path.is_file():
        raise SystemExit(
            f"{base}: missing {path}. Holm family A (policy-adjusted leakage slopes) declares "
            f"one test per base; without this file the family is incomplete. Run the "
            "cross-judge audit for this base before comparing.")
    blob = json.loads(path.read_text())
    model = ((blob.get("models") or {}).get("helpfulness"))
    if not isinstance(model, dict):
        raise SystemExit(
            f"{base}: {path} has no models.helpfulness block; the policy-adjusted "
            "leak->helpfulness fit is missing from the declared family.")
    if model.get("error"):
        raise SystemExit(
            f"{base}: {path} models.helpfulness records a fit error ({model['error']}). A "
            "failed fit is a blocking analysis error, not a smaller Holm family.")
    # Convergence is checked EXPLICITLY, exactly as _interaction_p does for families B and C.
    # statsmodels still returns a finite p-value vector from a MixedLM that hit the iteration
    # limit, so a finiteness check alone would let a non-converged fit supply a family-A member
    # -- and a small p from such a fit would be published as Holm-significant. That is the same
    # degraded-run-manufactures-significance failure O4 exists to close.
    # analysis/condition_adjusted_sensitivity.py:fit_policy_adjusted always writes `converged`,
    # so a missing key means a malformed or foreign file and is treated as non-converged.
    if model.get("converged") is not True:
        raise SystemExit(
            f"{base}: {path} reports models.helpfulness.converged={model.get('converged')!r}. "
            "The policy-adjusted leak->helpfulness fit did not converge (statsmodels still "
            "emits finite p-values in that case); refusing to publish a declared three-test "
            "family with a non-converged member.")
    if "p_value" not in model:
        raise SystemExit(
            f"{base}: {path} has no models.helpfulness.p_value; the policy-adjusted "
            "leak->helpfulness fit is missing from the declared family.")
    value = model["p_value"]
    if value is None or not isinstance(value, (int, float)) or isinstance(value, bool) \
            or not math.isfinite(float(value)):
        raise SystemExit(
            f"{base}: {path} reports models.helpfulness.p_value={value!r} (not a finite "
            "probability). The policy-adjusted fit failed; refusing to publish a comparison "
            "with an incomplete Holm family.")
    return float(value)


def _interaction_p(base: str, per_base: dict, term: str, family_name: str) -> float:
    """One declared member of Holm family B / C: a judge-interaction term's p-value.

    An unavailable model, a fit error, a non-converged fit, or a non-finite p BLOCKS the
    comparison rather than quietly reducing the family size."""
    inter = per_base[base]["instruments"]["helpfulness"]["interaction"]
    raw = inter.get("raw") or {}
    if not raw.get("available"):
        raise SystemExit(
            f"{base}: {family_name} requires the judge-interaction model, which is unavailable "
            f"({raw.get('error')}). Refusing to publish an incomplete declared family.")
    if raw.get("error"):
        raise SystemExit(
            f"{base}: {family_name} judge-interaction fit failed ({raw['error']}). A failed fit "
            "is a blocking analysis error, not a smaller Holm family.")
    if not raw.get("converged"):
        raise SystemExit(
            f"{base}: {family_name} judge-interaction fit did not converge. Refusing to report "
            "a declared three-test family with a non-converged member.")
    value = (raw.get(term) or {}).get("p")
    if value is None or not isinstance(value, (int, float)) or isinstance(value, bool) \
            or not math.isfinite(float(value)):
        raise SystemExit(
            f"{base}: {family_name} term {term!r} has p={value!r} (not a finite probability). "
            "Refusing to publish an incomplete declared family.")
    return float(value)


COMPARISON_FILE = "comparison.json"
STAGING_PREFIX = "tmp.staging."


def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _consumed_input_paths(base: str, opus_dir: str, gpt_dir: str) -> dict:
    """Every file the comparison actually READS for one base, labelled by side.

    The bindings used to cover only files under `gpt_dir`. But the comparison also reads both
    OPUS detail files and the Opus `per_turn.csv` (leakage), and those are the primary-judge
    surfaces the whole analysis is defined against -- a report bound to only half its inputs
    cannot show it still corresponds to the data beside it."""
    o, g = REPO_ROOT / opus_dir, REPO_ROOT / gpt_dir
    paths = {"opus/per_turn.csv": o / "per_turn.csv"}
    for inst in INSTRUMENTS:
        paths[f"opus/{inst}_detail.json"] = o / f"{inst}_detail.json"
        paths[f"gpt/{inst}_detail.json"] = g / f"{inst}_detail.json"
    paths["gpt/policy_adjusted.json"] = g / "policy_adjusted.json"
    paths[f"gpt/{RUN_STATE_FILE}"] = g / RUN_STATE_FILE
    # Not optional. `load_aligned` refuses to publish without it, so a published report always
    # read it -- and an input the report depends on but does not bind can be swapped afterwards
    # without the promotion record or the artifact verifier noticing.
    paths["gpt/input_manifest.jsonl"] = g / "input_manifest.jsonl"
    return paths


# The labels every published comparison must bind, so a reader can tell a complete binding from
# a partial one.
REQUIRED_INPUT_LABELS = (
    "opus/per_turn.csv",
    "opus/helpfulness_detail.json", "opus/pedagogy_detail.json",
    "gpt/helpfulness_detail.json", "gpt/pedagogy_detail.json",
    "gpt/policy_adjusted.json", f"gpt/{RUN_STATE_FILE}",
    "gpt/input_manifest.jsonl",
)


def _input_bindings(pairs) -> dict:
    """Hash every input the published comparison is computed from, so a later reader can tell
    whether the report still corresponds to the data sitting beside it."""
    bindings = {}
    for base, opus_dir, gpt_dir in pairs:
        entry = {"gpt_dir": gpt_dir, "opus_dir": opus_dir, "files": {}}
        for label, path in _consumed_input_paths(base, opus_dir, gpt_dir).items():
            if path.is_file():
                entry["files"][label] = _sha256_file(path)
        state_path = REPO_ROOT / gpt_dir / RUN_STATE_FILE
        if state_path.is_file():
            entry["cache_stamps"] = (json.loads(state_path.read_text()).get("cache_stamps") or {})
        bindings[base] = entry
    return bindings


def _assert_inputs_unchanged(before: dict, after: dict) -> None:
    """Refuse to publish if anything the analysis read changed while it ran.

    The bindings used to be computed only AFTER the report was built, so a concurrent base
    refresh could bind the NEW inputs to a report computed from the OLD ones -- and artifact
    verification, which checks exactly those recorded hashes, would accept it."""
    drift = []
    for base in sorted(set(before) | set(after)):
        b = (before.get(base) or {}).get("files") or {}
        a = (after.get(base) or {}).get("files") or {}
        for label in sorted(set(b) | set(a)):
            if b.get(label) != a.get(label):
                drift.append(f"{base}:{label}")
    if drift:
        raise SystemExit(
            "INPUTS CHANGED WHILE THE COMPARISON WAS RUNNING: "
            f"{drift[:8]}{' ...' if len(drift) > 8 else ''}. The report would describe data that "
            "no longer exists on disk; refusing to publish it. Re-run the comparison once the "
            "base outputs have settled.")


def _mark_comparison_state(out_dir: Path, state: str, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / RUN_STATE_FILE).write_text(json.dumps(
        {"state": state, **payload}, indent=2, default=str))


def compare(pairs, out_dir: Path, seed: int = 0) -> dict:
    _enforce_namespace(out_dir)
    # Publication is transactional, for the same reason per-base scoring is. `compare()` can now
    # fail partway on purpose -- a missing policy_adjusted.json or a non-converged fit is a
    # blocking error -- and previously that left the PREVIOUS comparison.json in place, with
    # nothing tying it to the base outputs beside it. A stale report next to refreshed bases is
    # exactly the O2 failure one level up: the manifest builder would hash it and the artifact
    # verifier had no comparison-level freshness check.
    _mark_comparison_state(out_dir, "comparing", {
        "complete": False,
        "note": "A comparison is being recomputed. Any comparison.json present is from an "
                "EARLIER run and must not be reported or packaged.",
        "bases": [p[0] for p in pairs]})
    # Snapshot every consumed input BEFORE the analysis reads it, so promotion can prove
    # nothing shifted underneath the report while it was being computed.
    inputs_before = _input_bindings(pairs)
    try:
        report = _compare_inner(pairs, out_dir, seed=seed, inputs_before=inputs_before)
    except BaseException:
        # Never leave a superseded report publishable behind a failed recomputation.
        stale = out_dir / COMPARISON_FILE
        if stale.is_file():
            stale.unlink()
        for d in sorted(out_dir.glob(f"{STAGING_PREFIX}*")):
            if d.is_dir():
                __import__("shutil").rmtree(d, ignore_errors=True)
        _mark_comparison_state(out_dir, "failed", {
            "complete": False,
            "note": "The comparison could not be produced (see the error). The superseded "
                    "comparison.json was removed so it cannot be reported or packaged.",
            "bases": [p[0] for p in pairs]})
        raise
    return report


def _compare_inner(pairs, out_dir: Path, seed: int = 0, inputs_before: dict | None = None) -> dict:
    per_base = {}
    # per-base agreement / interaction / DoD, per instrument
    all_records = {inst: [] for inst in INSTRUMENTS}
    for base, opus_dir, gpt_dir in pairs:
        base_block = {"opus_dir": opus_dir, "gpt_dir": gpt_dir,
                      "same_family_robustness_judge": base == SAME_FAMILY_BASE,
                      # kept for back-compat: "same_family" == the ROBUSTNESS-judge overlap
                      "same_family": base == SAME_FAMILY_BASE,
                      "same_family_note": ("GPT-5.6 Sol (robustness judge) judging the GPT-5.5 "
                                           "tutor base -- same model family; interpret with "
                                           "caution")
                                          if base == SAME_FAMILY_BASE else None,
                      "same_family_primary_judge": base == PRIMARY_JUDGE_FAMILY_BASE,
                      "same_family_primary_judge_note": ("Claude Opus 4.8 (primary judge) judged "
                                           "the Claude Sonnet 4.6 tutor base -- same model "
                                           "family; a property of the original study, disclosed "
                                           "for symmetry")
                                          if base == PRIMARY_JUDGE_FAMILY_BASE else None,
                      "instruments": {}}
        for inst in INSTRUMENTS:
            recs = load_aligned(base, opus_dir, gpt_dir, inst)
            all_records[inst].extend(recs)
            base_block["instruments"][inst] = {
                "agreement": agreement_metrics(recs, inst, seed=seed),
                "interaction": interaction_models(recs, inst),
                "difference_of_differences": difference_of_differences(recs, inst, seed=seed),
                "policy_adjusted_leak_to_helpfulness_p":
                    _policy_adjusted_help_p(base, gpt_dir) if inst == "helpfulness" else None,
            }
        per_base[base] = base_block

    # overall (pooled across bases -- descriptive; NOT a causal cross-family claim)
    overall = {inst: {"agreement": agreement_metrics(all_records[inst], inst, seed=seed)}
               for inst in INSTRUMENTS}

    # same-family sensitivity: Sonnet + Gemini only (drop the GPT-judge x GPT-tutor arm)
    non_family = [b for b in pairs if b[0] != SAME_FAMILY_BASE]
    nf_records = {inst: [] for inst in INSTRUMENTS}
    for base, opus_dir, gpt_dir in non_family:
        for inst in INSTRUMENTS:
            nf_records[inst].extend(load_aligned(base, opus_dir, gpt_dir, inst))
    sensitivity = {inst: {"agreement": agreement_metrics(nf_records[inst], inst, seed=seed)}
                   for inst in INSTRUMENTS}

    # Holm within three declared families (helpfulness instrument; the P2/J2 dissociation legs)
    families = _holm_families(pairs, per_base)

    report = {
        "analysis": "prospectively specified post hoc cross-judge robustness analysis over "
                    "frozen transcripts",
        "epistemic_status": "post hoc judge robustness",
        "primary_judge": "Claude Opus 4.8", "robustness_judge": "GPT-5.6 Sol",
        "wording_guardrails": {
            "supported": ["replicated across Claude Opus 4.8 and GPT-5.6 Sol",
                          "directionally consistent across two specified judges",
                          "judge-contingent"],
            "forbidden": ["generalizable across LLM judges", "judge-independent",
                          "universally helpful", "comprehensive judge validation",
                          "any human-preference or human-validity claim"],
            "consensus_averaging": "NOT performed; both instruments are reported separately",
            "equivalence": "a nonsignificant interaction is NOT evidence of judge invariance; "
                           "no equivalence test is run without a pre-approved frozen bound",
        },
        "same_family_flag": {
            "robustness_judge": {
                "base": SAME_FAMILY_BASE,
                "reason": "GPT-5.6 Sol (robustness judge) and the GPT-5.5 tutor share a model "
                          "family; this is the arm the Sonnet+Gemini-only sensitivity removes"},
            "primary_judge": {
                "base": PRIMARY_JUDGE_FAMILY_BASE,
                "reason": "Claude Opus 4.8 (primary judge) and the Claude Sonnet 4.6 tutor share "
                          "a model family; a property of the original confirmatory study, "
                          "disclosed for symmetry so the same-family caveat is not read as "
                          "applying only to the GPT arm"},
            "note": "Both judges have a same-family arm. The Sonnet+Gemini-only sensitivity "
                    "below removes the GPT-judge family confound; the Sonnet base still carries "
                    "the primary-judge (Claude) family overlap, which no reweighting removes.",
        },
        "per_base": per_base,
        "overall_pooled_descriptive": overall,
        "same_family_sensitivity_sonnet_gemini_only": sensitivity,
        "holm_families": families,
    }
    # Build in staging, promote atomically, write the state marker LAST -- so a reader that
    # requires state == "complete" never observes a half-written or superseded report.
    # Re-hash every consumed input and refuse to publish if any of them moved while the
    # analysis ran; the promoted bindings are this verified-stable snapshot.
    inputs_after = _input_bindings(pairs)
    if inputs_before is not None:
        _assert_inputs_unchanged(inputs_before, inputs_after)

    import shutil
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = out_dir / f"{STAGING_PREFIX}{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        (staging / COMPARISON_FILE).write_text(json.dumps(report, indent=2, default=str))
        os.replace(staging / COMPARISON_FILE, out_dir / COMPARISON_FILE)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    _mark_comparison_state(out_dir, "complete", {
        "complete": True,
        "bases": [p[0] for p in pairs],
        "declared_family_size": DECLARED_FAMILY_SIZE,
        "comparison_sha256": _sha256_file(out_dir / COMPARISON_FILE),
        "inputs": inputs_after,
        "note": "Complete promoted comparison. Consumers must require state == 'complete' and "
                "input hashes matching the base outputs packaged alongside it."})
    return report


def _holm_families(pairs, per_base) -> dict:
    """Three declared families, each of the three bases; Holm within each.

    Each family is fixed at DECLARED_FAMILY_SIZE tests. Every member must yield a finite p from
    an available, converged fit -- a missing policy_adjusted.json or a failed fit raises here
    rather than producing a smaller, more permissive correction."""
    if len(pairs) != DECLARED_FAMILY_SIZE:
        raise SystemExit(
            f"the cross-judge comparison declares {DECLARED_FAMILY_SIZE} tutor bases per Holm "
            f"family but {len(pairs)} pair(s) were supplied ({[p[0] for p in pairs]}). Compare "
            "all three bases, or do not publish Holm-adjusted results.")
    fam_a = "family_A_policy_adjusted_leakage_slopes_helpfulness"
    fam_b = "family_B_judge_x_leakage_interactions_helpfulness"
    fam_c = "family_C_judge_x_condition_interactions_helpfulness"
    slopes, leak_ix, cond_ix = [], [], []
    for base, _o, _gpt_dir in pairs:
        pa = per_base[base]["instruments"]["helpfulness"]["policy_adjusted_leak_to_helpfulness_p"]
        if pa is None or not math.isfinite(float(pa)):
            raise SystemExit(
                f"{base}: {fam_a} has no finite policy-adjusted leak->helpfulness p; refusing to "
                "publish an incomplete declared family.")
        slopes.append((base, float(pa)))
        leak_ix.append((base, _interaction_p(base, per_base, "judge_x_leakage_leaks_i", fam_b)))
        cond_ix.append((base, _interaction_p(base, per_base,
                                             "judge_x_policy_condition_ped", fam_c)))
    return {
        fam_a: holm(slopes, family_name=fam_a),
        fam_b: holm(leak_ix, family_name=fam_b),
        fam_c: holm(cond_ix, family_name=fam_c),
        "declared_family_size": DECLARED_FAMILY_SIZE,
        "note": "Three separately declared families of three tests each; raw and Holm-adjusted "
                "p reported. The multiplicity denominator is the DECLARED family size, so a "
                "missing or failed test blocks the comparison instead of shrinking the "
                "correction. Do NOT infer equivalence from a nonsignificant interaction.",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pair", action="append", default=None,
                    help="base:opus_dir:gpt_dir (repeatable; overrides the defaults)")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    if args.pair:
        pairs = [tuple(p.split(":", 2)) for p in args.pair]
    else:
        pairs = DEFAULT_PAIRS
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    _enforce_namespace(out_dir)   # refuse a canonical/frozen results dir before any write
    report = compare(pairs, out_dir, seed=args.seed)
    print(f"wrote {out_dir}/comparison.json")
    for base, block in report["per_base"].items():
        fam = " [SAME-FAMILY]" if block["same_family"] else ""
        for inst in INSTRUMENTS:
            a = block["instruments"][inst]["agreement"]
            print(f"  {base:7s} {inst:11s}{fam}: n={a['n_turns']} "
                  f"spearman={_r(a['spearman_of_per_turn_means'])} "
                  f"qwk={_r(a['quadratic_weighted_kappa_on_medians'])} "
                  f"signed_diff(GPT-Opus)={_r(a['mean_signed_diff_gpt_minus_opus'])} "
                  f"exact={_r(a['exact_agreement_on_medians'])}")


def _r(x):
    return "n/a" if x is None else f"{x:.3f}"


if __name__ == "__main__":
    main()
