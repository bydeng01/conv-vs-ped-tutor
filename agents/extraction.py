"""Frozen final-answer extraction (paper-plan.md §9, metric 1).

A valid final answer MUST appear after an explicit `FINAL ANSWER:` marker and
parse as an integer, decimal, fraction, or simple numeric expression. If no
marker is present, the response is scored INCORRECT — there is NO last-number
fallback. This rule is frozen before data collection and replaces the Step-1
last-number heuristic.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Optional

# Capture everything after the marker up to end of line.
_MARKER_RE = re.compile(r"final\s*answer\s*[:\-]?\s*(.+)", re.IGNORECASE)

# A simple numeric value: integer, decimal, fraction a/b, optionally signed,
# optionally wrapped in $ or x= ; we extract the first such token after marker.
_VALUE_RE = re.compile(
    r"[-+]?\$?\s*(?:\d+\s*/\s*\d+|\d+\.\d+|\d+)"
)


def extract_final_answer(text: str) -> Optional[float]:
    """Return the numeric final answer if (and only if) a FINAL ANSWER marker is
    present and a value parses; otherwise None (scored incorrect upstream)."""
    if not text:
        return None
    m = _MARKER_RE.search(text)
    if not m:
        return None
    tail = m.group(1)
    vm = _VALUE_RE.search(tail)
    if not vm:
        return None
    token = vm.group(0).replace("$", "").replace(" ", "")
    try:
        if "/" in token:
            return float(Fraction(token))
        return float(token)
    except (ValueError, ZeroDivisionError):
        return None


def has_final_marker(text: str) -> bool:
    """Whether the text contains a usable FINAL ANSWER marker (for the §6
    marker-emission acceptance band)."""
    return extract_final_answer(text) is not None
