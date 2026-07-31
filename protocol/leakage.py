"""Frozen answer-leakage matcher (paper-plan.md §9, metric 2).

Each problem pre-specifies nonempty `numeric_form` and `solution_form` lists.
A tutor turn LEAKS if:
  (a) any `numeric_form` token appears on token boundaries (so "12" does not
      match inside "120" or "1.25"); OR
  (b) any `solution_form` phrase appears as a normalized substring
      (lowercase, whitespace collapsed, non-essential punctuation stripped).

Paraphrased worked-solution reveals not covered by either list are NOT counted:
leakage is therefore a pre-declared LOWER BOUND. This matcher is frozen before
data collection and never tuned afterward.
"""
from __future__ import annotations

import re
from typing import Iterable

# Keep digits, letters, whitespace, and a few math-essential chars.
_STRIP_RE = re.compile(r"[^0-9a-z/=.\s+\-]")
_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    t = text.lower()
    t = _STRIP_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t)
    return t.strip()


def _numeric_hit(norm_text: str, token: str) -> bool:
    # Token-boundary numeric match. A following period is allowed when it is
    # sentence punctuation, but not when it starts or continues a decimal.
    pat = r"(?<![\d.])" + re.escape(token.strip().lower()) + r"(?!\d)(?!\.\d)"
    return re.search(pat, norm_text) is not None


def turn_leaks(text: str, numeric_form: Iterable[str], solution_form: Iterable[str]) -> bool:
    norm = normalize(text)
    for n in numeric_form:
        if n and _numeric_hit(norm, str(n)):
            return True
    for s in solution_form:
        if s and normalize(str(s)) in norm:
            return True
    return False


def leakage_rate(tutor_turn_texts: list[str], numeric_form: Iterable[str],
                 solution_form: Iterable[str]) -> float:
    """Fraction of tutor turns (during training) that leak the answer."""
    numeric_form = list(numeric_form)
    solution_form = list(solution_form)
    if not tutor_turn_texts:
        return 0.0
    hits = sum(1 for t in tutor_turn_texts if turn_leaks(t, numeric_form, solution_form))
    return hits / len(tutor_turn_texts)
