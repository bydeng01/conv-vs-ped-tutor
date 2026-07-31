"""Shared session state types used by the harness, agents, and LangGraph nodes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

Speaker = Literal["tutor", "student", "system"]


@dataclass
class Turn:
    speaker: Speaker
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Problem:
    id: str
    role: str          # training | immediate | interference | delayed | transfer
    topic: str
    prompt: str
    canonical_answer: float
    leakage: dict[str, list[str]] = field(default_factory=dict)
    isomorph_of: Optional[str] = None


@dataclass
class SessionResult:
    """Outcome of one problem session (tutored or cold)."""
    session_id: str
    condition: str            # conv | ped | cold
    problem_id: str
    seed: int
    transcript: list[Turn]
    final_answer: Optional[float]
    correct: Optional[bool]
    n_tutor_turns: int
    n_student_turns: int
    total_tokens: int
