"""Session runner.

`run_problem_session` drives one problem to completion for either a tutored
condition (tutor != None) or the cold baseline (tutor == None). The same runner
serves all conditions, so the only thing that varies is the tutor's policy
structure. The full train -> immediate -> interference -> delayed -> transfer
protocol (paper-plan.md §7) is composed from these single-problem sessions and
is filled in once the 12-problem set exists (Step 3).
"""
from __future__ import annotations

from typing import Optional

import yaml

from agents.cold_baseline import MAX_ATTEMPTS
from agents.config import repo_path
from agents.model_client import extract_final_answer
from agents.state import Problem, SessionResult, Turn
from domain.algebra.checker import is_correct


def load_problems(path: str) -> list[Problem]:
    with open(repo_path(path)) as f:
        data = yaml.safe_load(f)
    problems = []
    for p in data["problems"]:
        problems.append(Problem(
            id=p["id"],
            role=p["role"],
            topic=p["topic"],
            prompt=p["prompt"],
            canonical_answer=float(p["canonical_answer"]),
            leakage=p.get("leakage", {}),
            isomorph_of=p.get("isomorph_of"),
        ))
    return problems


def _tok(turn: Turn) -> int:
    return int(turn.meta.get("tokens", 0))


def run_problem_session(
    problem: Problem,
    student,
    tutor,                      # TutorAgent or None (cold)
    seed: int,
    condition: str,
    max_turns: int = 8,
    cold_success_prob: float = 0.5,
    stop_on_commit: bool = True,
) -> SessionResult:
    # During tutored TRAINING, the tutor must engage even if the student blurts an
    # early answer (otherwise no teaching happens). Set stop_on_commit=False there.
    # For probes/Step-1 dialogues, the default True ends the turn on a commit.
    transcript: list[Turn] = []
    total_tokens = 0
    final: Optional[float] = None
    n_tutor = n_student = 0

    tutored = tutor is not None
    if not tutored:
        # Cold baseline: unaided attempts only.
        for attempt in range(MAX_ATTEMPTS):
            st = student.respond(transcript, problem, seed, attempt,
                                 tutored=False, cold_success_prob=cold_success_prob)
            transcript.append(st); n_student += 1; total_tokens += _tok(st)
            if st.meta.get("committed_final"):
                final = st.meta.get("final_answer"); break
    else:
        for round_i in range(max_turns):
            st = student.respond(transcript, problem, seed, round_i, tutored=True)
            transcript.append(st); n_student += 1; total_tokens += _tok(st)
            if st.meta.get("committed_final"):
                final = st.meta.get("final_answer")
                if stop_on_commit:
                    break
            tt = tutor.respond(transcript, problem, seed, round_i)
            transcript.append(tt); n_tutor += 1; total_tokens += _tok(tt)

    # Condition-neutral forced elicitation if the student never committed.
    if final is None:
        commit = student.force_commit(transcript, problem, seed, n_student,
                                      tutored=tutored, cold_success_prob=cold_success_prob)
        transcript.append(commit); n_student += 1; total_tokens += _tok(commit)
        final = commit.meta.get("final_answer")

    session_id = f"{condition}_{problem.id}_seed{seed}"
    return SessionResult(
        session_id=session_id,
        condition=condition,
        problem_id=problem.id,
        seed=seed,
        transcript=transcript,
        final_answer=final,
        correct=is_correct(final, problem.canonical_answer),
        n_tutor_turns=n_tutor,
        n_student_turns=n_student,
        total_tokens=total_tokens,
    )
