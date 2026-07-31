# Independence metric — frozen rubric and attempt-detection regex

**Status: FROZEN 2026-06-18, before any confirmatory data collection.** This file
releases the operational definition of the independence ratio (paper-plan.md §9.3,
metric 3). It is frozen with the metrics code and is never tuned after data
collection.

The independence metric is **regex-primary with an LLM-verification pass**. The
regex (below) is authoritative; the LLM pass is a documented robustness check whose
disagreements default to the regex result and are logged. The regex is owned by the
metrics pipeline (R2) and lives verbatim in `analysis/metrics.py`
(`INDEPENDENCE_ATTEMPT_PATTERNS`, `attempts_reasoning`). The surrounding rubric
prose and worked-example bank are R3's to expand for the supplement; the *decision
artifacts* — the regex and the judge rubric text — are frozen here as written.

## What the metric measures

Per §9.3: the **independence ratio** is the fraction of student **training** turns
that **attempt a reasoning step** (an algebraic expression or a numerical
computation) before the next tutor turn. In the continuous protocol every student
training turn is immediately followed by a tutor turn, so in practice this is
"does this student training turn contain an attempt." The metric is computed only
over student turns tagged `component = student_train`; probes are untutored and are
not part of independence.

The metric is computed **identically for ConvTutor and PedTutor**. It is
deliberately **not** the same code as PedTutor's internal attempt detector
(`agents/ped_tutor.py`): that detector is an agent-internal routing signal, and
reusing it would couple the reported metric to one agent's internals. The two may
look similar; this regex is the metric's own, independently defined and frozen
artifact.

## Frozen attempt-detection regex

A student turn **attempts a reasoning step** if and only if its text matches at
least one of the following patterns (case-insensitive). These four strings are the
frozen artifact:

```
(E)   [0-9a-z\)]\s*=\s*[-+(]?\s*[0-9a-z]        # an explicit equation: something = something
(C)   \d+(?:\.\d+)?\s*[-+*/×·]\s*\d+(?:\.\d+)?  # an arithmetic computation: number <op> number
(A1)  \d+(?:\.\d+)?[a-z]\b                       # a coefficient·variable term: e.g. 12x, 0.5x
(A2)  \b[a-z]\s*[-+*/]\s*[0-9a-z(]              # a variable in an operator relation: e.g. x - 3, x/2
```

**Decision rule.** Attempt = `match(E) OR match(C) OR match(A1) OR match(A2)`.

A bare number, or a bare answer guess with no supporting work (no operator, no
`=`, no variable relation), does **not** count — that is a guess, not a reasoning
step. This is the **conservative** choice: it does not inflate the independence
ratio. (The conservative direction matters because P3 predicts PedTutor's
independence is *higher*; the definition must not be one that manufactures that
gap.)

### Worked examples (from calibration transcripts)

Counted as an attempt (regex TRUE):

- `0.20 * 48 = 9.6` — arithmetic computation (C) and equation (E)
- `0.50x + 9.6 = 14.4 + 0.30x` — coefficient·variable (A1), equation (E)
- `0.5*x + 0.2*48 = 0.3*(x+48)` — computation (C)
- `So 0.5x + 9.6 = 0.3x + 14.4, then 0.2x = 4.8` — (A1)/(E)
- `2x + 5 = 68` — (A1)/(E)
- `is it x = 24?` — equation (E): the student wrote a symbolic relation

NOT counted (regex FALSE):

- `how do I make an equation from that?` — help-seeking, no symbolic work
- `I'm not sure how to start setting this up` — expresses confusion
- `Can you just tell me the answer?` — answer request
- `a number increased by 7 equals 19` — prose; the word "equals", not `=`
- `I think it is 24` — a bare numeric guess
- `let x be the unknown number` — names a variable but performs no operation

### Known boundaries (declared, conservative)

- A symbolic candidate such as `x = 24` is counted as an attempt because the
  student produced an algebraic relation, even though it may be a guess. Counting
  it is conservative against P3 (it raises both conditions similarly and cannot
  selectively widen the predicted gap).
- Because matching is case-insensitive, an unusual prose construction like
  `I + you` would match (A2). This is vanishingly rare in mixture-problem student
  turns; the LLM-verification pass is the robustness check for such edge cases, and
  any disagreement defaults to the regex result and is logged.
- Paraphrased reasoning with no symbolic content (e.g. "I multiplied the percent by
  the volume") is **not** captured. Like the leakage matcher, the independence
  regex is a conservative detector of *explicit* symbolic/numeric work.

## LLM-verification pass (frozen rubric)

For each student training turn, a `role = "judge"` (Opus) call applies the rubric
below to confirm or deny "attempted a reasoning step." The judge is given **only
the student turn and this rubric** — never the canonical answer, never the tutor's
text. Its verdict is compared to the regex; the regex is authoritative, so the
reported value is always the regex result. Disagreements are counted and logged as
a robustness statistic (`independence_verify.json`), not used to override the
metric.

**Rubric text (verbatim, frozen):**

> A student turn ATTEMPTED a reasoning step if it contains the student's own
> mathematical work toward solving the problem: writing or manipulating an
> equation, performing an arithmetic computation, defining and combining variables,
> or carrying out an algebraic step. It did NOT attempt a reasoning step if it only
> asks for help, restates or paraphrases the problem, expresses confusion, or
> states a bare numeric guess with no supporting work. Judge only what THIS turn
> contains, not whether any value is correct.

The judge is instructed to return a single JSON object
`{"attempted": true|false, "reason": "<short>"}`; the parser also accepts a bare
yes/no/true/false. An unparseable reply is treated as "no verdict" (it does not
count toward agreement and the regex result stands).

## Where this is implemented

- `analysis/metrics.py`: `INDEPENDENCE_ATTEMPT_PATTERNS`, `attempts_reasoning`,
  `INDEPENDENCE_RUBRIC_TEXT`, `INDEPENDENCE_JUDGE_SYSTEM`, `verify_independence`,
  `reconcile` (regex authoritative), `make_judge_fn`.
- `analysis/compute_metrics.py --verify-independence`: runs the live judge pass.
- `tools/test_metrics.py`: offline checks of the regex labels and the reconcile
  logic.
