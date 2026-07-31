"""Student simulator.

A separate (weaker, Llama-3.1-8B) model call with an explicit knowledge frontier
and behavior priors (paper-plan.md §6). It is the highest-risk component: if it
never asks for the answer, answer-leakage collapses to zero for both tutors and
the comparison dies; if it is too strong, it solves from pretraining and the
cold baseline is high. Both are checked in the pilot (Step 2/7).

The student has session memory only and no privileged access to canonical
answers. What it can recover from a session is the experiment's analog of
"learning."
"""
from __future__ import annotations

from agents.config import role_spec
from agents.model_client import ModelClient, extract_final_answer
from agents.state import Problem, Turn

# Verbatim, pinned student system prompt (mirrored in supplement/prompts.md).
STUDENT_SYSTEM_PROMPT = """You are a student learning algebra. You know:
- Basic arithmetic.
- How to solve a linear equation once it is set up.
You do NOT know:
- How to translate a word problem into an equation.
- Which quantity to assign to a variable.
- How to identify the underlying relationship in rate/work/mixture problems.

Behave like a real, somewhat-struggling student. Translating the words into an
equation is the hard part for you; your arithmetic is usually fine once an
equation is set up.
- When you genuinely cannot see how to set the problem up, you sometimes ask for
  help or just ask for the answer.
- Sometimes you restate the problem instead of making progress.
- Otherwise you attempt a step.
Do not invent a method you are unsure of. Keep replies short (1-3 sentences). When
you are ready to commit to a final answer, write it on its own line as:
FINAL ANSWER: <number>
If you are explicitly asked to state your final answer, you MUST reply with that
exact line and nothing else."""

# Condition-NEUTRAL elicitation. Applied identically to cold / conv / ped after
# the dialogue, with no hint, so it cannot advantage any condition. It does not
# tutor; it only asks the student to commit in a parseable form (paper-plan §9).
COMMIT_INSTRUCTION = (
    "You must now commit to your best single numeric guess for the ORIGINAL "
    "problem. Even if you are unsure or would rather ask for help, you MUST write "
    "an actual number — do not ask a question and do not leave it blank. Reply "
    "with exactly one line and nothing else:\n"
    "FINAL ANSWER: <number>"
)

# Used only if the first commit came back with no parseable number.
COMMIT_RETRY = (
    "That had no number. Write your best guess as a single number now — any number "
    "is better than none. One line, nothing else:\n"
    "FINAL ANSWER: <number>"
)


class StudentSimulator:
    name = "student"

    def __init__(self, client: ModelClient):
        self.client = client

    def _student_message_view(self, transcript: list[Turn], problem: Problem) -> list[dict]:
        """From the STUDENT's view: tutor turns are 'user', student turns are
        'assistant'. The problem is presented as the opening user message."""
        messages = [{"role": "user", "content": f"Problem: {problem.prompt.strip()}"}]
        for t in transcript:
            if t.speaker == "tutor":
                messages.append({"role": "user", "content": t.text})
            elif t.speaker == "student":
                messages.append({"role": "assistant", "content": t.text})
        return messages

    def respond(self, transcript: list[Turn], problem: Problem, seed: int,
                turn_index: int, tutored: bool = True,
                cold_success_prob: float = 0.5) -> Turn:
        messages = self._student_message_view(transcript, problem)
        # Anthropic requires the message list to start with 'user' and not end
        # with a trailing 'assistant'; the opening problem guarantees a 'user'.
        mock_meta = {
            "canonical_answer": problem.canonical_answer,
            "problem_id": problem.id,
            "turn_index": turn_index,
            "tutored": tutored,
            "cold_success_prob": cold_success_prob,
        }
        comp = self.client.complete(
            role="student",
            system=STUDENT_SYSTEM_PROMPT,
            messages=messages,
            seed=seed,
            tags={"component": "student", "problem_id": problem.id, "turn_index": turn_index},
            mock_meta=mock_meta,
        )
        final = extract_final_answer(comp.text)
        return Turn(
            speaker="student",
            text=comp.text,
            meta={
                "tokens": comp.input_tokens + comp.output_tokens,
                "committed_final": final is not None,
                "final_answer": final,
            },
        )

    def force_commit(self, transcript: list[Turn], problem: Problem, seed: int,
                     turn_index: int, tutored: bool = True,
                     cold_success_prob: float = 0.5) -> Turn:
        """Condition-neutral forced elicitation: make the student commit a numeric
        answer in parseable form. Used when no natural commit occurred. Retries
        once if the first reply has no number (a weak/answer-seeking student may
        echo the marker but leave it blank)."""
        messages = self._student_message_view(transcript, problem)
        # Avoid two consecutive 'user' messages (Anthropic forbids it): if the
        # last message is already 'user' (e.g. a tutor turn), append to it.
        if messages and messages[-1]["role"] == "user":
            messages[-1] = {"role": "user",
                            "content": messages[-1]["content"] + "\n\n" + COMMIT_INSTRUCTION}
        else:
            messages.append({"role": "user", "content": COMMIT_INSTRUCTION})

        mock_meta = {
            "canonical_answer": problem.canonical_answer, "problem_id": problem.id,
            "turn_index": turn_index, "tutored": tutored,
            "cold_success_prob": cold_success_prob, "committing": True,
        }

        def _commit(msgs, retry):
            return self.client.complete(
                role="student", system=STUDENT_SYSTEM_PROMPT, messages=msgs, seed=seed,
                tags={"component": "student_commit", "problem_id": problem.id,
                      "turn_index": turn_index, "retry": retry},
                mock_meta=mock_meta,
            )

        comp = _commit(messages, retry=False)
        final = extract_final_answer(comp.text)
        tokens = comp.input_tokens + comp.output_tokens
        if final is None:
            retry_msgs = messages + [
                {"role": "assistant", "content": comp.text or "(blank)"},
                {"role": "user", "content": COMMIT_RETRY},
            ]
            comp2 = _commit(retry_msgs, retry=True)
            tokens += comp2.input_tokens + comp2.output_tokens
            f2 = extract_final_answer(comp2.text)
            if f2 is not None:
                comp, final = comp2, f2
        return Turn(
            speaker="student",
            text=comp.text,
            meta={
                "tokens": tokens,
                "committed_final": final is not None,
                "final_answer": final,
                "forced_commit": True,
            },
        )
