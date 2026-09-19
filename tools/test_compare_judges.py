"""Offline tests for the cross-judge comparison (analysis/compare_judges.py).

Run: python tools/test_compare_judges.py

Fixtures are tiny synthetic Opus/GPT detail files + per_turn.csv on disk; the statistics are
checked against hand values and against invariances (rep-order, same-family exclusion).
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import analysis.compare_judges as C  # noqa: E402

_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}")


# ------------------------------------------------------------------ fixture builder
def _detail(turns, mean_key):
    by_run = {}
    for t in turns:
        by_run.setdefault(t["run_id"], []).append(t)
    runs = []
    for run_id, ts in by_run.items():
        means = [t["overall_mean"] for t in ts]
        runs.append({"run_id": run_id, "condition": ts[0]["condition"],
                     "replicate_id": ts[0]["replicate_id"],
                     mean_key: sum(means) / len(means), "n_turns": len(ts), "turns": ts})
    return {"runs": runs}


def _dialogue_hash(run_id, pid, ti) -> str:
    """Stand-in for the frozen per-turn dialogue digest. Deterministic from the turn identity so
    the fixture manifest and the fixture GPT detail agree exactly, the way a real base does."""
    return hashlib.sha256(f"{run_id}|{pid}|{ti}".encode()).hexdigest()


def _turn(run_id, cond, rep, pid, ti, values):
    import statistics
    return {"run_id": run_id, "condition": cond, "replicate_id": str(rep),
            "problem_id": pid, "turn_index": ti, "overall_mean": sum(values) / len(values),
            "overall_var": statistics.variance(values) if len(values) > 1 else 0,
            "overall_values": values, "n_valid": len(values),
            "dialogue_sha256": _dialogue_hash(run_id, pid, ti)}


def write_run_state(gpt_dir: Path, stamps: dict, *, state="complete", complete=True):
    """Mirror the runner's transactional promotion marker (analysis/run_cross_judge_audit.py
    promote_outputs) so fixtures look like a real promoted output set."""
    (gpt_dir / "run_state.json").write_text(json.dumps(
        {"state": state, "complete": complete, "reps": 3, "cache_stamps": stamps,
         "backend": "live"}))


def write_input_manifest(gpt_dir: Path, grid, base: str, overrides: dict | None = None):
    """Mirror the runner's frozen input_manifest.jsonl. `overrides` maps
    (run_id, problem_id, turn_index) -> replacement dialogue_sha256."""
    overrides = overrides or {}
    lines = []
    for cond, rep, pid, ti in grid:
        rid = f"{base}-{cond}-r{rep}"
        key = (rid, pid, ti)
        lines.append(json.dumps({
            "run_id": rid, "condition": cond, "replicate_id": str(rep), "problem_id": pid,
            "turn_index": ti,
            "dialogue_sha256": overrides.get(key, _dialogue_hash(rid, pid, ti))}))
    (gpt_dir / "input_manifest.jsonl").write_text("\n".join(lines) + "\n")


def build_base(root: Path, base: str, opus_fn, gpt_fn, leak_fn):
    """Write opus + gpt {helpfulness,pedagogy}_detail.json and per_turn.csv for a base.
    opus_fn/gpt_fn(cond, rep, pid, ti) -> list of 3 int rep values; leak_fn -> bool."""
    opus_dir = root / f"opus_{base}"
    gpt_dir = root / f"gpt_{base}"
    opus_dir.mkdir(parents=True, exist_ok=True)
    gpt_dir.mkdir(parents=True, exist_ok=True)
    grid = [(cond, rep, pid, ti)
            for cond in ("conv", "ped") for rep in range(4)
            for pid in ("p1", "p2", "p3") for ti in (0,)]
    stamps = {}
    for inst, mean_key in (("helpfulness", "helpfulness_mean"), ("pedagogy", "pedagogy_mean")):
        opus_turns, gpt_turns = [], []
        for cond, rep, pid, ti in grid:
            rid = f"{base}-{cond}-r{rep}"
            opus_turns.append(_turn(rid, cond, rep, pid, ti, opus_fn(inst, cond, rep, pid, ti)))
            gpt_turns.append(_turn(rid, cond, rep, pid, ti, gpt_fn(inst, cond, rep, pid, ti)))
        (opus_dir / f"{inst}_detail.json").write_text(json.dumps(_detail(opus_turns, mean_key)))
        # GPT details carry the cache stamp of the run that promoted them (see run_state below)
        stamps[inst] = {"instrument": inst, "backend": "live", "reps": 3,
                        "returned_model": "gpt-5.6-sol", "seed_policy": "unseeded",
                        "plan_freeze": f"stand-in-{base}"}
        (gpt_dir / f"{inst}_detail.json").write_text(
            json.dumps({**_detail(gpt_turns, mean_key), "stamp": stamps[inst]}))
    # The comparator requires a CURRENT COMPLETE promoted set (transactional promotion, O2).
    write_run_state(gpt_dir, stamps)
    # ...and the frozen input manifest binding every scored turn to its planned dialogue text.
    # Fixtures used to omit this entirely, which is precisely how the optional-manifest hole
    # stayed invisible: the whole suite ran against unbound comparisons.
    write_input_manifest(gpt_dir, grid, base)
    # per_turn.csv (leaks only used by the comparison)
    with open(opus_dir / "per_turn.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["condition", "replicate_id", "problem_id",
                                          "turn_index", "leaks"])
        w.writeheader()
        for cond, rep, pid, ti in grid:
            w.writerow({"condition": cond, "replicate_id": rep, "problem_id": pid,
                        "turn_index": ti, "leaks": leak_fn(cond, rep, pid, ti)})
    return str(opus_dir.relative_to(REPO_ROOT)), str(gpt_dir.relative_to(REPO_ROOT))


# ---------------------------------------------------- non-degenerate rating fixtures
#
# Every fixture feeding a SUCCESSFUL compare() must vary within condition. Constant
# ratings make score_difference an exact function of condition (-1 on every conv turn,
# +1 on every ped turn), so C(condition) explains the outcome completely: the interaction
# fit's residual scale collapses to ~2e-32, the standard error on leaks_i comes back nan,
# and compare() correctly refuses to publish a Holm family holding a non-finite p.
#
# Whether that scale lands on exact zero (-> nan -> refusal) or on a denormal (-> a finite
# but meaningless p; this fixture produced 0.157 on one machine) is floating-point luck
# that varies by platform and package build. A constant fixture is therefore a coin flip,
# not a test -- and the coin came up differently on CI than on the author's laptop.
#
# The wobble below is keyed on (replicate + problem) mod 3 rather than on either alone, so
# the crossed replicate/problem variance components cannot absorb it and a genuine residual
# survives (scale ~0.22, se ~0.19). Ratings stay within 1..5 and the ped-minus-conv contrast
# is still exactly +2, so structural assertions are unaffected.


def opus_ratings(inst, cond, rep, pid, ti):
    """Primary-judge ratings: flat by condition. The wobble lives on the GPT side."""
    return [4, 4, 4] if cond == "conv" else [3, 3, 3]


def gpt_ratings(inst, cond, rep, pid, ti):
    """Robustness-judge ratings whose MEDIAN varies within condition. See the note above."""
    wobble = (rep + {"p1": 0, "p2": 1, "p3": 2}[pid]) % 3 == 0
    if cond == "conv":
        return [3, 4, 4] if wobble else [3, 4, 3]   # median 4 or 3
    return [4, 5, 5] if wobble else [4, 4, 5]       # median 5 or 4


# ------------------------------------------------------------------ pure-function tests
def test_quadratic_weighted_kappa():
    print("\n[quadratic-weighted kappa]")
    check("identical ratings -> kappa 1.0",
          abs(C.quadratic_weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) - 1.0) < 1e-9)
    # perfectly reversed on a symmetric set -> strongly negative
    k = C.quadratic_weighted_kappa([1, 2, 4, 5], [5, 4, 2, 1])
    check("reversed ratings -> negative kappa", k < -0.5)
    # a known 2-observation off-by patterns: mild agreement
    k2 = C.quadratic_weighted_kappa([1, 2, 3, 4, 5, 5, 4, 3, 2, 1],
                                    [1, 2, 3, 4, 5, 4, 5, 3, 1, 2])
    check("near-agreement -> high positive kappa", 0.7 < k2 <= 1.0)


def test_holm():
    print("\n[Holm step-down within a family]")
    rows = C.holm([("a", 0.01), ("b", 0.04), ("c", 0.03)])
    adj = {r["label"]: round(r["p_holm"], 4) for r in rows}
    # sorted 0.01(x3=.03), 0.03(x2=.06), 0.04(x1=.04 -> max(.06,.04)=.06)
    check("a: 0.01*3 = 0.03", math.isclose(adj["a"], 0.03, abs_tol=1e-9))
    check("c: 0.03*2 = 0.06", math.isclose(adj["c"], 0.06, abs_tol=1e-9))
    check("b: monotone-enforced to 0.06", math.isclose(adj["b"], 0.06, abs_tol=1e-9))
    check("input order preserved", [r["label"] for r in rows] == ["a", "b", "c"])
    check("adjusted p is compared with <= alpha (Round 1 fix preserved)",
          C.holm([("a", 0.05 / 3), ("b", 0.9), ("c", 0.9)])[0]["significant_holm_0.05"] is True)


def _raises(fn):
    try:
        fn()
        return False
    except SystemExit:
        return True


def test_holm_family_size_is_fixed_at_three():
    """O4: `holm` used to drop missing/nonfinite p-values and use only the survivors as the
    multiplicity denominator, so a degraded run shrank its own correction into significance.
    The declared family is three tests; a missing member blocks instead."""
    print("\n[O4: Holm denominator is the DECLARED family size; missing tests block]")
    check("declared family size constant is 3", C.DECLARED_FAMILY_SIZE == 3)
    # the exact scenario in the review: one available p=.04 with two failed tests must NOT be
    # reported as Holm-adjusted .04 (which m=1 would give, and which is significant at .05)
    check("one available p with two failed tests is refused, not reported at m=1",
          _raises(lambda: C.holm([("a", 0.04), ("b", None), ("c", None)])))
    check("a single nonfinite member blocks the whole family",
          _raises(lambda: C.holm([("a", 0.04), ("b", float("nan")), ("c", 0.5)])))
    check("infinite p blocks", _raises(lambda: C.holm([("a", 0.04), ("b", float("inf")),
                                                       ("c", 0.5)])))
    check("a family supplied with fewer than three tests is refused",
          _raises(lambda: C.holm([("a", 0.01), ("b", 0.02)])))
    check("a family supplied with more than three tests is refused",
          _raises(lambda: C.holm([("a", 0.01), ("b", 0.02), ("c", 0.03), ("d", 0.04)])))
    # the denominator really is 3, and every row reports it
    rows = C.holm([("a", 0.01), ("b", 0.9), ("c", 0.9)])
    check("smallest p is multiplied by the DECLARED m=3",
          math.isclose(rows[0]["p_holm"], 0.03, abs_tol=1e-12))
    check("each row records the family size it was corrected against",
          all(r["family_size"] == 3 for r in rows))


def test_median_and_rep_order_invariance():
    print("\n[median integer + repetition-order invariance (no rep-index pairing)]")
    check("median of 3 ints is the middle", C._median_int([5, 3, 4]) == 4)
    check("median is order-invariant",
          C._median_int([5, 3, 4]) == C._median_int([3, 4, 5]) == C._median_int([4, 5, 3]))


def test_agreement_on_fixture():
    print("\n[agreement metrics on a controlled fixture]")
    # records where GPT = Opus + 1 (constant scale shift): perfect rank corr, signed diff +1
    recs = [{"run_id": "r", "condition": "conv", "replicate_id": "0", "problem_id": "p",
             "turn_index": i, "leaks_i": 0.0,
             "opus_mean": float(m), "gpt_mean": float(m + 1 if m < 5 else 5),
             "opus_median": float(m), "gpt_median": float(min(5, m + 1)),
             "opus_var": 0.0, "gpt_var": 0.0, "opus_n_valid": 3, "gpt_n_valid": 3,
             "opus_values": [m, m, m], "gpt_values": [min(5, m + 1)] * 3}
            for i, m in enumerate([1, 2, 3, 4, 1, 2, 3, 4])]
    a = C.agreement_metrics(recs, "helpfulness")
    check("Spearman ~ 1.0 under a monotone shift", a["spearman_of_per_turn_means"] > 0.99)
    check("mean signed diff (GPT-Opus) = +1", math.isclose(a["mean_signed_diff_gpt_minus_opus"], 1.0))
    check("systematic shift is visible despite high correlation",
          a["mean_signed_diff_gpt_minus_opus"] > 0.5 and a["spearman_of_per_turn_means"] > 0.9)
    check("exact agreement on medians = 0 (all shifted by 1)", a["exact_agreement_on_medians"] == 0.0)
    check("within-one agreement on medians = 1.0", a["within_one_agreement_on_medians"] == 1.0)
    check("valid-rep rate reported for both judges",
          a["valid_rep_rate_opus"] == 1.0 and a["valid_rep_rate_gpt"] == 1.0)


def _rev(values):
    return list(reversed(values))


def test_load_aligned_and_rep_order_invariance():
    print("\n[load_aligned key equality + rep-order invariance end to end]")
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        root = Path(td)

        def opus_fn(inst, cond, rep, pid, ti):
            base = 4 if cond == "conv" else 3
            return [base, base, min(5, base + (rep % 2))]

        def gpt_fn(inst, cond, rep, pid, ti):
            base = 3 if cond == "conv" else 4
            return [base, min(5, base + 1), base]

        odir, gdir = build_base(root, "sonnet", opus_fn, gpt_fn, lambda c, r, p, t: r % 2 == 0)
        recs = C.load_aligned("sonnet", odir, gdir, "helpfulness")
        check("aligned 24 turns", len(recs) == 24)
        check("leaks joined from Opus per_turn", all(r["leaks_i"] in (0.0, 1.0) for r in recs))
        m1 = C.agreement_metrics(recs, "helpfulness")

        # rewrite GPT detail with each turn's reps REVERSED; medians/means unchanged.
        gpt_path = REPO_ROOT / gdir / "helpfulness_detail.json"
        blob = json.loads(gpt_path.read_text())
        for run in blob["runs"]:
            for t in run["turns"]:
                t["overall_values"] = _rev(t["overall_values"])
        gpt_path.write_text(json.dumps(blob))
        recs2 = C.load_aligned("sonnet", odir, gdir, "helpfulness")
        m2 = C.agreement_metrics(recs2, "helpfulness")
        check("rep-order permutation leaves QWK unchanged (no rep-index pairing)",
              m1["quadratic_weighted_kappa_on_medians"] == m2["quadratic_weighted_kappa_on_medians"])
        check("rep-order permutation leaves Spearman unchanged",
              m1["spearman_of_per_turn_means"] == m2["spearman_of_per_turn_means"])


def test_interaction_and_dod_and_formula():
    print("\n[interaction formula + difference-of-differences]")
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        root = Path(td)

        # GPT rates leaky turns systematically higher than Opus -> nonzero judge x leakage
        def opus_fn(inst, cond, rep, pid, ti):
            return [4, 4, 4] if cond == "conv" else [3, 3, 3]

        def gpt_fn(inst, cond, rep, pid, ti):
            leak = (rep % 2 == 0)
            bump = 1 if leak else 0
            base = 3 if cond == "conv" else 4
            # The -1 wobble is what makes this fit well posed. Without it,
            # score_difference is an exact function of (condition, leaks_i) -- the two
            # regressors -- so the residual collapses to ~2e-32 and se/p come back nan.
            # The checks below only assert that coef/se/p/ci are PRESENT, so a nan fit
            # satisfied them silently: this test looked green while measuring nothing.
            # See the note above build_base. The +1 leakage bump the fixture exists to
            # create is preserved; the wobble only breaks the exact determinism.
            wob = -1 if (rep + {"p1": 0, "p2": 1, "p3": 2}[pid]) % 3 == 0 else 0
            m = max(1, base + bump + wob)
            return [m, m, m]

        odir, gdir = build_base(root, "sonnet", opus_fn, gpt_fn, lambda c, r, p, t: r % 2 == 0)
        recs = C.load_aligned("sonnet", odir, gdir, "helpfulness")
        inter = C.interaction_models(recs, "helpfulness")
        check("interaction formula is score_difference ~ leaks_i + C(condition)",
              inter["raw"].get("formula") == "score_difference ~ leaks_i + C(condition)")
        check("raw interaction fit is available and converged",
              inter["raw"].get("available") and inter["raw"].get("converged"))
        check("judge x leakage term present with coef/se/p/ci",
              set(("coef", "se", "p", "ci95")) <= set(inter["raw"]["judge_x_leakage_leaks_i"]))
        check("judge x policy term present",
              "coef" in inter["raw"]["judge_x_policy_condition_ped"])
        check("standardized (scale-use) refit present",
              inter["standardized_within_judge_and_base"].get("available"))
        dod = C.difference_of_differences(recs, "helpfulness")
        check("DoD has 4 replicate-level values", dod["n_replicates"] == 4)
        check("DoD reports mean, CI, and signed-rank p",
              "mean_dod" in dod and "dod_ci95" in dod and "p_two_sided" in dod)


def test_compare_end_to_end_and_same_family():
    print("\n[compare(): guardrails, same-family flag + Sonnet+Gemini-only sensitivity]")
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        root = Path(td)

        of, gf = opus_ratings, gpt_ratings

        pairs = []
        for base in ("sonnet", "gpt", "gemini"):
            odir, gdir = build_base(root, base, of, gf, lambda c, r, p, t: r % 2 == 0)
            # policy_adjusted.json (compare reads the helpfulness p from it)
            (REPO_ROOT / gdir).mkdir(parents=True, exist_ok=True)
            (REPO_ROOT / gdir / "policy_adjusted.json").write_text(json.dumps(
                {"models": {"helpfulness": {"p_value": 0.2 if base != "gpt" else 0.9,
                                           "converged": True}}}))
            pairs.append((base, odir, gdir))
        # the comparison OUT must live in the allowed namespace (guard enforced);
        # the fixture opus/gpt dirs may live anywhere (they are only read).
        import shutil
        out = Path(REPO_ROOT) / "results/judge_robustness/gpt-5.6-sol/_test_cmp/comparison"
        if out.parent.exists():
            shutil.rmtree(out.parent)
        report = C.compare(pairs, out, seed=0)
        check("comparison.json written", (out / "comparison.json").is_file())
        check("epistemic status is post hoc judge robustness",
              report["epistemic_status"] == "post hoc judge robustness")
        check("consensus averaging explicitly NOT performed",
              "NOT performed" in report["wording_guardrails"]["consensus_averaging"])
        check("forbidden wording lists 'judge-independent'",
              "judge-independent" in report["wording_guardrails"]["forbidden"])
        check("gpt base flagged same-family (robustness judge)",
              report["per_base"]["gpt"]["same_family"] is True
              and report["per_base"]["gpt"]["same_family_robustness_judge"] is True)
        check("sonnet base not flagged robustness-judge same-family",
              report["per_base"]["sonnet"]["same_family"] is False)
        check("sonnet base flagged PRIMARY-judge same-family (Opus/Claude x Sonnet/Claude)",
              report["per_base"]["sonnet"]["same_family_primary_judge"] is True)
        check("same_family_flag discloses BOTH judges' overlaps symmetrically",
              "robustness_judge" in report["same_family_flag"]
              and "primary_judge" in report["same_family_flag"])
        # same-family sensitivity excludes the gpt base (24 sonnet + 24 gemini = 48 turns)
        n = report["same_family_sensitivity_sonnet_gemini_only"]["helpfulness"]["agreement"]["n_turns"]
        check("sensitivity excludes the same-family GPT base (48 = sonnet+gemini)", n == 48)
        overall_n = report["overall_pooled_descriptive"]["helpfulness"]["agreement"]["n_turns"]
        check("overall pooled includes all three bases (72)", overall_n == 72)
        fams = report["holm_families"]
        check("three declared Holm families present",
              set(k for k in fams if k not in ("note", "declared_family_size")) == {
                  "family_A_policy_adjusted_leakage_slopes_helpfulness",
                  "family_B_judge_x_leakage_interactions_helpfulness",
                  "family_C_judge_x_condition_interactions_helpfulness"})
        check("Holm family A reports raw and adjusted p per base",
              all("p_raw" in r and "p_holm" in r
                  for r in fams["family_A_policy_adjusted_leakage_slopes_helpfulness"]))
        check("every family is corrected against the declared size of three",
              fams["declared_family_size"] == 3
              and all(r["family_size"] == 3
                      for fam in ("family_A_policy_adjusted_leakage_slopes_helpfulness",
                                  "family_B_judge_x_leakage_interactions_helpfulness",
                                  "family_C_judge_x_condition_interactions_helpfulness")
                      for r in fams[fam]))
        shutil.rmtree(out.parent)   # remove the namespace scratch (outside the tempdir)


def test_guards_namespace_and_provenance():
    print("\n[guards: --out namespace refusal + mock/synthetic provenance gate]")
    # namespace: only results/judge_robustness/ is writable
    for canonical in ("results/confirmatory", "results/ablation", "results/anything"):
        try:
            C._enforce_namespace(REPO_ROOT / canonical)
            refused = False
        except SystemExit:
            refused = True
        check(f"compare refuses --out under {canonical}", refused)
    try:
        C._enforce_namespace(REPO_ROOT / "results/judge_robustness/gpt-5.6-sol/comparison")
        allowed = True
    except SystemExit:
        allowed = False
    check("compare allows results/judge_robustness/...", allowed)

    # provenance gate: a MOCK/synthetic GPT detail must be refused
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        root = Path(td)
        of = lambda i, c, r, p, t: [4, 4, 4]
        gf = lambda i, c, r, p, t: [3, 4, 3]
        odir, gdir = build_base(root, "sonnet", of, gf, lambda c, r, p, t: r % 2 == 0)
        # taint the GPT helpfulness detail with a mock/do-not-report stamp
        gpath = REPO_ROOT / gdir / "helpfulness_detail.json"
        blob = json.loads(gpath.read_text())
        blob["backend"] = "mock"
        blob["score_source"] = "MOCK synthetic -- DO NOT REPORT"
        gpath.write_text(json.dumps(blob))
        try:
            C.load_aligned("sonnet", odir, gdir, "helpfulness")
            refused = False
        except SystemExit:
            refused = True
        check("load_aligned refuses a MOCK/do-not-report GPT detail", refused)


_FIXTURE_GRID = [(cond, rep, pid, ti)
                 for cond in ("conv", "ped") for rep in range(4)
                 for pid in ("p1", "p2", "p3") for ti in (0,)]


def _rewrite_manifest(gpt_dir: Path, base: str, overrides: dict):
    write_input_manifest(gpt_dir, _FIXTURE_GRID, base, overrides)


def test_dialogue_manifest_binding_is_mandatory():
    """Require a nonempty, complete dialogue manifest when binding comparison inputs.

    Missing manifests must not turn dialogue checks into optional comparisons."""
    print("\n[R9-F3: the frozen dialogue manifest is required, covering, and non-empty]")
    of = lambda i, c, r, p, t: [4, 4, 4]
    gf = lambda i, c, r, p, t: [3, 4, 3]
    fresh = lambda root: build_base(root, "sonnet", of, gf, lambda c, r, p, t: r % 2 == 0)

    # (a) a DELETED manifest must abort, not degrade to "no hash check possible"
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        odir, gdir = fresh(Path(td))
        (REPO_ROOT / gdir / "input_manifest.jsonl").unlink()
        check("a missing input manifest aborts the comparison",
              _raises(lambda: C.load_aligned("sonnet", odir, gdir, "helpfulness")))

    # (b) stripping dialogue_sha256 from the SCORES must abort. This is the other half of the
    # old `if g_hash and want_hash` guard: with the manifest intact, an absent hash on the GPT
    # side bought exactly the same silent free pass as deleting the manifest.
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        odir, gdir = fresh(Path(td))
        gpath = REPO_ROOT / gdir / "helpfulness_detail.json"
        blob = json.loads(gpath.read_text())
        for run in blob["runs"]:
            for t in run["turns"]:
                t.pop("dialogue_sha256", None)
        gpath.write_text(json.dumps(blob))
        check("scored turns with no dialogue_sha256 abort (unbound != verified)",
              _raises(lambda: C.load_aligned("sonnet", odir, gdir, "helpfulness")))

    # (c) a manifest covering only SOME scored turns must abort. Partial coverage would leave
    # the uncovered turns unbound while the run still looked hash-checked.
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        odir, gdir = fresh(Path(td))
        man = REPO_ROOT / gdir / "input_manifest.jsonl"
        man.write_text("\n".join(man.read_text().splitlines()[:5]) + "\n")
        check("a manifest that does not cover every scored turn aborts",
              _raises(lambda: C.load_aligned("sonnet", odir, gdir, "helpfulness")))

    # (d) an empty expected hash binds nothing and must abort rather than compare equal
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        odir, gdir = fresh(Path(td))
        first = _FIXTURE_GRID[0]
        rid = f"sonnet-{first[0]}-r{first[1]}"
        _rewrite_manifest(REPO_ROOT / gdir, "sonnet", {(rid, first[2], first[3]): ""})
        check("an empty dialogue_sha256 in the manifest aborts",
              _raises(lambda: C.load_aligned("sonnet", odir, gdir, "helpfulness")))

    # (e) the binding surfaces must REQUIRE the manifest, not merely record it when present.
    # Without this the report could publish bound to 7 of its 8 inputs and the manifest could
    # be swapped afterwards with neither the promotion record nor the verifier noticing.
    check("the comparison requires the manifest among its bound inputs",
          "gpt/input_manifest.jsonl" in C.REQUIRED_INPUT_LABELS)
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        odir, gdir = fresh(Path(td))
        labels = C._consumed_input_paths("sonnet", odir, gdir)
        check("the manifest is bound unconditionally, not only when it happens to exist",
              "gpt/input_manifest.jsonl" in labels)
    V = _load_verifier()
    check("artifact verification requires the manifest binding too",
          "gpt/input_manifest.jsonl" in V.REQUIRED_COMPARISON_INPUTS)


def test_alignment_guards():
    print("\n[alignment guards: identity, dialogue hash, leakage join]")
    of = lambda i, c, r, p, t: [4, 4, 4]
    gf = lambda i, c, r, p, t: [3, 4, 3]

    def fresh(root):
        return build_base(root, "sonnet", of, gf, lambda c, r, p, t: r % 2 == 0)

    # (a) condition / replicate_id disagreement between Opus and GPT must abort
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        odir, gdir = fresh(Path(td))
        gpath = REPO_ROOT / gdir / "helpfulness_detail.json"
        blob = json.loads(gpath.read_text())
        blob["runs"][0]["turns"][0]["condition"] = "ped"      # mislabel one GPT turn
        gpath.write_text(json.dumps(blob))
        try:
            C.load_aligned("sonnet", odir, gdir, "helpfulness"); ok = False
        except SystemExit:
            ok = True
        check("condition/replicate mismatch between judges aborts", ok)

    # (b) a GPT dialogue_sha256 disagreeing with the frozen input manifest must abort
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        odir, gdir = fresh(Path(td))
        gpath = REPO_ROOT / gdir / "helpfulness_detail.json"
        blob = json.loads(gpath.read_text())
        t0 = blob["runs"][0]["turns"][0]
        t0["dialogue_sha256"] = "a" * 64
        gpath.write_text(json.dumps(blob))
        # The manifest still covers EXACTLY the scored turns (so this exercises the hash
        # comparison itself, not the coverage check) but claims a different hash for that unit.
        _rewrite_manifest(REPO_ROOT / gdir, "sonnet",
                          {(t0["run_id"], t0["problem_id"], t0["turn_index"]): "b" * 64})
        try:
            C.load_aligned("sonnet", odir, gdir, "helpfulness"); ok = False
        except SystemExit:
            ok = True
        check("GPT dialogue hash disagreeing with the input manifest aborts", ok)

    # (c) an unjoinable leakage row must abort rather than silently become None
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        odir, gdir = fresh(Path(td))
        pt = REPO_ROOT / odir / "per_turn.csv"
        rows = pt.read_text().splitlines()
        pt.write_text("\n".join([rows[0]] + rows[2:]) + "\n")   # drop one leakage row
        try:
            C.load_aligned("sonnet", odir, gdir, "helpfulness"); ok = False
        except SystemExit:
            ok = True
        check("missing leakage join aborts (never silently dropped)", ok)


def test_degraded_analysis_blocks_the_comparison():
    """O4 end-to-end: the comparator used to tolerate a missing policy_adjusted.json and a
    failed/non-converged fit and still write a report, silently shrinking the Holm family."""
    print("\n[O4: a missing or failed declared test blocks the comparison]")
    import shutil
    of, gf = opus_ratings, gpt_ratings   # NOT constant -- see the note above build_base
    out = REPO_ROOT / "results/judge_robustness/gpt-5.6-sol/_test_degraded/comparison"

    def run(mutate=None, drop_policy_for=None):
        if out.parent.exists():
            shutil.rmtree(out.parent)
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
            pairs = []
            for base in ("sonnet", "gpt", "gemini"):
                odir, gdir = build_base(Path(td), base, of, gf, lambda c, r, p, t: r % 2 == 0)
                if base != drop_policy_for:
                    (REPO_ROOT / gdir / "policy_adjusted.json").write_text(json.dumps(
                        {"models": {"helpfulness": {"p_value": 0.2,
                                                   "converged": True}}}))
                if mutate:
                    mutate(base, REPO_ROOT / gdir)
                pairs.append((base, odir, gdir))
            try:
                C.compare(pairs, out, seed=0)
                return True
            except SystemExit:
                return False
            finally:
                if out.parent.exists():
                    shutil.rmtree(out.parent)

    check("all three declared tests present -> comparison is produced", run())
    check("a MISSING policy_adjusted.json blocks the comparison (family A incomplete)",
          not run(drop_policy_for="gemini"))

    def null_p(base, gdir):
        if base == "gpt":
            (gdir / "policy_adjusted.json").write_text(json.dumps(
                {"models": {"helpfulness": {"p_value": None, "converged": True}}}))
    check("a policy-adjusted fit that produced no p blocks the comparison", not run(null_p))

    def nan_p(base, gdir):
        if base == "sonnet":
            (gdir / "policy_adjusted.json").write_text(
                '{"models": {"helpfulness": {"p_value": NaN, "converged": true}}}')
    check("a nonfinite policy-adjusted p blocks the comparison", not run(nan_p))

    # Holm family A must block a NON-CONVERGED policy-adjusted fit exactly as families B and C
    # do. statsmodels still emits a finite p-value from a MixedLM that hit the iteration limit,
    # so a finiteness check alone would let a small p from a non-converged fit be published as
    # Holm-significant -- the degraded-run-manufactures-significance failure O4 exists to close.
    def not_converged(base, gdir):
        if base == "gemini":
            (gdir / "policy_adjusted.json").write_text(json.dumps(
                {"models": {"helpfulness": {"p_value": 0.012, "converged": False}}}))
    check("a NON-CONVERGED policy-adjusted fit blocks the comparison (family A)",
          not run(not_converged))

    def no_converged_key(base, gdir):
        if base == "gpt":
            (gdir / "policy_adjusted.json").write_text(json.dumps(
                {"models": {"helpfulness": {"p_value": 0.2}}}))
    check("a policy_adjusted.json with no `converged` key blocks (malformed/foreign)",
          not run(no_converged_key))

    def fit_error(base, gdir):
        if base == "sonnet":
            (gdir / "policy_adjusted.json").write_text(json.dumps(
                {"models": {"helpfulness": {"error": "fit failed: LinAlgError"}}}))
    check("a policy-adjusted fit that recorded an error blocks", not run(fit_error))

    # the same convergence rule on BOTH sides of the family boundary
    check("family A and families B/C both refuse a non-converged fit",
          _raises(lambda: C._policy_adjusted_help_p_from_blob(
              "gemini", {"models": {"helpfulness": {"p_value": 0.012, "converged": False}}}))
          if hasattr(C, "_policy_adjusted_help_p_from_blob") else
          _raises(lambda: C._interaction_p(
              "gemini",
              {"gemini": {"instruments": {"helpfulness": {"interaction": {
                  "raw": {"available": True, "converged": False,
                          "judge_x_leakage_leaks_i": {"p": 0.012}}}}}}},
              "judge_x_leakage_leaks_i", "family_B")))

    # a fit that fails / does not converge is blocking too
    check("a non-converged interaction fit is a blocking analysis error",
          _raises(lambda: C._interaction_p(
              "sonnet",
              {"sonnet": {"instruments": {"helpfulness": {"interaction": {
                  "raw": {"available": True, "converged": False,
                          "judge_x_leakage_leaks_i": {"p": 0.04}}}}}}},
              "judge_x_leakage_leaks_i", "family_B")))
    check("a failed interaction fit is a blocking analysis error",
          _raises(lambda: C._interaction_p(
              "sonnet",
              {"sonnet": {"instruments": {"helpfulness": {"interaction": {
                  "raw": {"available": True, "error": "fit failed: LinAlgError"}}}}}},
              "judge_x_leakage_leaks_i", "family_B")))
    check("an unavailable interaction model is a blocking analysis error",
          _raises(lambda: C._interaction_p(
              "sonnet",
              {"sonnet": {"instruments": {"helpfulness": {"interaction": {
                  "raw": {"available": False, "error": "statsmodels import failed"}}}}}},
              "judge_x_leakage_leaks_i", "family_B")))


def test_requires_current_complete_promoted_outputs():
    """O2 consumer side: the comparator must require a CURRENT COMPLETE promoted output set,
    not merely files that happen to exist."""
    print("\n[O2: comparison requires a current complete promoted set + matching stamps]")
    of = lambda i, c, r, p, t: [4, 4, 4]      # noqa: E731
    gf = lambda i, c, r, p, t: [3, 4, 3]      # noqa: E731

    def aligned_ok(mutate):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
            odir, gdir = build_base(Path(td), "sonnet", of, gf, lambda c, r, p, t: r % 2 == 0)
            mutate(REPO_ROOT / gdir)
            try:
                C.load_aligned("sonnet", odir, gdir, "helpfulness")
                return True
            except SystemExit:
                return False

    check("a complete promoted set with matching stamps compares", aligned_ok(lambda d: None))
    check("a missing run_state.json refuses",
          not aligned_ok(lambda d: (d / "run_state.json").unlink()))

    def half_promoted(d):
        blob = json.loads((d / "run_state.json").read_text())
        blob.update(state="scoring", complete=False)
        (d / "run_state.json").write_text(json.dumps(blob))
    check("outputs invalidated by a later incomplete attempt refuse to be compared",
          not aligned_ok(half_promoted))

    def stamp_drift(d):
        blob = json.loads((d / "helpfulness_detail.json").read_text())
        blob["stamp"] = {**blob["stamp"], "returned_model": "gpt-5.6-sol-OTHER"}
        (d / "helpfulness_detail.json").write_text(json.dumps(blob))
    check("a detail file whose stamp differs from the promoted run refuses",
          not aligned_ok(stamp_drift))

    def cache_rescored(d):
        (d / "cache").mkdir(exist_ok=True)
        (d / "cache" / "helpfulness_cache.json").write_text(json.dumps(
            {"stamp": {"instrument": "helpfulness", "returned_model": "gpt-5.6-sol-LATER"},
             "entries": {}}))
    check("a cache re-scored after promotion refuses (stale results vs new cache)",
          not aligned_ok(cache_rescored))

    def cache_matching(d):
        stamp = json.loads((d / "helpfulness_detail.json").read_text())["stamp"]
        (d / "cache").mkdir(exist_ok=True)
        (d / "cache" / "helpfulness_cache.json").write_text(
            json.dumps({"stamp": stamp, "entries": {}}))
    check("a cache whose stamp matches the promoted run is accepted",
          aligned_ok(cache_matching))


def test_failed_comparison_leaves_no_publishable_report():
    """Invalidate an old comparison before recomputation and bind a successful report
    to its inputs. Missing policy-adjusted results or a non-converged fit must not
    leave the previous report publishable beside refreshed base outputs."""
    print("\n[R4-F4: comparison publication is transactional and input-bound]")
    import shutil
    of, gf = opus_ratings, gpt_ratings   # NOT constant -- see the note above build_base
    out = REPO_ROOT / "results/judge_robustness/gpt-5.6-sol/_t_cmp_tx/comparison"
    if out.parent.exists():
        shutil.rmtree(out.parent)

    def build(td, degrade=None):
        pairs = []
        for base in ("sonnet", "gpt", "gemini"):
            odir, gdir = build_base(Path(td), base, of, gf, lambda c, r, p, t: r % 2 == 0)
            (REPO_ROOT / gdir / "policy_adjusted.json").write_text(json.dumps(
                {"models": {"helpfulness": {"p_value": 0.2, "converged": True}}}))
            if degrade:
                degrade(base, REPO_ROOT / gdir)
            pairs.append((base, odir, gdir))
        return pairs

    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        C.compare(build(td), out, seed=0)
        check("a successful comparison publishes comparison.json", (out / "comparison.json").is_file())
        state = json.loads((out / "run_state.json").read_text())
        check("comparison run_state is marked complete",
              state["state"] == "complete" and state["complete"] is True)
        check("comparison binds a sha256 of its own report",
              state["comparison_sha256"] == C._sha256_file(out / "comparison.json"))
        check("comparison records input hashes for all three bases",
              set(state["inputs"]) == {"sonnet", "gpt", "gemini"})
        # Bind the Opus inputs as well as the GPT inputs.
        check("bindings cover every required input label on both sides",
              all(set(C.REQUIRED_INPUT_LABELS) <= set(v["files"])
                  for v in state["inputs"].values()))
        check("bindings include the Opus detail files and per_turn.csv (was: gpt only)",
              all(any(k.startswith("opus/") for k in v["files"])
                  and "opus/per_turn.csv" in v["files"]
                  for v in state["inputs"].values()))
        check("no staging directory survives a successful publication",
              not any(out.glob("tmp.staging.*")))
        first = (out / "comparison.json").read_text()

    # now a recomputation that FAILS on a blocking O4 condition
    def non_converged(base, gdir):
        if base == "gemini":
            (gdir / "policy_adjusted.json").write_text(json.dumps(
                {"models": {"helpfulness": {"p_value": 0.012, "converged": False}}}))

    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        try:
            C.compare(build(td, degrade=non_converged), out, seed=0)
            failed = False
        except SystemExit:
            failed = True
        check("the degraded recomputation is refused", failed)
        check("the SUPERSEDED comparison.json is gone (was: left publishable)",
              not (out / "comparison.json").is_file())
        state2 = json.loads((out / "run_state.json").read_text())
        check("comparison run_state reports the failure",
              state2["state"] == "failed" and state2["complete"] is False)
        check("no staging directory is left behind by the failed run",
              not any(out.glob("tmp.staging.*")))

    # and the artifact verifier refuses a stale/unbound comparison
    V = _load_verifier()
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        C.compare(build(td), out, seed=0)
        root = out.parent
        check("verifier accepts a current, input-bound comparison",
              V.comparison_failures(root) == [])
        (out / "run_state.json").unlink()
        check("verifier refuses a comparison with no promotion marker",
              V.comparison_failures(root) != [])
        C.compare(build(td), out, seed=0)
        (out / "comparison.json").write_text(first + "\n")   # tamper after publication
        check("verifier refuses a comparison.json that changed after publication",
              V.comparison_failures(root) != [])
    check("verifier is silent when no comparison has been produced yet",
          V.comparison_failures(REPO_ROOT / "results/judge_robustness/gpt-5.6-sol") == [])
    shutil.rmtree(out.parent)


def test_source_mutation_during_comparison_blocks_publication():
    """Snapshot both judges' inputs before analysis and recheck them before publication.

    Computing hashes only after analysis could bind new inputs to an old report."""
    print("\n[R8-F2: inputs are snapshotted before analysis and re-verified before promotion]")
    import shutil
    of, gf = opus_ratings, gpt_ratings   # NOT constant -- see the note above build_base
    out = REPO_ROOT / "results/judge_robustness/gpt-5.6-sol/_t_mutate/comparison"
    shutil.rmtree(out.parent, ignore_errors=True)

    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as td:
        pairs = []
        for base in ("sonnet", "gpt", "gemini"):
            odir, gdir = build_base(Path(td), base, of, gf, lambda c, r, p, t: r % 2 == 0)
            (REPO_ROOT / gdir / "policy_adjusted.json").write_text(json.dumps(
                {"models": {"helpfulness": {"p_value": 0.2, "converged": True}}}))
            pairs.append((base, odir, gdir))

        check("the consumed-input map covers both sides",
              set(C.REQUIRED_INPUT_LABELS) <=
              set(C._consumed_input_paths(*pairs[0])))

        # a stable run publishes
        C.compare(pairs, out, seed=0)
        check("a stable comparison publishes", (out / "comparison.json").is_file())

        # Mutate an OPUS input and confirm the snapshot notices. NOTE: read/write in BINARY --
        # the fixture CSV is written with csv's \r\n terminators, and a read_text/write_text
        # round trip would silently rewrite them as \n and corrupt the restore.
        opus_pt = REPO_ROOT / pairs[0][1] / "per_turn.csv"
        original = opus_pt.read_bytes()
        before = C._input_bindings(pairs)
        opus_pt.write_bytes(original + b"conv,0,p1,0,False\r\n")
        after = C._input_bindings(pairs)
        check("mutating an OPUS input is visible to the snapshot comparison (was: unhashed)",
              _raises(lambda: C._assert_inputs_unchanged(before, after)))
        opus_pt.write_bytes(original)
        check("an unchanged snapshot pair passes",
              C._assert_inputs_unchanged(before, C._input_bindings(pairs)) is None)

        # End to end: an input that shifts WHILE compare() runs must block publication. The
        # post-analysis snapshot is what catches it, so a drifting second snapshot models a
        # concurrent base refresh exactly.
        real_bindings = C._input_bindings
        seen = {"n": 0}

        def drifting(prs):
            seen["n"] += 1
            b = real_bindings(prs)
            if seen["n"] > 1:                    # the re-hash before promotion sees a change
                b["sonnet"]["files"]["opus/per_turn.csv"] = "0" * 64
            return b

        C._input_bindings = drifting
        try:
            blocked = _raises(lambda: C.compare(pairs, out, seed=0))
        finally:
            C._input_bindings = real_bindings
        check("a source that changed while the comparison ran blocks publication", blocked)
        check("the superseded report is removed rather than left publishable",
              not (out / "comparison.json").is_file())
        check("a re-run over settled inputs publishes again",
              C.compare(pairs, out, seed=0) is not None
              and (out / "comparison.json").is_file())
    shutil.rmtree(out.parent, ignore_errors=True)


def test_comparison_verification_does_not_fail_open():
    """Require the comparison report, its hash, and complete input bindings.

    A complete run-state record alone is insufficient."""
    print("\n[R8-F4: comparison verification requires complete integrity evidence]")
    import shutil
    V = _load_verifier()
    root = REPO_ROOT / "results/judge_robustness/gpt-5.6-sol/_t_failopen"
    shutil.rmtree(root, ignore_errors=True)
    cdir = root / "comparison"
    cdir.mkdir(parents=True)

    check("a genuinely pre-comparison layer is silent", V.comparison_failures(root) == [])

    (cdir / "run_state.json").write_text(json.dumps(
        {"state": "complete", "complete": True, "comparison_sha256": "abc", "inputs": {}}))
    check("a complete run_state with NO comparison.json fails (was: passed)",
          V.comparison_failures(root) != [])

    (cdir / "comparison.json").write_text("{}")
    (cdir / "run_state.json").write_text(json.dumps({"state": "complete", "complete": True}))
    check("a report with no comparison_sha256 and no inputs fails (was: passed)",
          V.comparison_failures(root) != [])

    sha = V.sha256(cdir / "comparison.json")
    (cdir / "run_state.json").write_text(json.dumps(
        {"state": "complete", "complete": True, "comparison_sha256": sha,
         "inputs": {"sonnet": {"gpt_dir": "x", "opus_dir": "y", "files": {}}}}))
    check("inputs listing only one of the three bases fails (was: passed)",
          V.comparison_failures(root) != [])

    (cdir / "comparison.json").unlink()
    (cdir / "run_state.json").unlink()
    check("removing both leaves the layer legitimately pre-comparison",
          V.comparison_failures(root) == [])
    shutil.rmtree(root, ignore_errors=True)


def _load_verifier():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_verify_artifact_cmp", REPO_ROOT / "artifact" / "verify_artifact.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    test_quadratic_weighted_kappa()
    test_holm()
    test_holm_family_size_is_fixed_at_three()
    test_median_and_rep_order_invariance()
    test_agreement_on_fixture()
    test_load_aligned_and_rep_order_invariance()
    test_interaction_and_dod_and_formula()
    test_compare_end_to_end_and_same_family()
    test_guards_namespace_and_provenance()
    test_alignment_guards()
    test_dialogue_manifest_binding_is_mandatory()
    test_requires_current_complete_promoted_outputs()
    test_degraded_analysis_blocks_the_comparison()
    test_failed_comparison_leaves_no_publishable_report()
    test_source_mutation_during_comparison_blocks_publication()
    test_comparison_verification_does_not_fail_open()
    print(f"\n{_passed} passed, {_failed} failed")
    raise SystemExit(1 if _failed else 0)


if __name__ == "__main__":
    main()
