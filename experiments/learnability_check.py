"""Learnability gate (decision point before building PedTutor).

Runs the continuous protocol (protocol/full_session) twice on the frozen-candidate
problems: cold (no tutor) and ConvTutor. Question: does tutoring on the mixture
TRAINING items lift the student's untutored DELAYED/TRANSFER accuracy above the
cold floor (~0%)? If yes, the domain is learnable and we proceed to PedTutor. If
even ConvTutor (which fully explains/leaks) cannot lift it, the domain is too hard
and we ease difficulty.

Usage (needs ANTHROPIC_API_KEY + GROQ_API_KEY for the mixed config):
  python experiments/learnability_check.py --models configs/models.yaml
  python experiments/learnability_check.py --backend mock   # offline plumbing test
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.config import load_models_config, resolve_backend  # noqa: E402
from agents.conv_tutor import ConvTutor  # noqa: E402
from agents.logging_utils import RunLogger, new_run_id  # noqa: E402
from agents.model_client import ModelClient  # noqa: E402
from protocol.full_session import SCORED_PHASES, run_full_session  # noqa: E402
from protocol.session import load_problems  # noqa: E402


def _fmt(acc):
    return "  n/a" if acc is None else f"{acc:5.0%}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="configs/models.yaml")
    ap.add_argument("--backend", choices=["mock", "live"], default=None)
    ap.add_argument("--domain", default="domain/algebra/problems.yaml")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-train-turns", type=int, default=3)
    ap.add_argument("--with-cold", action="store_true",
                    help="also run the cold condition through the full protocol "
                         "(more calls). Off by default — cold probe accuracy is "
                         "already ~0%% from the cold-only calibration.")
    args = ap.parse_args()

    models_cfg = load_models_config(args.models)
    backend = resolve_backend(models_cfg, args.backend)
    run_id = new_run_id(prefix="learn")
    logger = RunLogger(run_id)
    client = ModelClient(models_cfg=models_cfg, backend=backend, logger=logger)
    problems = load_problems(args.domain)

    if backend == "mock":
        print("\n*** WARNING: backend=mock — synthetic results, plumbing test only. ***\n")

    print(f"run_id={run_id} backend={backend} seed={args.seed} "
          f"tutor={models_cfg['roles']['tutor']['model']} "
          f"student={models_cfg['roles']['student']['model']}")

    # ConvTutor through the full protocol (the gate). Cold is optional — its probe
    # accuracy is already ~0% from the cold-only calibration.
    cold = None
    if args.with_cold:
        cold = run_full_session(problems, client, tutor=None, seed=args.seed, condition="cold")
    conv = run_full_session(problems, client, tutor=ConvTutor(client), seed=args.seed,
                            condition="conv", max_train_turns=args.max_train_turns)

    report = {"run_id": run_id, "backend": backend, "seed": args.seed, "by_condition": {}}
    print("\n================ LEARNABILITY CHECK ================")
    cold_hdr = "cold" if cold else "cold~0"
    print(f"{'phase':12s} {cold_hdr:>6s} {'ConvTutor':>10s}   lift")
    for phase in SCORED_PHASES:
        c = cold.role_accuracy(phase) if cold else 0.0
        v = conv.role_accuracy(phase)
        lift = "" if v is None else f"{(v - (c or 0)):+.0%}"
        print(f"{phase:12s} {_fmt(c):>6s} {_fmt(v):>10s}   {lift}")
        report["by_condition"][phase] = {"cold": c, "conv": v}

    delayed_cold = (cold.role_accuracy("delayed") if cold else 0.0) or 0.0
    delayed_conv = conv.role_accuracy("delayed") or 0.0
    transfer_conv = conv.role_accuracy("transfer") or 0.0
    learnable = (delayed_conv > delayed_cold) or (transfer_conv > 0.0)
    report["learnable_gate"] = learnable
    report["tokens"] = {"cold": (cold.total_tokens if cold else None), "conv": conv.total_tokens}

    print("===================================================")
    print(f"GATE (does ConvTutor lift delayed/transfer above cold?): "
          f"{'PASS — learnable' if learnable else 'FAIL — too hard, ease difficulty'}")
    print(f"conv tokens={conv.total_tokens}" + (f"  cold tokens={cold.total_tokens}" if cold else ""))
    logger.write_json("learnability_report.json", report)
    print(f"logs: logs/{run_id}/")


if __name__ == "__main__":
    main()
