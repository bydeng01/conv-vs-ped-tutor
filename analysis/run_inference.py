"""Run the Week-3 inferential analysis (paper-plan.md §10) over a compute_metrics output
dir. Consumes the conversation summaries that compute_metrics already wrote
(per_replicate.csv, per_session.csv, per_turn.csv with the judge's helpfulness filled);
writes inference.json and prints the J1 / J2 / accuracy / cost-normalized verdicts.

This is post-hoc and read-only over the frozen metrics — it implements the pre-registered
tests, tunes nothing, and reports P1-P3 / J1 / J2 regardless of outcome (§11).

Usage:
  # after: python analysis/compute_metrics.py logs/conf-s0-* --out results/confirmatory --judge-helpfulness
  python analysis/run_inference.py results/confirmatory
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import inferential as I  # noqa: E402


def _repo_rel(p: Path) -> str:
    """Repo-relative path string for provenance -- never an absolute or home path,
    so a regenerated inference.json can't leak a local username."""
    try:
        return str(p.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return p.name


def _scrub_paths(s: str) -> str:
    """Redact the user segment of any absolute home path in the serialized output
    (e.g. an env/import error that quotes a local install path), so a regenerated
    file never leaks a username. Only the '/Users/<name>' or '/home/<name>' segment
    is replaced; the rest of the diagnostic path is kept."""
    return re.sub(r'(/Users/|/home/)[^/\s"]+', r'\1<user>', s)


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.open()))


def _git(*args: str):
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def _provenance(per_session: list[dict], per_replicate: list[dict],
                freeze_tag: str = "confirmatory-freeze",
                freeze_commit: str | None = None, base: str = "primary") -> dict:
    """Stamp the contributing run ids, the pre-registration freeze commit, the
    analysis-code commit, the tutor base, and the stats-library versions onto every
    output (§10). `freeze_tag` defaults to the primary; a cross-model base passes its
    extension freeze tag so its results bind to the extension pre-registration, not the
    primary's. Only the provenance LABEL changes -- the inference is identical.
    `freeze_commit` is resolved + validated by the caller (fail-fast on an unresolvable
    tag); falls back to resolving here only if not supplied."""
    run_ids = sorted({r.get("run_id") for r in per_session if r.get("run_id")})
    import scipy  # noqa: PLC0415
    try:
        import statsmodels  # noqa: PLC0415
        sm_ver = statsmodels.__version__
    except Exception:  # noqa: BLE001
        sm_ver = None
    return {
        "freeze_tag": freeze_tag,
        "freeze_commit": freeze_commit if freeze_commit is not None else _git("rev-parse", freeze_tag),
        "base": base,
        "analysis_commit": _git("rev-parse", "HEAD"),
        "analysis_commit_dirty": bool(_git("status", "--porcelain")),
        "n_run_ids": len(run_ids),
        "run_ids": run_ids,
        "n_replicates_loaded": len({r.get("replicate_id") for r in per_replicate}),
        "scipy": scipy.__version__,
        "statsmodels": sm_ver,
    }


def _fmt_p(p):
    return "  n/a" if p is None or p != p else (f"{p:.4f}" if p >= 1e-4 else "<1e-4")


def _marginal_line(name, r):
    star = "SIG" if r["significant_in_predicted_direction"] else "n.s."
    return (f"  {name:16} conv {r['conv_mean']:.3f} vs ped {r['ped_mean']:.3f} | "
            f"diff {r['mean_diff_conv_minus_ped']:+.3f} CI{tuple(round(x,3) for x in r['diff_ci95'])} | "
            f"Wilcoxon p={_fmt_p(r['p_two_sided'])} | delta {r['cliffs_delta_conv_vs_ped']:+.2f} | "
            f"conv>ped {r['n_conv_gt_ped']}/{r['n']} | {star}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir", help="a compute_metrics output dir (per_*.csv inside)")
    ap.add_argument("--freeze-tag", default="confirmatory-freeze",
                    help="pre-registration freeze tag stamped in provenance. Default = "
                         "the primary. For a cross-model base, pass its extension freeze "
                         "tag (e.g. 'crossmodel-freeze') so the base's results bind to "
                         "the extension pre-registration, never the primary's.")
    ap.add_argument("--freeze-commit", default=None,
                    help="explicit frozen commit for a release artifact extracted without "
                         ".git metadata. In a git checkout, omit this and resolve --freeze-tag "
                         "normally. The supplied value must be a 40-character hex commit and "
                         "must match metrics_summary.json's collected freeze head.")
    args = ap.parse_args()
    d = Path(args.results_dir)
    if not d.is_absolute():
        d = REPO_ROOT / d

    # Fail fast if the freeze tag does not resolve to a real commit: provenance must
    # bind to an actual freeze, never silently write a null freeze_commit (a typo or a
    # not-yet-created `crossmodel-freeze` would otherwise look extension-bound but carry
    # no freeze evidence).
    if args.freeze_commit is not None:
        if not re.fullmatch(r"[0-9a-fA-F]{40}", args.freeze_commit):
            raise SystemExit("--freeze-commit must be a complete 40-character hexadecimal commit")
        freeze_commit = args.freeze_commit.lower()
        resolved_tag = _git("rev-parse", args.freeze_tag)
        if resolved_tag is not None and resolved_tag.lower() != freeze_commit:
            raise SystemExit(
                f"--freeze-commit {freeze_commit[:12]} disagrees with resolved "
                f"--freeze-tag {args.freeze_tag!r} ({resolved_tag[:12]})")
    else:
        freeze_commit = _git("rev-parse", args.freeze_tag)
    if freeze_commit is None:
        raise SystemExit(
            f"--freeze-tag {args.freeze_tag!r} does not resolve to a commit (git rev-parse "
            "failed). Create/point the freeze tag first, pass an existing tag, or in an "
            "extracted release artifact also pass its documented --freeze-commit; the "
            "inference provenance must bind to a real freeze commit.")

    # metrics_summary.json is MANDATORY: it carries the analyzed base, the contributing run
    # list, and the freeze head(s) the runs were collected at. Without it, run_inference
    # cannot tell a clean compute_metrics output from a hand-assembled / stale CSV dir that
    # could pool bases or carry the wrong freeze -- so refuse rather than default to primary.
    summ_path = d / "metrics_summary.json"
    if not summ_path.exists():
        raise SystemExit(
            f"no metrics_summary.json in {d}; run compute_metrics first. run_inference will "
            "not infer from CSVs alone (a hand-assembled dir could pool bases or carry the "
            "wrong freeze).")
    try:
        summ = json.loads(summ_path.read_text())
    except (ValueError, OSError) as e:
        raise SystemExit(f"unreadable metrics_summary.json in {d}: {e}")
    base = summ.get("base", "primary")

    # Wrong-provenance guards (not just null): a non-primary base must NOT be stamped with the
    # primary freeze, and the resolved freeze tag must match the freeze the runs were actually
    # collected at -- so forgetting --freeze-tag on a base result is refused, not mislabeled.
    if base != "primary" and args.freeze_tag == "confirmatory-freeze":
        raise SystemExit(
            f"results dir base={base!r} but --freeze-tag is the primary 'confirmatory-freeze'. "
            "Pass the extension freeze tag (e.g. 'crossmodel-freeze') so the base binds to its "
            "own pre-registration, not the primary's.")
    heads = [h for h in summ.get("freeze_heads", []) if h]
    if heads and not any(h == freeze_commit or h.startswith(freeze_commit)
                         or freeze_commit.startswith(h) for h in heads):
        raise SystemExit(
            f"--freeze-tag {args.freeze_tag!r} ({str(freeze_commit)[:12]}) does not match the "
            f"freeze head(s) the runs were collected at: {[str(h)[:12] for h in heads]}. "
            "Pass the freeze tag the runs were actually frozen and collected under.")

    per_replicate = _read_csv(d / "per_replicate.csv")
    per_session = _read_csv(d / "per_session.csv")
    per_turn = _read_csv(d / "per_turn.csv")
    if not per_replicate:
        raise SystemExit(f"no per_replicate.csv in {d} — run compute_metrics --judge-helpfulness first")
    # No smuggled-in rows: every per_session run must be one the summary recorded analyzing.
    summ_runs = {r.get("run_id") for r in summ.get("runs", [])}
    ps_runs = {r.get("run_id") for r in per_session if r.get("run_id")}
    if summ_runs and (ps_runs - summ_runs):
        raise SystemExit(
            f"per_session.csv has run_ids not in metrics_summary.json: {sorted(ps_runs - summ_runs)} "
            "(mismatched / hand-assembled results dir).")

    j1 = I.j1(per_replicate)
    j2 = I.j2(per_turn) if per_turn else {"note": "no per_turn rows"}
    acc = I.accuracy(per_replicate)
    cost = I.cost_normalized(per_session, j1) if per_session else {}

    j1["joint_J1"]["J2_supported"] = j2.get("J2_supported")
    verdict = I.verdict(j1, j2 if "leak_to_helpfulness" in j2 else None)
    report = {"results_dir": _repo_rel(d), "alpha": I.ALPHA,
              "provenance": _provenance(per_session, per_replicate, args.freeze_tag,
                                        freeze_commit, base),
              "verdict": verdict,
              "j1": j1, "j2": j2, "accuracy": acc, "cost_normalized": cost,
              "note": "Frozen §10 plan, run post-hoc. Two-sided Wilcoxon, paired by "
                      "replicate id (unit = conversation). J2 = crossed replicate+problem "
                      "mixed-effects models, with a conversation-clustered signed-rank as "
                      "a robustness check. Reported regardless of outcome (§11); nothing "
                      "tuned, dropped, or re-spec'd."}
    (d / "inference.json").write_text(_scrub_paths(json.dumps(report, indent=2, default=str)))

    # ----- console -----
    print(f"\n=== J1 — paired marginals (n={j1['P1_leakage']['n_replicates']} replicates, "
          f"two-sided Wilcoxon, alpha={I.ALPHA}) ===")
    print(_marginal_line("P1 leakage", j1["P1_leakage"]), "   [predicted conv>ped]")
    print(_marginal_line("P2 helpfulness", j1["P2_helpfulness"]), "   [LIVE TEST: conv>ped]")
    print(_marginal_line("P3 independence", j1["P3_independence"]), "   [predicted ped>conv]")
    jj = j1["joint_J1"]
    print(f"  -> J1 marginal supported: {jj['J1_marginal_supported']} "
          f"(P1 sep={jj['P1_separates']}, P3 sep={jj['P3_separates']}, "
          f"P2 sig conv>ped={jj['P2_significant_conv_gt_ped']})")

    if "J2_supported" in j2:
        op = "canonical crossed (replicate+problem) mixed-effects" if j2.get("mixed_effects_available") \
             else "conversation-clustered signed-rank (statsmodels unavailable)"
        print(f"\n=== J2 — per-turn coupling (operative test: {op}) ===")
        for leg, lab, pdir in (("leak_to_helpfulness", "leak -> helpfulness", "+"),
                               ("leak_to_next_independence", "leak -> next-turn independence", "-")):
            L = j2[leg]; cs = L["cluster_summary"]; dsc = L["descriptive_pooled"]; me = L["mixed_effects"]
            star = "SIG" if L["operative_significant_in_predicted_direction"] else "n.s."
            print(f"  {lab:32} [{L['operative_method']}, predicted '{pdir}'] {star}")
            if me.get("available") and "coef" in me:
                print(f"      mixed-effects:   coef {me['coef']:+.3f} "
                      f"CI{tuple(round(x, 3) for x in me['ci95'])} "
                      f"(p={_fmt_p(me['p'])}, converged={me['converged']})")
            else:
                print(f"      mixed-effects:   unavailable ({str(me.get('error','?'))[:55]})")
            print(f"      cluster-summary: within-replicate effect "
                  f"{cs['mean_within_replicate_effect']:+.3f} (n_rep={cs['n_replicates_used']}, "
                  f"p={_fmt_p(cs['p_two_sided'])})")
            print(f"      descriptive:     leaky {dsc['leaky_mean']} (n={dsc['n_leaky']}) "
                  f"vs non-leaky {dsc['nonleaky_mean']} (n={dsc['n_nonleaky']})")
        print(f"  -> J2 supported (both legs): {j2['J2_supported']}")
        for lim in j2.get("limitations", []):
            print(f"  LIMITATION: {lim}")
        if not j2.get("mixed_effects_available"):
            print("  NOTE: canonical §10 mixed-effects model did not run (statsmodels/scipy "
                  "conflict). Operative result is the conversation-clustered signed-rank; "
                  "`pip install -U \"statsmodels>=0.14.5\"` to also run the spec'd mixed model.")

    print("\n=== accuracy (secondary; descriptive, no test) ===")
    for cond in ("cold", "conv", "ped"):
        cells = " ".join(f"{c.split('_')[1][:3]}={acc[cond][c]['mean']:.2f}" for c in I.ROLE_ACCURACY
                         if acc[cond][c]['mean'] is not None)
        print(f"  {cond:5} {cells}")

    if cost:
        print("\n=== cost-normalized sensitivity (per 1k tutor tokens) ===")
        for col, r in cost.items():
            if "note" in r:
                continue
            print(f"  {col:34} diff {r['mean_diff_conv_minus_ped']:+.3f} "
                  f"p={_fmt_p(r['p_two_sided'])} | {'SIG' if r['significant_in_predicted_direction'] else 'n.s.'}"
                  f" | flips_vs_raw={r['flips_under_normalization']}")

    print("\n=== §11 VERDICT (reported regardless of outcome; no file-drawer) ===")
    for v in verdict:
        if v["p"] is None:
            pstr = ""
        elif isinstance(v["p"], str):
            pstr = f" | {v['p']}"
        else:
            pstr = f" | p={_fmt_p(v['p'])}"
        print(f"  {v['verdict'].upper():14} {v['claim']}")
        print(f"                 {v['effect']} | {v['ci']}{pstr}")

    prov = report["provenance"]
    print(f"\n=== provenance ===")
    print(f"  freeze {prov['freeze_tag']}={str(prov['freeze_commit'])[:12]} | "
          f"analysis HEAD={str(prov['analysis_commit'])[:12]}"
          f"{' (dirty tree)' if prov['analysis_commit_dirty'] else ''} | "
          f"{prov['n_run_ids']} run ids | statsmodels {prov['statsmodels']} / scipy {prov['scipy']}")

    print(f"\nwrote {d}/inference.json")
    print("Inferential result — reported regardless of outcome (§11); nothing tuned. "
          "J2 (per-turn coupling) is the headline; J1/P2 are reported honestly whatever they show.")


if __name__ == "__main__":
    main()
