"""Compute the post-hoc metrics for one or more stored runs (paper-plan.md §9).

Reads only logs/<run_id>/calls.jsonl + domain/algebra/problems.yaml, and writes
tidy tables to results/:

  per_turn.csv        one row per TRAINING tutor turn (J2 input; helpfulness reserved)
  per_session.csv     one row per session (leakage, independence, accuracy, cost)
  per_replicate.csv   one row per (condition, replicate_id) -- the unit of §10's primary tests
  metrics_summary.json  the same, plus a non-inferential J1 paired preview
  independence_verify.json   (only with --verify-independence) the LLM-verify pass

The inferential tests (Wilcoxon, Cliff's delta, mixed-effects) are Week 3 (§10) and
are NOT run here; the J1 preview is descriptive only (paired conv-ped differences,
no p-values).

Usage:
  # offline, regex-only independence (no API key needed):
  python analysis/compute_metrics.py logs/conv-* logs/ped-* logs/cold-*

  # add the independence LLM-verification pass (judge = Opus; needs ANTHROPIC_API_KEY):
  python analysis/compute_metrics.py logs/ped-<run_id> --verify-independence
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import metrics as M       # noqa: E402
from analysis import divergence as D     # noqa: E402


def _repo_path(p: str) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else (REPO_ROOT / pp)


def _session_base(calls: list[dict]) -> str:
    """The single cross-model tutor-base tag stamped on a run's calls, or 'primary' if
    untagged. A run dir must be single-base; mixed base tags in one dir are corruption
    and refused (the runner stamps one base per run)."""
    found = {(c.get("tags") or {}).get("base") for c in calls}
    found.discard(None)
    if len(found) > 1:
        raise SystemExit(f"corrupt run dir: multiple base tags in one session: {sorted(found)}")
    return found.pop() if found else "primary"


def _session_freeze_head(run_dir: Path) -> str | None:
    """The freeze HEAD the run was collected at (confirmatory_meta.json freeze.head), or
    None if absent (e.g. a non-confirmatory run). Stamped into metrics_summary so inference
    can verify the --freeze-tag it is told actually matches where the runs were collected."""
    try:
        m = json.loads((run_dir / "confirmatory_meta.json").read_text())
    except (ValueError, OSError):
        return None
    return (m.get("freeze") or {}).get("head")


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _j1_paired_preview(per_replicate: list[dict]) -> list[dict]:
    """DESCRIPTIVE ONLY (no inference; §10 J1 is Week 3). For each replicate id with
    both a conv and a ped row, the paired conv-ped differences in the J1 measures.
    The predicted directions are helpfulness>0, leakage>0, independence<0."""
    by_rid: dict[str, dict[str, dict]] = {}
    for r in per_replicate:
        by_rid.setdefault(r["replicate_id"], {})[r["condition"]] = r
    out = []
    for rid, conds in sorted(by_rid.items()):
        if "conv" not in conds or "ped" not in conds:
            continue
        c, p = conds["conv"], conds["ped"]

        def diff(k):
            a, b = c.get(k), p.get(k)
            return (a - b) if (a is not None and b is not None) else None
        out.append({
            "replicate_id": rid,
            "leakage_conv_minus_ped": diff("leakage_rate"),
            "independence_conv_minus_ped": diff("independence_ratio"),
            "helpfulness_conv_minus_ped": diff("helpfulness_mean"),  # None until Step 6
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+", help="one or more logs/<run_id>/ dirs")
    ap.add_argument("--domain", default="domain/algebra/problems.yaml")
    ap.add_argument("--out", default="results", help="output dir (default: results/)")
    ap.add_argument("--verify-independence", action="store_true",
                    help="run the independence LLM-verification pass (judge=Opus; "
                         "needs ANTHROPIC_API_KEY). Off by default (regex-only).")
    ap.add_argument("--models", default="configs/models.yaml",
                    help="models config for the judge "
                         "(with --verify-independence / --judge-helpfulness)")
    ap.add_argument("--seed", type=int, default=0, help="seed for judge calls")
    ap.add_argument("--judge-helpfulness", action="store_true",
                    help="run the perceived-helpfulness judge pass (paper-plan §9.4; "
                         "judge=Opus; needs the judge API key unless --judge-backend "
                         "mock). Fills the reserved helpfulness / helpfulness_mean "
                         "columns and writes results/helpfulness_detail.json. Off by "
                         "default.")
    ap.add_argument("--judge-pedagogy", action="store_true",
                    help="run the pedagogical-quality judge pass (EXTENSION; "
                         "supplement/judge_pedagogy_rubric.md; judge=Opus, same as the "
                         "helpfulness judge; needs the judge API key unless "
                         "--judge-backend mock). Fills the reserved pedagogy / "
                         "pedagogy_mean columns and writes results/pedagogy_detail.json. "
                         "With --judge-helpfulness also set, writes the three-evaluator "
                         "results/divergence_detail.json. Off by default.")
    ap.add_argument("--judge-backend", default="live", choices=("live", "mock"),
                    help="backend for the helpfulness judge: 'live' (real judge; needs "
                         "the key) or 'mock' (offline plumbing test, no key). Default live.")
    ap.add_argument("--judge-reps", type=int, default=3,
                    help="judge repetitions per turn (paper-plan §9.4 = 3).")
    ap.add_argument("--offline-cache-only", action="store_true",
                    help="with --judge-helpfulness and/or --judge-pedagogy, reuse a "
                         "complete live-score cache without an API key or network access. "
                         "Any cache miss aborts; no synthetic or live score is substituted.")
    ap.add_argument("--full-window", action="store_true",
                    help="disclosure/sensitivity view: compute leakage/independence/helpfulness "
                         "over the FULL transcript instead of the frozen answer-phase window "
                         "(metric-amendment-2026-06-19.md). Default off (windowed).")
    ap.add_argument("--include-partial", action="store_true",
                    help="also include runs that are NOT full continuous-protocol "
                         "sessions (e.g. single-problem run.py / smoke runs). Off by "
                         "default so a broad glob can't pollute the per-replicate table.")
    args = ap.parse_args()
    if args.offline_cache_only and not (args.judge_helpfulness or args.judge_pedagogy):
        ap.error("--offline-cache-only requires --judge-helpfulness and/or --judge-pedagogy")
    if args.offline_cache_only and args.judge_backend != "live":
        ap.error("--offline-cache-only reuses the released live-score caches; "
                 "--judge-backend must remain 'live'")
    if args.offline_cache_only and args.verify_independence:
        ap.error("--offline-cache-only does not cover the optional independence LLM pass")

    out_dir = _repo_path(args.out)
    pbi = M.problem_index(args.domain)

    sessions, skipped, bases, freeze_heads = [], [], set(), set()
    for d in args.run_dirs:
        rd = Path(d)
        if not (rd / "calls.jsonl").exists():
            print(f"  skip {d}: no calls.jsonl")
            continue
        calls = M.load_calls(rd)
        if not args.include_partial and not M.is_full_protocol(calls):
            skipped.append(d)
            continue
        bases.add(_session_base(calls))
        fh = _session_freeze_head(rd)
        if fh:
            freeze_heads.add(fh)
        sessions.append(M.analyze_session(rd, pbi, answer_phase=not args.full_window))
    if skipped:
        print(f"  skipped {len(skipped)} non-full-protocol run(s) "
              f"(single-problem / smoke; use --include-partial to keep):")
        for d in skipped:
            print(f"      {d}")
    if not sessions:
        raise SystemExit("no full-protocol sessions found "
                         "(pass continuous-protocol run dirs, or --include-partial)")
    # Cross-model mixing guard: each tutor base is analyzed SEPARATELY and never pooled
    # (paper-plan §12). Refuse a run that spans more than one base -- a broad glob like
    # logs/conf-* would otherwise silently average primary + GPT + Gemini cells that
    # share replicate ids before inference. This is a guardrail, not operator discipline.
    if len(bases) > 1:
        raise SystemExit(
            f"REFUSING to pool multiple tutor bases in one analysis run: {sorted(bases)}. "
            "Each base is analyzed separately (paper-plan §12). Re-run compute_metrics once "
            "per base, each with that base's run dirs and a per-base --out dir "
            "(e.g. results/confirmatory_<base>).")
    base = next(iter(bases)) if bases else "primary"

    per_turn, per_session = [], []
    for sm in sessions:
        per_turn.extend(M.per_turn_rows(sm))
        per_session.append(M.per_session_row(sm))
    per_replicate = M.per_replicate_rows(sessions)

    _write_csv(out_dir / "per_turn.csv", per_turn)
    _write_csv(out_dir / "per_session.csv", per_session)
    _write_csv(out_dir / "per_replicate.csv", per_replicate)

    summary = {
        "n_sessions": len(sessions),
        "base": base,
        "freeze_heads": sorted(freeze_heads),
        "runs": [{"run_id": sm.run_id, "condition": sm.condition,
                  "replicate_id": sm.replicate_id, "seed": sm.seed} for sm in sessions],
        "per_session": per_session,
        "per_replicate": per_replicate,
        "j1_paired_preview_DESCRIPTIVE_ONLY": _j1_paired_preview(per_replicate),
        "note": "Inferential tests (Wilcoxon / Cliff's delta / mixed-effects) are "
                "Week 3 (paper-plan.md §10); helpfulness is filled in Step 6.",
    }

    # Write the regex-primary outputs FIRST so an optional verify pass that lacks an
    # API key cannot lose the main results.
    (out_dir / "metrics_summary.json").write_text(json.dumps(summary, indent=2, default=str))

    # ----- optional independence LLM-verification pass (live judge) -----
    if args.verify_independence:
        verify_out = _run_verify(sessions, args)
        summary["independence_verify"] = verify_out["aggregate"]
        (out_dir / "independence_verify.json").write_text(
            json.dumps(verify_out, indent=2, default=str))
        (out_dir / "metrics_summary.json").write_text(json.dumps(summary, indent=2, default=str))

    # ----- optional LLM-judge passes (helpfulness §9.4; pedagogy EXTENSION) -----
    # Like --verify-independence: the regex-primary tables are already on disk, so a
    # live pass that lacks the judge key fails without losing the main results. Each
    # judge runs separately and writes its own detail json; then the reserved columns
    # are filled IN PLACE in a SINGLE table rebuild (so running both judges keeps both
    # fills), and the three-evaluator divergence view is written when both are present.
    h_detail = p_detail = None
    h_by_turn = h_by_run = p_by_turn = p_by_run = None
    if args.judge_helpfulness:
        h_by_turn, h_by_run, h_detail = _run_judge_helpfulness(sessions, args, pbi, out_dir)
        (out_dir / "helpfulness_detail.json").write_text(json.dumps(h_detail, indent=2, default=str))
    if args.judge_pedagogy:
        p_by_turn, p_by_run, p_detail = _run_judge_pedagogy(sessions, args, pbi, out_dir)
        (out_dir / "pedagogy_detail.json").write_text(json.dumps(p_detail, indent=2, default=str))

    if args.judge_helpfulness or args.judge_pedagogy:
        h_by_turn, h_by_run = h_by_turn or {}, h_by_run or {}
        p_by_turn, p_by_run = p_by_turn or {}, p_by_run or {}
        per_turn, per_session = [], []
        for sm in sessions:
            per_turn.extend(M.per_turn_rows(sm, helpfulness=h_by_turn.get(sm.run_id),
                                            pedagogy=p_by_turn.get(sm.run_id)))
            per_session.append(M.per_session_row(sm, helpfulness_mean=h_by_run.get(sm.run_id),
                                                 pedagogy_mean=p_by_run.get(sm.run_id)))
        per_replicate = M.per_replicate_rows(sessions, helpfulness_by_run=h_by_run,
                                             pedagogy_by_run=p_by_run)
        _write_csv(out_dir / "per_turn.csv", per_turn)
        _write_csv(out_dir / "per_session.csv", per_session)
        _write_csv(out_dir / "per_replicate.csv", per_replicate)
        summary["per_session"] = per_session
        summary["per_replicate"] = per_replicate
        summary["j1_paired_preview_DESCRIPTIVE_ONLY"] = _j1_paired_preview(per_replicate)
        if h_detail is not None:
            summary["helpfulness"] = _judge_summary_block(h_detail, "helpfulness_mean")
        if p_detail is not None:
            summary["pedagogy"] = _judge_summary_block(p_detail, "pedagogy_mean")
        # The three-evaluator divergence view needs all three signals, so it is written
        # only when BOTH judges ran (the helpfulness leg comes from --judge-helpfulness);
        # matches supplement/judge_pedagogy_rubric.md + decisions-log 2026-06-27.
        div = None
        if args.judge_pedagogy and args.judge_helpfulness:
            div = D.divergence_view(per_turn, per_session)
            (out_dir / "divergence_detail.json").write_text(json.dumps(div, indent=2, default=str))
            summary["divergence"] = {
                "note": div["note"],
                "signals_present_per_turn": div["signals_present_per_turn"],
                "signals_present_per_session": div["signals_present_per_session"],
                "per_turn_agreement": div["per_turn_agreement"],
                "per_session_agreement": div["per_session_agreement"],
            }
        (out_dir / "metrics_summary.json").write_text(json.dumps(summary, indent=2, default=str))
        if h_detail is not None:
            _print_judge_table("perceived-helpfulness", h_detail, "helpfulness_mean")
        if p_detail is not None:
            _print_judge_table("pedagogical-quality", p_detail, "pedagogy_mean")
        if div is not None:
            _print_divergence(div)

    # ----- console summary -----
    print(f"\nwrote {out_dir}/  (per_turn={len(per_turn)} rows, "
          f"per_session={len(per_session)}, per_replicate={len(per_replicate)})")
    print(f"{'condition':9s} {'rep':>4s} {'leak':>6s} {'indep':>6s} "
          f"{'imm':>5s} {'del':>5s} {'tra':>5s} {'tutTok':>8s} {'calls':>6s}")
    for r in per_session:
        def f(x, pct=True):
            if x is None:
                return "   -"
            return f"{x:5.0%}" if pct else f"{x}"
        print(f"{r['condition']:9s} {str(r['replicate_id']):>4s} "
              f"{f(r['leakage_rate']):>6s} {f(r['independence_ratio']):>6s} "
              f"{f(r['acc_immediate']):>5s} {f(r['acc_delayed']):>5s} {f(r['acc_transfer']):>5s} "
              f"{r['tutor_tokens']:>8d} {r['n_model_calls']:>6d}")
    print("\nInferential tests are Week 3 (§10); J1 preview in metrics_summary.json is "
          "descriptive only. helpfulness columns are reserved for Step 6.")


def _run_verify(sessions, args) -> dict:
    """Run the independence LLM-verification pass with a live Opus judge. Judge
    calls go to their own logs/<indepverify-*>/ dir (post-hoc measurement, kept out
    of the experiment's calls.jsonl and out of the cost accounting)."""
    import os

    from agents.config import load_models_config
    from agents.logging_utils import RunLogger, new_run_id
    from agents.model_client import ModelClient

    models_cfg = load_models_config(args.models)
    # Fail fast and helpfully if the judge's API key is absent (e.g. offline/CI runs).
    judge_spec = models_cfg["roles"]["judge"]
    provider = judge_spec.get("provider") or models_cfg.get("provider") or "anthropic"
    key_env = (models_cfg.get("providers", {}).get(provider, {}).get("api_key_env")
               or ("ANTHROPIC_API_KEY" if provider == "anthropic" else ""))
    if key_env and not os.environ.get(key_env):
        raise SystemExit(
            f"--verify-independence needs the judge key {key_env} (provider {provider}, "
            f"model {judge_spec.get('model')}). The regex-primary metric is already "
            f"written to results/; run the verify pass locally where the key is set:\n"
            f"  {key_env}=... python analysis/compute_metrics.py <run_dirs> --verify-independence")

    logger = RunLogger(new_run_id(prefix="indepverify"))
    client = ModelClient(models_cfg=models_cfg, backend="live", logger=logger)
    judge_fn = M.make_judge_fn(client, seed=args.seed)

    per_run, all_rows = [], []
    tot_judged = tot_dis = 0
    for sm in sessions:
        if not sm.indep_items:
            continue
        v = M.verify_independence(sm.indep_items, judge_fn)
        tot_judged += v.n_judged
        tot_dis += v.n_disagree
        all_rows.extend({**r, "run_id": sm.run_id, "condition": sm.condition} for r in v.rows)
        per_run.append({"run_id": sm.run_id, "condition": sm.condition,
                        "n_total": v.n_total, "n_judged": v.n_judged,
                        "n_disagree": v.n_disagree, "agreement_rate": v.agreement_rate,
                        "disagreements": v.disagreements})
    agg = {"n_judged": tot_judged, "n_disagree": tot_dis,
           "agreement_rate": ((tot_judged - tot_dis) / tot_judged) if tot_judged else None,
           "judge_log": f"logs/{logger.run_id}/"}
    print(f"\nindependence LLM-verify: agreement={agg['agreement_rate']} "
          f"({tot_judged - tot_dis}/{tot_judged}); regex is authoritative, "
          f"disagreements default to regex and are logged.")
    return {"aggregate": agg, "per_run": per_run, "rows": all_rows}


def _judge_key_env(models_cfg) -> tuple[str, str, dict]:
    """(provider, key_env, judge_spec) for the judge role, mirroring _run_verify."""
    judge_spec = models_cfg["roles"]["judge"]
    provider = judge_spec.get("provider") or models_cfg.get("provider") or "anthropic"
    key_env = (models_cfg.get("providers", {}).get(provider, {}).get("api_key_env")
               or ("ANTHROPIC_API_KEY" if provider == "anthropic" else ""))
    return provider, key_env, judge_spec


def _valid_cache_entry(v) -> bool:
    """A reusable per-rep cache entry is {'scores': {...}} carrying exactly the
    invariant the judges write: parse_judge_scores/parse_pedagogy_scores only
    ever produce dicts whose values are ints 1..5 or None, with a non-None
    'overall' (the per-turn metric; a rep without it returns None and is never
    cached). Enforcing the full semantic invariant -- not just the dict shape --
    means a junk payload (scores={}, overall=None/'bad'/9) can never become a
    silent cache HIT that suppresses re-judging while aggregate_reps quietly
    drops the rep. Sub-fields may legitimately be None (only 'overall' is
    required by the parsers), so no exact field set is imposed: a missing and a
    None sub-score aggregate identically. Anything invalid is dropped and
    re-judged."""
    def ok(x) -> bool:
        return isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 5

    if not isinstance(v, dict) or not isinstance(v.get("scores"), dict):
        return False
    scores = v["scores"]
    return ok(scores.get("overall")) and all(x is None or ok(x) for x in scores.values())


def _load_judge_cache(cache_path: Path, stamp: dict) -> dict:
    """Load the reusable per-rep entries from <out>/*_cache.json for this stamp.

    The same schema boundary as _persist_judge_cache, enforced BEFORE any paid
    call: the blob must be a dict, its judge stamp must match, entries must be a
    dict, and each entry must pass _valid_cache_entry. Anything malformed is
    ignored exactly like a corrupt cache (it is repaired by the next flush) --
    never trusted into judge_session where a wrong shape would abort the pass
    after money was spent.
    """
    try:
        blob = json.loads(cache_path.read_text())
    except Exception:  # noqa: BLE001 - an absent or corrupt cache is just ignored
        return {}
    if not isinstance(blob, dict) or blob.get("judge") != stamp:
        return {}
    entries = blob.get("entries")
    if not isinstance(entries, dict):
        return {}
    return {k: v for k, v in entries.items() if _valid_cache_entry(v)}


def _persist_judge_cache(cache_path: Path, stamp: dict, cache: dict,
                         replace_foreign: bool = False) -> None:
    """Atomically flush the per-rep judge cache to disk (crash-resumability).

    Called after EVERY session (and again in a finally), not once per pass, so a
    mid-pass death — a 429 storm outlasting the backoff, network loss, credit
    exhaustion (QuotaExhausted), Ctrl-C, SIGKILL — forfeits at most the in-flight
    session's paid calls; a re-run of the same command resumes from the last flush.
    Persistence timing only: stamp, keys, and entry values are byte-identical to
    what the single pre-fix end-of-pass write produced.

    The read-merge-write-replace below is ONE critical section under an exclusive
    flock on tmp.lock.<name> (created empty next to the cache and left behind;
    both transient names keep the *_cache.json suffix so the results/*/ gitignore
    rules cover them). Flushes from concurrent writers on the same out dir are
    therefore strictly serialized, and each flush re-decides against the file it
    actually replaces:
      * SAME-stamp on disk -> its entries are merged into a FILE-ONLY copy of
        `cache` before writing, so every replace is a superset of the file it
        replaces -- no writer can discard entries another process already paid
        for. The live in-memory `cache` is never mutated here: this run's scored
        rows / detail / CSVs stay exactly what THIS process judged, and the
        on-disk union only feeds future runs at startup (a single-process run
        only ever re-reads its own last snapshot, so the merge is a no-op). For
        a key scored by both writers the file keeps this process's rep -- either
        is a legitimate sample from the same instrument (reps are stochastic by
        design).
      * FOREIGN-stamp on disk -> the flush is SKIPPED unless replace_foreign (the
        completed-pass write): a partial pass may never clobber another
        instrument's cache no matter when that cache appeared; only a completed
        pass owns the file, exactly like the pre-fix end-of-pass write.
      * absent, corrupt, or malformed (valid JSON, wrong shape) on disk ->
        nothing recoverable; write freely, never raise mid-pass.
    The pid-unique tmp + os.replace keeps a death mid-write from ever leaving a
    truncated cache (the loader silently discards corrupt files, which would
    re-pay the whole pass).
    """
    import fcntl
    import os

    lock_path = cache_path.with_name("tmp.lock." + cache_path.name)
    with open(lock_path, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            existing = json.loads(cache_path.read_text())
        except Exception:  # noqa: BLE001 - absent or corrupt: nothing recoverable
            existing = None
        if not isinstance(existing, dict) or not isinstance(existing.get("entries"), dict):
            existing = None  # malformed shape: equally nothing recoverable
        merged = dict(cache)
        if existing is not None:
            if existing.get("judge") == stamp:
                for k, v in existing["entries"].items():
                    if _valid_cache_entry(v):  # same boundary as _load_judge_cache
                        merged.setdefault(k, v)
            elif not replace_foreign:
                return  # lock released by the with-block
        tmp = cache_path.with_name(f"tmp.{os.getpid()}.{cache_path.name}")
        tmp.write_text(json.dumps({"judge": stamp, "entries": merged},
                                  indent=2, default=str))
        os.replace(tmp, cache_path)


def _run_judge_helpfulness(sessions, args, pbi, out_dir) -> tuple:
    """Run the perceived-helpfulness judge pass (paper-plan §9.4). Judge calls go to
    their own logs/helpfuljudge-*/ dir (post-hoc measurement, kept out of the
    experiment's calls.jsonl and the §9.5 cost accounting -- exactly like the
    independence verify). Returns (by_turn, by_run, detail):
      by_turn  {run_id: {(problem_id, turn_index): per-turn helpfulness mean}}
      by_run   {run_id: per-session helpfulness_mean}
      detail   full per-turn rows (reps + variance) for results/helpfulness_detail.json
    Per-rep scores are cached in <out>/helpfulness_cache.json keyed by
    (run_id, problem_id, turn_index, rep) so re-runs don't re-pay; the cache is
    namespaced by the judge (backend/model/temperature) and ignored if that changes."""
    import os

    from agents.config import load_models_config
    from agents.logging_utils import RunLogger, new_run_id
    from agents.model_client import ModelClient
    from analysis import judge as J

    models_cfg = load_models_config(args.models)
    provider, key_env, judge_spec = _judge_key_env(models_cfg)

    # The judge is part of "only the tutor changes": a reportable (live) helpfulness pass
    # must use the SAME judge as the frozen primary, or P2 / the helpfulness leg of J2 are
    # not comparable across bases. Enforce it here (mock is the offline plumbing path, exempt).
    if args.judge_backend == "live":
        primary_judge = load_models_config("configs/models.yaml")["roles"]["judge"]
        if judge_spec != primary_judge:
            raise SystemExit(
                "--judge-helpfulness (live, reportable): the judge role differs from the "
                "frozen primary judge (configs/models.yaml). The judge must be IDENTICAL "
                "across bases (paper-plan §9.4/§12).\n  this run's judge: "
                f"{judge_spec}\n  primary judge:   {primary_judge}")
        if args.judge_reps != 3:
            raise SystemExit("--judge-helpfulness (live): judge reps must be 3 "
                             f"(paper-plan §9.4); got {args.judge_reps}.")

    stamp = {"backend": args.judge_backend, "model": judge_spec.get("model"),
             "temperature": judge_spec.get("temperature")}
    cache_path = out_dir / "helpfulness_cache.json"
    cache = _load_judge_cache(cache_path, stamp)

    # Live judge needs its key unless this is the strict released-cache path. The
    # latter supplies a tripwire in place of a client: a missing score must abort,
    # never become a network call or a synthetic value.
    if (args.judge_backend == "live" and not args.offline_cache_only
            and key_env and not os.environ.get(key_env)):
        raise SystemExit(
            f"--judge-helpfulness needs the judge key {key_env} (provider {provider}, "
            f"model {judge_spec.get('model')}). The regex-primary metrics are already "
            f"written to results/; run the judge pass locally where the key is set:\n"
            f"  {key_env}=... python analysis/compute_metrics.py <run_dirs> --judge-helpfulness\n"
            f"or do an offline plumbing run with the mock judge (no key, synthetic "
            f"scores -- do NOT report):\n"
            f"  python analysis/compute_metrics.py <run_dirs> --judge-helpfulness --judge-backend mock")

    if args.offline_cache_only:
        if not cache:
            raise SystemExit(
                f"--offline-cache-only found no valid released scores in {cache_path}; "
                "copy the matching helpfulness_cache.json into --out first")

        def judge_fn(*_args, **_kwargs):
            raise RuntimeError(
                "offline helpfulness cache miss: refusing provider access or synthetic score")

        judge_log = "none (offline cache-only reconstruction)"
    else:
        logger = RunLogger(new_run_id(prefix="helpfuljudge"))
        client = ModelClient(models_cfg=models_cfg, backend=args.judge_backend, logger=logger)
        judge_fn = J.make_helpfulness_judge_fn(client, seed=args.seed)
        judge_log = f"logs/{logger.run_id}/"

    by_turn, by_run, runs = {}, {}, []
    try:
        for sm in sessions:
            turn_rows = J.judge_session(sm, pbi, judge_fn, reps=args.judge_reps, cache=cache)
            if cache and not args.offline_cache_only:
                _persist_judge_cache(cache_path, stamp, cache)
            if not turn_rows:
                continue  # e.g. cold (no tutor turns)
            by_turn[sm.run_id] = J.helpfulness_by_turn(turn_rows)
            by_run[sm.run_id] = J.session_helpfulness_mean(turn_rows)
            runs.append({"run_id": sm.run_id, "condition": sm.condition,
                         "replicate_id": sm.replicate_id,
                         "helpfulness_mean": by_run[sm.run_id],
                         "n_turns": len(turn_rows), "turns": turn_rows})
    finally:
        # judge_session mutates `cache` per rep, so even a crash part-way through a
        # session persists every rep already scored (the rows are rebuilt free on
        # re-run). The empty gate keeps a scoreless failure from creating a file;
        # the helper itself refuses to replace a foreign-stamp cache mid-run.
        if cache and not args.offline_cache_only:
            _persist_judge_cache(cache_path, stamp, cache)
    # A completed pass always owns the file -- the only write allowed to replace a
    # foreign-stamp cache, matching the pre-resumability single end-of-pass write.
    if not args.offline_cache_only:
        _persist_judge_cache(cache_path, stamp, cache, replace_foreign=True)
    detail = {"judge": stamp, "reps": args.judge_reps,
              "judge_log": judge_log,
              "score_source": ("released live-score cache" if args.offline_cache_only
                               else "judge calls"),
              "runs": runs}
    return by_turn, by_run, detail


def _run_judge_pedagogy(sessions, args, pbi, out_dir) -> tuple:
    """Run the pedagogical-quality judge pass (EXTENSION; supplement/judge_pedagogy_rubric.md).
    A near-exact mirror of _run_judge_helpfulness: same role='judge' Opus, the SAME
    same-judge / reps / key guards (the pedagogy judge must be the identical judge as the
    frozen helpfulness primary, or the divergence is not comparable across bases), judge
    calls written to their own logs/pedjudge-*/ dir (post-hoc; out of §9.5 cost), per-rep
    cache in <out>/pedagogy_cache.json namespaced by the judge stamp. Returns
    (by_turn, by_run, detail) with the pedagogy fields."""
    import os

    from agents.config import load_models_config
    from agents.logging_utils import RunLogger, new_run_id
    from agents.model_client import ModelClient
    from analysis import judge_pedagogy as JP

    models_cfg = load_models_config(args.models)
    provider, key_env, judge_spec = _judge_key_env(models_cfg)

    if args.judge_backend == "live":
        primary_judge = load_models_config("configs/models.yaml")["roles"]["judge"]
        if judge_spec != primary_judge:
            raise SystemExit(
                "--judge-pedagogy (live, reportable): the judge role differs from the "
                "frozen primary judge (configs/models.yaml). The judge must be IDENTICAL "
                "to the helpfulness judge across bases (paper-plan §9.4/§12; the divergence "
                "view compares the two).\n  this run's judge: "
                f"{judge_spec}\n  primary judge:   {primary_judge}")
        if args.judge_reps != 3:
            raise SystemExit("--judge-pedagogy (live): judge reps must be 3 "
                             f"(matches the helpfulness judge); got {args.judge_reps}.")

    stamp = {"backend": args.judge_backend, "model": judge_spec.get("model"),
             "temperature": judge_spec.get("temperature")}
    cache_path = out_dir / "pedagogy_cache.json"
    cache = _load_judge_cache(cache_path, stamp)

    if (args.judge_backend == "live" and not args.offline_cache_only
            and key_env and not os.environ.get(key_env)):
        raise SystemExit(
            f"--judge-pedagogy needs the judge key {key_env} (provider {provider}, "
            f"model {judge_spec.get('model')}). The regex-primary metrics are already "
            f"written to results/; run the judge pass locally where the key is set:\n"
            f"  {key_env}=... python analysis/compute_metrics.py <run_dirs> "
            f"--judge-helpfulness --judge-pedagogy\n"
            f"or do an offline plumbing run with the mock judge (no key, synthetic "
            f"scores -- do NOT report):\n"
            f"  python analysis/compute_metrics.py <run_dirs> --judge-helpfulness "
            f"--judge-pedagogy --judge-backend mock")

    if args.offline_cache_only:
        if not cache:
            raise SystemExit(
                f"--offline-cache-only found no valid released scores in {cache_path}; "
                "copy the matching pedagogy_cache.json into --out first")

        def judge_fn(*_args, **_kwargs):
            raise RuntimeError(
                "offline pedagogy cache miss: refusing provider access or synthetic score")

        judge_log = "none (offline cache-only reconstruction)"
    else:
        logger = RunLogger(new_run_id(prefix="pedjudge"))
        client = ModelClient(models_cfg=models_cfg, backend=args.judge_backend, logger=logger)
        judge_fn = JP.make_pedagogy_judge_fn(client, seed=args.seed)
        judge_log = f"logs/{logger.run_id}/"

    by_turn, by_run, runs = {}, {}, []
    try:
        for sm in sessions:
            turn_rows = JP.judge_pedagogy_session(sm, pbi, judge_fn, reps=args.judge_reps, cache=cache)
            if cache and not args.offline_cache_only:
                _persist_judge_cache(cache_path, stamp, cache)
            if not turn_rows:
                continue  # e.g. cold (no tutor turns)
            by_turn[sm.run_id] = JP.pedagogy_by_turn(turn_rows)
            by_run[sm.run_id] = JP.session_pedagogy_mean(turn_rows)
            runs.append({"run_id": sm.run_id, "condition": sm.condition,
                         "replicate_id": sm.replicate_id,
                         "pedagogy_mean": by_run[sm.run_id],
                         "n_turns": len(turn_rows), "turns": turn_rows})
    finally:
        # Mirrors _run_judge_helpfulness: persist reps scored before a mid-session
        # crash; scoreless failures create nothing, foreign-stamp caches are safe.
        if cache and not args.offline_cache_only:
            _persist_judge_cache(cache_path, stamp, cache)
    # A completed pass always owns the file (pre-resumability behavior).
    if not args.offline_cache_only:
        _persist_judge_cache(cache_path, stamp, cache, replace_foreign=True)
    detail = {"judge": stamp, "reps": args.judge_reps,
              "judge_log": judge_log,
              "score_source": ("released live-score cache" if args.offline_cache_only
                               else "judge calls"),
              "runs": runs}
    return by_turn, by_run, detail


def _judge_summary_block(detail: dict, mean_key: str) -> dict:
    """The compact per-run block recorded in metrics_summary.json for a judge pass."""
    return {
        "judge": detail["judge"], "reps": detail["reps"], "judge_log": detail["judge_log"],
        "per_run": [{"run_id": r["run_id"], "condition": r["condition"],
                     "replicate_id": r["replicate_id"],
                     mean_key: r[mean_key], "n_turns": r["n_turns"]}
                    for r in detail["runs"]],
    }


def _print_judge_table(label: str, detail: dict, mean_key: str) -> None:
    print(f"\n{label} (judge={detail['judge']['model']}, "
          f"reps={detail['reps']}, backend={detail['judge']['backend']}):")
    for r in detail["runs"]:
        m = r[mean_key]
        print(f"  {r['condition']:9s} rep={str(r['replicate_id']):>4s} "
              f"{mean_key}={m if m is None else round(m, 3)} "
              f"({r['n_turns']} training turns)")


def _print_divergence(div: dict) -> None:
    print("\nthree-evaluator divergence (DESCRIPTIVE; helpfulness vs pedagogy vs independence):")
    print(f"  signals present per turn: {div['signals_present_per_turn']}")
    for a in div["per_turn_agreement"]:
        pe, sp = a["pearson"], a["spearman"]
        print(f"  per-turn {a['pair']:>12s}: "
              f"pearson={pe if pe is None else round(pe, 3)} "
              f"spearman={sp if sp is None else round(sp, 3)} (n={a['n']})")
    top = div["top_turn_disagreements"][:8]
    if top:
        print("  turns where the three evaluators most disagree (standardized spread):")
        for r in top:
            zr = {k: (None if v is None else round(v, 2)) for k, v in r["z"].items()}
            print(f"    {r['condition']:5s} rep={str(r['replicate_id']):>4s} "
                  f"{r['problem_id']} t{r['turn_index']} "
                  f"spread={round(r['disagreement'], 2)} [{r['pattern']}] z={zr}")


if __name__ == "__main__":
    main()
