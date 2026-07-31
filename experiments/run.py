"""Experiment entry point.

Step-1 usage (single problem, offline mock backend):

    python experiments/run.py --condition conv --backend mock --problems seed-001
    python experiments/run.py --condition cold --backend mock --problems seed-001

Every model call is logged to logs/<run_id>/calls.jsonl; a readable transcript
is written per session; a results.json summary is written per run. Metrics are
computed post-hoc from the logs (Step 5), never here.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the repo root importable when run as a script.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.config import load_models_config, resolve_backend  # noqa: E402
from agents.conv_tutor import ConvTutor  # noqa: E402
from agents.ped_tutor import PedTutor  # noqa: E402
from agents.logging_utils import RunLogger, new_run_id  # noqa: E402
from agents.model_client import ModelClient  # noqa: E402
from protocol.session import load_problems, run_problem_session  # noqa: E402
from student.simulator import StudentSimulator  # noqa: E402


def build_client(backend_override, logger):
    models_cfg = load_models_config()
    backend = resolve_backend(models_cfg, backend_override)
    return ModelClient(models_cfg=models_cfg, backend=backend, logger=logger), backend


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", choices=["conv", "ped", "cold"], required=True,
                    help="conv = ConvTutor; ped = PedTutor; cold = no-tutor baseline.")
    ap.add_argument("--backend", choices=["mock", "live"], default=None)
    ap.add_argument("--problems", default="seed-001",
                    help="comma-separated problem ids, or 'all'")
    ap.add_argument("--domain", default="domain/algebra/problems.yaml")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    run_id = new_run_id(prefix=f"{args.condition}")
    logger = RunLogger(run_id)
    client, backend = build_client(args.backend, logger)

    all_problems = load_problems(args.domain)
    if args.problems == "all":
        chosen = all_problems
    else:
        wanted = {p.strip() for p in args.problems.split(",")}
        chosen = [p for p in all_problems if p.id in wanted]
    if not chosen:
        raise SystemExit(f"No problems matched {args.problems!r} in {args.domain}")

    student = StudentSimulator(client)
    tutor = {"conv": ConvTutor, "ped": PedTutor}.get(args.condition)
    tutor = tutor(client) if tutor else None

    print(f"run_id={run_id}  backend={backend}  condition={args.condition}  "
          f"problems={[p.id for p in chosen]}  seed={args.seed}")

    summaries = []
    for problem in chosen:
        result = run_problem_session(
            problem=problem, student=student, tutor=tutor,
            seed=args.seed, condition=args.condition,
        )
        logger.write_transcript(
            session_id=result.session_id,
            header={
                "condition": result.condition, "problem_id": result.problem_id,
                "seed": result.seed, "backend": backend,
                "canonical_answer": problem.canonical_answer,
                "final_answer": result.final_answer, "correct": result.correct,
                "tutor_turns": result.n_tutor_turns, "student_turns": result.n_student_turns,
                "total_tokens": result.total_tokens,
            },
            turns=result.transcript,
        )
        summaries.append({
            "session_id": result.session_id, "problem_id": result.problem_id,
            "role": problem.role, "final_answer": result.final_answer,
            "canonical_answer": problem.canonical_answer, "correct": result.correct,
            "tutor_turns": result.n_tutor_turns, "student_turns": result.n_student_turns,
            "total_tokens": result.total_tokens,
        })
        print(f"  [{problem.id}] final={result.final_answer} "
              f"canonical={problem.canonical_answer} correct={result.correct} "
              f"tutor_turns={result.n_tutor_turns} tokens={result.total_tokens}")

    logger.write_json("results.json", {
        "run_id": run_id, "backend": backend, "condition": args.condition,
        "seed": args.seed, "sessions": summaries,
    })
    print(f"logs + transcripts: logs/{run_id}/")


if __name__ == "__main__":
    main()
