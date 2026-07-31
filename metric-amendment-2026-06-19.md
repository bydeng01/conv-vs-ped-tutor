# Metric amendment & frozen analysis specification

**Status: FROZEN 2026-06-19 — post-pilot, pre-confirmatory.** No confirmatory data has been
collected (the pilots are non-inferential, paper-plan §10). This document amends the
relevant parts of `paper-plan.md` §9/§10/§11; once the confirmatory run begins it freezes
with them. Prompted by an external reviewer and the pilot; none of it is tuned toward a
result (see the integrity note).

## 1. Answer-phase evaluation window (stopping rule)

All turn-level metrics are computed only over the **answer phase** of each training problem —
the tutoring up to the point the student first commits an answer. Post-resolution turns are
not tutoring and are excluded.

**Definition.** For each `training` problem, let `c` = the sequence index of the **first**
`student_train` turn whose text yields a parseable answer under the frozen `FINAL ANSWER:`
extractor (§9.1). A turn with no marker is not a commit (conservative; keeps more turns).

**Inclusion (identical for ConvTutor and PedTutor, and for all three metrics):**
- Visible tutor turns: include those whose call sequence is **< c** (seen by the student
  before it committed). Exclude turns at or after `c`.
- Student training turns: include those with sequence **≤ c** (up to and including the
  commit turn).
- If a problem has **no** in-training commit, the window is the full training exchange for
  that problem (no truncation).

**Applies uniformly to:** answer-leakage (P1), independence ratio (P3), and
annotator-perceived helpfulness (P2 — the judge rates only in-window tutor turns).

**Rationale & disclosure.** Post-commit turns confound the metrics (pilot: ConvTutor emitted
14/24 post-commit turns of motivational filler vs PedTutor's 2/24). The rule is
condition-neutral, but it yields **shorter windows for ConvTutor** (it resolves fast) and
**longer for PedTutor** (it scaffolds to the answer); this is the intended
"tutoring-until-answer" comparison and is stated openly. The rule and the extractor are
frozen and never tuned after confirmatory data.

## 2. Construct rename

"perceived/felt helpfulness" → **annotator-perceived helpfulness.** It measures how helpful a
tutor turn *appears to an external evaluator applying the rubric* — **not** the learner's
subjective experience and **not** pedagogical quality. It is an RLHF-like (reward-model-style)
proxy, to be validated against human annotators (§4). The rubric in
`supplement/judge_rubric.md` is unchanged; only the name and scope statement change.

## 3. Hypotheses & analysis plan (direction unchanged)

- **P1, P2, P3 unchanged in direction.** P2 is explicitly flagged: **the pilot provides no
  supporting evidence; a null or reversed P2 is plausible and will be reported as such**
  (the §11 negative-result clause stands; P2/J2 remain the live tests).
- **Unit of analysis = the conversation (per `(condition, replicate_id)` summary), not pooled
  turns.** Turns are correlated within a conversation; pooling them overstates n.
- **Aggregation.** Per-conversation metric = mean over that conversation's in-window turns;
  primary tests on per-replicate paired summaries (Wilcoxon signed-rank, paired by replicate
  id, two-tailed α=0.05), effect size Cliff's delta.
- **Uncertainty.** Report 95% CIs on every metric at the conversation level (bootstrap or
  rank-based) and the variance of the 3 judge reps per turn.
- **Correlated turns.** The J2 coupling (leakage→helpfulness; leakage→next-turn independence)
  uses a mixed-effects model with replicate and problem random effects; per-turn averages are
  never reported as if independent.
- **n = 10 replicates × 3 conditions** (unchanged).

## 4. Judge-validation set (new; gated on an IRB check)

Sample dialogue prefixes stratified across conditions and across the judge's score range;
have several **adult annotators** independently score them with the same frozen rubric, and
report (i) LLM–human agreement, (ii) human–human agreement (inter-rater reliability), and
(iii) CIs. The learner remains simulated; only this validation involves humans, and they are
**annotators, not learners**. **Before recruiting, verify the institution's human-subjects /
IRB requirements** — do not assert "no human subjects" categorically.

## 5. Confirmatory run

Run the 10×3 confirmatory experiment only after §§1–4 are frozen. Report **P1–P3 regardless of
outcome**, with conversation-level results and uncertainty — not pooled turn-level averages.

## Integrity note

Post-pilot, pre-confirmatory; frozen before any confirmatory data. The window rule was
proposed by an external reviewer and **demonstrably does not rescue P2** in the pilot (the
ConvTutor−PedTutor helpfulness gap goes −0.60 → −0.30 under the window — smaller but still
reversed), so it is not a result-favoring adjustment. Recorded in `decisions-log.md`
2026-06-19.
