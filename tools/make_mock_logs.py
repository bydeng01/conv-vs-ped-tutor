"""Generate clean stored sessions for exercising the metrics pipeline offline.

Runs the continuous protocol (protocol/full_session) on the MOCK backend, once
per condition, each into its own logs/<run_id>/ directory. The mock text is not
behaviorally realistic (the generic mock tutor ignores the scoped node prompts),
but it exercises every code path the metrics pipeline depends on: per-problem
student/tutor calls, PedTutor's several-calls-per-visible-turn cost accounting,
phase labels, and the new problem_id tag on tutor calls.

Each run dir also gets a full_session_result.json (the harness's own
ItemResult/FullSessionResult accounting) so the pipeline's log-derived numbers can
be cross-checked against the source of truth at the harness level.

This is a development/test utility (like experiments/ped_smoke.py); it does not
change any experiment runtime behavior. Output is synthetic — do NOT report it.

Usage:
  python tools/make_mock_logs.py --seed 0 --conditions cold,conv,ped
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.conv_tutor import ConvTutor  # noqa: E402
from agents.logging_utils import RunLogger, new_run_id  # noqa: E402
from agents.model_client import ModelClient  # noqa: E402
from agents.config import load_models_config  # noqa: E402
from protocol.full_session import run_full_session  # noqa: E402
from protocol.session import load_problems  # noqa: E402
from agents.ped_tutor import PedTutor  # noqa: E402

_TUTORS = {"cold": None, "conv": ConvTutor, "ped": PedTutor}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--conditions", default="cold,conv,ped")
    ap.add_argument("--domain", default="domain/algebra/problems.yaml")
    ap.add_argument("--max-train-turns", type=int, default=3)
    args = ap.parse_args()

    models_cfg = load_models_config()
    problems = load_problems(args.domain)

    print("*** backend=mock: synthetic plumbing data, not a result ***")
    for cond in [c.strip() for c in args.conditions.split(",") if c.strip()]:
        if cond not in _TUTORS:
            raise SystemExit(f"unknown condition {cond!r}")
        run_id = new_run_id(prefix=cond)
        logger = RunLogger(run_id)
        client = ModelClient(models_cfg=models_cfg, backend="mock", logger=logger)
        TutorCls = _TUTORS[cond]
        tutor = TutorCls(client) if TutorCls else None
        res = run_full_session(problems, client, tutor=tutor, seed=args.seed,
                               condition=cond, max_train_turns=args.max_train_turns)
        logger.write_json("full_session_result.json", asdict(res))
        print(f"  {cond:5s} -> logs/{run_id}/  "
              f"items={len(res.items)} calls={logger._call_seq} "
              f"total_tokens={res.total_tokens} tutor_calls={res.n_model_calls}")


if __name__ == "__main__":
    main()
