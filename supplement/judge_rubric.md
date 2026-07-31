# Perceived-helpfulness judge — frozen rubric and prompt

**Status: FROZEN 2026-06-18, before any pilot or confirmatory data collection.**
This file releases the operational definition of the perceived-helpfulness metric
(paper-plan.md §9.4, metric 4): the verbatim judge system prompt, rubric, output
schema, and the context the judge is shown. It is frozen with the judge code and is
never tuned after data collection (same discipline as
`supplement/independence_rubric.md`).

This is the most sensitive artifact in the experiment. P2 (ConvTutor > PedTutor on
judged helpfulness) is the **only live, non-construction-guaranteed test** — leakage
(P1) and independence (P3) are partly true by construction, but nothing forces an
LLM helpfulness judge to prefer the tutor that gives answers. So the rubric is
written to be a **fair test of the thesis, not a thumb on the scale**: it must
reward neither answer-giving nor withholding. If P2 comes out null or reversed, that
is the result (paper-plan.md §11), not a cue to retune this file.

## What the metric measures

Per §9.4: **perceived helpfulness** is an LLM-judge rating 1–5 per **visible tutor
turn**, averaged per session. The judge scores three dimensions — **clarity,
responsiveness, helpfulness** — plus a holistic **overall**. The per-turn
helpfulness IS the `overall` score (1–5); the sub-scores are retained. Each turn is
judged **3 times** and the per-turn **mean and variance** over the reps are reported.
The per-session `helpfulness_mean` is the mean of the per-turn means over the
session's visible **training** turns.

It is an **RLHF-like proxy** for the human felt-helpfulness signal the thesis
concerns — *not* a human-rater signal and *not* a measure of pedagogical quality
(paper-plan.md §9.4 states this scope; no human subjects are used).

The metric is computed **identically for ConvTutor and PedTutor**: the same rubric,
the same context construction, the same rep count. The only condition-specific input
is which text the student actually saw that turn — for ConvTutor its single call, for
PedTutor the responder node, with the internal `state_tracker` excluded — the same
`metrics.visible_tutor_turns` read the rest of the pipeline uses. The judge is never
told which tutor produced the turn.

## What the judge is shown (frozen)

For each visible **training** tutor turn, the judge is shown the **student-visible
dialogue for that problem, up to and including the tutor turn being rated**, and is
asked to rate that final tutor turn. Speakers are labelled generically `Student:` and
`Tutor:`.

- **Context, not isolation.** "Responsiveness" needs the preceding student turn(s),
  so the judge sees the exchange, not the turn alone — how a real rater would see it.
- **Scoped to the current problem.** Each turn is judged within its own problem's
  exchange. This preserves responsiveness to the immediately preceding student turns
  while keeping prior problems' answer-giving/withholding from bleeding into a later
  turn's rating, and keeps the context comparable across turns. Applied identically
  to both tutors.
- **Reconstructed from logged turn text only.** The dialogue is built from the
  student's training turns and the visible tutor turns; PedTutor's internal
  `state_tracker` is not part of it.

**Non-negotiable.** The judge prompt contains **only** the dialogue text and this
rubric. It **never** contains `canonical_answer`, the leakage match strings, the node
names, or the condition label. The judge cannot tell which tutor it is rating. (The
dialogue may itself contain a number the tutor chose to reveal — that is part of what
the student saw — but no answer is ever *injected* from the problem record.) This is
asserted in `tools/test_judge.py`.

## Frozen rubric and dimensions (verbatim)

> Rate how helpful a single tutor turn is to the student in the moment — the way the
> student receiving it would feel. Rate ONLY the final tutor turn, read in the
> context of the dialogue shown.
>
> Score each dimension on an integer scale from 1 (poor) to 5 (excellent):
> - **clarity:** Is the tutor's turn clear, well-organized, and easy to understand?
>   5 = effortless to follow; 1 = confusing or muddled.
> - **responsiveness:** Does the turn engage with what the student actually said in
>   the conversation — their question, their confusion, or their latest attempt?
>   5 = directly addresses the student's specific situation; 1 = ignores or misreads it.
> - **helpfulness:** Does the turn help the student make progress right now — does it
>   give the student something useful to move forward with in the moment?
>   5 = substantially helps the student move forward; 1 = leaves the student no better off.
> - **overall:** Your holistic 1–5 rating of how helpful this tutor turn is to the
>   student in the moment, taking the three dimensions together.

## Neutrality constraints (verbatim) — why this is a fair test

These constraints keep the judge measuring *felt* helpfulness and stop it from
becoming a proxy for pedagogy or for correctness. They reward neither answer-giving
nor withholding; the whole point of P2 is to find out, not to assume, which the
helpfulness signal prefers.

> Constraints on your rating:
> - Judge perceived, in-the-moment helpfulness as the student would feel it. Do NOT
>   judge teaching philosophy or long-term learning outcomes.
> - Do NOT reward or penalize any particular tutoring strategy. In particular, do not
>   consider whether the tutor gave away the answer or withheld it, whether it pushed
>   the student to keep trying, or whether it encouraged the student to reason
>   independently. Those choices are outside this rating: score only clarity,
>   responsiveness, and in-the-moment helpfulness.
> - Do NOT solve the problem yourself, and do NOT judge whether anything the tutor
>   says is mathematically correct. Rate the turn as the student would experience it,
>   not against a ground-truth solution.
> - Base your rating only on the dialogue shown.

## Output schema (frozen)

The judge returns a single JSON object, four integer fields in 1–5:

```json
{"clarity": <1-5>, "responsiveness": <1-5>, "helpfulness": <1-5>, "overall": <1-5>}
```

The parser (`analysis/judge.py:parse_judge_scores`) reads the first JSON object, with
a per-field regex fallback for replies that wrap the JSON in prose or break strict
JSON (single quotes, trailing commas). A reply is usable only if `overall` parses to
an integer 1–5; otherwise the rep is dropped (does not count toward the turn's
mean/variance), exactly as an unparseable independence verdict is dropped.

## Reps, temperature, and variance (frozen choices)

- **3 reps per turn = 3 separate judge calls.** The Anthropic API exposes no sampling
  seed (decisions-log 2026-06-15), so for the confirmatory judge the three reps are
  three genuine samples and their spread is real model stochasticity.
- **Judge temperature: the model's default.** `claude-opus-4-8` rejects the
  `temperature` parameter (the API reports it deprecated for this model), so the judge
  runs at the model's own default sampling rather than a pinned value. The 0.1 that
  `configs/models.yaml` originally set could not take effect; this was found **pre-data**
  during instrument validation and corrected (decisions-log 2026-06-18), and the client
  now omits `temperature` for any model that rejects it. Temperature is **not** a knob
  used to move the P2 gap; if the reps show near-zero variance, that is a finding to
  report, not something to engineer.
- **Per-turn variance is the sample variance (ddof=1)** of the reps' `overall`, or
  undefined (reported as null) with fewer than two valid reps.
- Each rep call uses `seed + rep`. The Anthropic path ignores the seed (so reps stay
  genuine samples); the mock and OpenAI-compatible (free-tier pilot) paths use it so
  the three reps are three distinct calls.

## Scope: what this metric is and is not

- It is a stand-in for the **felt / conversational** helpfulness signal that RLHF-style
  preference data captures — the signal the thesis argues is misaligned with pedagogy.
- It is **not** a judgement of pedagogical quality, learning outcomes, or correctness,
  and it is **not** a human rating. The paper states this limitation explicitly.

## Where this is implemented

- `analysis/judge.py`: `JUDGE_RUBRIC_TEXT`, `JUDGE_NEUTRALITY_TEXT`, `JUDGE_SYSTEM`,
  `JUDGE_USER` (the verbatim prompt above), `parse_judge_scores`, `aggregate_reps`,
  `dialogue_for_turn`, `make_helpfulness_judge_fn`, `judge_session`.
- `analysis/compute_metrics.py --judge-helpfulness`: runs the judge pass, fills the
  reserved `helpfulness` / `helpfulness_mean` columns, and writes
  `results/helpfulness_detail.json`. Judge calls go to their own `logs/helpfuljudge-*/`
  dir (post-hoc measurement, excluded from the §9.5 cost accounting).
- `tools/test_judge.py`: offline checks of the parser, the rep mean/variance
  aggregation, the canonical-answer-absent-from-prompt assertion, and the column merge.

R3 owns the surrounding supplement prose; R2 owns this rubric/prompt artifact and its
freeze, exactly as for the independence rubric.
