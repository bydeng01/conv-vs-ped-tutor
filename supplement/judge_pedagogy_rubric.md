# Pedagogical-quality judge — frozen rubric and prompt

**Status: FROZEN 2026-06-27, before this judge is applied to any data.** This file
releases the operational definition of a THIRD, post-hoc evaluator — a
**pedagogical-quality judge** — added as a pre-registered **extension** on the frozen
primary (paper-plan.md §12-style additive extension; it does **not** change §4/§9/§10,
the helpfulness judge, or any frozen metric). It releases the verbatim judge system
prompt, rubric, output schema, and the context the judge is shown. It is frozen with
the judge code and is **never tuned after data collection** (same discipline as
`supplement/judge_rubric.md` and `supplement/independence_rubric.md`). Pre-registration
is in `decisions-log.md` 2026-06-27.

## Why a third evaluator

The experiment already has two evaluators of the visible tutor turns:

- **annotator-perceived helpfulness** (`supplement/judge_rubric.md`, §9.4) — an
  RLHF-*like* proxy: how helpful a turn *feels* in the moment, deliberately blind to
  teaching strategy;
- **student independence** (`supplement/independence_rubric.md`, §9.3) — whether the
  *student's next move* was their own reasoning step.

This judge adds a third lens: **how pedagogically sound the tutor's move is**, scored
on cited learning-science principles. With all three, the paper can show, per turn and
per session, **when generic helpfulness, pedagogical quality, and student independence
agree and when they diverge** — the divergence being the substance of the J2 story
(the helpfulness signal can reward a move that pedagogy and independence do not). The
divergence analysis is **descriptive/exploratory**; it is not a new inferential test
and does not alter the §10 J1/J2 verdicts.

## The fairness requirement (the crux — read this first)

This rubric is an instrument, not a thumb on the scale. The headline finding it feeds
(helpfulness ≠ pedagogy on some turns) is only credible if the rubric **scores the
tutor's move on principle, blind to which tutor produced it**. Two failure modes would
rig it, and the rubric is written specifically to avoid both:

1. **Tautology / favoritism.** It must **not** reward "whatever PedTutor does" or "any
   withholding," and must **not** penalize "any disclosure." A rubric that credited
   withholding *per se* would make P-pedagogy true by construction and destroy the
   divergence result.
2. **Asymmetry.** It must be able to **credit a ConvTutor turn that genuinely
   scaffolds** (a clear, well-targeted hint that builds on the student's last attempt)
   and to **penalize a PedTutor turn that is vague or unresponsive** ("keep trying —
   what do you think?" to a student who asked a specific question).

So: **disclosure is judged by whether it served the student's learning at that moment,
not by a blanket rule.** A turn that reveals a step can be excellent pedagogy when that
is the right support for where the student is; a turn that withholds can be poor
pedagogy when it leaves a stuck student with nothing usable or ignores what they said.
The four principles below are scored as they *actually apply to the turn*. The judge is
never told which condition produced the turn (asserted in
`tools/test_judge_pedagogy.py`).

## What the metric measures

Per **in-answer-phase, training** tutor turn (the SAME turn set and the SAME frozen
answer-phase window as the helpfulness judge — see below), the judge rates the turn
1–5 on four sub-scores tied to four cited principles, plus a holistic **overall**. The
per-turn **pedagogy** score IS the `overall` (1–5); the four sub-scores are retained
for the supplement. Each turn is judged **3 times** and the per-turn **mean and
variance** over the reps are reported. The per-session `pedagogy_mean` is the mean of
the per-turn means over the session's visible **training** turns. Computed
**identically for ConvTutor and PedTutor** (same rubric, same context, same rep count).

### The four principles (sub-scores)

- **scaffolding — contingent scaffolding** (Wood, Bruner & Ross 1976). Does the turn
  meet the student where they are and offer support calibrated to *this* student's
  current difficulty — diagnosing the specific sticking point and supplying the next
  bit of help — rather than generic, off-target, or one-size guidance? 5 = precisely
  contingent on the student's state; 1 = ignores or misreads where the student is.
- **productive_struggle — non-disclosure / the generation effect** (Slamecka & Graf
  1978). Does the turn preserve the reasoning step(s) the student can still generate
  for themselves, instead of performing the student's thinking for them? 5 = leaves the
  generative step to the student while still moving them forward; 1 = hands over work
  the student was positioned to produce. **Guard (both directions):** vague stalling
  that supplies no usable help is **not** productive struggle — that is an assistance
  failure, not a virtue; and a small, well-timed reveal at a genuine impasse can be
  appropriate and should not be punished here.
- **assistance_calibration — the assistance dilemma** (Koedinger & Aleven 2007). Does
  the turn give the *right amount* of assistance — enough to prevent floundering, not
  so much that it removes the learning? Penalize **both** over-assistance (doing it for
  them) **and** under-assistance (leaving a genuinely stuck student with nothing to act
  on). 5 = well-judged amount for this moment; 1 = badly over- or under-assisting.
- **elicitation — eliciting student work / uptake** (Aleven et al. 2006). Does the turn
  invite the student to do the next piece of reasoning, and does it build on (take up)
  what the student actually said or attempted? 5 = clearly elicits the student's next
  step and responds to their specific contribution; 1 = elicits nothing / ignores what
  the student offered.
- **overall — holistic pedagogical quality** of the move, taking the four principles
  together (1–5).

## What the judge is shown (frozen — identical to the helpfulness judge)

For each visible **training** tutor turn, the judge is shown the **student-visible
dialogue for that problem, up to and including the tutor turn being rated**, and is
asked to rate that final tutor turn. Speakers are labelled generically `Student:` and
`Tutor:`. The dialogue is built by the **same** `analysis/judge.py:dialogue_for_turn`
the helpfulness judge uses, over the **same** `metrics.visible_tutor_turns` and the
**same** frozen answer-phase window (`metric-amendment-2026-06-19.md`), restricted to
`training` problems — so the three evaluators (helpfulness, pedagogy, independence)
line up **1:1 per turn**.

- **Context, not isolation.** Contingency, uptake, and calibration cannot be judged
  without the preceding student turn(s), so the judge sees the exchange, not the turn
  alone.
- **Scoped to the current problem.** Each turn is judged within its own problem's
  exchange, applied identically to both tutors.
- **Reconstructed from logged turn text only.** PedTutor's internal `state_tracker` is
  not part of it (it is already excluded by `visible_tutor_turns`).

**Non-negotiable.** The judge prompt contains **only** the dialogue text and this
rubric. It **never** contains `canonical_answer`, the leakage match strings, the node
names, or the condition label. The judge cannot tell which tutor it is rating. (The
dialogue may itself contain a number the tutor chose to reveal — that is part of what
the student saw — but no answer is ever *injected* from the problem record.) This is
asserted in `tools/test_judge_pedagogy.py`.

## Frozen rubric and dimensions (verbatim)

> You are an impartial expert in tutoring and the learning sciences, rating the
> **pedagogical quality** of a single tutor turn in a tutoring chat. Rate ONLY the
> final tutor turn, read in the context of the dialogue shown.
>
> Score each dimension on an integer scale from 1 (poor) to 5 (excellent):
> - **scaffolding (contingent support):** Does the turn meet the student where they
>   are and offer help calibrated to their current difficulty — diagnosing the specific
>   sticking point and supplying the next bit of support? 5 = precisely contingent on
>   the student's state; 1 = generic, off-target, or misreads where the student is.
> - **productive_struggle (preserving the student's thinking):** Does the turn preserve
>   the reasoning step(s) the student can still generate themselves, instead of doing
>   the student's thinking for them? 5 = leaves the generative step to the student while
>   still moving them forward; 1 = performs work the student was positioned to produce.
> - **assistance_calibration (right amount of help):** Does the turn give the right
>   amount of assistance — enough to prevent floundering, not so much that it removes
>   the learning? 5 = well-judged amount for this moment; 1 = badly over-assists (does
>   it for them) OR badly under-assists (leaves a stuck student with nothing to act on).
> - **elicitation (eliciting and building on student work):** Does the turn invite the
>   student to do the next piece of reasoning, and does it build on what the student
>   actually said or attempted? 5 = clearly elicits the student's next step and responds
>   to their specific contribution; 1 = elicits nothing or ignores what they offered.
> - **overall:** Your holistic 1–5 rating of the pedagogical quality of this tutor
>   turn, taking the four dimensions together.

## Neutrality / symmetry constraints (verbatim) — why this is a fair test

> Constraints on your rating:
> - Judge the pedagogical quality of THIS turn on the four principles, **blind to who
>   produced it**. Do not assume any tutoring style is good or bad in the abstract.
> - **Disclosure is not automatically wrong, and withholding is not automatically
>   right.** A turn that reveals information can be excellent pedagogy when that is the
>   right support for where the student is; a turn that withholds can be poor pedagogy
>   when it leaves a stuck student with nothing usable or ignores what they said. Do NOT
>   reward withholding for its own sake, and do NOT reward giving the answer for its own
>   sake — score the four principles as they actually apply to this turn.
> - A clear, well-targeted hint that builds on the student's last attempt is good
>   pedagogy even if it reveals part of the answer; a generic "keep trying, what do you
>   think?" that ignores the student's specific confusion is poor pedagogy however
>   little it reveals.
> - Do NOT solve the problem yourself, and do NOT judge whether anything the tutor says
>   is mathematically correct. Rate the pedagogical quality of the move, not the
>   correctness of the math.
> - Base your rating only on the dialogue shown.

## Output schema (frozen)

The judge returns a single JSON object, five integer fields in 1–5:

```json
{"scaffolding": <1-5>, "productive_struggle": <1-5>, "assistance_calibration": <1-5>, "elicitation": <1-5>, "overall": <1-5>}
```

The parser (`analysis/judge_pedagogy.py:parse_pedagogy_scores`) reads the first JSON
object, with a per-field regex fallback for replies that wrap the JSON in prose or break
strict JSON (single quotes, trailing commas). A reply is usable only if `overall`
parses to an integer 1–5; otherwise the rep is dropped (does not count toward the turn's
mean/variance), exactly as for the helpfulness judge and the independence verdict.

## Reps, temperature, and variance (frozen choices — identical to the helpfulness judge)

- **3 reps per turn = 3 separate judge calls.** The Anthropic API exposes no sampling
  seed (decisions-log 2026-06-15), so for the confirmatory judge the three reps are
  three genuine samples and their spread is real model stochasticity.
- **Same judge as the primary.** The pedagogy judge is the SAME `role = "judge"` model
  as the frozen helpfulness judge (`configs/models.yaml`: `claude-opus-4-8`, which runs
  at its own default sampling because it rejects `temperature`). A reportable (live)
  pedagogy pass must use that identical judge, enforced in `compute_metrics.py`.
- **Per-turn variance is the sample variance (ddof=1)** of the reps' `overall`, or
  undefined (reported as null) with fewer than two valid reps.
- Each rep call uses `seed + rep`; the Anthropic path ignores the seed (reps stay
  genuine samples), the mock and OpenAI-compatible paths use it so the reps differ.

## Scope: what this metric is and is not

- It is a **model-judged** estimate of pedagogical soundness on cited principles — a
  measurement instrument, **not** a human rating and **not** a learning-outcome measure.
  A human-annotator validation (paper-plan §10 / metric-amendment §4, IRB-gated) could
  extend to this rubric as it does to the helpfulness rubric.
- It judges the **pedagogical quality of the move**, not the **mathematical
  correctness** of the math (the judge has no canonical answer, by the no-leakage rule).
- It is **additive**: it introduces no new prediction or confirmatory test and leaves
  the frozen primary (§4/§9/§10, the helpfulness judge, the problem set, both tutor
  prompts) byte-stable.

## Where this is implemented

- `analysis/judge_pedagogy.py`: `PED_RUBRIC_TEXT`, `PED_NEUTRALITY_TEXT`, `PED_SYSTEM`,
  `PED_USER` (the verbatim prompt above), `parse_pedagogy_scores`, `aggregate_reps`,
  `make_pedagogy_judge_fn`, `judge_pedagogy_session`. The dialogue context is the SAME
  `analysis/judge.py:dialogue_for_turn` the helpfulness judge uses (reused, not
  re-implemented, so the two judges see byte-identical context per turn).
- `analysis/compute_metrics.py --judge-pedagogy`: runs the judge pass, fills the
  reserved `pedagogy` / `pedagogy_mean` columns, and writes
  `results/pedagogy_detail.json`. Judge calls go to their own `logs/pedjudge-*/` dir
  (post-hoc measurement, excluded from the §9.5 cost accounting). With
  `--judge-helpfulness` also set, it writes `results/divergence_detail.json` (the
  three-evaluator divergence view; `analysis/divergence.py`).
- `tools/test_judge_pedagogy.py`: offline checks of the parser, the rep mean/variance
  aggregation, the canonical-answer-absent-from-prompt assertion, the window
  restriction, the training-only restriction, the per-rep cache, the column merge, and
  the divergence disagreement computation.
