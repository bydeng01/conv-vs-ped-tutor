"""Matched visible-turn-budget compute-fairness pass (paper-plan.md §10).

§10 names two compute-fairness controls: the cost-normalized sensitivity (outcomes per 1k
tutor tokens — already in analysis/inferential.py `cost_normalized`) and "the primary
comparison fixes the same visible-turn budget across tutors." This module is the second one,
run as a read-only robustness re-analysis over the frozen confirmatory tables/logs.

The frozen rule (decisions-log.md 2026-06-26, written before this result was read): for each
(problem, replicate) pair, K = min over conv/ped of the in-window (answer-phase) visible
tutor-turn count; truncate BOTH conditions to the first K tutor turns of that problem and the
student turns up to (and including) the response to the K-th tutor turn. The three marginals
are recomputed over the truncated turns with the SAME aggregation as the frozen per-session
metrics, then run through the SAME §10 inference (analysis/inferential.py `j1`/`j2`). J2 is a
secondary robustness; the per-1k-tutor-token sensitivity is surfaced alongside so both §10
views appear together. Any marginal whose direction or significance changes vs its full-window
value is flagged.

Nothing here re-runs a session, re-judges a turn, or modifies a window/rubric/prompt/metric/
problem/log. It REUSES: the frozen per-turn leakage flags (per_turn.csv `leaks`), the cached
per-turn helpfulness scores (per_turn.csv `helpfulness` / helpfulness_cache.json — the judge is
NOT called), the frozen independence regex (metrics.attempts_reasoning, applied to the
truncated student window), and analysis/inferential.py. Reported regardless of outcome (§11).

Usage:
  python analysis/matched_budget.py results/confirmatory
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import median

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import inferential as I  # noqa: E402
from analysis import metrics as M  # noqa: E402
from analysis import run_inference as R  # noqa: E402  (reuse _git/_provenance/_read_csv/_fmt_p)

CONDITIONS = ("conv", "ped")
MARGINALS = (("leakage_rate", "P1_leakage"),
             ("helpfulness_mean", "P2_helpfulness"),
             ("independence_ratio", "P3_independence"))


# ---------------------------------------------------------------- pure truncation core
def matched_k(n_conv: int, n_ped: int) -> int:
    """The frozen matched budget for one (problem, replicate): the pairwise minimum of the
    two conditions' in-window visible tutor-turn counts. Data-independent in form; a single K,
    never chosen to flatter a result."""
    return min(int(n_conv), int(n_ped))


def truncate_problem(tutor_by_seq: list[dict], student_by_seq: list[dict], k: int) -> tuple[list, list]:
    """Apply the frozen rule to ONE (condition, problem): keep the first `k` visible tutor
    turns (already ordered by call sequence) and the student turns up to and including the
    response to the k-th kept tutor turn. The student cutoff is anchored to the FIRST DROPPED
    tutor turn — keep student turns whose seq is before that turn's first call — so that with
    k = this condition's full in-window count nothing is dropped and the rule degenerates
    exactly to the full answer-phase window (including any student turns trailing the last tutor
    turn in a no-commit problem). k<=0 drops the problem entirely (both turn sets empty). Pure:
    operates on plain dicts, so it is unit-testable without logs. Each tutor dict needs
    `first_seq`; each student dict needs `seq`."""
    kept_tutor = list(tutor_by_seq[:k])
    if k <= 0 or not kept_tutor:
        return [], []
    if k >= len(tutor_by_seq):                       # no tutor turn dropped -> full window
        return kept_tutor, list(student_by_seq)
    cutoff = tutor_by_seq[k]["first_seq"]            # first call of the first DROPPED tutor turn
    kept_student = [s for s in student_by_seq if s["seq"] < cutoff]
    return kept_tutor, kept_student


# ---------------------------------------------------------------- loaders / joins
def _to_bool(x) -> bool:
    return str(x).strip().lower() == "true"


def _to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_sessions(run_ids: list[str], domain: str = "domain/algebra/problems.yaml") -> list:
    """Re-derive each confirmatory session with the FROZEN metrics (analysis/metrics.py,
    answer-phase window). Pure parsing + frozen regex — no model/judge call. Read-only over
    logs/<run_id>/calls.jsonl."""
    pbi = M.problem_index(domain)
    out = []
    for rid in run_ids:
        out.append(M.analyze_session(REPO_ROOT / "logs" / rid, pbi))
    return out


def build_problem_tables(sessions: list, per_turn: list[dict]) -> dict:
    """Per (condition, replicate_id, problem_id): the ordered in-window tutor turns and student
    turns. The tutor turns carry the REUSED frozen per-turn leakage flag and cached helpfulness
    (joined from per_turn.csv by (condition, replicate_id, problem_id, turn_index)); a hard
    assert confirms the stored flags match the log-derived ones (so 'reuse the frozen flags' is
    literal and verified). Student turns carry the frozen independence-regex `attempt`."""
    pt = {}
    for r in per_turn:
        if r["condition"] not in CONDITIONS:
            continue
        pt[(r["condition"], r["replicate_id"], r["problem_id"], str(r["turn_index"]))] = r

    tables: dict[tuple, dict] = {}
    for sm in sessions:
        cond, rid = sm.condition, sm.replicate_id
        if cond not in CONDITIONS:
            continue
        for it in sm.leak_items:                     # in-window TRAINING tutor turns
            pid, ti = it["problem_id"], it["turn_index"]
            row = pt.get((cond, rid, pid, str(ti)))
            if row is None:
                raise AssertionError(f"per_turn.csv missing tutor turn {(cond, rid, pid, ti)}")
            if _to_bool(row["leaks"]) != bool(it["leaks"]):
                raise AssertionError(f"frozen leak flag mismatch at {(cond, rid, pid, ti)}: "
                                     f"per_turn={row['leaks']} vs log={it['leaks']}")
            tables.setdefault((cond, rid, pid), {"tutor": [], "student": []})["tutor"].append({
                "problem_id": pid, "turn_index": ti,
                "first_seq": it["first_seq"], "last_seq": it["last_seq"],
                "leaks": _to_bool(row["leaks"]),                 # REUSED frozen per-turn flag
                "helpfulness": _to_float(row.get("helpfulness")),  # REUSED cached score (no judge)
                "next_turn_independence": row.get("next_turn_independence"),
            })
        for it in sm.indep_items:                    # in-window student TRAINING turns
            pid = it["problem_id"]
            tables.setdefault((cond, rid, pid), {"tutor": [], "student": []})["student"].append({
                "seq": it["seq"], "attempt": bool(it["attempt"]),   # frozen independence regex
            })

    for v in tables.values():
        v["tutor"].sort(key=lambda r: r["first_seq"])
        v["student"].sort(key=lambda r: r["seq"])
    return tables


# ---------------------------------------------------------------- truncation + marginals
def compute_truncation(tables: dict) -> tuple[dict, dict, dict]:
    """Returns (counts, K_map, truncated). counts[(cond,rid,pid)] = in-window tutor count;
    K_map[(rid,pid)] = pairwise-min K; truncated[(cond,rid)] = pooled kept tutor + student turns
    across that conversation's problems."""
    counts = {k: len(v["tutor"]) for k, v in tables.items()}
    K_map = {}
    for (rid, pid) in sorted({(rid, pid) for (_, rid, pid) in tables}):
        K_map[(rid, pid)] = matched_k(counts.get(("conv", rid, pid), 0),
                                      counts.get(("ped", rid, pid), 0))
    truncated: dict[tuple, dict] = {}
    for (cond, rid, pid), v in tables.items():
        kt, ks = truncate_problem(v["tutor"], v["student"], K_map[(rid, pid)])
        t = truncated.setdefault((cond, rid), {"tutor": [], "student": []})
        t["tutor"].extend(kt)
        t["student"].extend(ks)
    return counts, K_map, truncated


def truncated_per_replicate(truncated: dict) -> list[dict]:
    """Per-conversation truncated marginals, with the SAME aggregation as the frozen
    per-session metrics: leakage_rate = leaky/total over kept tutor turns; helpfulness_mean =
    mean of cached per-turn helpfulness over kept tutor turns; independence_ratio =
    attempt/total over kept student turns."""
    rows = []
    for (cond, rid), v in sorted(truncated.items()):
        leaks = [t["leaks"] for t in v["tutor"]]
        helps = [t["helpfulness"] for t in v["tutor"] if t["helpfulness"] is not None]
        atts = [s["attempt"] for s in v["student"]]
        rows.append({
            "condition": cond, "replicate_id": rid,
            "leakage_rate": (sum(leaks) / len(leaks)) if leaks else None,
            "helpfulness_mean": (sum(helps) / len(helps)) if helps else None,
            "independence_ratio": (sum(atts) / len(atts)) if atts else None,
            "n_kept_tutor_turns": len(v["tutor"]),
            "n_kept_student_turns": len(v["student"]),
        })
    return rows


def truncated_per_turn(truncated: dict) -> list[dict]:
    """Kept tutor turns as a per_turn-shaped table for the SAME J2 (analysis/inferential.py)."""
    rows = []
    for (cond, rid), v in sorted(truncated.items()):
        for t in v["tutor"]:
            rows.append({
                "condition": cond, "replicate_id": rid, "problem_id": t["problem_id"],
                "turn_index": t["turn_index"], "leaks": t["leaks"],
                "helpfulness": t["helpfulness"],
                "next_turn_independence": t["next_turn_independence"],
            })
    return rows


# ---------------------------------------------------------------- realized counts (§9.5)
def _summary(values: list) -> dict:
    # Descriptive disclosure CIs (not a marginal NHST); bootstrap_ci's default seed=0 keeps them
    # reproducible — they are reported as uncertainty on the realized counts, not independent draws.
    v = [x for x in values if x is not None]
    return {"mean": (sum(v) / len(v)) if v else None,
            "median": float(median(v)) if v else None,
            "ci95": I.bootstrap_ci(v) if v else (None, None), "n": len(v)}


def realized_counts(per_session: list[dict]) -> dict:
    """Realized in-window visible tutor turns per conversation (conv vs ped) + the §9.5
    model-call / token totals, summarized per condition with conversation-level CIs. Plus the
    paired (ped-conv) turn-count gap."""
    out = {"per_condition": {}}
    series = {}
    for cond in CONDITIONS:
        rows = [r for r in per_session if r["condition"] == cond]
        vt = [int(r["n_train_tutor_turns"]) for r in rows]      # in-window visible tutor turns
        series[cond] = {r["replicate_id"]: int(r["n_train_tutor_turns"]) for r in rows}
        out["per_condition"][cond] = {
            "n_conversations": len(rows),
            "inwindow_visible_tutor_turns": _summary(vt),
            "model_calls": _summary([int(r["n_model_calls"]) for r in rows]),
            "tutor_tokens": _summary([int(r["tutor_tokens"]) for r in rows]),
            "total_tokens": _summary([int(r["total_tokens"]) for r in rows]),
        }
    # paired ped-conv turn-count gap (conversation-level)
    rids = sorted(set(series["conv"]) & set(series["ped"]), key=lambda x: (len(x), x))
    diffs = [series["ped"][r] - series["conv"][r] for r in rids]
    conv_m = out["per_condition"]["conv"]["inwindow_visible_tutor_turns"]["mean"]
    ped_m = out["per_condition"]["ped"]["inwindow_visible_tutor_turns"]["mean"]
    out["turn_count_gap_ped_minus_conv"] = {
        "conv_mean": conv_m, "ped_mean": ped_m,
        "mean_diff": (sum(diffs) / len(diffs)) if diffs else None,
        "median_diff": float(median(diffs)) if diffs else None,
        "ci95": I.bootstrap_ci(diffs) if diffs else (None, None),
        "n_pairs": len(rids),
        "n_ped_gt_conv": sum(1 for d in diffs if d > 0),
    }
    return out


# ---------------------------------------------------------------- side-by-side + flags
def _verdict(full: dict, trunc: dict) -> tuple[str, bool]:
    """One-line verdict for a marginal under the matched budget, comparing the truncated paired
    test to its full-window value. `changed` is the §10 flag (direction flips OR significance
    changes)."""
    f_sig = full["significant_in_predicted_direction"]
    t_sig = trunc["significant_in_predicted_direction"]
    f_dir = full["direction_matches_prediction"]
    t_dir = trunc["direction_matches_prediction"]
    sign_flip = (full["mean_diff_conv_minus_ped"] != 0 and trunc["mean_diff_conv_minus_ped"] != 0
                 and (full["mean_diff_conv_minus_ped"] > 0) != (trunc["mean_diff_conv_minus_ped"] > 0))
    changed = (f_sig != t_sig) or sign_flip or (f_dir != t_dir)
    if sign_flip:
        verdict = "flips direction under matched visible-turn budget"
    elif f_sig and not t_sig:
        verdict = "vanishes under matched visible-turn budget"
    elif not f_sig and t_sig:
        verdict = "strengthens to significant under matched visible-turn budget"
    elif abs(trunc["cliffs_delta_conv_vs_ped"]) + 1e-9 < abs(full["cliffs_delta_conv_vs_ped"]):
        verdict = "holds (same direction/significance) but weakens under matched visible-turn budget"
    else:
        verdict = "holds under matched visible-turn budget"
    return verdict, bool(changed)


def compare(full_j1: dict, trunc_j1: dict) -> dict:
    out = {}
    for _col, key in MARGINALS:
        f, t = full_j1[key], trunc_j1[key]
        verdict, changed = _verdict(f, t)
        out[key] = {
            "full_window": _slim(f), "matched_budget": _slim(t),
            "verdict": verdict, "changed_under_matched_budget": changed,
        }
    return out


def _slim(r: dict) -> dict:
    return {k: r[k] for k in ("conv_mean", "ped_mean", "mean_diff_conv_minus_ped", "diff_ci95",
                              "p_two_sided", "cliffs_delta_conv_vs_ped", "n",
                              "n_conv_gt_ped", "n_ped_gt_conv",
                              "significant_in_predicted_direction",
                              "direction_matches_prediction")}


# ---------------------------------------------------------------- orchestration
def run(results_dir: Path) -> dict:
    per_turn = R._read_csv(results_dir / "per_turn.csv")
    per_session = R._read_csv(results_dir / "per_session.csv")
    if not per_turn or not per_session:
        raise SystemExit(f"need per_turn.csv and per_session.csv in {results_dir} "
                         "(run compute_metrics.py --judge-helpfulness first)")
    cp_session = [r for r in per_session if r["condition"] in CONDITIONS]
    run_ids = sorted({r["run_id"] for r in cp_session if r.get("run_id")})

    sessions = load_sessions(run_ids)
    tables = build_problem_tables(sessions, per_turn)
    counts, K_map, truncated = compute_truncation(tables)

    # sanity: pooled kept-at-full equals the frozen per-conversation counts (no-op when K=full)
    trunc_pr = truncated_per_replicate(truncated)
    trunc_pt = truncated_per_turn(truncated)

    trunc_j1 = I.j1(trunc_pr)
    trunc_j2 = I.j2(trunc_pt) if trunc_pt else {"note": "no truncated turns"}

    # the frozen full-window primary, for the side-by-side
    full = json.loads((results_dir / "inference.json").read_text())
    comparison = compare(full["j1"], trunc_j1)

    # §10 step-4: how thin is the ped-leaky cell once the budget is matched?
    full_pt = [r for r in per_turn if r["condition"] in CONDITIONS]
    matched_cells = _cells_by_condition([{**r, "leaks": bool(r["leaks"])} for r in trunc_pt])
    full_cells = _cells_by_condition([{"condition": r["condition"], "leaks": _to_bool(r["leaks"])}
                                      for r in full_pt])
    PED_LEAKY_MIN = 10
    j2_cells = {"full_window": full_cells, "matched_budget": matched_cells,
                "ped_leaky_min_for_adequate_power": PED_LEAKY_MIN,
                "ped_leaky_underpowered_under_matched_budget": matched_cells["ped_leaky"] < PED_LEAKY_MIN,
                "note": "Frozen J2 pools conv+ped (condition NOT a covariate, §10); leakage "
                        "correlates with condition, so the pooled leaky cell is mostly conv. The "
                        "ped-leaky cell is reported here descriptively and is NOT used to re-spec J2."}

    flagged = [k for k, v in comparison.items() if v["changed_under_matched_budget"]]

    report = {
        "analysis": "matched visible-turn-budget compute-fairness pass (paper-plan §10)",
        "rule": "K = per-(problem,replicate) min of in-window visible tutor-turn counts; "
                "truncate both conditions to the first K tutor turns and the student turns up to "
                "the response to the K-th turn (frozen 2026-06-26 before this result was read).",
        "provenance": R._provenance(cp_session, trunc_pr),
        "realized_counts": realized_counts(cp_session),
        "matched_K_by_problem_replicate": {f"{rid}|{pid}": k for (rid, pid), k in sorted(K_map.items())},
        "inwindow_tutor_counts_by_problem_replicate": {
            f"{cond}|{rid}|{pid}": n for (cond, rid, pid), n in sorted(counts.items())},
        "k0_dropped_cells": _k0_dropped(K_map, counts),
        "marginals_full_vs_matched": comparison,
        "flagged_marginals": flagged,
        "j2_matched_budget": _j2_slim(trunc_j2),
        "j2_full_window": _j2_slim(full.get("j2", {})),
        "j2_leaky_cell_sizes_by_condition": j2_cells,
        "cost_normalized_per_1k_tutor_tok": full.get("cost_normalized", {}),
        "note": "Read-only over the frozen results/logs at freeze 1a12b56. Reuses the frozen "
                "per-turn leakage flags, the CACHED per-turn helpfulness (judge NOT re-run), and "
                "the frozen independence regex. Same §10 inference as the primary (paired "
                "two-sided Wilcoxon, Cliff's delta, conversation-level CIs). Reported regardless "
                "of outcome (§11); K is the single pairwise minimum, not tuned.",
    }
    return report


def _k0_dropped(K_map: dict, counts: dict) -> dict:
    """The (problem, replicate) cells where K=0 — one condition had 0 in-window tutor turns, so
    the matched budget drops the cell for BOTH conditions. The rule is condition-blind (min() is
    symmetric); disclosed because it removes real turns. In the confirmatory data every K=0 cell
    happens to be a ConvTutor immediate-commit problem (conv 0 in-window tutor turns, ped > 0) —
    `cells` records the per-condition counts so the asymmetry is visible, not assumed."""
    cells = []
    for (rid, pid), k in sorted(K_map.items()):
        if k == 0:
            cells.append({"replicate_id": rid, "problem_id": pid,
                          "conv_inwindow_tutor_turns": counts.get(("conv", rid, pid), 0),
                          "ped_inwindow_tutor_turns": counts.get(("ped", rid, pid), 0)})
    return {"n_cells": len(cells), "cells": cells}


def _cells_by_condition(per_turn_rows: list[dict]) -> dict:
    """Leaky / non-leaky turn counts split by condition. The frozen J2 pools conv+ped and
    leakage correlates with condition, so this exposes how thin the ped-leaky cell is — the §10
    step-4 concern. (J2 is NOT re-spec'd; this is descriptive disclosure only.)"""
    out = {c: {"leaky": 0, "nonleaky": 0} for c in CONDITIONS}
    for r in per_turn_rows:
        c = r["condition"]
        if c in out:
            out[c]["leaky" if r["leaks"] else "nonleaky"] += 1
    out["pooled"] = {"leaky": sum(out[c]["leaky"] for c in CONDITIONS),
                     "nonleaky": sum(out[c]["nonleaky"] for c in CONDITIONS)}
    out["ped_leaky"] = out["ped"]["leaky"]
    return out


def _j2_slim(j2: dict) -> dict:
    if not j2 or "leak_to_helpfulness" not in j2:
        return {"note": j2.get("note", "unavailable") if isinstance(j2, dict) else "unavailable"}
    out = {"n_turns": j2.get("n_turns"), "J2_supported": j2.get("J2_supported")}
    for leg in ("leak_to_helpfulness", "leak_to_next_independence"):
        L = j2[leg]
        cs, me, dsc = L["cluster_summary"], L["mixed_effects"], L["descriptive_pooled"]
        out[leg] = {
            "operative_method": L["operative_method"],
            "operative_significant_in_predicted_direction": L["operative_significant_in_predicted_direction"],
            "n_leaky": dsc["n_leaky"], "n_nonleaky": dsc["n_nonleaky"],
            "leaky_mean": dsc["leaky_mean"], "nonleaky_mean": dsc["nonleaky_mean"],
            "cluster_within_rep_effect": cs["mean_within_replicate_effect"],
            "cluster_p": cs["p_two_sided"], "cluster_n_rep": cs["n_replicates_used"],
            "mixed_available": bool(me.get("available") and "coef" in me),
            "mixed_coef": me.get("coef"), "mixed_p": me.get("p"), "mixed_ci95": me.get("ci95"),
        }
    return out


# ---------------------------------------------------------------- final CSV export (version-controlled)
# Written to the top-level results/ dir, where .gitignore tracks `*.final.csv` (everything else
# under results/ is gitignored). These are the committed, write-up-facing tables; the full detail
# stays in results/confirmatory/matched_budget.json.
_MARGINAL_COLS = ["block", "metric", "window", "group_a", "a_value", "group_b", "b_value",
                  "diff_a_minus_b", "ci95_lo", "ci95_hi", "p_two_sided", "effect_name",
                  "effect_value", "n", "significant_in_predicted_direction", "verdict",
                  "changed_vs_full"]
_TURN_COLS = ["metric", "condition", "mean", "median", "ci95_lo", "ci95_hi", "n"]


def marginal_csv_rows(report: dict) -> list[dict]:
    """Long table: each marginal (P1/P2/P3) and each J2 leg, full window vs matched budget."""
    rows = []
    for _col, key in MARGINALS:
        c = report["marginals_full_vs_matched"][key]
        for window, w in (("full", c["full_window"]), ("matched", c["matched_budget"])):
            rows.append({
                "block": "marginal", "metric": key, "window": window,
                "group_a": "conv", "a_value": w["conv_mean"],
                "group_b": "ped", "b_value": w["ped_mean"],
                "diff_a_minus_b": w["mean_diff_conv_minus_ped"],
                "ci95_lo": w["diff_ci95"][0], "ci95_hi": w["diff_ci95"][1],
                "p_two_sided": w["p_two_sided"], "effect_name": "cliffs_delta_conv_vs_ped",
                "effect_value": w["cliffs_delta_conv_vs_ped"], "n": w["n"],
                "significant_in_predicted_direction": w["significant_in_predicted_direction"],
                "verdict": c["verdict"] if window == "matched" else "",
                "changed_vs_full": c["changed_under_matched_budget"] if window == "matched" else "",
            })
    cells = report.get("j2_leaky_cell_sizes_by_condition", {})
    for window, j2, wkey in (("full", report["j2_full_window"], "full_window"),
                             ("matched", report["j2_matched_budget"], "matched_budget")):
        if "leak_to_helpfulness" not in j2:
            continue
        wc = cells.get(wkey, {})
        for leg in ("leak_to_helpfulness", "leak_to_next_independence"):
            L = j2[leg]
            mixed = L.get("mixed_available")
            lk, nl = L.get("leaky_mean"), L.get("nonleaky_mean")
            n_str = f"{L['n_leaky']}leaky/{L['n_nonleaky']}nonleaky"
            if wc:
                n_str += f" (leaky conv{wc['conv']['leaky']}/ped{wc['ped']['leaky']})"
            rows.append({
                "block": "j2", "metric": leg, "window": window,
                "group_a": "leaky_turns", "a_value": lk,
                "group_b": "nonleaky_turns", "b_value": nl,
                "diff_a_minus_b": (lk - nl) if (lk is not None and nl is not None) else "",
                "ci95_lo": (L["mixed_ci95"][0] if mixed and L.get("mixed_ci95") else ""),
                "ci95_hi": (L["mixed_ci95"][1] if mixed and L.get("mixed_ci95") else ""),
                "p_two_sided": L["mixed_p"] if mixed else L["cluster_p"],
                "effect_name": "mixed_coef" if mixed else "cluster_within_rep_effect",
                "effect_value": L["mixed_coef"] if mixed else L["cluster_within_rep_effect"],
                "n": n_str,
                "significant_in_predicted_direction": L["operative_significant_in_predicted_direction"],
                "verdict": "", "changed_vs_full": "",
            })
    return rows


def turn_csv_rows(report: dict) -> list[dict]:
    """Realized in-window visible tutor turns + §9.5 totals per conversation (conv vs ped),
    plus the paired ped-minus-conv turn-count gap."""
    rc = report["realized_counts"]
    rows = []
    for metric in ("inwindow_visible_tutor_turns", "model_calls", "tutor_tokens", "total_tokens"):
        for cond in CONDITIONS:
            s = rc["per_condition"][cond][metric]
            rows.append({"metric": metric, "condition": cond, "mean": s["mean"],
                         "median": s["median"], "ci95_lo": s["ci95"][0], "ci95_hi": s["ci95"][1],
                         "n": s["n"]})
    g = rc["turn_count_gap_ped_minus_conv"]
    rows.append({"metric": "inwindow_visible_tutor_turns_gap", "condition": "ped_minus_conv",
                 "mean": g["mean_diff"], "median": g["median_diff"],
                 "ci95_lo": g["ci95"][0], "ci95_hi": g["ci95"][1], "n": g["n_pairs"]})
    return rows


def _write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_final_csvs(report: dict, results_root: Path) -> list[Path]:
    """Write the version-controlled `*.final.csv` tables to the top-level results/ dir."""
    results_root.mkdir(parents=True, exist_ok=True)
    p1 = results_root / "matched_budget.final.csv"
    p2 = results_root / "matched_budget_turns.final.csv"
    _write_csv(p1, _MARGINAL_COLS, marginal_csv_rows(report))
    _write_csv(p2, _TURN_COLS, turn_csv_rows(report))
    return [p1, p2]


# ---------------------------------------------------------------- console
def _line(name, c):
    fw, mb = c["full_window"], c["matched_budget"]
    def fmt(r):
        star = "SIG" if r["significant_in_predicted_direction"] else "n.s."
        return (f"conv {r['conv_mean']:.3f} vs ped {r['ped_mean']:.3f} | "
                f"diff {r['mean_diff_conv_minus_ped']:+.3f} "
                f"CI{tuple(round(x, 3) for x in r['diff_ci95'])} | "
                f"p={R._fmt_p(r['p_two_sided'])} | δ {r['cliffs_delta_conv_vs_ped']:+.2f} | {star}")
    print(f"  {name}")
    print(f"     full-window  : {fmt(fw)}")
    print(f"     matched-budget: {fmt(mb)}")
    print(f"     -> {c['verdict']}{'  [FLAGGED: changed]' if c['changed_under_matched_budget'] else ''}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir", help="a compute_metrics output dir (per_*.csv + inference.json)")
    args = ap.parse_args()
    d = Path(args.results_dir)
    if not d.is_absolute():
        d = REPO_ROOT / d

    report = run(d)
    (d / "matched_budget.json").write_text(json.dumps(report, indent=2, default=str))
    finals = write_final_csvs(report, REPO_ROOT / "results")

    rc = report["realized_counts"]
    print("\n=== realized in-window visible tutor turns (conv vs ped; conversation-level) ===")
    for cond in CONDITIONS:
        s = rc["per_condition"][cond]["inwindow_visible_tutor_turns"]
        c = rc["per_condition"][cond]
        print(f"  {cond:4} mean {s['mean']:.2f} median {s['median']:.1f} "
              f"CI{tuple(round(x, 2) for x in s['ci95'])} (n={s['n']}) | "
              f"calls {c['model_calls']['mean']:.0f} tutor_tok {c['tutor_tokens']['mean']:.0f}")
    g = rc["turn_count_gap_ped_minus_conv"]
    print(f"  gap (ped-conv): mean {g['mean_diff']:+.2f} median {g['median_diff']:+.1f} "
          f"CI{tuple(round(x, 2) for x in g['ci95'])} | ped>conv in {g['n_ped_gt_conv']}/{g['n_pairs']} replicates")
    k0 = report["k0_dropped_cells"]
    if k0["n_cells"]:
        cells = ", ".join(f"r{c['replicate_id']}/{c['problem_id']}" for c in k0["cells"])
        print(f"  K=0 dropped cells (one side had 0 in-window tutor turns; dropped for BOTH): "
              f"{k0['n_cells']} [{cells}]")

    print("\n=== marginals: full window vs matched visible-turn budget "
          "(same §10 paired Wilcoxon, n=10) ===")
    _line("P1 leakage      [predicted conv>ped]", report["marginals_full_vs_matched"]["P1_leakage"])
    _line("P2 helpfulness  [LIVE TEST conv>ped]", report["marginals_full_vs_matched"]["P2_helpfulness"])
    _line("P3 independence [predicted ped>conv]", report["marginals_full_vs_matched"]["P3_independence"])

    print("\n=== J2 coupling under the matched budget (SECONDARY robustness) ===")
    j2 = report["j2_matched_budget"]
    if "leak_to_helpfulness" in j2:
        for leg, lab in (("leak_to_helpfulness", "leak->helpfulness   "),
                         ("leak_to_next_independence", "leak->next-indep    ")):
            L = j2[leg]
            print(f"  {lab} cells leaky={L['n_leaky']} nonleaky={L['n_nonleaky']} | "
                  f"leaky {L['leaky_mean']} vs nonleaky {L['nonleaky_mean']} | "
                  f"cluster eff {L['cluster_within_rep_effect']:+.3f} p={R._fmt_p(L['cluster_p'])} "
                  f"(n_rep={L['cluster_n_rep']})"
                  + (f" | mixed coef {L['mixed_coef']:+.3f} p={R._fmt_p(L['mixed_p'])}"
                     if L["mixed_available"] else " | mixed n/a"))
        cells = report["j2_leaky_cell_sizes_by_condition"]
        mc, fc = cells["matched_budget"], cells["full_window"]
        print(f"  leaky cells by condition: matched conv {mc['conv']['leaky']} / ped {mc['ped']['leaky']} "
              f"(full window conv {fc['conv']['leaky']} / ped {fc['ped']['leaky']}); pooled "
              f"{mc['pooled']['leaky']} leaky / {mc['pooled']['nonleaky']} non-leaky.")
        if cells["ped_leaky_underpowered_under_matched_budget"]:
            print(f"  NOTE: the ped-leaky cell is SMALL under truncation (ped_leaky={mc['ped']['leaky']} "
                  f"< {cells['ped_leaky_min_for_adequate_power']}). The frozen J2 pools conv+ped, so the "
                  "pooled coupling stands, but the WITHIN-ped leakage evidence is underpowered; reported "
                  "descriptively, J2 is NOT re-spec'd (§10 step 4).")

    print("\n=== cost-normalized sensitivity (per 1k tutor tokens; the OTHER §10 view) ===")
    for col, r in report["cost_normalized_per_1k_tutor_tok"].items():
        if "note" in r:
            continue
        print(f"  {col:34} diff {r['mean_diff_conv_minus_ped']:+.3f} p={R._fmt_p(r['p_two_sided'])} | "
              f"{'SIG' if r['significant_in_predicted_direction'] else 'n.s.'} "
              f"| flips_vs_raw={r['flips_under_normalization']}")

    print("\n=== §10 FLAG ===")
    if report["flagged_marginals"]:
        print(f"  flagged (direction/significance changed under matched budget): "
              f"{report['flagged_marginals']}")
    else:
        print("  no marginal changes direction or significance under the matched visible-turn budget.")

    prov = report["provenance"]
    print(f"\nprovenance: freeze {str(prov['freeze_commit'])[:12]} | analysis HEAD "
          f"{str(prov['analysis_commit'])[:12]}{' (dirty)' if prov['analysis_commit_dirty'] else ''} | "
          f"{prov['n_run_ids']} run ids | scipy {prov['scipy']} / statsmodels {prov['statsmodels']}")
    print(f"wrote {d}/matched_budget.json")
    for p in finals:
        print(f"wrote {p}  (version-controlled)")


if __name__ == "__main__":
    main()
