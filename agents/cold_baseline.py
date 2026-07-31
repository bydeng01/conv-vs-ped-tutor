"""Cold baseline: the test harness with the tutor removed.

The student attempts the problem with no tutoring at all. This is the most
important diagnostic in the design: it must be LOW (target 20-40%) or a high
delayed-test score is uninterpretable (build brief; paper-plan.md §3, §8).

There is no tutor agent here. The cold baseline is driven directly by the
session harness with `tutor=None`; this module documents the condition and gives
the harness a stable import point.
"""
from __future__ import annotations

CONDITION = "cold"

# The student makes a small number of unaided attempts per problem before
# committing. Kept low so the floor reflects genuine inability, not persistence.
MAX_ATTEMPTS = 2
