"""Offline tests for the matched visible-turn-budget pass (analysis/matched_budget.py).

Synthetic, known-answer fixtures (no API key / network / live data needed):
  - matched_k is the pairwise minimum.
  - truncate_problem keeps the first K tutor turns and the student turns up to the response to
    the K-th kept turn, degenerating to the full window at K = full count (incl. trailing
    students) and dropping the cell at K = 0.
  - the truncation machinery produces the expected per-(problem, replicate) K and turn sets.
  - a CONSTRUCTED case where truncation FLIPS a marginal is detected and flagged.
  - NO judge call is made anywhere in the pass (cached helpfulness is reused) — enforced with a
    tripwire `analysis.judge` that raises on any access.
And one integration check, skipped if the confirmatory data is absent:
  - recomputing every marginal with NO truncation (pool all turns) reproduces the frozen
    per_replicate.csv exactly (the foundational faithfulness invariant).

Run:  python tools/test_matched_budget.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import inferential as I  # noqa: E402
from analysis import matched_budget as mb  # noqa: E402
from analysis import run_inference as R  # noqa: E402

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


# --------------------------------------------------------------- synthetic builders
def _tutor(ti, first, last, leaks, helpfulness=5.0, nti=True):
    return {"problem_id": None, "turn_index": ti, "first_seq": first, "last_seq": last,
            "leaks": leaks, "helpfulness": helpfulness, "next_turn_independence": nti}


def _student(seq, attempt):
    return {"seq": seq, "attempt": attempt}


# --------------------------------------------------------------- matched_k
def test_matched_k():
    print("\n[matched_k = pairwise minimum]")
    check("min(4,7)=4", mb.matched_k(4, 7) == 4)
    check("min(7,4)=4 (symmetric)", mb.matched_k(7, 4) == 4)
    check("min(0,5)=0", mb.matched_k(0, 5) == 0)
    check("min(3,3)=3", mb.matched_k(3, 3) == 3)


# --------------------------------------------------------------- truncate_problem
def test_truncate_problem():
    print("\n[truncate_problem: first K tutor turns + students up to the K-th]")
    # ConvTutor-like single-seq tutor turns; student leads each problem then responds.
    tutor = [_tutor(0, 2, 2, False), _tutor(1, 4, 4, False),
             _tutor(2, 6, 6, True), _tutor(3, 8, 8, True)]
    student = [_student(1, False), _student(3, True), _student(5, True),
               _student(7, True), _student(9, True)]

    kt, ks = mb.truncate_problem(tutor, student, 2)
    check("K=2 keeps first 2 tutor turns", [t["turn_index"] for t in kt] == [0, 1])
    check("K=2 keeps students before the first DROPPED tutor turn (seq<6): {1,3,5}",
          [s["seq"] for s in ks] == [1, 3, 5])

    kt, ks = mb.truncate_problem(tutor, student, 4)
    check("K=full keeps all tutor turns", [t["turn_index"] for t in kt] == [0, 1, 2, 3])
    check("K=full keeps all students (no-op)", [s["seq"] for s in ks] == [1, 3, 5, 7, 9])

    kt, ks = mb.truncate_problem(tutor, student, 0)
    check("K=0 drops the whole cell", kt == [] and ks == [])

    # No-commit problem with a student TRAILING the last tutor turn: K=full must keep it.
    student_trailing = student + [_student(11, True)]
    kt, ks = mb.truncate_problem(tutor, student_trailing, 4)
    check("K=full keeps a student trailing the last tutor turn (degeneracy fix)",
          [s["seq"] for s in ks] == [1, 3, 5, 7, 9, 11])

    # PedTutor-like multi-seq tutor turns (state_tracker+responder): boundary is first_seq.
    ped_tutor = [_tutor(0, 2, 3, False), _tutor(1, 5, 6, False),
                 _tutor(2, 8, 9, False), _tutor(3, 11, 12, False)]
    ped_student = [_student(1, False), _student(4, True), _student(7, True),
                   _student(10, True), _student(13, True)]
    kt, ks = mb.truncate_problem(ped_tutor, ped_student, 2)
    check("ped K=2 keeps first 2 tutor turns", [t["turn_index"] for t in kt] == [0, 1])
    check("ped K=2 keeps students before the 3rd tutor's first call (seq<8): {1,4,7}",
          [s["seq"] for s in ks] == [1, 4, 7])


# --------------------------------------------------------------- expected K + turn sets
def _tables_two_conditions():
    """One replicate, one problem: conv has 2 in-window tutor turns, ped has 5."""
    tables = {}
    conv_t = [_tutor(0, 2, 2, True), _tutor(1, 4, 4, False)]
    conv_s = [_student(1, False), _student(3, True), _student(5, True)]
    ped_t = [_tutor(0, 2, 3, False), _tutor(1, 5, 6, True), _tutor(2, 8, 9, False),
             _tutor(3, 11, 12, False), _tutor(4, 14, 15, False)]
    ped_s = [_student(1, False), _student(4, True), _student(7, True), _student(10, True),
             _student(13, True), _student(16, True)]
    tables[("conv", "0", "train-1")] = {"tutor": conv_t, "student": conv_s}
    tables[("ped", "0", "train-1")] = {"tutor": ped_t, "student": ped_s}
    return tables


def test_expected_K_and_turn_sets():
    print("\n[compute_truncation: expected per-(problem,replicate) K and turn sets]")
    counts, K_map, truncated = mb.compute_truncation(_tables_two_conditions())
    check("count conv=2, ped=5", counts[("conv", "0", "train-1")] == 2
          and counts[("ped", "0", "train-1")] == 5)
    check("K = min(2,5) = 2", K_map[("0", "train-1")] == 2)
    check("conv kept all 2 tutor turns (no-op, it is the minimum)",
          len(truncated[("conv", "0")]["tutor"]) == 2)
    check("ped truncated to first 2 tutor turns",
          [t["turn_index"] for t in truncated[("ped", "0")]["tutor"]] == [0, 1])
    check("ped students truncated to before the 3rd tutor's first call (seq<8): {1,4,7}",
          [s["seq"] for s in truncated[("ped", "0")]["student"]] == [1, 4, 7])


# --------------------------------------------------------------- constructed flip + flag
def _flip_tables(n_rep=6):
    """Per replicate, one problem: conv has 5 tutor turns whose leaks are concentrated LATE
    [F,F,T,T,T] (full rate 0.6); ped has 2 tutor turns [T,F] (rate 0.5). Full window: conv>ped
    (predicted). Matched budget K=min(5,2)=2 truncates conv to its first two CLEAN turns (rate
    0.0) while ped is unchanged (0.5) -> the conv-ped leakage difference FLIPS sign."""
    tables = {}
    for r in range(n_rep):
        rid = str(r)
        conv_t = [_tutor(0, 2, 2, False), _tutor(1, 4, 4, False), _tutor(2, 6, 6, True),
                  _tutor(3, 8, 8, True), _tutor(4, 10, 10, True)]
        conv_s = [_student(1, True), _student(3, True), _student(5, True), _student(7, True),
                  _student(9, True), _student(11, True)]
        ped_t = [_tutor(0, 2, 2, True), _tutor(1, 4, 4, False)]
        ped_s = [_student(1, True), _student(3, True), _student(5, True)]
        tables[("conv", rid, "train-1")] = {"tutor": conv_t, "student": conv_s}
        tables[("ped", rid, "train-1")] = {"tutor": ped_t, "student": ped_s}
    return tables


def _pool_all(tables):
    pooled = {}
    for (cond, rid, _pid), v in tables.items():
        t = pooled.setdefault((cond, rid), {"tutor": [], "student": []})
        t["tutor"].extend(v["tutor"])
        t["student"].extend(v["student"])
    return pooled


def test_flip_detected_and_flagged():
    print("\n[constructed truncation FLIP is detected and flagged]")
    tables = _flip_tables()
    full_j1 = I.j1(mb.truncated_per_replicate(_pool_all(tables)))     # no truncation
    _counts, _K, truncated = mb.compute_truncation(tables)
    matched_j1 = I.j1(mb.truncated_per_replicate(truncated))

    fp1, mp1 = full_j1["P1_leakage"], matched_j1["P1_leakage"]
    check("full window: P1 conv>ped, significant", fp1["significant_in_predicted_direction"]
          and fp1["mean_diff_conv_minus_ped"] > 0)
    check("matched budget: P1 difference flips sign (now ped>conv)",
          mp1["mean_diff_conv_minus_ped"] < 0)
    verdict, changed = mb._verdict(fp1, mp1)
    check("flip is flagged (changed=True)", changed is True)
    check("verdict names the flip", "flip" in verdict)

    # compare() rolls the flag up
    comparison = mb.compare(full_j1, matched_j1)
    check("compare() lists P1 as changed", comparison["P1_leakage"]["changed_under_matched_budget"])


# --------------------------------------------------------------- NO judge calls
class _Tripwire:
    """Raises on ANY attribute access — installed as analysis.judge to prove the pass never
    touches the judge."""
    def __getattr__(self, name):
        raise RuntimeError(f"matched-budget pass must not call the judge (accessed judge.{name})")


def test_no_judge_calls():
    print("\n[no judge calls — cached helpfulness reused]")
    # matched_budget must not have imported the judge at all.
    check("analysis.judge not imported by the matched-budget module",
          "analysis.judge" not in sys.modules)

    saved = sys.modules.get("analysis.judge")
    sys.modules["analysis.judge"] = _Tripwire()
    try:
        tables = _flip_tables()
        _counts, _K, truncated = mb.compute_truncation(tables)
        per_rep = mb.truncated_per_replicate(truncated)
        per_turn = mb.truncated_per_turn(truncated)
        I.j1(per_rep)
        I.j2(per_turn)
        # cached helpfulness is reused verbatim, not recomputed
        cached_ok = all(t["helpfulness"] == 5.0
                        for v in truncated.values() for t in v["tutor"])
        check("full truncation+inference pipeline runs without touching the judge", True)
        check("per-turn helpfulness is the cached input value (reused, not re-judged)", cached_ok)
    except RuntimeError as e:
        check(f"pipeline must not call the judge ({e})", False)
    finally:
        if saved is None:
            sys.modules.pop("analysis.judge", None)
        else:
            sys.modules["analysis.judge"] = saved


# --------------------------------------------------------------- integration: pool-all == frozen
def test_pool_all_reproduces_frozen():
    print("\n[integration: no-truncation recompute reproduces frozen per_replicate.csv]")
    d = REPO_ROOT / "results" / "confirmatory"
    per_turn = R._read_csv(d / "per_turn.csv")
    per_session = [r for r in R._read_csv(d / "per_session.csv") if r["condition"] in mb.CONDITIONS]
    frozen = [r for r in R._read_csv(d / "per_replicate.csv") if r["condition"] in mb.CONDITIONS]
    if not (per_turn and per_session and frozen):
        print("  SKIP  confirmatory data not present")
        return
    run_ids = sorted({r["run_id"] for r in per_session})
    # The CSVs above are tracked; the raw transcripts they were built from are not
    # (~100 MB, gitignored). Recomputing needs the transcripts, so on a fresh clone this
    # integration check has no input and skips rather than dying on FileNotFoundError.
    if not all((REPO_ROOT / "logs" / rid / "calls.jsonl").exists() for rid in run_ids):
        print("  SKIP  raw transcripts absent (logs/ is gitignored; unpack the released "
              "artifact into logs/ to exercise this)")
        return
    sessions = mb.load_sessions(run_ids)
    tables = mb.build_problem_tables(sessions, per_turn)
    recomp = {(r["condition"], r["replicate_id"]): r
              for r in mb.truncated_per_replicate(_pool_all(tables))}
    bad = 0
    for fr in frozen:
        rc = recomp[(fr["condition"], fr["replicate_id"])]
        for col in ("leakage_rate", "independence_ratio", "helpfulness_mean"):
            if not approx(float(fr[col]), rc[col]):
                bad += 1
    check("pool-all reproduces frozen leakage/independence/helpfulness (0 mismatches)", bad == 0)


# --------------------------------------------------------------- final CSV row builders
def _mini_report():
    full = {"conv_mean": 0.4, "ped_mean": 0.1, "mean_diff_conv_minus_ped": 0.3,
            "diff_ci95": (0.2, 0.4), "p_two_sided": 0.01, "cliffs_delta_conv_vs_ped": 0.9,
            "n": 10, "significant_in_predicted_direction": True}
    matched = {**full, "mean_diff_conv_minus_ped": 0.28, "diff_ci95": (0.18, 0.38),
               "p_two_sided": 0.02, "cliffs_delta_conv_vs_ped": 0.85}
    leg = {"operative_method": "mixed_effects",
           "operative_significant_in_predicted_direction": True,
           "n_leaky": 57, "n_nonleaky": 199, "leaky_mean": 4.9, "nonleaky_mean": 4.6,
           "cluster_within_rep_effect": 0.26, "cluster_p": 0.004, "cluster_n_rep": 10,
           "mixed_available": True, "mixed_coef": 0.29, "mixed_p": 0.0002, "mixed_ci95": [0.1, 0.5]}
    j2 = {"n_turns": 256, "J2_supported": True,
          "leak_to_helpfulness": leg, "leak_to_next_independence": leg}
    summ = {"mean": 13.5, "median": 11.5, "ci95": (10.3, 17.1), "n": 10}
    rc = {"per_condition": {c: {"inwindow_visible_tutor_turns": summ, "model_calls": summ,
                                "tutor_tokens": summ, "total_tokens": summ}
                            for c in ("conv", "ped")},
          "turn_count_gap_ped_minus_conv": {"mean_diff": 8.8, "median_diff": 11.0,
                                            "ci95": (4.6, 12.6), "n_pairs": 10}}
    marg_cell = {"full_window": full, "matched_budget": matched,
                 "verdict": "holds under matched visible-turn budget",
                 "changed_under_matched_budget": False}
    return {"marginals_full_vs_matched": {"P1_leakage": marg_cell, "P2_helpfulness": marg_cell,
                                          "P3_independence": marg_cell},
            "j2_full_window": j2, "j2_matched_budget": j2, "realized_counts": rc}


def test_final_csv_rows():
    print("\n[final CSV row builders]")
    rep = _mini_report()
    mrows = mb.marginal_csv_rows(rep)
    p1 = [r for r in mrows if r["block"] == "marginal" and r["metric"] == "P1_leakage"]
    check("two marginal rows per metric (full + matched)", len(p1) == 2)
    check("verdict only on the matched row",
          p1[0]["window"] == "full" and p1[0]["verdict"] == ""
          and p1[1]["window"] == "matched" and p1[1]["verdict"].startswith("holds"))
    j2rows = [r for r in mrows if r["block"] == "j2"]
    check("four J2 rows (2 legs x full/matched)", len(j2rows) == 4)
    check("J2 cell sizes recorded in n", all("leaky" in str(r["n"]) for r in j2rows))
    trows = mb.turn_csv_rows(rep)
    check("turns table has a ped_minus_conv gap row",
          any(r["condition"] == "ped_minus_conv" and approx(r["mean"], 8.8) for r in trows))


def main():
    test_matched_k()
    test_truncate_problem()
    test_expected_K_and_turn_sets()
    test_flip_detected_and_flagged()
    test_no_judge_calls()
    test_final_csv_rows()
    test_pool_all_reproduces_frozen()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
