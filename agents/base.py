"""Shared agent scaffolding.

A tutor agent exposes a single method:

    respond(transcript, problem, seed, turn_index) -> Turn

ConvTutor implements this with a one-node LangGraph; PedTutor (Step 4) with a
multi-node state machine over the SAME model. The session harness treats both
identically, which is what makes the comparison controlled: only the policy
structure behind `respond` differs.
"""
from __future__ import annotations

from typing import Protocol

from .model_client import ModelClient
from .state import Problem, Turn


class TutorAgent(Protocol):
    name: str

    def respond(self, transcript: list[Turn], problem: Problem, seed: int, turn_index: int) -> Turn:
        ...


def tutor_message_view(transcript: list[Turn]) -> list[dict[str, str]]:
    """Convert a transcript into Anthropic-style messages from the TUTOR's view:
    student turns become 'user', tutor turns become 'assistant'. The student
    always speaks first, so the sequence starts with a 'user' message."""
    messages: list[dict[str, str]] = []
    for t in transcript:
        if t.speaker == "student":
            messages.append({"role": "user", "content": t.text})
        elif t.speaker == "tutor":
            messages.append({"role": "assistant", "content": t.text})
        # system turns are not included in the message list
    return messages


def mock_meta_for(problem: Problem, turn_index: int, tutored: bool = True) -> dict:
    """Parameters passed to the mock backend so its behavior is explicit and
    auditable. Ignored entirely by the live backend."""
    return {
        "canonical_answer": problem.canonical_answer,
        "problem_id": problem.id,
        "turn_index": turn_index,
        "tutored": tutored,
    }
