"""Run the NON-INFERENTIAL pilot (paper-plan.md §10): 1-2 replicates x
{cold, conv, ped} on the LIVE models, each session into its own logs/<run_id>/ dir,
so the judge + metrics can be read over a PAIRED conv/ped session for the M2 go/no-go
(paper-plan.md §11).

This is the live analog of tools/make_mock_logs.py and it changes NO harness runtime
behavior: it just drives protocol.full_session.run_full_session once per condition per
replicate, identically for both tutors (condition-neutral). Pilot output is
non-inferential -- no p-values, no stop/scale decision from it (paper-plan.md §10); it
exists for the M2 manipulation-check + cost gates only.

Scope / integrity:
  - It deliberately does NOT add condition/replicate_id call tags. That is R1's
    CONFIRMATORY runner (Step-6 brief "out of scope"; decisions-log 2026-06-18 Step 5).
    The metrics pipeline already infers condition from the tutor component and pairs by
    seed, so for the pilot the SEED is the replicate id: replicate r uses
    seed = base_seed + r for all three conditions, and analysis/compute_metrics.py pairs
    that replicate's conv and ped sessions by that seed.
  - The confirmatory 10x3 run is R1's runner (with explicit condition/replicate_id
    tags), NOT this script.

Needs the keys the chosen models config requires. For the default configs/models.yaml:
ANTHROPIC_API_KEY (tutor + judge) and OPENROUTER_API_KEY (student).

Usage:
  # one paired replicate, live:
  python experiments/run_pilot.py --replicates 1 --conditions cold,conv,ped
  # then read the paired conv/ped helpfulness + manipulation checks:
  python analysis/compute_metrics.py logs/cold-* logs/conv-* logs/ped-* \
      --out results/pilot --judge-helpfulness
  # offline plumbing rehearsal (synthetic; NOT a pilot result):
  python experiments/run_pilot.py --backend mock --replicates 1
See experiments/PILOT.md.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.config import load_models_config  # noqa: E402
from agents.logging_utils import RunLogger, new_run_id  # noqa: E402
from agents.model_client import ModelClient  # noqa: E402
from protocol.full_session import run_full_session  # noqa: E402
from protocol.session import load_problems  # noqa: E402


def _tutor_cls(cond: str):
    """Resolve the tutor class for a condition. Lazy import so the cold condition
    (no tutor) runs even where langgraph is unavailable; the tutors import langgraph."""
    if cond == "cold":
        return None
    if cond == "conv":
        from agents.conv_tutor import ConvTutor
        return ConvTutor
    if cond == "ped":
        from agents.ped_tutor import PedTutor
        return PedTutor
    raise SystemExit(f"unknown condition {cond!r} (expected cold|conv|ped)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replicates", type=int, default=1,
                    help="number of paired replicates (non-inferential pilot: 1-2).")
    ap.add_argument("--base-seed", type=int, default=0,
                    help="replicate r uses seed = base-seed + r (the pilot replicate id).")
    ap.add_argument("--conditions", default="cold,conv,ped")
    ap.add_argument("--domain", default="domain/algebra/problems.yaml")
    ap.add_argument("--models", default="configs/models.yaml")
    ap.add_argument("--backend", default="live", choices=("live", "mock"),
                    help="'live' (real models; needs the config's keys) or 'mock' "
                         "(offline plumbing rehearsal -- synthetic, NOT a result).")
    ap.add_argument("--max-train-turns", type=int, default=4)
    args = ap.parse_args()

    models_cfg = load_models_config(args.models)
    problems = load_problems(args.domain)
    conds = [c.strip() for c in args.conditions.split(",") if c.strip()]

    if args.backend == "mock":
        print("*** backend=mock: synthetic plumbing data, NOT a pilot result ***")
    print(f"pilot: {args.replicates} replicate(s) x {conds}  (models={args.models})")

    for r in range(args.replicates):
        seed = args.base_seed + r
        print(f"\n=== replicate {r}  (seed / replicate_id = {seed}) ===")
        for cond in conds:
            TutorCls = _tutor_cls(cond)
            run_id = new_run_id(prefix=cond)
            logger = RunLogger(run_id)
            client = ModelClient(models_cfg=models_cfg, backend=args.backend, logger=logger)
            tutor = TutorCls(client) if TutorCls else None
            res = run_full_session(problems, client, tutor=tutor, seed=seed,
                                   condition=cond, max_train_turns=args.max_train_turns)
            logger.write_json("full_session_result.json", asdict(res))
            print(f"  {cond:5s} -> logs/{run_id}/  items={len(res.items)} "
                  f"calls={logger._call_seq} total_tokens={res.total_tokens} "
                  f"tutor_calls={res.n_model_calls}")

    print("\nNext: pair the conv/ped sessions for each replicate with the judge + metrics:")
    print("  python analysis/compute_metrics.py logs/cold-* logs/conv-* logs/ped-* "
          "--out results/pilot --judge-helpfulness")
    print("Then check the M2 gates (experiments/PILOT.md, paper-plan.md §11).")


if __name__ == "__main__":
    main()
