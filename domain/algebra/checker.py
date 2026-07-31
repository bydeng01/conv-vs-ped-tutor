"""Exact-answer correctness checking (paper-plan.md §9, metric 1).

Numerical equality with tolerance 1e-6. Kept tiny and dependency-free so it can
be reused by the metrics pipeline (Step 5)."""
from __future__ import annotations

from typing import Optional

TOLERANCE = 1e-6


def is_correct(student_answer: Optional[float], canonical: float, tol: float = TOLERANCE) -> bool:
    if student_answer is None:
        return False
    return abs(float(student_answer) - float(canonical)) <= tol
