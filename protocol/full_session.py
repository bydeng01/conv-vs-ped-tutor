"""Continuous protocol (paper-plan.md §7).

One run is a single instance with the student carrying ONE conversation across
all phases:

    training (tutored)  ->  immediate (probe)  ->  interference (probe)
                        ->  delayed (probe)    ->  transfer (probe)

- Training items are tutored (tutor != None); the tutor sees the problem and the
  current problem's dialogue. ConvTutor tutors each problem independently; the
  STUDENT accumulates everything in its running context (the "session memory").
- All probes are answered with NO tutor, from that carried memory. This is the
  operational measure of in-context recoverability (paper-plan §2).
- Cold baseline = run with tutor=None (training is also untutored).

Phase labels are attached to every scored item. Scoring uses the frozen marker
extraction; a forced commit (with one retry) guarantees a numeric answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agents.extraction import extract_final_answer
from agents.model_client import ModelClient
from agents.state import Problem, Turn
from domain.algebra.checker import is_correct
from student.simulator import (COMMIT_INSTRUCTION, COMMIT_RETRY,
                               STUDENT_SYSTEM_PROMPT)

PHASE_ORDER = ["training", "immediate", "interference", "delayed", "transfer"]
SCORED_PHASES = ["immediate", "delayed", "transfer"]  # interference not a learning measure


@dataclass
class ItemResult:
    phase: str
    problem_id: str
    final_answer: Optional[float]
    correct: bool
    n_student_turns: int
    n_tutor_turns: int
    tutor_tokens: int = 0      # tutor-side tokens for this item (summed over node calls)
    n_model_calls: int = 0     # tutor model calls for this item (PedTutor: >1 per turn)


@dataclass
class FullSessionResult:
    condition: str
    seed: int
    items: list[ItemResult] = field(default_factory=list)
    total_tokens: int = 0      # student + tutor tokens (paper-plan.md §9.5)
    student_tokens: int = 0
    tutor_tokens: int = 0
    n_model_calls: int = 0     # total tutor model calls across the session

    def role_accuracy(self, role: str) -> Optional[float]:
        xs = [i.correct for i in self.items if i.phase == role]
        return (sum(xs) / len(xs)) if xs else None


class _Student:
    """The student's single growing conversation (student POV: its replies are
    'assistant', everything presented to it is 'user')."""

    def __init__(self, client: ModelClient, seed: int):
        self.client = client
        self.seed = seed
        self.msgs: list[dict[str, str]] = []
        self.tokens = 0

    def _reply(self, problem: Problem, tutored: bool, committing: bool, tag: str) -> str:
        comp = self.client.complete(
            role="student", system=STUDENT_SYSTEM_PROMPT, messages=self.msgs, seed=self.seed,
            tags={"component": tag, "problem_id": problem.id},
            mock_meta={"canonical_answer": problem.canonical_answer, "problem_id": problem.id,
                       "tutored": tutored, "committing": committing, "cold_success_prob": 0.5},
        )
        self.msgs.append({"role": "assistant", "content": comp.text})
        self.tokens += comp.input_tokens + comp.output_tokens
        return comp.text

    def say_user(self, content: str):
        # Avoid consecutive user messages (Anthropic-safe).
        if self.msgs and self.msgs[-1]["role"] == "user":
            self.msgs[-1]["content"] += "\n\n" + content
        else:
            self.msgs.append({"role": "user", "content": content})

    def commit(self, problem: Problem) -> Optional[float]:
        self.say_user(COMMIT_INSTRUCTION)
        text = self._reply(problem, tutored=False, committing=True, tag="student_commit")
        final = extract_final_answer(text)
        if final is None:
            self.say_user(COMMIT_RETRY)
            text = self._reply(problem, tutored=False, committing=True, tag="student_commit")
            final = extract_final_answer(text)
        return final


def _run_training(stu: _Student, problem: Problem, tutor, seed: int,
                  max_turns: int) -> tuple[int, int, int]:
    """Tutored dialogue; student carries memory. Returns
    (tutor-turn count, tutor tokens, tutor model-call count).

    Tutor tokens/calls are read from each tutor Turn's meta. For PedTutor a single
    visible turn sums several internal node calls (meta['tokens'] and
    meta['n_model_calls']); for ConvTutor it is one call. This accounting is
    condition-neutral -- it reads the same meta fields for both tutors."""
    stu.say_user(f"New problem to work through with your tutor:\n{problem.prompt.strip()}")
    first = stu._reply(problem, tutored=True, committing=False, tag="student_train")
    dialogue = [Turn("student", first)]
    n_tutor = tutor_tokens = tutor_calls = 0
    for r in range(max_turns):
        tutor_turn = tutor.respond(dialogue, problem, seed, r)
        dialogue.append(tutor_turn)
        n_tutor += 1
        tutor_tokens += int(tutor_turn.meta.get("tokens", 0))
        tutor_calls += int(tutor_turn.meta.get("n_model_calls", 1))
        stu.say_user(f"Tutor: {tutor_turn.text}")
        reply = stu._reply(problem, tutored=True, committing=False, tag="student_train")
        dialogue.append(Turn("student", reply))
    return n_tutor, tutor_tokens, tutor_calls


def _run_probe(stu: _Student, problem: Problem) -> ItemResult:
    """Untutored probe answered from carried memory."""
    stu.say_user(f"Now solve this problem on your own (no tutor):\n{problem.prompt.strip()}")
    text = stu._reply(problem, tutored=False, committing=False, tag="student_probe")
    final = extract_final_answer(text)
    n_student = 1
    if final is None:
        final = stu.commit(problem)
        n_student += 1
    return ItemResult(problem.role, problem.id, final,
                      is_correct(final, problem.canonical_answer), n_student, 0)


def run_full_session(problems: list[Problem], client: ModelClient, tutor,
                     seed: int, condition: str, max_train_turns: int = 4) -> FullSessionResult:
    by_role = {role: [p for p in problems if p.role == role] for role in PHASE_ORDER}
    stu = _Student(client, seed)
    res = FullSessionResult(condition=condition, seed=seed)

    for role in PHASE_ORDER:
        for p in by_role.get(role, []):
            if role == "training" and tutor is not None:
                n_tutor, t_tokens, t_calls = _run_training(stu, p, tutor, seed, max_train_turns)
                # training answer is not scored
                res.items.append(ItemResult("training", p.id, None, False, 0, n_tutor,
                                            tutor_tokens=t_tokens, n_model_calls=t_calls))
                res.tutor_tokens += t_tokens
                res.n_model_calls += t_calls
            else:
                # training-in-cold and every probe phase are untutored
                item = _run_probe(stu, p)
                res.items.append(item)

    res.student_tokens = stu.tokens
    res.total_tokens = stu.tokens + res.tutor_tokens   # tutor_tokens accumulated above
    return res
