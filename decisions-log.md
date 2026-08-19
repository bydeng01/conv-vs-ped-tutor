# Decisions Log

This file records every non-trivial design decision, deviation from the build
brief, and ambiguity resolution made while building the experiment. The purpose
is integrity: predictions, metric definitions, and the analysis plan are
pre-registered in `paper-plan.md` and must not change retroactively. Anything
that *does* change, or any judgment call not fully specified by the design spec, is
logged here with a date and a reason.

## Format

Each entry uses the following shape:

```
### YYYY-MM-DD — <short title>
**Context:** what prompted the decision.
**Decision:** what was chosen.
**Reason:** why this choice (prefer the option that makes the comparison cleaner).
**Alternatives considered:** what else was on the table, and why rejected.
**Affects:** files / components touched.
```

Entries are append-only and ordered oldest-first.

---

### 2026-06-14 — Offline-runnable build with mockable model client
**Context:** The offline environment has no `ANTHROPIC_API_KEY`. Step 1's "done when" needs a
full end-to-end run, and we want to develop without burning API budget.
**Decision:** The model client (`agents/model_client.py`) supports two backends
selected by config / env: `live` (real Anthropic API) and `mock` (deterministic,
seeded, offline). All orchestration, logging, and metrics are backend-agnostic.
**Reason:** Lets the whole pipeline run and be inspected now; real runs are a
config flip once a key is present. The mock is deterministic per seed so
transcripts are reproducible and the harness can be unit-tested.
**Alternatives considered:** (a) require a key up front — rejected, blocks
progress and costs money during scaffolding; (b) build code without running —
rejected, violates the design spec's "run it and inspect before moving on" discipline.
**Affects:** `agents/model_client.py`, all configs, `experiments/configs/*`.

### 2026-06-14 — Model strings (current latest per tier)
**Context:** Brief specifies Sonnet-tier tutor, Haiku-tier student, Opus-tier
judge, read from config, never hardcoded.
**Decision:** `configs/models.yaml` sets tutor=`claude-sonnet-4-6`,
student=`claude-haiku-4-5-20251001`, judge=`claude-opus-4-8`. Read at runtime.
**Reason:** Matches the design spec's tiering with the current model generation;
keeping them in one config makes capability control explicit and auditable.
**Affects:** `configs/models.yaml`, `agents/config.py`.

### 2026-06-14 — Seed problem precedes domain authoring
**Context:** Step 1 must "run end to end on one problem," but full domain
authoring is Step 3 (deliberately after student calibration).
**Decision:** `domain/algebra/problems.yaml` ships initially with ONE clearly
marked placeholder problem (`seed-001`) used only to exercise the harness. The
real 12-problem set is authored in Step 3 at the calibrated difficulty and will
replace/extend this file. The placeholder is not used for any reported metric.
**Reason:** Satisfies Step 1 without pre-committing to problem difficulty before
calibration, which the design spec explicitly orders after.
**Affects:** `domain/algebra/problems.yaml`.

### 2026-06-14 — Adopt the existing README's repo layout
**Context:** A detailed `README.md` already exists in the repo and prescribes a
layout (`agents/`, `student/`, `domain/`, `protocol/`, `experiments/`,
`analysis/`) and references `paper-plan.md §9` for metric definitions.
**Decision:** Build to the README's layout rather than an alternative `src/cvp/`
package layout, and number `paper-plan.md` sections so §9 = Metrics resolves.
**Reason:** The README is pre-existing project intent; matching it keeps the repo
self-consistent and the controlled comparison "self-evident" as the README
intends (the two tutors differ only by `agents/conv_tutor.py` vs `ped_tutor.py`).
**Affects:** whole tree; `paper-plan.md` section numbering.

### 2026-06-15 — Correct stale implementation paths in decisions log
**Context:** Methodological audit found that earlier decisions-log entries still referenced the rejected `src/cvp/` layout after the repository adopted top-level `agents/`, `student/`, `domain/`, `protocol/`, and `experiments/` directories.
**Decision:** Updated the stale path references from `src/cvp/model_client.py` to `agents/model_client.py` and from `src/cvp/config.py` to `agents/config.py`.
**Reason:** This is a mechanical consistency fix only; it does not change predictions, metrics, analysis, prompts, implementation behavior, or experimental design.
**Alternatives considered:** Leave the stale references and report them only — rejected because path correction is explicitly allowed as a low-risk consistency fix.
**Affects:** `decisions-log.md`.

### 2026-06-15 — Pre-freeze methodological amendments (external audit response)
**Context:** Before any data collection, an external methodological audit
(reviewed by the project lead) found several issues in `paper-plan.md`. Because no
data has been collected, the pre-registration is amendable now; once collection
begins it freezes. Two issues required a maintainer decision (resolved as noted)
and the rest are corrections/clarifications that strengthen integrity.
**Decision:** Amended `paper-plan.md` as follows:
  1. **Protocol (§7).** Replaced the under-specified per-problem flow with one
     continuous protocol instance: training is tutored (tutor conditions only);
     immediate/delayed/transfer items are **no-tutor probes** answered from
     carried session memory; interference sits between immediate and delayed;
     cold uses the identical probe schedule with no tutoring. Every turn is
     `phase`-labeled. (Fixes the critical flaw that probes would otherwise be
     tutored, measuring assistance rather than recovery.)
  2. **Statistical power (§10) — LEAD DECISION: "expand probes + n=10 +
     problem-level analysis."** n increased from 5 to **10 confirmatory**
     replicates; n=5 demoted to a non-inferential pilot (no stop/scale p-value
     from it). Rationale: at n=5 the minimum two-sided signed-rank p is 0.0625.
     Unit of analysis is now problem-level (multiple probe items per phase) with
     a mixed-effects/cluster-robust robustness test alongside the per-replicate
     Wilcoxon.
  3. **Problem set (§5).** Expanded to **19** items (6 training, 3 immediate, 4
     interference, 3 delayed, 3 transfer) so each phase yields multiple items;
     resolves the old 12-vs-13 count contradiction. Added a frozen
     **anti-memorization constraint**: delayed/transfer answers must differ
     numerically from all training answers.
  4. **Pairing (§10).** "Paired by seed" → "paired by **replicate id**" (fixes
     problem/condition order, initial context, controllable randomness); the live
     API exposes no sampling seed, so model stochasticity is reported as
     within-replicate noise.
  5. **Construct framing (§1/§2/§6) — LEAD DECISION: "reframe as in-context
     recoverability."** The measured construct is now stated as **in-context
     recoverability after interference**, an explicit proxy for (not an instance
     of) durable learning; no weight-change/post-session claim is made. P3
     relabeled "delayed recoverability."
  6. **Predictions (§4).** P6 reframed as a **mediator** of P1 (not independent
     confirmatory evidence; headline rests on P2 + P3/P4). P7 reclassified as a
     **calibration precondition**, not a thesis prediction.
  7. **Metrics (§9).** Froze `FINAL ANSWER:`-marker extraction (no last-number
     fallback; unmarked = incorrect). Leakage `*_form` specified as **nonempty
     lists** with a frozen matcher (token-boundary numeric match; substring for
     solution form; uncovered paraphrases counted as a declared lower bound).
     Independence "intervention" defined as the next tutor turn, with a frozen
     LLM-verification rubric. Added an RLHF-*like*-proxy scope note to perceived
     helpfulness. Expanded cost accounting to per-call/turn token totals incl.
     PedTutor internal node calls.
  8. **Compute-fairness (§10).** Primary comparison fixes the same visible-turn
     budget; added a cost-normalized (per-1k-token) sensitivity analysis that
     flags results that vanish under matched budgets.
  9. **Falsification (§11).** Added a pre-committed outcome-interpretation table
     covering previously uncovered cases (cold high; P2 unmet; either tutor wins
     everything; leakage absent).
**Reason:** Each change either fixes a validity threat that would make the result
uninterpretable (1, 3, 4, 8) or removes a researcher degree of freedom / sharpens
honesty before freeze (2, 5, 6, 7, 9). All are pre-data and logged.
**Alternatives considered:** (a) the audit's suggestion to add **blind human
helpfulness ratings** — **rejected** as out of scope (brief: "No human subjects");
instead the LLM judge is explicitly labeled an RLHF-like proxy. (b) n=10-only
keeping single probe items, and (c) keep-illustrative/drop-p-values — both
rejected by the project lead in favor of the expanded-probe design.
**Affects:** `paper-plan.md` (§§1,2,3,4,5,6,7,8,9,10,11, header); downstream
implementation owes: continuous-protocol runner with phase labels and carried
memory, frozen extraction + leakage matcher, expanded problem authoring,
replicate-id seeding, cost accounting across PedTutor node calls,
`supplement/independence_rubric.md`, `supplement/judge_rubric.md`.

### 2026-06-15 — Free OpenAI-compatible providers for pilot/calibration only
**Context:** Free API access (OpenRouter, GroqCloud, Cerebras) is available for
the non-inferential pilot/calibration; paid Anthropic is reserved for the final
confirmatory run. The design spec mandates Anthropic for all three roles.
**Decision:** Added an OpenAI-compatible live path to `agents/model_client.py`
(provider chosen per role or globally in config: `anthropic` or an
OpenAI-compatible endpoint via `base_url` + `api_key_env`). Added
`configs/models.free.yaml` (default: Groq — tutor `llama-3.3-70b-versatile`,
student `llama-3.1-8b-instant`, judge `llama-3.3-70b-versatile`). The
final-stage config `configs/models.yaml` remains Anthropic.
**Reason:** Calibration and the pilot are explicitly non-inferential (paper-plan
§10); using free models there conserves paid budget without affecting the
confirmatory result. Capability tiering (capable tutor = same for both agents;
weaker student; third judge) is preserved.
**Caveat (must hold):** because the pilot model differs from the final model, the
cold-baseline and ConvTutor-leakage gates (failure modes #1, #3) MUST be
re-verified on the final Anthropic model before the confirmatory run; the pilot
result does not transfer automatically.
**Alternatives considered:** spend paid Anthropic budget on calibration —
rejected as wasteful for a non-inferential step; build a bespoke client per
provider — rejected, all three are OpenAI-compatible so one adapter suffices.
**Affects:** `agents/model_client.py`, `configs/models.free.yaml`,
`configs/models.yaml`, `experiments/calibrate.py`.

### 2026-06-15 — Frozen extraction, leakage matcher, and calibration tooling
**Context:** Step-2 calibration needs trustworthy scoring and a leakage read,
which the amended §9 specifies but the Step-1 harness did not yet implement.
**Decision:** Implemented `agents/extraction.py` (frozen `FINAL ANSWER:`-marker
extraction; no last-number fallback — replaces the Step-1 heuristic, which is now
removed from `model_client.py`), `protocol/leakage.py` (frozen token-boundary +
substring matcher), a candidate `domain/algebra/calibration.yaml` (8 equation-
setup word problems, clearly separate from the final 19), and
`experiments/calibrate.py` (reads failure modes #1 and #3 plus the §6 student
acceptance bands). Behavior classification in the calibrator is an explicitly
approximate regex read; the frozen independence metric (regex + LLM verification)
is Step 5.
**Reason:** Lets the highest-information live step run with correct, pre-registered
scoring before the frozen problem set is authored.
**Affects:** `agents/extraction.py`, `agents/model_client.py`,
`protocol/leakage.py`, `domain/algebra/calibration.yaml`,
`experiments/calibrate.py`.

### 2026-06-15 — Forced-commit elicitation turn (first live calibration finding)
**Context:** First live calibration (Groq llama-3.1-8b student / llama-3.3-70b
tutor) returned cold accuracy 0% with **FINAL-marker rate 0%**: the weak student
never emitted the `FINAL ANSWER:` line, so the frozen marker-only extraction
(§9) scored every session incorrect regardless of true performance. The 0% was a
measurement artifact, not a result. (ConvTutor leakage 32% — failure mode #3 is
clear.)
**Decision:** Added a **condition-neutral forced-commit turn**: when the student
has not committed by the end of the dialogue, it is asked once to state its final
answer as `FINAL ANSWER: <number>` (no hint, no tutoring), applied identically
across cold/conv/ped. Implemented in `student/simulator.py` (`force_commit`,
`COMMIT_INSTRUCTION`) and `protocol/session.py`; the student prompt now also
mandates the exact line when explicitly asked. The frozen extraction and leakage
matcher are UNCHANGED — only elicitation was strengthened (explicitly permitted
by §6).
**Reason:** Makes scoring reliable without weakening the anti-gaming extraction
rule. The commit turn is identical across conditions, so it cannot advantage any
condition. Merging the instruction into a trailing user turn avoids consecutive
user messages (Anthropic-safe for the final run).
**Alternatives considered:** (a) re-introduce a last-number fallback in
extraction — rejected, it reopens the §9 ambiguity the audit closed; (b) force a
marker on every student turn — rejected, it would eliminate multi-turn dialogue
and inflate immediate commits.
**Affects:** `student/simulator.py`, `protocol/session.py`,
`agents/model_client.py` (mock), `supplement/prompts.md`. **Next:** re-run
calibration; the cold baseline is only interpretable once marker rate ≥95%.

### 2026-06-15 — Provider split + frugality after Groq daily token cap
**Context:** The re-run hit Groq's free per-day token cap (TPD ~100k) on
`llama-3.3-70b-versatile` mid-run; the 70B tutor over long dialogues is the token
sink. The backoff had also (a) retried this non-recoverable daily limit and
(b) double-tried the no-seed fallback on rate-limit errors, wasting calls.
**Decision:** (1) Split providers in `configs/models.free.yaml`: tutor →
**Cerebras** `llama-3.3-70b` (separate quota), student stays Groq
`llama-3.1-8b-instant`. (2) Trim calibration cost: tutor `max_tokens` 1024→600,
student 512→400, and `calibrate.py` caps ConvTutor dialogues at `--max-turns 4`.
(3) `model_client._with_backoff` now raises `QuotaExhausted` immediately on
per-day/quota/credit caps (with switch-provider guidance) instead of retrying;
(4) the no-seed fallback fires ONLY when the seed param itself is rejected, not on
429s. These are pilot-infrastructure choices; they do not affect metrics,
analysis, or the final Anthropic run.
**Alternatives considered:** wait for Groq's daily reset — rejected as slow;
shrink the candidate batch — rejected, 8 problems is already minimal for a
read.
**Affects:** `configs/models.free.yaml`, `experiments/calibrate.py`,
`agents/model_client.py`, `experiments/CALIBRATION.md`.

### 2026-06-15 — Calibration finding: domain too easy → harden + stronger student
**Context:** First clean calibration (tutor Cerebras `gpt-oss-120b`, student Groq
`llama-3.1-8b-instant`, markers 100%): cold baseline **75%** (failure mode #1 —
too easy), ConvTutor leakage 60.7% (PASS), ask-for-answer rate 0.06 (very low).
The final student (Haiku) is *stronger* than Llama-8B, so the domain must be hard
enough for Haiku, not just for 8B.
**Decision (two maintainer choices):** (1) **Harden the domain, staying in
algebra** — replaced the v1 calibration batch with 10 genuinely multi-step word
problems (quadratic work/rate, mixture, relative speed, coin system, age, digit,
multi-step fraction/percent); all answers verified with sympy. (2) **Bump the
calibration student** from `llama-3.1-8b-instant` to `openai/gpt-oss-20b` (Groq)
so calibrated difficulty transfers closer to the final Haiku student.
**Open item (not yet acted):** ask-for-answer rate is far below the §6 target
(0.35–0.65). Leakage did not collapse (the tutor volunteers answers), but a low
ask rate weakens PedTutor's deferral_gate mechanism. Plan: re-check on the harder
batch (genuine stuckness should raise it); if still low, strengthen the student
prompt's help-seeking (allowed by §6) — logged when done.
**Reason:** A low cold baseline is the precondition that makes every downstream
outcome interpretable; hardening the materials is the design spec's prescribed response
to "too easy," preferred over crippling the student.
**Affects:** `domain/algebra/calibration.yaml`, `configs/models.free.yaml`.
**Next:** re-run calibration; target cold 20–40% on `gpt-oss-20b`, then re-verify
on Haiku before authoring the frozen 19.

### 2026-06-15 — Revert student (gpt-oss-20b too strong) + tutor-engagement fix
**Context:** With student `openai/gpt-oss-20b` on the hard batch, cold = **100%**
(it is a reasoning model and solved all 10). Leakage read 0% and behavior
ask=0.00/restate=0.90 — all ARTIFACTS of the strong student committing on turn 0,
so the ConvTutor loop broke before the tutor ever spoke (0 tutor turns → 0/0
leakage).
**Decision:** (1) Reverted the calibration student to `llama-3.1-8b-instant` (the
weakest capable English-math model on the free tier) on the hard batch — a
combination not yet tested. (2) **Design fix:** added `stop_on_commit` to
`run_problem_session` (default True). Tutored TRAINING dialogues now run with
`stop_on_commit=False` (set by `calibrate.py`), so the tutor engages every round
even if the student blurts an early answer — otherwise no teaching occurs and
leakage is unmeasurable. This also informs the Step-7 protocol: training is a
multi-turn teaching dialogue; the student's answer is scored only on untutored
probes, not during training.
**Reason:** A student that solves instantly produces no tutoring interaction, so
neither leakage nor the thesis mechanism can be observed; the weak student plus
forced tutor engagement restores a real dialogue.
**Alternatives considered:** keep gpt-oss-20b and harden further — rejected, a
reasoning model defeats the "weak learner" premise regardless of difficulty.
**Affects:** `configs/models.free.yaml`, `protocol/session.py`,
`experiments/calibrate.py`. **Next:** re-run; read cold on Llama-8B over the hard
batch.

### 2026-06-15 — Calibration PASSES core gates; tune student ask-rate
**Context:** Llama-8B on the hard batch gave cold **20%** (PASS, bottom of band),
leakage **57.5%** (PASS), markers 100% (PASS). Transcript review confirmed the
dynamics are real and on-thesis: cold student stalls at equation setup
("how do I make an equation from that?") and commits a wrong guess; ConvTutor
dumps the full worked solution incl. the answer on turn 1 before the student
really tries, and the student parrots it. BUT ask-for-answer was 0.02 vs the §6
target ~0.5 — the design spec explicitly says to verify this prior in the pilot.
**Decision:** Per the design spec's own student spec, strengthened the student prompt so
that when stuck it asks for the answer directly about half the time (with example
phrasings), and broadened the calibration behavior classifier to count blunt
answer-requests (it previously missed them; conceptual help-seeking like "how do
I…" still counts as restate, not asking). Core gates already pass; this restores
the decisive "student demands answer → ConvTutor complies / PedTutor defers" case.
**Note:** cold 20% is the FLOOR on Llama-8B; the final Haiku student is stronger,
so expect higher cold on Haiku — may need a difficulty bump when porting (logged).
Also observed: the 8B occasionally emits an empty turn (handled by forced commit);
revisit only if frequent.
**Alternatives considered:** amend the §6 prior down to match observed behavior —
deferred; the design spec wants an answer-seeking student, so tune first and re-verify.
**Affects:** `student/simulator.py`, `experiments/calibrate.py`,
`supplement/prompts.md`. **Next:** one confirmation run, then author the frozen 19.

### 2026-06-15 — Robust commit (ask-nudge regressed marker rate)
**Context:** After the ask-rate nudge, behavior bands passed (ask 0.39, restate
0.27) and cold rose to 30% (PASS), but marker rate fell 100%→70%. Transcript:
the now-answer-seeking student, on the forced-commit turn, echoed "FINAL ANSWER:"
with NO number (it followed the format but left it blank, having asked for help).
**Decision:** Strengthened `COMMIT_INSTRUCTION` to demand an actual number even
when guessing ("do not ask a question and do not leave it blank"), and added a
one-shot `COMMIT_RETRY` in `force_commit` if the first reply parses to no number.
This keeps probe scoring reliable (every probe must yield a numeric commit)
without touching the frozen extraction.
**Reason:** Probes are scored on the committed number; a blank commit would score
a capable-but-stuck student as wrong for the wrong reason. The retry is condition-
neutral and contains no hint.
**Affects:** `student/simulator.py`, `supplement/prompts.md`. **Next:** confirm
marker rate ≥95% with cold still ~20–40%, then close Step 2.

### 2026-06-15 — Step 2 (calibration) CLOSED on the free-model proxy
**Context:** Confirmation run (Cerebras `gpt-oss-120b` tutor, Groq
`llama-3.1-8b-instant` student, hard batch, seed 0): cold **30%** (PASS), leakage
**50%** (PASS), marker rate **100%** (PASS), ask **0.41** (PASS), restate 0.34
(slightly over the 0.10–0.30 band).
**Decision:** Treat Step 2 as complete on the proxy. The restate overage (0.04)
is within run-to-run noise (0.27 on the prior run) and restate is a secondary,
classifier-approximate characterization, not a core gate. Deliberately NOT tuning
further — chasing a 0.04 noise overage on a soft band would be result-chasing,
which the rigor rule forbids. Behavior now sits at roughly ask 0.40 / restate 0.30
/ attempt 0.25 vs the design spec's ideal ~0.5 / 0.2 / 0.3 (a touch more restating, a
touch less attempting); accepted as a minor, documented deviation.
**Caveat (unchanged):** difficulty is calibrated to Llama-8B; the final student is
Haiku (stronger), so the frozen 19 must be re-verified on Haiku and likely
hardened a notch before the confirmatory run.
**Affects:** none (analysis/log only). **Next:** Step 3 — author the frozen 19.

### 2026-06-15 — Calibrate difficulty on the final student (Haiku) before authoring
**Context:** Maintainer choice: rather than author the 19 at the Llama-8B
difficulty and risk re-authoring after Haiku proves stronger, calibrate the
difficulty directly on Haiku first, then author once.
**Decision:** Added `--cold-only` to `experiments/calibrate.py` (skips all
ConvTutor/tutor calls; measures only the cold baseline + marker rate) so the
Haiku difficulty check is cheap and isolated. Run with
`--models configs/models.yaml --cold-only` and an Anthropic key. Leakage on the
final tutor (Sonnet) is a separate later check; it was already demonstrated on
the proxy. Target: Haiku cold in 20–40% on the batch that will seed the 19.
**Reason:** Authoring 19 good problems is real effort; setting difficulty against
the actual final student avoids a redo and is more rigorous than extrapolating
from a weaker proxy.
**Affects:** `experiments/calibrate.py`, `experiments/CALIBRATION.md`. **Next:**
run Haiku cold-only; author the 19 at the difficulty that lands Haiku in band.

### 2026-06-15 — Student model changed: Haiku → Llama-3.1-8B (Claude stays tutor)
**Context:** Haiku cold-only on the hard algebra batch = **100%**. Transcripts show
Haiku ROLE-PLAYS the struggling student as prompted ("I'm not sure… can you tell
me the answer?") but commits the CORRECT answer when forced. The weakest Claude is
too capable to be a genuine learner; making it act weak doesn't lower its actual
accuracy. No standard academic domain where Haiku is competent will give a low
cold baseline.
**Decision (maintainer choice):** Final config = **Claude Sonnet tutor + Llama-
3.1-8B student + Claude Opus judge** (`configs/models.yaml` updated, mixed
providers). The student is only the learner instrument and must genuinely
struggle; Llama-8B does (cold ~30% on the hard batch, real setup failures in
transcripts). The TUTOR — the model whose conversational alignment the paper
studies — stays Claude, same for both agents (capability control intact).
**Reason:** Satisfies the design spec's actual intent ("student must genuinely
struggle") better than a Haiku student that can't struggle; keeps the empirical
claim about Claude; reuses the existing Llama-8B difficulty calibration; avoids an
open-ended hunt for a domain hard enough to break Haiku (which risked an
unlearnable cold≈0). Deviation from the design spec's literal "Haiku student," logged.
**Implication:** difficulty is already calibrated for the real student (Llama-8B).
Still must verify ConvTutor leakage on the REAL tutor (Sonnet) — gpt-oss-120b
leaked 50%, but Sonnet must be checked directly (failure mode #3) before authoring
the frozen 19.
**Alternatives considered:** all-Claude with a much harder domain (rejected: risks
unlearnable cold≈0, costs paid iteration); all open models (rejected here: the
paper's claim is strongest with Claude as the tutor).
**Affects:** `configs/models.yaml`. **Next:** one full calibration with the mixed
config (Sonnet tutor + Llama student) to confirm Llama cold ~20–40% and Sonnet
leakage; then author the frozen 19.

### 2026-06-15 — Mixed config verified; Step 2 fully closed
**Context:** Full calibration with the FINAL config (Sonnet tutor + Llama-8B
student) on the hard batch: cold **30%** (PASS), markers **100%** (PASS), Sonnet
ConvTutor leakage **52.5%** (PASS) — confirmed genuine by reading transcripts
(Sonnet works through to the answer; not a matcher false-positive). Behavior
ask 0.24 / restate 0.52 (off the §6 bands).
**Decision:** Step 2 closed on the real config. Behavior bands logged as
DESCRIPTIVE of the Llama-8B student (they bounce with tutor/seed and are partly an
artifact of finding #2 below); not tuned further (rigor: no chasing noise).
**Findings to carry into Step 4:**
  1. **Tutor lacks the problem statement.** ConvTutor.respond builds only the
     student/tutor dialogue (`tutor_message_view`), so the tutor never sees the
     problem text and sometimes must ask the student for it (seen in
     conv_hard-002). Fix in Step 4: give BOTH ConvTutor and PedTutor the problem
     in-context (identically, to stay condition-neutral). This also inflates the
     "restate" count (student re-explaining the problem).
  2. Leakage `numeric_form` false-positive risk: choose frozen-19 answers that do
     NOT appear in the problem statement, so a numeric hit really means the answer
     was revealed.
**Affects:** none (analysis/log). **Next:** Step 3 — author the frozen 19.

### 2026-06-15 — Frozen-19 cold check: difficulty is right (probe cold 22%)
**Context:** Cold-only on the 19 (Llama-8B student, seed 0). All-19 cold was 42%,
but that mixes in training (50%) and percentage interference (75%). Broken down by
role: training 50%, immediate 67%, interference 75%, delayed 0%, transfer 0%.
**Decision:** The calibration target is PROBE cold (immediate+delayed+transfer) =
**22%** — in the 20–40% band → cold gate PASS. Fixed `calibrate.py` to report cold
by role and gate on probe cold (the all-problem average was misleading). The
student fails delayed/transfer unaided (0/6 at this seed), which is the desired
floor; the structurally-identical immediate-1 was solved, so the family is
learnable (not impossibly hard). Single-seed per-role figures are noisy (6 binary
samples for delayed/transfer); the confirmatory run produces the cold baseline
with variance across 10 replicates, so no separate multi-seed calibration is
needed.
**Note:** immediate cold (67%) is on the high side (compresses room for an
immediate-accuracy split), but the dissociation lives mainly in delayed/transfer
where cold is ~0%. Acceptable.
**Affects:** `experiments/calibrate.py` (per-role cold + probe-cold gate).
**Next:** second-person review of the 19, then freeze; then Step 4 (PedTutor).

### 2026-06-15 — Adversarial review of the 19; fixes applied (rev 2)
**Context:** An independent adversarial review (subagent) checked the 19 for
correctness, ambiguity, isomorphism, difficulty, and leakage strings. Math all
correct. Findings: (MUST FIX) transfer-3 was the memorized "three consecutive
integers" template — a weak model can recall the answer without using the taught
method, contaminating the transfer cell, and its structure didn't cleanly mirror
train-5. (MINOR) transfer-1's isomorph pointer was off; single-digit `solution_form`
strings like "x = 5" substring-match "x = 51", biasing the leakage metric (P6) up.
**Decision (rev 2 of problems.yaml):**
  - Replaced transfer-3 with a plank-cutting problem that mirrors train-5's
    `(a·x − c) + x = T` structure under a new (length) surface.
  - Repointed transfer-1 → train-4 (both pure-ratio relations).
  - Re-tuned EVERY relationship answer to a distinctive TWO-DIGIT value, so
    incidental small numbers (step numbers, counts) can't false-trigger leakage;
    dropped the fragile bare "x = N" leakage substrings (numeric_form already
    matches the number on token boundaries).
  - Re-ran tools/verify_problems.py: all answers re-derived, anti-memorization
    holds (train {12,14,16,19,23,27}; delayed {17,18,26}; transfer {15,24,29}),
    no answer appears in its prompt, added a single-digit-answer warning.
**Reason:** transfer is the thesis-critical cell; removing the memorized template
and the leakage noise protects P4/P6. Difficulty is structure-driven, so the
renumbering should leave the cold baseline ~unchanged (re-check recommended).
**Affects:** `domain/algebra/problems.yaml`, `tools/verify_problems.py`.
**Next:** final human/independent sign-off (+ optional quick cold re-check), then freeze;
then Step 4 (PedTutor + the tutor-sees-the-problem fix).

### 2026-06-15 — independent second-person review: transfer-1 fixed + leakage hardened
**Context:** an independent second-person review confirmed all 19 answers and
found one MUST-FIX: transfer-1 was ratio-plus-PERIMETER (`2(x+3x)=232`), not
structurally isomorphic to its `train-4` target (ratio-plus-DIFFERENCE,
`4x−x=42`). The same review also applied low-risk leakage hardening directly.
**Decision:** (1) Applied the review's proposed transfer-1 rewrite (maintainer
approved): "length is 4 times its width; its length is 87 units greater than its
width" → `4x−x=87` → width 29 (answer unchanged, geometry surface kept, now a
true ratio-difference isomorph of train-4). Updated `tools/verify_problems.py`
re-derivation; all checks pass. (2) Accepted the review's applied fixes: spelled-out
`solution_form` phrases (catch word-form reveals the digit matcher would miss),
`.0`/`.00` numeric variants, and a `protocol/leakage.py` matcher tweak so a
sentence-final period after a number counts while `12` still rejects `120`/`12.5`.
Verified by unit checks.
**Reason:** transfer is the thesis-critical cell; a genuine isomorph protects P4.
The leakage changes strengthen P6 measurement and are pre-data, so permissible;
the matcher is now considered FINAL and frozen.
**IMPORTANT re-check needed:** the probe-cold 22% read was on rev-1 numbers. The
set has since been fully renumbered (rev 2 two-digit answers + the review's transfer-1),
so a fresh cold-only run on the CURRENT 19 is required before freezing.
**Affects:** `domain/algebra/problems.yaml`, `tools/verify_problems.py`,
`protocol/leakage.py`. **Next:** cold re-check on current 19 → freeze →
Step 4.

### 2026-06-15 — Construct-validity fix: wrong failure mode; redesign domain
**Context:** Cold-only on the (renumbered) 19 gave probe cold 11%, but the
transcripts revealed WHY: Llama-8B sets up the linear-relationship equations
**correctly** (immediate-1: `4x+11=3(x+11)`; immediate-2: `x+(2x+5)=68`;
delayed-1: `4x+13=3(x+13)`) and then bails — an artifact of the ask-nudge plus the
forced-commit guess. So the family is too easy at the SETUP level (the skill the
student is supposed to lack), and the low cold was manufactured by our prompt.
A student that already has the target skill can't show differential learning, so
the dissociation could never appear — a construct-validity failure.
**Decision (maintainer choice "redesign harder + drop the ask-nudge"):**
  1. Reverted the student prompt's ask-nudge so help-seeking is GENUINE (the
     student asks only when actually stuck). The thesis does not need nudged
     asking — ConvTutor leaks by VOLUNTEERING full solutions (Sonnet 52%), not
     because the student asks.
  2. Re-author the family around structures Llama genuinely fails to SET UP:
     mixture/concentration and relative-motion (the grab-bag styles where it
     scored ~30%). Solving stays linear, consistent with the frontier.
  3. New candidate batch `domain/algebra/calibration.yaml` (4 mixture + 4 motion,
     all sympy-verified) for a cold-only mini-test BEFORE re-authoring the 19.
**Reason:** A valid learning experiment requires the student to genuinely lack the
taught skill; setup difficulty must be real, not prompt-induced.
**Implication:** the current `domain/algebra/problems.yaml` (linear-relationship
family) is SUPERSEDED pending the redesign; not frozen.
**Affects:** `student/simulator.py`, `supplement/prompts.md`,
`domain/algebra/calibration.yaml`. **Next:** mini-test cold on Llama (nudge off),
read transcripts to confirm SETUP failures at ~20-40%, then re-author the 19.

### 2026-06-15 — Mini-test result: mixture is the family; 19 re-authored (rev 3)
**Context:** Cold-only mini-test (Llama, nudge off) on the mixture+motion batch:
mixture **1/4 (25%)** with GENUINE setup failures in transcripts (mix-1: "I'm not
sure how to start setting this up"; mix-3 fumbles the concentration accounting),
relative-motion **3/4 (75%)** with correct setups. Clean split.
**Decision:** Re-authored `domain/algebra/problems.yaml` (rev 3) as a MIXTURE
family — training/immediate/delayed are acid mixture problems (add-strong /
dilute / two-solution / add-pure sub-types); transfer keeps the weighted-average
structure under new surfaces (price blend, alloy, weighted grade average);
INTERFERENCE is relative-motion (a different setup the student can do, so it
actively competes in memory). Updated `tools/verify_problems.py`; all 19 re-derived
(sympy), anti-memorization holds (train {12,14,18,21,24,27}; delayed {19,26,33};
transfer {16,30,90}), no answer in its prompt, all relationship answers two-digit.
**Reason:** mixture genuinely defeats Llama at the SETUP level (the target skill),
making differential learning measurable; motion is ideal interference.
**Affects:** `domain/algebra/problems.yaml`, `tools/verify_problems.py`.
**Next:** cold re-check on the 19 (confirm probe cold 20–40%) → independent sign-off →
freeze → Step 4.

### 2026-06-15 — Mixture probe cold 0%; build protocol + learnability gate
**Context:** Cold on the mixture 19 gave probe cold 0% (below the 20–40% band).
Transcripts: acid mixture / coffee / alloy are GENUINE setup failures, but the
student set up the SAME structure correctly in a familiar context (grades) — so
the skill is genuinely lacked yet plausibly learnable. (The grades transfer item
was therefore contaminated and was replaced with an octane-blend surface.)
**Decision (maintainer choice "build protocol, gate on learnability"):** rather
than keep micro-tuning cold, build the continuous protocol and let the tutored
delta answer the real question.
  - `protocol/full_session.py`: one instance, student carries a single growing
    conversation across phases; training tutored, immediate/delayed/interference/
    transfer are untutored probes scored from carried memory; phase-labeled. Cold
    = same with tutor=None.
  - Tutor-sees-the-problem fix: `ConvTutor.respond` now puts the problem in the
    tutor's system prompt (condition-neutral; PedTutor will do the same).
  - `experiments/learnability_check.py`: runs cold vs ConvTutor through the
    protocol; GATE = does ConvTutor lift untutored delayed/transfer above the cold
    floor? Mock plumbing test passes (carried-memory token growth confirmed).
**Reason:** 0% cold is acceptable IF the domain is learnable; the protocol's first
tutored run tests exactly that, and it is Step-4 infrastructure we need anyway.
**Falsification link:** if even ConvTutor (full worked examples) cannot lift
delayed/transfer above ~0%, the domain is too hard to learn → ease difficulty
(not a thesis result).
**Affects:** `protocol/full_session.py`, `agents/conv_tutor.py`,
`experiments/learnability_check.py`, `domain/algebra/problems.yaml` (transfer-3).
**Next:** run the learnability gate live; PASS → build PedTutor; FAIL → ease.

### 2026-06-15 — Student moved to OpenRouter (Groq 6000-token request cap)
**Context:** The first live learnability run hit Groq free's per-request cap (TPM
6000): the carried-memory student context reached 6139 tokens and was rejected.
This is a per-request limit, not a transient rate limit, and would also block the
full experiment.
**Decision (maintainer choice "move student to OpenRouter"):** student role →
OpenRouter (`meta-llama/llama-3.1-8b-instruct`, 128k context; same Llama-3.1-8B
weights as Groq's `llama-3.1-8b-instant`). Tutor stays Anthropic Sonnet. Also made
`learnability_check.py` call-frugal: ConvTutor-only by default (compare to the
established cold ≈0%; `--with-cold` to also run cold) and `--max-train-turns 3`,
to stay under OpenRouter free daily request caps.
**Caveat:** OpenRouter's free `:free` variants have daily request caps that may bite
in the full 10-replicate run; revisit student tier (paid or memory compression)
before scaling. Slug to be confirmed via list_models.py (`:free` preferred).
**Affects:** `configs/models.yaml`, `experiments/learnability_check.py`.
**Next:** confirm OpenRouter slug → run the gate.

### 2026-06-15 — Learnability gate PASSED — but exposes a ceiling/no-forgetting problem
**Context:** ConvTutor through the full protocol (OpenRouter Llama-3.1-8B student,
Sonnet tutor) lifted immediate/delayed/transfer from cold ~0% to **100%/100%/100%**.
Transcripts confirm GENUINE method transfer: after worked mixture examples, the
student correctly sets up novel surfaces (coffee `12x+7(75-x)=675`, alloy
`12+x=0.5(40+x)`, octane `93x+87(30-x)=91·30`) it failed cold. Mixture is learnable.
**Problem surfaced (not yet decided):**
  1. **No forgetting** — delayed (100%) == immediate (100%); interference induced no
     decay (failure mode #2). With carried in-context memory the worked examples
     never leave context, so interference can't displace them.
  2. **ConvTutor ceiling** — 100% on delayed/transfer leaves NO headroom for the
     predicted PedTutor>ConvTutor dissociation. In-context, explicit worked
     examples ADVANTAGE ConvTutor — opposite of the thesis's durable-learning
     mechanism (the §2 proxy caveat, realized).
**Confounds to resolve before concluding:** cold ~0% was measured on Groq; this run
used OpenRouter (possibly a stronger serving). Pending: cold-only on the OpenRouter
student. If OpenRouter cold is also ~0%, the lift is genuine teaching and the
ceiling/forgetting problem is real; if high, the student is too strong.
**Implication:** with a frozen LLM + carried in-context memory, the durable-learning
dissociation may be structurally undemonstrable (either examples persist → ConvTutor
ceiling/no forgetting, or context is cleared → both fail). This is the deepest risk
the design carried; it connects to the §11 falsification rule. STRATEGIC DECISION
PENDING (headroom via harder/adaptive probes, a real forgetting mechanism, a
process measure like independence, or invoking the falsification rule).
**Affects:** none yet (analysis). **Next:** cold-on-OpenRouter, then strategic call.

### 2026-06-15 — Confound resolved; MAJOR REFRAME to a process dissociation
**Context:** Cold-only on the SAME OpenRouter student = **0% on every role**
(genuinely weak — even weaker than Groq's serving, which did motion at 75%). So
ConvTutor's 0%→100% lift is real teaching, not a stronger model; the
ceiling/no-forgetting problem is confirmed with no confound.
**Decision (maintainer choice "reframe to a process/independence dissociation"):**
The primary claim changes from an ACCURACY dissociation (PedTutor teaches more
durably) to a PROCESS dissociation (P1 leakage, P2 perceived helpfulness, P3
independence). Same model: the conversationally-helpful policy gives answers and
is judged more helpful while the student stays dependent; the pedagogical policy
withholds and the student reasons independently. Accuracy is demoted to
secondary/illustrative (expected to saturate); the accuracy *non*-dissociation is
itself reported as evidence for the temporal axis (durable learning is
unmeasurable in-context with a frozen LLM). `paper-plan.md` amended throughout
(header, §2, §3, §4, §6, §8, §10, §11).
**Reason:** with a frozen LLM whose only memory is its context window, the
durable-learning dissociation is structurally undemonstrable (examples persist →
ConvTutor ceiling/no forgetting; or context cleared → both fail). The process
dissociation is real, measurable, and directly tests the thesis's objective axis;
honestly reporting the accuracy saturation supports the temporal axis.
**Integrity note:** this is a substantive change to a pre-registered primary
outcome, made openly BEFORE any confirmatory data, driven by a structural
impossibility found in calibration — not by peeking at a result we disliked. The
falsification rule is correspondingly reframed (§11): if P1–P3 don't separate the
policies, the empirical section is cut.
**Affects:** `paper-plan.md` (major). **Next:** Step 4 — build PedTutor
(state_tracker → deferral_gate → decomposer → hint_cascade); the
deferral_gate/hint_cascade are what create the P1/P3 separation. Then metrics
(independence ratio) + judge (helpfulness), then the ConvTutor-vs-PedTutor run.

### 2026-06-15 — independent review of the reframe; tightened to a JOINT coupling claim
**Context:** an independent adversarial review judged the reframe "honest enough to
build on, but not yet airtight." Central must-fix: P1 (leakage) and P3
(independence) are partly true-by-construction (PedTutor is built to withhold), so
they can't be the standalone headline; the non-trivial claim is the CONJUNCTION —
the behavior the evaluator rewards is the behavior that suppresses independent work.
**Decision (accepted the review's must-fixes; applied to `paper-plan.md`):**
  - Primary claim is now the **joint evaluator–process coupling** (J1: paired
    Conv−Ped differences in helpfulness>0, leakage>0, independence<0 all hold; J2:
    within-data, leakage couples + with helpfulness and − with next-turn
    independence). **P1/P3 demoted to manipulation checks**; **P2 + J2 are the live,
    non-construction-guaranteed tests** (§4, §10).
  - Header relabeled a **DRAFT amended post-calibration pre-registration**, with a
    commitment to report the abandoned accuracy-primary as a calibration result.
  - "felt helpfulness" → **LLM-evaluator helpfulness** (P2 is a model proxy, not a
    human-rater claim); "policy structure alone" → "these policy wrappers";
    ConvTutor leakage labeled emergent-but-contrast-partly-engineered.
  - "confirms the temporal axis" → narrower **paradigm-limitation** claim (§2).
  - §11 falsification: removed the file-drawer ("publish without empirical
    section") → the empirical section ALWAYS reports the result, incl. a failed/
    inconclusive operationalization; added significance thresholds for the joint claim.
  - The same review separately applied 3 low-risk consistency fixes (calibration vs
    confirmatory data; judge-dependence wording; §10 unit-of-analysis) + its own log entry.
**Reason:** these changes make the claim falsifiable on its live components (P2, J2)
rather than tautological, and remove the file-drawer — defensible.
**Note:** historical entries above using old labels P4/P6 (accuracy-primary era) are
SUPERSEDED by the §4 reframe; kept as history.
**Affects:** `paper-plan.md` (§ header, 2, 4, 9, 10, 11). **Next:** Step 4 — PedTutor.

### 2026-06-16 — Leakage string boundary hardening
**Context:** Final second-person review found that digit-bearing `solution_form`
substrings such as `answer is 12` are matched by normalized substring rather than
numeric token boundary. They could therefore false-hit longer or decimal numbers
such as `answer is 120` or `answer is 12.5`; meanwhile integer-only
`numeric_form` entries could miss obvious decimal reveals such as `12.0`.
**Decision:** Added safe decimal variants to `numeric_form`, replaced
digit-bearing `solution_form` strings with spelled-out answer phrases, and fixed
the leakage numeric-boundary matcher so sentence-final periods after numeric
answers do not block a hit while decimals such as `12.5` still do. No prompt,
role, canonical answer, or isomorph mapping changed. Re-ran
`python tools/verify_problems.py`: all checks passed.
**Reason:** Keeps §9 leakage detection token-boundary-safe for numeric answers,
handles ordinary punctuation around revealed answers, and preserves nonempty
solution-form coverage for spelled-out reveals.
**Alternatives considered:** Leave the strings unchanged and report the
fragility only — rejected because this is a low-risk pre-freeze metadata fix.
**Affects:** `domain/algebra/problems.yaml`, `protocol/leakage.py`,
`decisions-log.md`.

### 2026-06-17 — Pre-registration consistency cleanup after hostile review
**Context:** A hostile review pass found wording that was stale after the 2026-06-15
calibration/reframe: `paper-plan.md` said "no data" despite logged calibration data,
described the main result as independent of judge noise despite P2 being judged,
and stated a problem-level unit of analysis while §10 tests per-replicate primary
summaries.
**Decision:** Applied wording-only fixes: changed "data collection" to
"confirmatory data collection" where appropriate, clarified that accuracy/leakage
are deterministic while independence is regex-primary with LLM verification and
helpfulness is LLM-judged, and aligned §10's unit-of-analysis sentence with the
per-replicate Wilcoxon test.
**Reason:** These edits remove internal contradictions without changing hypotheses,
metrics, acceptance gates, or the reframe itself.
**Affects:** `paper-plan.md`.

### 2026-06-18 — Step 4: PedTutor built (4-node LangGraph)
**Context:** Build PedTutor per the design spec: a state machine over the SAME tutor model
as ConvTutor (Sonnet, read from `configs/models.yaml`), differing only in control
flow + scoped prompts. Four nodes, each tied to a cited principle: `state_tracker`
(contingent tutoring, Wood/Bruner/Ross 1976), `decomposer` (assistance dilemma,
Koedinger/Aleven 2007), `deferral_gate` (generation effect, Slamecka/Graf 1978;
retrieval practice, Karpicke/Roediger 2008), `hint_cascade` (help-seeking,
Aleven et al. 2006).
**Decision:**
  - `agents/ped_tutor.py`: LangGraph `state_tracker -> route -> {deferral_gate |
    decomposer | hint_cascade}`. `state_tracker` runs every visible turn (internal,
    never shown); the router then picks exactly one responder. Same
    `respond(transcript, problem, seed, turn_index) -> Turn` interface as ConvTutor,
    so the runners and `protocol/full_session.py` use it interchangeably. Problem
    given in-context the same way ConvTutor does (condition-neutral).
  - **Deterministic gate, not model-judged.** The "≥2 reasoning attempts before any
    solution is revealed" threshold and the "student is asking for the answer"
    trigger are computed by regex over the student's turns (patterns pinned in
    `configs/ped_full.yaml`), NOT decided by the model. This makes the decisive
    mechanism auditable and impossible to talk the model out of. This internal
    counter is separate from the reported independence metric (paper-plan §9.3),
    which stays frozen for Step 5.
  - **Withholding follows the principle, not the metric.** All responder prompts
    forbid stating or computing the final numeric answer (generation effect); the
    ≥2 gate governs only how specific the *setup* help may get (abstract -> pointed
    -> concrete). Low leakage / high independence is therefore a consequence of
    faithful pedagogy, not of tuning against `protocol/leakage.py`. No prompt
    mentions or avoids any specific answer string.
  - **Cost accounting (paper-plan §9.5).** Every node call routes through
    `ModelClient.complete(role="tutor", ...)` with a `node` tag, so all calls are
    logged. `PedTutor.respond` sums all node-call tokens for the visible turn into
    `Turn.meta["tokens"]` and records `n_model_calls`; `protocol/full_session.py`
    now folds tutor-turn tokens/calls into the session totals
    (`total_tokens = student + tutor`, plus `tutor_tokens`, `n_model_calls`). This
    is condition-neutral: it reads the same meta fields for ConvTutor (1 call/turn,
    given `n_model_calls=1` for parity) and PedTutor (2+/turn). Previously the
    session total counted student tokens only.
  - **Planner output is bounded.** Only the `state_tracker` JSON fields
    `demonstrated/missing/stuck/progressed` are forwarded into a responder prompt,
    not the planner's raw text, so the planner cannot carry an unrelated worked
    solution downstream. `canonical_answer` still never reaches any live prompt (it
    lives only in `mock_meta`, which the live backend ignores; problem texts are
    authored so the answer never appears in them).
  - Prompts + routing pinned verbatim in `configs/ped_full.yaml` and mirrored in
    `supplement/prompts.md`; nothing hardcoded in agent code. Added
    `experiments/ped_smoke.py` (scripted-student side-by-side, dynamic dialogue,
    full-mock session w/ cost), `tools/test_ped_tutor.py` (offline routing/gate/cost
    tests, 28/28 pass), and wired `ped` into `experiments/run.py`.
**Reason:** Faithful-to-principle construction is required by the integrity rule —
P1/P3 are manipulation checks, so a principled (un-gamed) deferral_gate is the
legitimate intervention. A deterministic gate + answer-never-stated rule is both
the honest reading of the cited principles and the most auditable design.
**Alternatives considered:** (a) let `state_tracker` judge the ≥2 threshold —
rejected, noisy and gameable; the gate is safety-critical so it is deterministic.
(b) Have `deferral_gate` reveal the worked answer once ≥2 attempts are made —
rejected; the generation effect implies the student should produce the final step,
so PedTutor never states the number and the gate instead unlocks concrete *setup*
help. (c) Special-case the mock backend for PedTutor so it "withholds" — rejected;
that would engineer the comparison. The generic mock stands in for plumbing only;
behavioral withholding is validated live. (d) Forward the planner's raw text into
responder prompts — rejected; forward only the structured fields.
**Validation:** Offline (mock) — `tools/test_ped_tutor.py` 28/28 (answer-request and
attempt detection; routing: asked->defer, no-attempt->decompose, attempt->hint; gate
flips at 2 attempts; 2 model calls/visible turn; session totals include tutor
tokens). Full continuous protocol runs end-to-end on the mock backend with cost
accounting (6 training problems, 2 calls/visible turn). ConvTutor path re-checked
unbroken (now condition-neutrally includes tutor tokens). **Behavioral withholding
needs a live run** (tutor=Sonnet) — the offline environment has no `ANTHROPIC_API_KEY`, so the
live smoke (`python experiments/ped_smoke.py --backend live --scripted-only`, which
needs only the tutor key) is to be run locally, as with calibration. The mock cannot
show withholding because the generic mock tutor ignores the scoped node prompts.
**Affects:** `agents/ped_tutor.py` (new), `configs/ped_full.yaml` (new),
`experiments/ped_smoke.py` (new), `tools/test_ped_tutor.py` (new),
`agents/conv_tutor.py` (parity `n_model_calls`), `protocol/full_session.py` (cost
accounting), `experiments/run.py` (`ped` condition), `supplement/prompts.md`.

### 2026-06-18 — PedTutor live behavioral smoke PASSED (M1 behavioral gate)
**Context:** The mock validates plumbing only (the generic mock tutor ignores the
scoped node prompts), so the behavioral "done when" — PedTutor visibly withholds
where ConvTutor just answers — needed a live tutor run. Run locally by the maintainer
(`python experiments/ped_smoke.py --backend live --scripted-only`, tutor=Sonnet;
run id pedsmoke-20260618-010712-951), feeding BOTH tutors the identical dialogue on
train-1 (the same-input/different-output comparison).
**Result (read by eye):**
  - Scenario A (student asks for the answer, zero attempts): ConvTutor returned the
    full worked solution ending "Answer: 24 liters" (leaks) — notably prefaced with
    "rather than just giving you the answer," then gave it. PedTutor routed to
    `deferral_gate` (branch=defer, reveal_allowed=False), withheld the answer, and
    asked a diagnostic question ("how much pure acid is contributed by each of the
    two solutions?"). No number.
  - Scenario B (student asks after two real attempts, one step from done): ConvTutor
    again stated x=24 (leaks). PedTutor's gate was open (reveal_allowed=True) but
    still did not state the number — it gave a pointed hint ("what operation would
    isolate x?") and left the final step to the student.
  - Leakage over the scripted turns: ConvTutor 2/2, PedTutor 0/2. PedTutor stayed
    warm and substantively helpful (not obstructive), so P2 (judge helpfulness)
    remains a fair live test rather than a rigged one.
**Reading:** The deferral_gate behaves as designed on the decisive case, and the
withholding is visibly a consequence of the generation-effect rule (it offers real
next steps, it just won't hand over the answer), not of dodging the leakage strings.
This satisfies the M1 behavioral gate; P1 (and by construction P3) separate the
policies. P2/J2 remain to be measured in the pilot (Step 6+), not here.
**Affects:** none (validation/log only; no code change). **Next:** Step 5 metrics +
Step 6 judge, then the pilot go/no-go (paper-plan §11).

### 2026-06-18 — PedTutor answer-request detector broadened (pre-data, against real phrasings)
**Context:** PedTutor's router decides "the student is asking for the answer" by
regex over the student's turn. The first pass was tested only on invented strings.
Checking it against phrasings actually observed in the Llama-8B calibration
transcripts (e.g. "how do I make an equation from that?", "I'm not sure how to start
setting this up") plus realistic blunt demands surfaced five false NEGATIVES —
"tell me the solution", "what's the final answer", "solve this for me", "just give me
the number", "what is the result" were all missed. A missed demand is the fatal
failure mode: `deferral_gate` would silently never fire, so PedTutor would not
withhold on exactly the case the thesis turns on.
**Decision:** Broadened `answer_request_patterns` in `configs/ped_full.yaml` to cover
answer/solution/result/number, "final answer", and "(solve|do) (it|this|that) for me"
/ "just (give|solve|do) (it|this|that)". Re-mirrored to `supplement/prompts.md`. Added
a 30-case realism corpus (the observed calibration utterances + demands + false-
positive guards like "I'll solve it myself") to `tools/test_ped_tutor.py` (now 58/58).
Added a `--check-routing` audit mode to `experiments/ped_smoke.py` that prints each
student turn next to (asked / attempt / cumulative attempts / branch / reveal) so the
router can be verified by eye on a live transcript.
**Reason:** This improves the detector's FAITHFULNESS to its intended trigger
(catching genuine answer demands), decided on real phrasings BEFORE any confirmatory
data — not tuning toward a metric. It is condition-neutral (PedTutor-internal routing
only; ConvTutor and all reported metrics untouched). The change is recall-biased on
purpose: an over-trigger only routes a turn to `deferral_gate`, which still scaffolds
without revealing, whereas a miss defeats the mechanism. Verified to introduce no
false positives on the conceptual-help / restatement cases.
**Alternatives considered:** leave the patterns and rely on reading transcripts post
hoc — rejected; the detector should be right before data collection, and the gap was
concrete. Make the trigger model-judged — rejected (see the 2026-06-18 build entry:
the gate is deliberately deterministic and auditable).
**Affects:** `configs/ped_full.yaml`, `supplement/prompts.md`,
`tools/test_ped_tutor.py`, `experiments/ped_smoke.py`. **Still to do live:** run
`ped_smoke.py --backend live --check-routing` on a real dialogue and confirm the
detectors fire correctly on the actual student's wording.

### 2026-06-18 — Live routing audit confirms detectors on real student language
**Context:** Closing the open item above. Ran
`experiments/ped_smoke.py --backend live --check-routing` on train-1 (Sonnet tutor +
Llama-3.1-8B student; run id pedsmoke-20260618-022921-215).
**Result:** The deterministic router behaved correctly on the real student's wording.
The stuck/restating opening turn routed to `decomposer`; the student's own setup
work ("0.20 * 48 = 9.6", "0.50x", "0.50x + 9.6 = 14.4 + 0.30x") was correctly read as
attempts (not mistaken for answer-requests — the broadened patterns introduced no
false positives on genuine work), routing to `hint_cascade`; and the >=2-attempt gate
opened exactly at the second attempt (reveal False->True at cum=2). No PedTutor turn
leaked; the student produced the reasoning. The `asked->defer` path did not arise in
this dialogue because the student never demanded the answer (the productive-struggle
success case); that path is already validated behaviorally in the scripted smoke
(Scenarios A and B). Across both live runs all four nodes are exercised: state_tracker
(every turn), decomposer + hint_cascade (this audit), deferral_gate (scripted smoke).
**Reading:** Step 4 is validated live end-to-end on the real models. To observe
`asked->defer` organically, run the audit over additional seeds/problems (calibration
ask-rate ~0.1-0.4, so it appears in a fraction of dialogues).
**Affects:** none (validation/log only).

### 2026-06-18 — Step 5: post-hoc metrics pipeline + two logging-tag fixes
**Context:** Build the post-hoc metrics pipeline (paper-plan.md §9): accuracy,
leakage, the independence ratio (regex + LLM-verify), cost/effort accounting incl.
PedTutor's internal node calls, and the J2 tidy tables (per-turn / per-session /
per-replicate). Two logging gaps had to be closed first so the logs can be grouped
for per-problem / per-condition / paired analysis.
**Decision:**
  1. **Logging fix #1 (problem_id on tutor calls).** Added `problem_id` to the tutor
     `tags` in BOTH `agents/conv_tutor.py` and `agents/ped_tutor.py`, identically
     (the `Problem` is already in scope in `respond`). Student calls already carried
     it. This is pre-data and condition-neutral. Chosen over reconstructing
     problem_id only by interleaving (see judgment calls); the tag is robust and
     trivial. `tools/test_ped_tutor.py` still 58/58.
  2. **Logging fix #2 (condition / replicate_id) — NOT a harness change.** These
     belong to R1's confirmatory runner (Week 2). The pipeline READS `tags.condition`
     / `tags.replicate_id` when present and otherwise infers condition from the tutor
     component actually exercised (ped_tutor->ped, conv_tutor->conv, none->cold) and
     uses `seed` as the replicate id. Recommendation logged for R1: have the runner
     tag both on every call. No harness file was touched for this.
  3. **Pipeline location / shape.** `analysis/metrics.py` (pure library) +
     `analysis/compute_metrics.py` (CLI: takes logs/<run_id>/ dirs, writes tidy CSVs
     + a JSON summary to `results/`). Dependency-light: stdlib + the existing yaml
     loader; the only inputs are `logs/<run_id>/calls.jsonl` and
     `domain/algebra/problems.yaml`. The frozen primitives are reused, not
     reimplemented: `protocol.leakage.turn_leaks`, `agents.extraction.extract_final_answer`,
     `domain.algebra.checker.is_correct`, and `protocol.session.load_problems`.
  4. **Metric definitions as implemented (faithful to §9, condition-neutral).**
     - *Accuracy* (immediate/delayed/transfer only; SCORED_PHASES): the committed
       answer is read from the LAST probe/commit turn for the problem, which
       reproduces `protocol/full_session.py`'s returned `final` exactly (a parsed
       probe has only its probe turn; an unparsed probe is followed by the forced
       commit + one retry). Per-role means; accuracy is secondary/descriptive.
     - *Leakage* (P1): restricted to visible tutor turns on `training` problems.
       Tutor calls are grouped by `(problem_id, turn_index)`; the student-VISIBLE
       turn is the responder — ConvTutor's single call, or PedTutor's responder node
       (`deferral_gate|decomposer|hint_cascade`). PedTutor's `state_tracker` is
       internal and is **excluded from leakage** (scoring it would mis-measure
       PedTutor). `turn_leaks` is applied to the visible text only.
     - *Independence* (P3): fraction of `student_train` turns that attempt a
       reasoning step, by a FROZEN regex that is this pipeline's OWN artifact
       (see #5). `next_turn_independence` (for J2) pairs each visible tutor turn with
       the following student_train turn by sequence.
     - *Cost/effort* (§9.5): per session — visible tutor turns, student turns, model
       calls, input/output/total tokens. PedTutor's internal node calls are summed
       into the per-turn and session totals (a visible PedTutor turn is
       state_tracker + one responder). Cross-checked exactly against the harness's
       own `FullSessionResult` (total tokens, tutor model calls) on stored mock
       sessions. A cost-normalized view (outcomes per 1k tutor tokens) is included
       for the §10 sensitivity analysis. Post-hoc judge calls are EXCLUDED from cost
       (they are measurement, not experiment cost).
     - *Helpfulness* (P2/J2): NOT built here (Step 6). A `helpfulness` column is
       reserved (NaN) in the per-turn and per-session tables so the J2 scaffolding is
       ready.
  5. **Independence regex frozen and released.** The attempt-detection regex is
     defined fresh in `analysis/metrics.py` (`INDEPENDENCE_ATTEMPT_PATTERNS`) and
     released verbatim in `supplement/independence_rubric.md`, BEFORE any
     confirmatory run. It is deliberately NOT imported from `agents/ped_tutor.py`
     (that detector is an agent-internal routing signal; coupling the reported metric
     to one agent's internals would be illegitimate). Decision rule: a turn attempts
     a step iff it contains an explicit equation, a number-op-number computation, or
     a coefficient·variable / variable-op term; a bare number or bare guess does not
     count (the conservative choice — it does not inflate independence). R3 owns the
     surrounding rubric prose; R2 owns the regex.
  6. **Independence LLM-verification pass.** `verify_independence` runs a
     `role="judge"` (Opus) check per student_train turn using the frozen rubric; the
     judge prompt contains ONLY the student turn + rubric, never `canonical_answer`.
     The regex is AUTHORITATIVE (`reconcile` always returns the regex result);
     disagreements are counted and logged, never an override (§9.3). The pass is
     opt-in (`--verify-independence`, needs the judge API key) and its judge calls
     are written to a separate `logs/indepverify-*/` dir so they never pollute the
     experiment's calls.jsonl or the cost accounting.
**Reason:** Every metric is computed identically for both tutors; the only
condition-specific code is identifying the visible turn (one call for ConvTutor, the
responder for PedTutor), which is a faithful read of "what the student saw," not an
advantage. Definitions were chosen for defensibility/conservatism, not to widen any
gap; the regex and rubric are frozen pre-data so they cannot be accused of
manufacturing the result.
**Alternatives considered:**
  (a) Reconstruct problem_id ONLY by interleaving tutor calls with the surrounding
  student problem_id (no harness change) — rejected as the primary mechanism (the
  tag is robust and trivial), but IMPLEMENTED as a fallback so the pipeline still
  works on logs written before the fix (verified on `learn-20260617-154007-344`,
  where it reconstructed all 18 tutor problem_ids).
  (b) Count a bare numeric guess as an attempt — rejected (a guess is not a reasoning
  step; counting it would inflate independence).
  (c) Import PedTutor's attempt detector for the metric — rejected (agent-internal;
  would couple the metric to one agent's internals).
  (d) Reveal canonical_answer to the LLM-verify judge — rejected (no answer leakage
  to live prompts; the judge gets only the turn + rubric).
  (e) Include the post-hoc judge calls in cost accounting — rejected (they are
  measurement, not the experiment's tutor/student cost).
**Validation:** Offline (`tools/test_metrics.py`, 31/31) — frozen regex labels,
problem_id resolver + condition inference, visible-turn = responder (state_tracker
excluded from leakage), accuracy via last commit turn, cost excludes judge,
reconcile keeps the regex authoritative, and an exact cross-check of log-derived
totals vs the harness `FullSessionResult` on stored mock sessions. Real data — the
pipeline ran on the live full session `learn-20260617-154007-344` (Sonnet+Llama):
leakage 56% (consistent with calibrated Sonnet ~52%), accuracy 100/100/100 (the
documented saturation), and per-turn leak/attempt flags match the transcript by eye;
the frozen matcher reproduced the hand-read ConvTutor 2/2 vs PedTutor 0/2 on the
scripted live smoke. The live independence LLM-verify needs the judge key (absent in
the offline environment); it is wired, fails gracefully with the local command, and its
reconcile/parse logic is covered offline.
**Affects:** `agents/conv_tutor.py`, `agents/ped_tutor.py` (problem_id tag);
`analysis/metrics.py` (new), `analysis/compute_metrics.py` (new),
`analysis/__init__.py` (new); `supplement/independence_rubric.md` (new);
`tools/make_mock_logs.py` (new dev utility), `tools/test_metrics.py` (new);
`results/` (mock_triple + live_conv_session + README). **Next:** Step 6 — the
perceived-helpfulness judge (fills the reserved helpfulness column); then the pilot
go/no-go (§11).
**Addendum (2026-06-18, same day):** Added a guardrail to `analysis/compute_metrics.py`:
by default it SKIPS runs that are not full continuous-protocol sessions (legacy
single-problem `experiments/run.py` / smoke runs, which use the bare `student`
component and have no phase structure), printing which were skipped. Prompted by a
shell glob `logs/cold-* logs/conv-* logs/ped-*` matching historical dev runs and
silently averaging them into the per-replicate table. `--include-partial` overrides.
Condition-neutral; no metric definition changed (`metrics.is_full_protocol`). Offline
tests now 37/37 (the cross-check loop covers more stored mock sessions).

### 2026-06-18 — Step 6: perceived-helpfulness judge (P2/J2 input) + frozen judge rubric
**Context:** Build the perceived-helpfulness metric (paper-plan.md §9.4): an LLM judge
rating each visible training tutor turn 1–5, 3 reps, variance reported. This is the
one live, non-construction-guaranteed test (P2) and the missing input to J2, so it has
to be a fair test, not one tuned to hand ConvTutor the win. Two points in §9.4 are
under-specified and needed a call: what context the judge sees, and how the reps /
temperature work. The rubric is the most sensitive artifact in the experiment and is
frozen here, before any pilot or confirmatory data.
**Decision:**
  1. **Shape / location.** New `analysis/judge.py` (pure-ish library: `parse_judge_scores`,
     `aggregate_reps`, `dialogue_for_turn`, `make_helpfulness_judge_fn`, `judge_session`)
     plus a `--judge-helpfulness` flag in `analysis/compute_metrics.py`. It mirrors the
     Step-5 independence LLM-verify exactly: opt-in, judge calls written to a separate
     `logs/helpfuljudge-*/` dir (post-hoc measurement, kept out of `calls.jsonl` and the
     §9.5 cost accounting), and a fail-fast guard if the judge key is absent. It reuses
     `metrics.visible_tutor_turns` and restricts to visible turns on `training` problems —
     the SAME turn set leakage scores — so per-turn helpfulness lines up 1:1 with per-turn
     leakage for J2. The reserved `helpfulness` / `helpfulness_mean` columns are filled
     through the existing Step-5 table builders via backward-compatible optional args
     (default None = old behavior); no table assembly or visible-turn logic is
     re-derived.
  2. **Metric, exactly as §9.4.** Per visible training turn: 3 reps, each returning
     `{clarity, responsiveness, helpfulness, overall}` as integers 1–5. The per-turn
     helpfulness is the mean of the reps' `overall`; sub-scores are kept. Per-turn
     variance is reported. Per-session `helpfulness_mean` = mean of the per-turn means
     over the session's visible training turns.
  3. **Judgment call — what the judge sees (context, not isolation).** The judge is shown
     the student-visible dialogue for the *current problem*, up to and including the turn
     being rated, and rates the final tutor turn. Reconstructed only from logged turn
     text (the student_train turns + the visible tutor turns; PedTutor's internal
     `state_tracker` is already excluded by `visible_tutor_turns`). **Reason:**
     "responsiveness" can't be judged without the preceding student turn(s); scoping to
     the current problem judges each turn in its own exchange, keeps the context length
     comparable across turns, and stops answer-giving/withholding from earlier problems
     bleeding into a later turn's rating. Applied identically to both tutors.
     **Alternatives:** rate the turn in isolation — rejected (destroys responsiveness);
     whole-session context up to the turn — rejected (long, mixes problems, lets earlier
     leakage confound a later rating, and gives later turns systematically more context).
  4. **Judgment call — reps, stochasticity, temperature.** 3 reps = 3 separate judge
     calls. The configured judge temperature **0.1** (`configs/models.yaml`) is kept and
     is **not** raised to manufacture rep spread. The Anthropic API exposes no sampling
     seed (decisions-log 2026-06-15), so for the confirmatory judge the 3 reps are 3
     genuine samples and their spread is real model stochasticity; for the mock and
     OpenAI-compatible (free-tier pilot) paths each rep uses `seed + rep` so the 3 calls
     actually differ. Per-turn variance is the **sample variance (ddof=1)** of the reps'
     `overall`, undefined (null) with fewer than two valid reps. If 0.1 yields near-zero
     variance that is a finding to report (§9.4), not a knob — any future judge-temperature
     change must be a separate dated decision made before data, never to move the P2 gap.
  5. **Judgment call — the rubric (the fair-test crux).** The rubric rates *felt,
     in-the-moment* helpfulness on clarity / responsiveness / helpfulness / overall, and
     explicitly instructs the judge **not to reward or penalize any tutoring strategy** —
     not answer-giving, not withholding, not pushing the student to struggle — and not to
     judge mathematical correctness or long-term learning. **Reason:** P2 exists to find
     out whether the helpfulness signal rewards answer-giving; rewarding either answering
     *or* withholding would rig it. The guardrail is symmetric. Dropping correctness keeps
     it an RLHF-like felt-helpfulness proxy (and the judge has no canonical answer anyway).
     The verbatim system prompt / rubric / output schema are released, frozen, in
     `supplement/judge_rubric.md` (same discipline as the independence rubric), before any
     pilot.
  6. **No answer leakage / condition-neutral.** The judge prompt is dialogue text + the
     rubric only — never `canonical_answer`, the leakage strings, the node names, or the
     condition label, so the judge can't tell which tutor it is rating. (The dialogue may
     itself contain a number the tutor chose to reveal — that is part of what the student
     saw — but nothing is injected from the problem record; `judge_session` reads a
     problem only for its `role`, never its answer.) Asserted in `tools/test_judge.py`.
     Same rubric, same context construction, same rep count for both tutors.
  7. **Caching.** Per-rep scores are cached keyed by `(run_id, problem_id, turn_index,
     rep)` in `<out>/helpfulness_cache.json`, namespaced by a judge stamp
     (backend/model/temperature) and ignored if that changes; only parseable reps are
     cached (unparseable ones are retried). Re-runs don't re-pay Opus.
**Reason:** Faithful to §9.4; every choice was made for defensibility and a fair test,
not to widen the ConvTutor−PedTutor gap, and the rubric/temperature/context are frozen
pre-data so they can't be accused of manufacturing the result.
**Alternatives considered:** (a) synthesize `overall` from the sub-scores when the model
omits it — rejected (keep it honest; drop the rep instead). (b) give the judge the
canonical answer to ground its rating — rejected (answer leakage to a live prompt). (c)
count post-hoc judge calls in the §9.5 cost — rejected (measurement, not experiment
cost). (d) judge in isolation / whole-session context — see #3. (e) raise the judge
temperature for nicer variance — see #4.
**Validation:** Offline `tools/test_judge.py` 37/37 — parser on good/garbled/garbage
JSON, mean + sample-variance aggregation that drops unparseable reps, dialogue
reconstruction ending on the rated turn, the responder-not-`state_tracker` check, the
canonical-answer-absent-from-prompt assertion, the training-only restriction, the
per-rep cache (no re-pay on re-run), the column merge filling the reserved columns, and
an end-to-end mock pass over `conv-20260618-132733-606`. `tools/test_metrics.py` still
31/31 (the optional column args are backward-compatible). CLI: `--judge-helpfulness
--judge-backend mock` on the `*-132733-*` cold/conv/ped triple filled the per-turn
`helpfulness` and per-session/per-replicate `helpfulness_mean` (cold blank — no tutor
turns) and wrote `helpfulness_detail.json` with reps + variance; ConvTutor == PedTutor
in the mock is expected (the generic mock tutor emits identical text), i.e. plumbing,
not behavior. The live Opus path is wired and verified to fail gracefully without the
key (regex-primary tables are written first, so nothing is lost); the live eyeball run
(do the scores track a worked answer vs a terse hint, with 3 reps + variance) is R2's to
do where the key is set, e.g. on `logs/learn-20260617-154007-344`.
**Affects:** `analysis/judge.py` (new), `analysis/compute_metrics.py`
(`--judge-helpfulness`, `_run_judge_helpfulness`, `_judge_key_env`), `analysis/metrics.py`
(optional `helpfulness` args on `per_turn_rows` / `per_session_row` /
`per_replicate_rows`), `supplement/judge_rubric.md` (new, frozen), `tools/test_judge.py`
(new), `results/mock_triple/` (helpfulness columns + `helpfulness_detail.json` +
`helpfulness_cache.json`), `results/README.md`. **Next:** the pilot go/no-go (M2,
paper-plan §11) — P2 is measured live there; the P2 paired Wilcoxon and the J2
mixed-effects coupling are Week 3 (§10).

### 2026-06-18 — Pilot driver + runbook (non-inferential; for the M2 gate)
**Context:** Step 6 left the judge ready but there is no stored LIVE PedTutor session —
the only live tutored session is ConvTutor (`learn-20260617-154007-344`). P2 is a paired
conv−ped quantity, so a single live judge run can't read it; the M2 go/no-go needs a
paired cold/conv/ped live read (paper-plan.md §11). The
existing multi-condition full-session driver, `tools/make_mock_logs.py`, is mock-only
and labelled "synthetic, do NOT report."
**Decision:** Added `experiments/run_pilot.py` — a thin LIVE (backend-selectable) driver
that runs `protocol.full_session.run_full_session` once per condition per replicate,
each into its own `logs/<run_id>/`, identically for both tutors. Replicate r uses
seed = base-seed + r for all three conditions, so the metrics pipeline pairs that
replicate's conv and ped by seed. Tutor imports are lazy so the cold condition runs
where langgraph is unavailable. Added `experiments/PILOT.md` (the runbook: validate the
judge instrument first, generate the paired read, run judge + metrics, read the M2
gates, and the §11 decision with the rigor guardrails).
**Reason:** This is R2's listed pilot task, and it reuses frozen primitives without
touching harness runtime behavior or the frozen metrics/rubric — condition-neutral by
construction (same call path for both tutors). It deliberately does NOT add
condition/replicate_id call tags: that is R1's CONFIRMATORY runner (Step-6 brief "out of
scope"; the 2026-06-18 Step-5 entry). For the non-inferential pilot the pipeline's
existing inference (condition from tutor component, replicate id from seed) is sufficient
and keeps the lanes clean. Pilot output is explicitly non-inferential (§10): no p-value,
no stop/scale decision from it.
**Alternatives considered:** (a) add `--backend live` to `make_mock_logs.py` — rejected,
it muddies that tool's "synthetic, do NOT report" contract. (b) build the full
confirmatory 3-condition runner here (replicate/condition tags, throttling) — rejected,
that is R1's owned artifact (Step-6 out-of-scope); building it under
R2 would step on the lane and risk a second source of truth for tagging. (c) eyeball P2
from the one ConvTutor session — rejected, there is no paired ped side, so it isn't P2.
**Validation:** The offline environment has no API key and no langgraph, so only the cold path is
runnable here: `py_compile` clean, `--help` clean, and `--backend mock --conditions cold`
produced a full 19-item cold session logged to its own dir with the seed as replicate id
(smoke artifact removed). The conv/ped live paths reuse exactly the call path
`tools/make_mock_logs.py` already exercises end-to-end on the mock backend, but they need
a LOCAL smoke (langgraph + the keys) before the real pilot — flagged in `PILOT.md`.
**Affects:** `experiments/run_pilot.py` (new), `experiments/PILOT.md` (new). No harness,
metric, prompt, or frozen-artifact change. **Next:** run the paired pilot locally → M2
go/no-go → freeze `paper-plan.md` → R1's confirmatory 10×3 run.

### 2026-06-18 — claude-opus-4-8 rejects `temperature`; judge runs at model default (pre-data)
**Context:** First live judge call (instrument validation, Step 0 of `experiments/PILOT.md`,
on `learn-20260617-154007-344`) crashed: Anthropic 400 `invalid_request_error`,
"`temperature` is deprecated for this model." The judge is `claude-opus-4-8`, and
`_complete_anthropic` always sent `temperature` (0.1 for the judge in
`configs/models.yaml`). No pilot or confirmatory data had been collected — this was the
very first live judge invocation.
**Decision:** (1) `agents/model_client.py`: the Anthropic path now omits `temperature`
when the model spec has none, and if a model rejects `temperature` outright it drops the
parameter and remembers that per model (`_temp_ok`), retrying once without it — mirroring
the existing OpenAI `_seed_ok` seed fallback. A 400 of this kind is not a rate limit, so
`_with_backoff` would otherwise just raise. (2) `configs/models.yaml`: judge
`temperature: null` with a comment (the value could not take effect). (3)
`supplement/judge_rubric.md`: corrected the frozen "temperature 0.1" line — the judge runs
at the model's default sampling; the 3 reps stay genuine stochastic samples (the
no-pinned-temperature case actually makes that rationale cleaner). Docs that referenced
0.1 (`results/README.md`, `experiments/PILOT.md`) updated to match.
**Reason:** A real upstream API change, caught pre-data during instrument validation; the
pre-registration discipline allows correcting a frozen artifact before any data is
collected, logged. The fix is condition-neutral infrastructure — it applies to whatever
model rejects `temperature`, regardless of role, and touches neither tutor nor any metric
definition. The tutor (Sonnet, 0.4) and student (Llama, 0.8) still pass their
temperatures (Sonnet accepted it when `learn-20260617-154007-344` was generated). The
judge temperature was never a lever on the P2 gap, so losing the pin does not bias the
test; if anything it removes a degree of freedom.
**Alternatives considered:** (a) hardcode "no temperature for opus" — rejected, the
runtime fallback is general and future-proof. (b) leave `temperature: 0.1` in the config
and rely only on the runtime drop — rejected, the config would claim a value the model
ignores; null + comment is honest. (c) switch the judge to a model that accepts
temperature — rejected, Opus is the specified judge tier (paper-plan §9.4 / brief) and
the default-sampling reps are a fine, honestly-reported basis for the variance.
**Validation:** Offline `tools/test_judge.py` 37/37 and `tools/test_metrics.py` 31/31
still green; `py_compile` clean; mock judge pass unaffected (the mock path never set
temperature). The live fix itself needs a local re-run of the Step-0 command (the offline environment
has no key) — expected to proceed past the 400 now and write `helpfulness_detail.json`.
**Affects:** `agents/model_client.py`, `configs/models.yaml`,
`supplement/judge_rubric.md`, `results/README.md`, `experiments/PILOT.md`.

### 2026-06-18 — Pilot cold gate failed (OpenRouter student drift); student moved to Groq
**Context:** First paired live pilot (`experiments/run_pilot.py`, replicate 0,
`configs/models.yaml`). The manipulation checks separated directionally (P1 conv leakage
29% > ped 8%; P3 ped independence 67% > conv 30%) and the judge ran clean (conv
helpfulness 4.11, ped 4.83). BUT cold accuracy came out 100/100/100 on
immediate/delayed/transfer — the weak-student precondition (cold low; calibrated band
~0–22% on this set) is violated, so per paper-plan §11 the pilot is **uninterpretable**
(return to calibration; not a falsification). Diagnosis on
`logs/cold-20260618-213903-650`: (a) **no leakage** — `canonical_answer` is absent from
every student prompt; (b) the cold student **genuinely solves**, e.g. immediate-1
verbatim `0.2(46) + 0.8x = 0.4(46 + x) … 0.4x = 9.2 … x = 23` (correct), unaided. So the
student instrument is simply too strong. The slug `meta-llama/llama-3.1-8b-instruct` is
still live (`list_models.py`), so the cause is OpenRouter routing that slug to a stronger
provider/quantization than at calibration — it routes silently, and `calls.jsonl` stores
only the response text, not the serving provider, so the exact backend can't be recovered
post-hoc. The P2 reversal (ped > conv) is therefore an **artifact of an over-capable
student** (a competent student makes ConvTutor's answer-dumping look redundant and
PedTutor's hints apt), not evidence about the thesis, and is not interpreted.
**Decision:** Move the student off OpenRouter to **Groq `llama-3.1-8b-instant`** in
`configs/models.yaml` (provider `groq`, already defined in the providers block; temp 0.8,
max_tokens 512 unchanged). Groq serves one deterministic build (no provider/quant
roulette) and it is the serving Step-2 calibration validated as genuinely weak. The cold
and ConvTutor-leakage gates MUST be re-verified on this serving (`experiments/calibrate.py`)
before re-running the pilot — gate results don't transfer across servings (standing
caveat, decisions-log 2026-06-15).
**Reason:** Reproducibility. A controlled experiment needs a pinned, deterministic
student; OpenRouter's silent multi-provider routing is a reproducibility hazard that just
produced an uninterpretable run. The original reason for leaving Groq — its free tier's
6000-token/request cap, which the carried-memory protocol exceeds — is handled by a paid
Groq tier: peak STUDENT request sizes measured on this pilot are ~4.9k (cold), ~7.2k
(ped), ~9.5k (conv) input tokens, all within `llama-3.1-8b-instant`'s context on a paid
tier, and `_with_backoff` handles TPM limits.
**Alternatives considered:** (a) Pin the OpenRouter provider/quantization via provider
routing (`extra_body`) — viable but keeps a multi-provider dependency and still needs
per-provider verification; Groq is simpler and already calibration-validated. (b) Keep
OpenRouter and just re-run — rejected, non-reproducible (could drift again). (c) Drop to a
weaker model (`llama-3.2-3b/1b-instruct`) or harden the problem set — held in reserve if
Groq `llama-3.1-8b-instant` no longer cold-gates low on re-verification.
**Validation:** Config change only; the live cold re-verification is the user's to run (no
keys in the offline environment). Offline suites unaffected (`tools/test_judge.py` 37/37,
`tools/test_metrics.py` 31/31). The uninterpretable pilot under `results/pilot/` is kept
as the calibration finding, not reported as a result.
**Affects:** `configs/models.yaml` (student provider/model). **Next:** set `GROQ_API_KEY`,
confirm the slug via `list_models.py`, re-run the cold gate on the Groq student (require
cold low), then re-run the pilot.

### 2026-06-18 — Backoff misread a Groq per-minute rate limit as a permanent quota
**Context:** Re-running the pilot on the Groq student, the cold gate passed (probe cold
11.1% — immediate/delayed 0%, transfer 33% — student weak again, per the amended §6;
`calibrate.py`'s "20–40%" band is the stale pre-reframe target and now mis-flags low cold
as CHECK). But the pilot itself aborted: `_with_backoff` raised `QuotaExhausted` on Groq's
free-tier 429, which is a **tokens-per-minute** limit (`TPM: Limit 6000`, "try again in
110ms", `rate_limit_exceeded`) — i.e. transient. The abort happened because the message's
upsell URL ends in `.../settings/billing`, and "billing" was in the non-recoverable
substring net.
**Decision:** Tightened `_with_backoff`: a per-minute limit (`per minute`/`tpm`/`rpm`) is
detected first and treated as transient (retried with backoff); the daily/quota net no
longer includes "billing"/"credit" (upsell-URL words) and only fires when it is NOT a
per-minute limit. Verified: the exact Groq TPM 429 now retries to success, while a TPD
("tokens per day") error still fails fast as `QuotaExhausted`.
**Reason:** A transient per-minute throttle must back off, not abort a run; the old net
keyed on words that appear in Groq's upsell link. Condition-neutral (provider-/role-
agnostic infra). **Separately**, the Groq **free** tier (6000 TPM) is too small for the
carried-memory protocol regardless of backoff — peak student requests are ~9.5k input
tokens (conv), which cannot fit a 6000-token-per-minute budget in one shot — so the live
pilot needs Groq **Dev tier** (or another provider, e.g. Cerebras) for the student.
**Affects:** `agents/model_client.py` (`_with_backoff`). **Next:** student on a Groq Dev
tier (or Cerebras), then re-run the pilot.

### 2026-06-18 — Student moved to Cerebras (lead's call); two checks before trusting it
**Context:** Groq's free tier (6000 TPM) can't fit the carried-memory protocol's ~9.5k-token
student requests, and the maintainer opted for Cerebras over a Groq Dev-tier upgrade. Cerebras
serves one deterministic build (no OpenRouter routing roulette) and has TPM headroom.
**Decision:** Added a `cerebras` provider block to `configs/models.yaml` and pointed the
student at `cerebras` / `llama3.1-8b` (temp 0.8, max_tokens 512). Two things must be
verified before any pilot is trusted, both flagged inline in the config:
  1. **The slug must exist on the account.** As of 2026-06-15 (`models.free.yaml` note)
     this Cerebras account served only `gpt-oss-120b` and `zai-glm-4.7` — no weak small
     model. A weak student needs a small slug (e.g. `llama3.1-8b`) to actually be offered;
     confirm with `list_models.py` (CEREBRAS_API_KEY set) and adjust the slug.
  2. **The cold gate must read low on this serving.** Cerebras may run a higher-precision
     8B than Groq's calibrated-weak `llama-3.1-8b-instant`; a stronger serving would
     reproduce the OpenRouter cold-100% failure. Re-run `calibrate.py --cold-only` on the
     frozen problems first.
**Reason:** Honors the maintainer's provider choice while keeping the weak-student precondition
honest — the switch is only valid if both checks pass. If Cerebras has no small model or
cold-gates high, the fallbacks are Groq Dev tier (`llama-3.1-8b-instant`, already
calibration-validated weak) or a smaller model (`llama-3.2-3b/1b`). Condition-neutral
(student-only; tutor stays Anthropic Sonnet, the model under study).
**Alternatives considered:** Groq Dev tier — the calibrated-weak serving, viable if the
lead later prefers it. Pin OpenRouter provider/quant — keeps the routing-drift risk.
**Affects:** `configs/models.yaml` (providers + student). **Next:** confirm the Cerebras
slug, re-run the cold gate (require low), then the pilot.

### 2026-06-18 — Cerebras ruled out for the student; back to Groq, throughput is the open call
**Context:** `list_models.py` (live, CEREBRAS_API_KEY set) shows Cerebras serves exactly
two models — `gpt-oss-120b` and `zai-glm-4.7` — both large/capable, no weak small model.
Either as the student would ace the problems cold (the failure we just escaped on
OpenRouter), so Cerebras cannot be the weak student. Same run confirms Groq does serve the
weak `llama-3.1-8b-instant`.
**Decision:** Reverted the student to Groq `llama-3.1-8b-instant` (the calibration-validated
weak, deterministic serving). The Cerebras provider block stays in `configs/models.yaml`
(valid provider; annotated that it has no weak student model) in case it is wanted for a
capable role later — but the tutor is Anthropic Sonnet (the model under study), so Cerebras
has no role in the current setup.
**Reason:** The weak-student precondition is non-negotiable, and Cerebras's catalog can't
meet it. Groq `llama-3.1-8b-instant` is the only confirmed weak + deterministic option in
hand. **Open call (lead's):** throughput. Groq's free on_demand tier is 6000 TPM, which
fits cold (~4.9k peak) but not the tutored conditions (conv ~9.5k, ped ~7.2k single
requests), so a real pilot needs **Groq Dev tier** (recommended — clean, one config, no
code change), OR a free fallback via **OpenRouter pinned** to a specific weak
provider/quant (needs `extra_body` provider-routing support added to the OpenAI-compat
path + its own cold re-gate; reintroduces routing complexity), OR a smaller free model
(e.g. `llama-3.2-3b`) at the risk of being too weak to learn from tutoring.
**Affects:** `configs/models.yaml` (student back to Groq; Cerebras annotated). **Next:**
lead picks the throughput route; then re-gate cold and run the pilot.

### 2026-06-18 — OpenRouter pinning works; fp8 8B still too strong (weak student is Groq-specific)
**Context:** Per the maintainer's choice, added OpenRouter provider pinning to the OpenAI-compat
path (`extra_body` passthrough) plus per-call `served_provider` logging, and pinned the
student to DeepInfra fp8 `meta-llama/llama-3.1-8b-instruct`. Re-ran the pilot.
**Result:** Pinning verified live — `served_provider == DeepInfra` for every student call,
the pin (`allow_fallbacks:false`, `fp8`) recorded in `request.extra_body`, and a single
served provider across the whole run (no drift). BUT cold came back ~89%
(immediate 100%, delayed 67%, transfer 100%) — still far too strong. A reference-precision
8B (even fp8) is much more capable than Groq's `llama-3.1-8b-instant`, which is the only
serving that cold-gated low (11%, decisions-log earlier today). So the weak-student
precondition is **specific to Groq's quantized serving**, not a property of "Llama-3.1-8B."
P2 was a tie here (conv 4.79 vs ped 4.81) but moot — cold high → uninterpretable.
**Decision:** Keep the pinning + `served_provider` logging regardless of provider
(permanent drift protection + provenance; cheap, condition-neutral). The student serving is
still unresolved; the realistic options are: (a) pin a LOWER-precision OpenRouter endpoint
(int4/int3) if `list_endpoints.py` shows one, then re-gate cold; (b) Groq Dev tier
`llama-3.1-8b-instant` — the confirmed-weak serving; (c) a genuinely smaller model
(`llama-3.2-3b`) re-gated on BOTH cold (low) and learnability (can it learn from tutoring).
**Reason:** fp8 DeepInfra 8B is empirically too strong; pinning fixed drift/reproducibility
but not strength. This is also a reportable reproducibility caveat for the paper: the
learner instrument is a specific quantized serving, which should be named as such.
**Affects:** `agents/model_client.py` (`extra_body` passthrough + `served_provider`),
`experiments/list_endpoints.py` (new), `configs/models.yaml` (student pinned to OpenRouter).
**Next:** `list_endpoints.py` to see the quant menu; pick a weaker serving or move to Groq
Dev / a 3B; re-gate cold (and learnability if 3B).

### 2026-06-18 — Resolved: pin OpenRouter -> Groq (the weak serving, no Dev plan)
**Context:** Groq's Dev tier was unavailable to the maintainer, and HF/other 8B servings are
near-full-precision (too strong). `list_endpoints.py meta-llama/llama-3.1-8b-instruct`
shows OpenRouter routes to **Groq** as one of six providers for this model
(quant "unknown", 131k ctx, $0.05/$0.08 per M).
**Decision:** Pin the student to OpenRouter -> Groq (`provider.order: ["Groq"]`,
`allow_fallbacks: false`, and **no** `quantizations` filter — Groq's quant is unreported, so
a filter would exclude it and break the pin). This recovers the calibration-validated weak
serving (expected cold ~11%) through OpenRouter's throughput, so neither a Groq Dev plan nor
the free 6000-TPM cap is in play; cost is ~pennies per pilot at Groq's 8B rates.
`served_provider` logs "Groq" per call to confirm the route held.
**Reason:** It is the actual weak serving (not a same-weights substitute), reached via the
throughput that already works (the DeepInfra pilot completed through OpenRouter), reusing the
pinning built earlier. HF was declined for the 8B because it would serve full precision
(too strong); HF/3B remains the fallback if the Groq route ever stops being offered.
**Affects:** `configs/models.yaml` (student pinned to OpenRouter->Groq). **Next:** re-gate
cold (expect ~11%), confirm `served_provider == "Groq"`, then run the pilot.

### 2026-06-19 — Continuous-protocol cold is not a floor: the student self-teaches from carried context
**Context:** With the student finally weak (OpenRouter->Groq, isolated cold 11%), the first
interpretable-looking pilot (`logs/cold-20260619-002056-378`) still showed a HIGH cold row
(immediate 67%, delayed 100%, transfer 100%). The cold GATE (`calibrate.py`, per-problem
isolated) and the pilot cold row (`run_full_session`, carried memory) disagree sharply, so
I traced the cold session item-by-item.
**Finding:** Committed answer per item, in session order: the cold student fails the first
five training items (0/5, fresh context), first succeeds on train-6, then climbs to
immediate 2/3, delayed 3/3, transfer 3/3. Accuracy rises monotonically as the student's OWN
untutored attempts accumulate in its context — it bootstraps the method from itself. The
isolated 11% is the true floor; the continuous ~89% is in-context self-teaching, not a
strong student (it fails every early item).
**Reading:** This is the cold-side of the carried-context accuracy saturation the plan
already documents (§2, §8 #2). It breaks the literal §11 "cold must be low" gate IN THE
PROTOCOL ACTUALLY RUN, because `calibrate.py` measures isolated cold while the experiment
carries memory. Open for the maintainer/R1/R3 (pre-registration), NOT patched here: (a) report
isolated cold (11%) as the genuine-difficulty evidence and note continuous cold saturates
via self-teaching — consistent with the accuracy-paradigm limitation; accuracy is secondary
and J1/J2 don't depend on the cold floor — amending §11 to measure cold in-protocol;
(b) make cold reach the probes without its own training attempts in context (breaks
condition-neutrality vs conv/ped, which carry context); (c) reduce bootstrapping (fewer
items / don't co-present isomorphs). A frozen-protocol / pre-registration decision.
**Affects:** none (finding/log only). Cross-ref the turn-level entry below (same pilot).

### 2026-06-19 — Judge follows the rubric; ConvTutor filler confounds per-session P2; J2 holds per-turn
**Context:** P2 came out reversed across the pilots (ped helpfulness >= conv every time;
this pilot conv 4.07 vs ped 4.67). To check whether that is the judge importing a pedagogy
bias (which would rig P2 against the thesis) or a real effect, I pulled the conv/ped turns
the judge split, with the four sub-scores and the rated tutor text
(`results/pilot_groq/helpfulness_detail.json`, `logs/conv-20260619-002114-958`,
`logs/ped-20260619-002402-470`). n=1, non-inferential, and on a pilot that is uninterpretable
for the cold-floor reason above — directional only.
**Finding:**
  - The judge is FAITHFUL to the rubric. The biggest ped>conv splits are turns where
    ConvTutor abandons the math for motivational filler ("# Keep Up That Amazing Attitude!
    your mindset is just as important as the math...", "It's been a true pleasure today 😊")
    scored overall 2.0 (helpfulness sub-score 2.0), versus PedTutor's substantive next-step
    hints ("Just compute 14.4 - 9.6, then divide both sides by 0.2") scored 5.0. It
    penalizes content-free filler, not answer-giving, and not tutoring strategy.
  - ConvTutor DEGRADES over turns: mean helpfulness 5.00 / 4.50 / 3.67 / 3.11 across turns
    0-3 (excellent on the worked-answer turn, filler by turn 3). PedTutor stays high and
    flat: 4.39 / 5.00 / 4.61 / 4.67. Root cause: `stop_on_commit=False` + a fixed
    `max_train_turns=4`, so ConvTutor keeps going after the student has already committed and
    drifts into social chit-chat; PedTutor's nodes stay on task.
  - J2 (the headline coupling) holds WITHIN conv: leaky (answer-revealing) turns score
    helpfulness 4.86 (n=7) vs non-leaky 3.75 (n=17), +1.11 — the felt-helpfulness judge
    rewards answer-giving, as the thesis predicts. (ped leaky n=1, not meaningful.)
**Reading:** The per-session P2 reversal is a FILLER ARTIFACT — ConvTutor's post-commit
chit-chat dilutes its mean — not the judge disfavoring answers. The per-turn J2 coupling,
which paper-plan §4/§10 designates the headline, is directionally supported. So the earlier
"P2 reversed -> core claim fails" was a misread: J2 looks right and the judge is a fair
test. Still n=1 on an uninterpretable pilot; not a result.
**Open question (flagged for R1, NOT changed):** whether the training dialogue should stop
when the student commits (`stop_on_commit`) so post-resolution filler is not generated or
scored. Doing so would raise ConvTutor's per-session helpfulness and likely restore P2's
predicted direction — which is exactly why any such change must be made for the PRINCIPLED
reason (post-commit chit-chat is not tutoring), condition-neutral (both tutors), and
pre-data, never because it helps P2 (the rigor rule). Recorded as a question for the maintainer.
**Affects:** none (analysis/log only; no code, metric, or prompt change). Cross-ref the
cold-floor entry above.

### 2026-06-19 — Pre-registration amendment: cold floor = isolated cold (option a)
**Context:** Resolving the cold-floor issue logged above (continuous-protocol cold is not a
floor; the student self-teaches from carried attempts). Lead's call: option (a). Pre-data
(no confirmatory data; the pilots are non-inferential), so `paper-plan.md` is still
amendable and freezes before the confirmatory run. (Operational note: `paper-plan.md` and
the other untracked planning docs had been swept into a GitHub Desktop stash during a
commit/pull and were restored from `stash@{0}` before this edit — they are not in any
commit's history; recommend committing them so they are tracked.)
**Decision:** Amended `paper-plan.md` (header amendment-history + §3, §6, §8, §11): the
interpretive cold floor is the **isolated, per-problem** cold accuracy (each item from a
fresh context), which is LOW (~11% in calibration) and establishes genuine difficulty. The
**continuous**-protocol cold accuracy saturates upward because the student self-teaches from
its own carried untutored attempts; it is reported **descriptively**, as the cold-side of
the carried-context accuracy saturation already owned in §2/§8, NOT as the floor. The §11
falsification gate now reads on **isolated** cold (high continuous-protocol cold is expected,
not a falsification). The protocol itself is unchanged.
**Reason:** Isolated cold is the honest genuine-difficulty measure (the student fails a
fresh problem); continuous-cold saturation is the same carried-context paradigm limitation
the plan already documents for accuracy, and accuracy is secondary — the primary J1/J2
process claims do not depend on the cold floor. Option (a) keeps the protocol and
condition-neutrality intact; it changes interpretation/gating only.
**Alternatives considered:** (b) make cold reach the probes without its own training
attempts in context — rejected, breaks condition-neutrality vs conv/ped (which carry
context). (c) reduce bootstrapping (fewer items / don't co-present isomorphs) — rejected as
a larger, frozen-problem-set change for no gain to the primary claims.
**Affects:** `paper-plan.md` (header, §3, §6, §8, §11). **Next:** resolve the ConvTutor
filler / `stop_on_commit` question (the other open issue), then re-pilot under the resolved
design and freeze.

### 2026-06-19 — Metric amendment & frozen analysis spec (answer-phase window; construct rename)
**Context:** An external comment on the ConvTutor filler (the other open issue). Rather
than `stop_on_commit` at generation time, it proposed computing all metrics on text
**up to the end of the answer phase**, plus several analysis-plan tightenings. Resolves the
filler issue (B) and supersedes the Option 1/Option 2 framing in `m2-decision-brief.md`.
**Decision:** Adopted, frozen post-pilot / pre-confirmatory, and written up in
`metric-amendment-2026-06-19.md` (the authoritative spec): (1) an **answer-phase evaluation
window** — per training problem, end at the student's first `FINAL ANSWER:` commit (frozen
extractor); include visible tutor turns with seq < commit and student turns with seq ≤ commit;
no commit ⇒ full window; applied **uniformly** to leakage, independence, and helpfulness,
identically for both tutors. (2) **Construct rename** to *annotator-perceived helpfulness*
(how helpful a turn appears to an external evaluator — not the learner's experience, not
pedagogy). (3) **Analysis plan**: unit = the conversation (per-replicate summary), not pooled
turns; per-replicate paired Wilcoxon + Cliff's delta; 95% CIs at conversation level; J2 via
mixed-effects with replicate/problem random effects; P1–P3 directions unchanged but **P2
flagged as unsupported by the pilot, null/reversed plausible**. (4) A **judge-validation set**
(adult annotators score a stratified sample with the same rubric; report LLM–human and
human–human agreement) — gated on an **IRB/human-subjects check** (stop asserting "no human
subjects" categorically). (5) Confirmatory 10×3 runs only after this freezes; report P1–P3
regardless of outcome with conversation-level uncertainty.
**Reason:** Locks the measurement before collecting more data, which protects the confirmatory
run from post-hoc-adjustment accusations. The window is the right measurement on principle
(post-commit chit-chat isn't tutoring) and — critically — **does not rescue P2** in the pilot
(gap −0.60 → −0.30, still reversed), so it is not result-favoring; the external
provenance reinforces that.
**Alternatives considered:** `stop_on_commit` at generation (rejected as primary — needs a
re-run and risks editing ConvTutor's minimal prompt / its *emergent* leakage story; may be
added later only as generation hygiene). A tutor-prompt "end the conversation" instruction —
rejected (contaminates the emergent-behavior claim).
**Affects:** `metric-amendment-2026-06-19.md` (new, frozen spec); supersedes filler handling
in `m2-decision-brief.md`. **Owes (implementation, next):** implement the window uniformly in
`analysis/metrics.py` + `analysis/judge.py` and test on the existing logs; fold the rename +
analysis plan into `paper-plan.md` §9/§10/§11; run the IRB check before the judge-validation
study. Then the confirmatory run.
**Addendum (2026-06-19, implementation done):** the answer-phase window is implemented to
spec. `metrics.commit_seqs` + `tutor_in_window`/`student_in_window`; `leakage_items` and
`independence_items` take a `commit_seq`; `analyze_session(..., answer_phase=True)` (the
frozen default) computes and applies it and stores `SessionMetrics.commit_seq`;
`judge.judge_session` rates only in-window turns; `compute_metrics.py --full-window` is the
disclosure/sensitivity fallback. Cost (§9.5) and probe accuracy are never windowed.
Verified on the pilot logs (reusing the judge cache, no new calls): windowed conv/ped =
leak 20%/5%, independence 50%/82%, helpfulness 4.33/4.64, **P2 = −0.30**; full window =
leak 29%/4%, independence 30%/77%, helpfulness 4.07/4.67, **P2 = −0.60** — matching the
earlier demonstration. Offline suites: `tools/test_metrics.py` 47/47 (new window section),
`tools/test_judge.py` 38/38 (new window test).
**Addendum (2026-06-19, paper-plan folded in):** the amendment is now reflected in
`paper-plan.md` — header amendment history; §9 lead-in answer-phase-window note; §9.2/§9.3
"answer phase" clauses; §9.4 renamed to *annotator-perceived helpfulness* with the
external-evaluator scope + IRB-gated human-validation note (supersedes the categorical "no
human subjects"); §10 unit-of-analysis = conversation, no pooled turns, conversation-level
CIs, correlated-turn handling; §11 P2-pilot-status note (no pilot support; null/reversed
plausible). `paper-plan.md` and `metric-amendment-2026-06-19.md` now agree. **Still owed:**
IRB/human-subjects check before the judge-validation study; then the confirmatory 10×3 run.

### 2026-06-18 — OpenRouter provider pinning + served-provider logging (lead chose OpenRouter, paid)
**Context:** Lead opted for OpenRouter (payment set up, so the free per-minute caps are
gone) over Groq Dev tier. The earlier OpenRouter failure was *unpinned* routing drifting to
a too-strong serving (cold 100%). To use OpenRouter safely the student must be pinned to one
serving and the serving must be recorded.
**Decision:** (1) `agents/model_client.py`: the OpenAI-compat path now passes a per-role
`extra_body` through to `chat.completions.create` (e.g. OpenRouter's
`{"provider": {"order": [...], "allow_fallbacks": false, "quantizations": [...]}}`), captures
the serving provider from the response into `Completion.provider`, and logs it as
`served_provider` (plus `request.extra_body`) in `calls.jsonl` — so any future drift is
visible and the pin is recorded. Condition-neutral, generic passthrough. (2)
`experiments/list_endpoints.py` (new, stdlib): lists OpenRouter provider/quant/context/price
for a model so a weak serving can be chosen. (3) `configs/models.yaml`: student ->
`openrouter` / `meta-llama/llama-3.1-8b-instruct` with an `extra_body.provider` pin
(`allow_fallbacks: false`); the `order`/`quantizations` are a starting guess (DeepInfra/fp8)
to CONFIRM via `list_endpoints` and the cold gate. (4) `experiments/PILOT.md`: added the
pinning workflow.
**Reason:** Pinning removes the routing roulette that broke reproducibility; logging the
served provider means a silent swap can't recur undetected. Lower precision (fp8/int4) is
the lever for matching the calibrated weakness — full precision was too strong — and the cold
gate decides. Fallback remains Groq Dev tier if no OpenRouter serving cold-gates low.
**Alternatives considered:** OpenRouter-specific `provider` field hardcoded — rejected in
favor of a generic `extra_body` passthrough (works for any OpenAI-compatible extra, no
special-casing). Groq Dev tier — viable fallback, not chosen by the maintainer.
**Validation:** Fake-client test: `extra_body` reaches `create()`, `served_provider` is
captured and logged, `request.extra_body` is logged. `tools/test_judge.py` 37/37,
`tools/test_metrics.py` 34/34; py_compile clean. The live provider/quant choice + cold
re-gate are the maintainer's to run (no OpenRouter key in the offline environment).
**Affects:** `agents/model_client.py`, `configs/models.yaml`,
`experiments/list_endpoints.py` (new), `experiments/PILOT.md`. **Next:** `list_endpoints`
-> pick a weak fp8/int4 serving -> cold gate low -> pilot.

### 2026-06-26 — Pre-confirmatory framing: evaluator–process coupling/divergence; J2 as headline
**Context:** Before the confirmatory 10×3 run, the paper's stated contribution had to
be locked. The non-inferential pilot (n=1, uninterpretable for the cold-floor reason,
decisions-log 2026-06-19) showed session-level P2 **reversed** (PedTutor ≥ ConvTutor)
and that the frozen answer-phase window does **not** rescue it (gap −0.60 → −0.30),
while the per-turn J2 coupling (leakier tutor turns rated more helpful) was
directionally supported (+1.11). No CONFIRMATORY data exists; the pilots are explicitly
non-inferential (paper-plan §10), so positioning is still amendable and freezes before
the confirmatory run.
**Decision:** Stated the empirical contribution as a controlled, wrapper-level
diagnostic of **evaluator–process coupling and its divergence** — when
annotator-perceived helpfulness, answer-leakage, and student independence agree vs.
diverge — with **J2 the headline result** within the pre-registered J1+J2 framework.
Edits, all in `paper-plan.md`: the title line (working title *Measuring
Evaluator–Process Coupling in LLM Tutors…*; the position paper kept as
the companion); a §1
"Empirical contribution" statement; a §11 paragraph making the "J2 holds while
session-level P2/J1 diverge" pattern an explicit, reportable finding (the divergence is
itself informative). One wording reconciliation in §4 — "The headline is supported only
as a conjunction" → "The joint claim is supported only as a conjunction" — so "headline"
refers to J2 consistently across the document.
**Reason:** Positioning + interpretation only, made openly BEFORE any confirmatory data,
so it is legitimate — not a new hypothesis and not a relabeling of outcomes. To be precise
about the "headline" label (and pre-empt a goalpost-moving read): §4/§10 already designated
the joint J1+J2 coupling as the primary *inference*, and J2 — the per-turn, construction-
independent component — was called "the headline coupling" in the 2026-06-19 entries; what
this edit does is make the single-word *label* consistent by reserving "headline" for J2,
resolving §4's residual "headline = joint claim" wording. It does not promote J2 over J1 as
the confirmatory bar (J1 still requires P2 significant; §11). The paper now reads as
interesting whether or not J1 holds, without calling a non-supported J1 "supported."
**Frozen content unchanged (baseline = the pre-reframe working tree, i.e. the
post-2026-06-19-amendment state):** relative to that baseline this reframe leaves
predictions (§4 — J1/J2/P1/P2/P3 definitions and directions), metric definitions (§9),
and the analysis plan (§10) unchanged — §9 and §10 byte-identical (verified by diffing
the pre-edit snapshot), the only §4 touch being the one wording swap above (no
prediction, definition, or direction altered). **Baseline caveat for a freeze-diff
review:** `paper-plan.md` is an untracked/new file, so a diff against the LAST COMMIT
also shows the §9 answer-phase-window and §10 conversation-unit content — that is the
EARLIER 2026-06-19 metric amendment (decided pre-confirmatory, logged that day; see
`metric-amendment-2026-06-19.md` and the 2026-06-19 entries), captured by the same single
freeze commit, NOT a #0 reframe change. Attribute §9/§10 content to the 2026-06-19
amendment, not to this entry. (The freeze is landed as TWO commits — baseline first,
then this reframe — so the #0 reframe is a standalone, git-verifiable diff and §4/§9/§10
byte-stability is checkable from git history: this entry and the paper-plan reframe ARE
the second commit.) The §11 P2-pilot-status note, the no-file-drawer commitment, and the
pre-committed outcome table are intact.
**Alternatives considered:** (a) keep framing the joint claim J1 as "the" result —
rejected; the pilot makes a partial divergence plausible, and a contribution that bets
on J1 holding is fragile and reads as result-dependent. (b) relabel a divergent/negative
J1 as support, or drop P2 from J1 — rejected outright (integrity). (c) reconcile
"headline" purely in §1/§11 and leave §4 untouched — rejected; §4 would keep using
"headline" for the joint claim, a residual internal contradiction.
**Affects:** `paper-plan.md` (title line, §1, §11; one §4 wording swap),
`decisions-log.md`. **Next:** independent #0 review of this diff, then the
confirmatory freeze commit (§4/§9/§10 unchanged).

### 2026-06-26 — Confirmatory 10×3 runner (R1): condition/replicate tags, freeze guard, resume
**Context:** Build R1's confirmatory runner: 10 replicates × {cold, conv, ped} through
the frozen continuous protocol, tagging every call with condition + replicate_id and
refusing to run off the frozen state. This closes "logging fix #2" the Step-5 entry
(2026-06-18) left to this runner — `analysis/metrics.py` already READS
`tags.condition` / `tags.replicate_id`. Built and mock-validated only; the maintainer runs the
live 10×3 (no keys in the offline environment).
**Decision:**
  - `experiments/run_confirmatory.py` (new). Tagging via a `TaggingClient(ModelClient)`
    subclass that merges authoritative `{condition, replicate_id}` base tags into EVERY
    `complete()` call. This is the single code path all roles/conditions take, so the
    stamp is uniform by construction; base tags are merged last (authoritative) and use
    keys disjoint from the agents' per-call tags (component/problem_id/turn_index/node/
    branch), so nothing is clobbered. The subclass lives in the runner and touches NO
    frozen file. The tagged condition values (cold/conv/ped) and replicate_id match what
    `metrics.infer_condition` / `infer_replicate_id` would otherwise infer, so there is
    no conflicting second source of truth — it just makes the inference explicit.
  - **Pairing.** Replicate r uses seed = base_seed + r for all three conditions, tagged
    `replicate_id = r` (the pairing key, independent of base_seed; §10).
  - **Freeze guard.** A pure `check_freeze(git_state, expected_commit, enforce)` records
    the HEAD hash + clean/dirty into each cell's `confirmatory_meta.json` and, on a live
    run, REFUSES unless the tree is clean AND HEAD == the freeze commit (resolved from
    `--freeze-commit`, `$FREEZE_COMMIT`, or a `confirmatory-freeze` tag). The match accepts
    only a full hash or a >=7-char prefix of HEAD; an empty/whitespace value resolves to
    not-set, so a stray `--freeze-commit "   "` cannot silently match a clean HEAD (this
    match logic was hardened after the adversarial #1 review flagged a loose-prefix /
    reverse-prefix bypass). Dirty = any
    modified/staged/untracked file (gitignored logs/ + results/ don't count, so the run
    can't dirty its own tree). On `--backend mock` the guard records but does not enforce
    (the offline environment rehearsal can't be at a not-yet-created freeze commit).
  - **Resume at (condition, replicate).** Deterministic per-cell run id
    `conf-s{base_seed}-{cond}-r{r}`; a cell is complete iff `full_session_result.json`
    exists. A resume runs only missing cells; an incomplete cell's dir is cleared
    (rmtree) before re-run, so a rate-limit abort never appends to / mixes a partial
    log. No retry/backoff was added — the client's existing `_with_backoff` is reused
    unchanged (sampling is not altered), and a `QuotaExhausted` propagates loudly.
  - **`phase` is NOT a new tag.** It is derived from the student `component`
    (student_train/probe/commit) + the problem's role, exactly as `metrics.py` already
    does. Logging-fix-#2 was scoped to condition/replicate_id; adding a phase tag would
    be a redundant harness change at the call sites.
  - `experiments/preflight.py` (new). Live gates before spending budget, on the frozen
    19 + pinned student: ISOLATED cold LOW (per-problem fresh-context, via
    `run_problem_session` — not the carried-memory protocol; the amended §6/§11 floor),
    FINAL-marker ≥ 95%, ConvTutor leakage present (failure-mode #3), `served_provider ==
    Groq`, and a 10×3 token estimate from a stored pilot. Reuses the frozen scoring
    primitives (`turn_leaks`, `is_correct`, `has_final_marker`); mirrors `calibrate.py`'s
    failure-mode reads on the frozen set; mock-validatable.
  - `experiments/RUN.md` (new): the live gate order — preflight → confirm freeze commit
    → run 10×3 → judge → metrics — with the rigor reminders.
  - `tools/test_run_confirmatory.py` (new, 61 checks): condition+replicate on every call
    for cold/conv/ped incl. a non-zero replicate (consistent with the metrics readers),
    the freeze guard (errors-dirty / records-clean / mock-records-only / wrong-commit /
    unpinned, plus the adversarial empty/whitespace/short/reverse-prefix cases), the
    seed=base+r pairing + unique run ids, resume (missing-only + partial-dir cleared, no
    replicate mixing), the TaggingClient merge, and a frozen-input hash check (problems +
    configs + rubrics + prompts.md byte-identical before/after a mock run).
**Reason:** Condition-neutral by construction (identical call path for conv and ped;
the only difference is the unavoidable cold-has-no-tutor); a single, explicit tag source
consistent with the metrics pipeline; freeze discipline that physically blocks an
off-freeze live run; resume that can't double-count or mix; and no knob anywhere that
tunes toward an outcome.
**Alternatives considered:** (a) add a base-tags field to `ModelClient` itself —
rejected; it edits a frozen file for broader scope than needed, whereas the runner-local
subclass is surgical. (b) add a `phase` tag at the call sites — rejected (harness change,
redundant with the derivable phase, beyond logging-fix-#2). (c) timestamp run ids
(`new_run_id`) — rejected; non-deterministic ids break idempotent resume, so a
deterministic per-cell id is used. (d) extend `experiments/run_pilot.py` — rejected; the
pilot is the non-inferential driver (no tags) and the design spec asks for a separate
confirmatory file. (e) special-case the mock to bypass the guard — rejected; the guard is
`enforce`-parameterized and mock simply records.
**Validation:** Offline suites green — `tools/test_metrics.py` 47, `tools/test_judge.py`
38, `tools/test_ped_tutor.py` 58, `tools/test_run_confirmatory.py` 61. Mock smoke:
n=2×3 → 6 session dirs, then n=10×3 → 30 (the second run RESUMED the 6 and added 24);
`analysis/compute_metrics.py` ingested the 30 into a paired per-replicate table (30 rows
= 10/condition; replicate_ids 0–9; 10 paired conv/ped J1-preview rows; condition read
from the tags). Frozen inputs byte-identical across a run; `preflight.py --backend mock`
runs the full gate plumbing. The LIVE run + preflight are the maintainer's (RUN.md); the
offline environment has no keys.
**Affects:** `experiments/run_confirmatory.py` (new), `experiments/preflight.py` (new),
`experiments/RUN.md` (new), `tools/test_run_confirmatory.py` (new), `decisions-log.md`.
**Next:** independent (adversarial-review) #1 review; then, after the #0 freeze
commit lands, the maintainer runs preflight → confirmatory 10×3 → judge → metrics.
**Addendum (2026-06-26, the independent adversarial-review fixes).** The independent review
(verdict needs-attention) raised four issues, all accepted and resolved pre-commit:
  1. (critical) **Live `--force` could delete + resample completed cells.** `--force` is
     now REFUSED on `--backend live` (`run_confirmatory.py`, raises with a quarantine
     instruction); it stays available for the mock rehearsal. Resume remains the only way
     to fill cells on a live run.
  2. (high) **Resume could skip a cell lacking freeze provenance.** `cell_complete` now
     gates on `confirmatory_meta.json` (the LAST file `run_cell` writes — the freeze-hash
     record), parsed and carrying condition + replicate_id, not on
     `full_session_result.json` (written earlier). A crash in the write gap now leaves the
     cell incomplete → re-run on resume. New tests cover the missing-meta sentinel.
  3. (high) **Preflight CHECK didn't fail the command.** Added
     `preflight.preflight_exit_code(backend, gates)`; on `--backend live` preflight now
     exits non-zero if any gate is False (report written first), so an automated workflow
     stops before the confirmatory run. Mock stays exit 0 (rehearsal). Unit-tested.
  4. (high) **Freeze-diff baseline ambiguity.** Resolved by (a) stating the baseline
     explicitly in the 2026-06-26 #0 framing entry (added in the reframe commit) — the
     "§9/§10 byte-identical" claim is relative to the pre-reframe working tree (the
     post-2026-06-19-amendment state), and the §9/§10 content in a diff-vs-last-commit is
     the earlier 2026-06-19 metric amendment, not a #0 change — and (b) landing the freeze
     as TWO commits: a baseline commit first (Step 5/6 + the 2026-06-19 amendment +
     planning docs + this runner, with paper-plan.md pre-reframe), then the #0 reframe
     (paper-plan.md + the framing entry) as a standalone, git-verifiable diff with
     §4/§9/§10 byte-stability checkable from history.
Offline suites after the fixes: `tools/test_run_confirmatory.py` 61, others unchanged
(47 / 38 / 58); `--force` live exits 1; the freeze guard still refuses a dirty tree.

### 2026-06-26 — Fail-fast provider-key precheck (preflight + confirmatory runner)
**Context:** Running `experiments/preflight.py` live crashed with a raw `RuntimeError`
("Provider 'openrouter' needs ... OPENROUTER_API_KEY ...") on the first student call,
because the student key was not exported. The student role is pinned to OpenRouter→Groq
(`configs/models.yaml`, `OPENROUTER_API_KEY`); the config is correct (`base_url` present)
— only the env var was missing. A mid-run traceback is poor UX; the codebase already has
a friendly judge-key guard in `analysis/compute_metrics.py`.
**Decision:** Added `run_confirmatory.missing_provider_keys(models_cfg, roles)` (mirrors
the provider/key resolution in `agents/model_client.py`) and a live precheck that calls
it before any model call: preflight checks tutor+student; the confirmatory runner checks
student (always) + tutor (when conv/ped is in the conditions). On a missing key it raises
a clear `SystemExit` naming the role/provider/env var and the `KEY=... python ...`
command, or suggests `--backend mock`. Tooling only — no harness file changed.
**Reason:** Pre-data tooling/UX fix; condition-neutral and behavior-neutral when keys are
present (it only fails earlier and more clearly when a key is absent, which would crash
anyway). It touches no prompt, problem, rubric, metric, prediction, or sampling. The
freeze tag is advanced to include it so the maintainer's live run + preflight have the guard
(still pre-confirmatory-data, so this is a legitimate pre-freeze fix).
**Alternatives considered:** (a) leave the raw RuntimeError — rejected (poor UX; a
fail-fast precheck matches the existing judge-key pattern). (b) put the helper in
`agents/model_client.py` — rejected (would touch frozen harness for broader scope than
needed; the runner-local helper is surgical and reused by preflight via import).
**Validation:** `python experiments/preflight.py --backend live` (no keys) now prints the
named-key message and exits 1 (no traceback); the runner's freeze guard still fires first
on a dirty tree. Offline suites: `tools/test_run_confirmatory.py` 63 (new precheck test),
others unchanged (47 / 38 / 58). Mock preflight/runner plumbing unaffected.
**Affects:** `experiments/run_confirmatory.py`, `experiments/preflight.py`,
`tools/test_run_confirmatory.py`, `decisions-log.md`.

### 2026-06-26 — Confirmatory 10×3 data COLLECTED at the freeze commit (pre-registration now binding)
**Context:** Record the data-collection event (not a design decision). With the
pre-registration frozen at commit `1a12b56` (tag `confirmatory-freeze`), the maintainer ran
the live confirmatory experiment.
**What was run:** Live preflight passed on the pinned student serving — isolated probe
cold 0.0% (LOW; precondition holds), FINAL-marker 100%, ConvTutor leakage 29.2% (present;
failure-mode #3 clear), `served_provider == "Groq"`. Then
`experiments/run_confirmatory.py --replicates 10 --freeze-commit 1a12b56`: **10 replicates
× {cold, conv, ped} = 30 cells, all complete**, each stamped with `condition` /
`replicate_id` on every call and the freeze hash in `confirmatory_meta.json` (verified: 30
dirs, 10 per condition, all recording head `1a12b56`). The run resumed cleanly across a
rate-limit abort (skipped completed cells, re-ran only missing ones). Models
(`configs/models.yaml`): tutor = Anthropic `claude-sonnet-4-6`, student = OpenRouter→Groq
`meta-llama/llama-3.1-8b-instruct`, judge = `claude-opus-4-8`.
**Consequence (integrity):** confirmatory data now exists, so the pre-registration is
**binding-frozen** — predictions (§4), metric definitions (§9), the analysis plan (§10),
the problem set, prompts, and rubrics do NOT change from here (project freeze rule). Any further
judgment call is reported, not retrofitted.
**Next:** `analysis/compute_metrics.py logs/conf-s0-* --out results/confirmatory
--judge-helpfulness` (Opus helpfulness judge; the descriptive per-replicate table + J1
preview), then the Week-3 inferential analysis (J1 paired Wilcoxon + Cliff's delta; J2
mixed-effects; §10). Report P1–P3 / J1 / J2 regardless of outcome (§11).
**Affects:** none (data-collection record; no code/spec change). The freeze tag stays at
`1a12b56`; this entry is appended post-freeze as the run record.

### 2026-06-26 — Week-3 inferential analysis built + run; CONFIRMATORY RESULT (reported per §11)
**Context:** Implement the frozen §10 inferential plan over the confirmatory tables and run it.
**Decision:** `analysis/inferential.py` + `analysis/run_inference.py` + `tools/test_inferential.py`
(25 checks), post-hoc over the compute_metrics output (no frozen metric/window/rubric touched).
J1 = two-sided paired Wilcoxon (paired by replicate, α=0.05) on leakage / helpfulness / independence,
Cliff's delta, conversation-level bootstrap 95% CIs, and the §11 joint verdict. **J2:** the canonical
§10 mixed-effects model (statsmodels, replicate random intercept) is attempted, but **statsmodels 0.14.4
is incompatible with scipy 1.17.1** (imports the removed `scipy._lib._util._lazywhere`), so it cannot run
in this env; the **operative J2 test is a dependency-light two-stage conversation-clustered signed-rank**
(within-replicate leaky-minus-non-leaky effect, signed-rank across replicates) — conversation-level (no
turn pooling, §10), same hypothesis and direction. Added `statsmodels>=0.14.5` to `requirements.txt`;
`pip install -U "statsmodels>=0.14.5"` then re-run to get the spec'd mixed model. Accuracy is descriptive
(no NHST, §4 S1); a cost-normalized (per-1k-tutor-token) sensitivity pass is included.
**Result (no file-drawer, §11; nothing tuned):**
  - **J1 NOT supported.** P1 leakage **significant** (conv .430 vs ped .064; Wilcoxon p=.0039; Cliff's δ
    +.96; conv>ped 9/10). P2 — the live helpfulness test — **n.s. and slightly reversed** (conv 4.703 vs
    ped 4.797; p=.160; δ −.10; CI [−.25, +.06]). P3 independence **n.s.** (ped .656 vs conv .580; p=.375;
    directionally as predicted). So the between-condition joint coupling does not hold (P2 fails the live
    test; P3 doesn't reach significance) — the §11-anticipated negative marginal result.
  - **J2 (the headline per-turn coupling) SUPPORTED** by the operative clustered test: leak→helpfulness
    within-replicate +0.279 (p=.0020); leak→next-turn-independence −0.421 (p=.0039). I.e. within
    conversations the answer-leaking turns are rated more helpful and are followed by less student
    reasoning — the thesis's objective-axis mechanism, at the turn level.
  - This is exactly the pre-registered **divergence**: J2 holds while session-level P2/J1 do not.
  - Accuracy saturates (S1): cold imm/del/tra ≈ .87/.87/.77, conv ≈ 1.0/.93/.83, ped ≈ .80/.90/.93.
    Cost-normalization does not flip P1 (leaky-turns/1k still p=.002).
**Reason:** implements §10 as frozen; the clustered signed-rank is a faithful conversation-level test of
the same coupling, used only because the named tool is broken in-env. No knob tuned toward an outcome.
**Alternatives considered:** (a) `pip install -U statsmodels` to run the canonical mixed model —
recommended next, not done unilaterally (user's machine). (b) hand-roll a GLMM — rejected (fragile,
credibility risk). (c) report only the descriptive pooled J2 — rejected; §10 forbids pooled turns for
inference, so the clustered signed-rank (the conversation as the unit) is the right operative test.
**Caveats:** n=10 (the smallest two-sided signed-rank p is .002 — P1 and J2 reach it; P2/P3 do not, so
they may be underpowered, not merely null). P3 separating only directionally (n.s.) is a wrinkle for the
§11(a) manipulation-check precondition (P1 separates strongly; P3 does not). The operative J2 is the
clustered test; the canonical §10 mixed model is **pending the statsmodels upgrade** — run it to confirm.
**Affects:** `analysis/inferential.py` (new), `analysis/run_inference.py` (new),
`tools/test_inferential.py` (new), `requirements.txt` (statsmodels pin),
`results/confirmatory/inference.json` (output). **Next:** upgrade statsmodels → run the canonical
mixed-effects J2; IRB-gated judge-validation; Week-4 write-up reporting P1–P3 / J1 / J2 as above.

### 2026-06-26 — Canonical §10 J2 mixed model now RUNS (statsmodels fix); crossed replicate+problem RE; verdict unchanged
**Context:** Completes the prior entry's explicit "Next: upgrade statsmodels → run the
canonical mixed-effects J2." The previous run's operative J2 was the dependency-light
conversation-clustered signed-rank because `statsmodels` could not import against
`scipy 1.17`; the spec'd mixed-effects model was pending. This is the planned §10
inferential layer — **read-only over the frozen results/logs; no upstream artifact (window,
rubrics, agent prompts, metric definitions, problem set) was touched.**
**Decision:** Installed `statsmodels 0.14.6` into `.venv` (compatible with `scipy 1.17.1`;
the `_lazywhere` import error was the old 0.14.4) and implemented the canonical §10 / metric-
amendment-§3 J2 model exactly: `outcome ~ leaks_i` with **CROSSED replicate AND problem
random intercepts** (statsmodels variance components over a single dummy group,
`re_formula="0"`). The prior `_try_mixedlm` used a **replicate-only** intercept — that was
not the full frozen spec; it is replaced by `_crossed_mixedlm`. A short optimizer sequence
`[lbfgs, bfgs, cg, powell]` is tried so a variance component pinned at the zero boundary
(common for the binary independence outcome) still converges; the fixed-effect estimate is
invariant to the optimizer (verified: −0.382→−0.386 across all of them), so this is
numerical hygiene, **not** a spec or result choice. The clustered signed-rank stays as a
reported robustness check. Added: provenance stamping (contributing run ids + freeze commit
`1a12b56` + analysis HEAD + scipy/statsmodels versions) on every output; a §11 `verdict()`
roll-up persisted to `inference.json` and printed; explicit LIMITATIONS (the binary
independence leg is fit as a linear-probability model — a logistic GLMM is a defensible
alternative deliberately NOT substituted post-hoc; J2 pools conv+ped so the coefficient
blends within/between-condition variation — condition is NOT added as a covariate per §10).
**Result (no file-drawer, §11; nothing tuned, dropped, or re-spec'd):**
  - **J2 (headline) SUPPORTED by the canonical crossed mixed model**, both legs converged:
    leak→helpfulness **coef +0.303, 95% CI [+0.169, +0.437], p≈9.1e-6**; leak→next-turn-
    independence **coef −0.386, 95% CI [−0.495, −0.276], p≈5.6e-12**. Agrees with the
    clustered signed-rank robustness check (+0.279, p=.002; −0.421, p=.004) and the
    descriptives (leaky helpfulness 4.95 vs 4.67; leaky next-indep 0.33 vs 0.73).
  - **Marginals / J1 UNCHANGED** (the mixed model only touches J2): P1 leakage **supported**
    (conv .430 vs ped .064; p=.0039; δ +.96), P2 helpfulness **not supported** (the live
    test; conv 4.703 vs ped 4.797; p=.160; δ −.10; n.s./reversed), P3 independence
    **inconclusive** (manipulation check n.s.; ped .656 vs conv .580; p=.375), **J1 not
    supported**. The pre-registered divergence holds: J2 holds while session-level P2/J1 do
    not. Accuracy saturates (S1). Cost-normalization does not flip P1.
**Verification:** `tools/test_inferential.py` now 43 checks (was 25) on SYNTHETIC known-answer
fixtures — hand-computed two-sided Wilcoxon p (n=6 all-positive → 0.03125 = 2/2⁶; n=8 →
0.0078125), the crossed mixed model recovering a planted fixed effect (true β=+1.0 → +0.97,
CI brackets 1.0, converged), conversation-level unit (n = replicates, not turns) asserted,
and the verdict mapping (a null/reversed P2 reads "not supported," never silently dropped).
All pass. Frozen-artifact byte-stability re-confirmed (`git diff confirmatory-freeze..HEAD`
over paper-plan / metric-amendment / domain / supplement / agents / metrics.py /
compute_metrics.py / judge.py is empty); `results/` and `logs/` are gitignored, so
regenerating `inference.json` changes nothing in version control. compute_metrics was NOT
re-run and nothing was re-judged.
**Optimizer-invariance (reproducible sweep, real `per_turn.csv`):** fitting each crossed leg
under every optimizer gives — helpfulness: lbfgs/cg/powell/nm +0.3028, bfgs +0.3057 (all
p<1e-5, positive); next-turn-independence: lbfgs −0.3815, bfgs −0.3759, cg −0.3858,
powell/nm −0.3856 (all p<1e-9, negative). Sign and significance never flip; the reported
fit is the first *converged* optimizer in the `[lbfgs,bfgs,cg,powell]` sequence (helpfulness
→ lbfgs; the binary independence leg hits the variance-component zero boundary so lbfgs/bfgs/cg
report `converged=False` and it lands on **powell**, −0.3856, `converged=True`). The sequence
is convergence hygiene; it does not select an estimate.
**Self-review:** an internal adversarial review (6 dimensions — read-only-upstream, frozen-spec
exactness, conversation unit, statistics re-derived independently, no-result-chasing,
provenance) returned **SHIP, zero must-fix**; the statistics review reproduced every
reported number to full float precision and confirmed the fixtures *pin* known values. The
independent-review gate is still owed before any freeze commit.
**Reason:** runs §10 exactly as frozen; the only model change is *toward* the spec
(replicate-only → crossed replicate+problem), not toward an outcome.
**Alternatives considered:** (a) logistic GLMM for the binary independence leg — rejected as
a post-hoc re-spec; disclosed as a limitation instead. (b) add `condition` as a covariate to
the J2 model — rejected (§10 forbids covariate-shopping; disclosed as a limitation).
(c) force lbfgs convergence by tweaking the model — rejected; used a standard optimizer
sequence and report the honest `converged` flag.
**HOLD (workflow):** not committed — the independent-review gate runs before any freeze
commit; must-fixes resolved first. The freeze tag stays at `1a12b56`.
**Affects:** `analysis/inferential.py` (crossed `_crossed_mixedlm`, `verdict()`, J2
limitations), `analysis/run_inference.py` (provenance + verdict table + richer J2 console),
`tools/test_inferential.py` (43 checks), `results/confirmatory/inference.json` (regenerated,
gitignored). `requirements.txt` already pinned `statsmodels>=0.14.5` (prior entry).

### 2026-06-26 — independent adversarial review of the §10 inference: MUST-FIX resolved; one nice-to-have DECLINED on freeze-discipline grounds
**Context:** An independent adversarial review of the §10 inferential layer
returned **NO-SHIP** on one must-fix plus two nice-to-haves. All six spec/integrity checks
otherwise passed (the independent review re-derived P1/P2/P3 and both J2 legs to match
`inference.json`). Resolving here before the freeze commit.
**MUST-FIX — log byte-stability was not git-verifiable.** `logs/` is gitignored (by design —
the confirmatory logs were *collected post-freeze* against freeze commit `1a12b56`, so they
were never part of the freeze tree), so "the logs are unchanged" could not be checked from git
history. **Resolution:** added a content-hash manifest `confirmatory-log-manifest.sha256`
(90 files = 30 run dirs `logs/conf-s0-{cold,conv,ped}-r{0..9}` × {calls.jsonl,
confirmatory_meta.json, full_session_result.json}, SHA-256, sorted by path). It pins the
exact log bytes the analysis consumed; anyone can re-verify with
`shasum -a 256 -c confirmatory-log-manifest.sha256` from the repo root (regenerate with
`find logs/conf-s0-* -type f | LC_ALL=C sort | xargs shasum -a 256`). Aggregate manifest hash
`b0b4671b…`. Honest scope note: this makes log immutability verifiable **from this commit
forward**; immutability between data collection and this manifest is operational (filesystem),
not git-provable — stated openly so the limitation is on record (the accepted option).
**The manifest must be committed for the guarantee to hold in a future checkout — the maintainer
owns the commit (workflow: no auto-commit); until then the file is created-and-verified but
untracked.**
**NICE-TO-HAVE 1 (done) — binary-leg estimate pin.** Added
`test_j2_mixed_recovers_binary_estimate`: a crossed-design fixture with a planted risk
difference Δ=−0.40 on the binary next-turn-independence outcome; the linear-probability mixed
model recovers coef −0.444 (CI [−0.537, −0.352] brackets −0.40, converged), so the binary leg
now PINS an estimate within tolerance, matching the continuous helpfulness leg (was
sign/significance-only). Suite now **48 checks, all pass**.
**NICE-TO-HAVE 2 (DECLINED — would violate freeze discipline).** the independent review flagged the stale
comment `domain/algebra/problems.yaml:17` "STATUS: NOT frozen" and suggested updating it.
**Not done, deliberately:** that line is **inside a FROZEN artifact**, and the freeze commit
`1a12b56` itself contains the "NOT frozen" text (verified: `git show
confirmatory-freeze:domain/algebra/problems.yaml` line 17 == the working-tree line; `git diff
confirmatory-freeze..HEAD -- domain/algebra/problems.yaml` is empty). Editing even a comment
there would break the verifiable byte-stability of the frozen problem set — the exact guarantee
both review passes relied on ("domain/ byte-stable vs confirmatory-freeze").
Per the project conventions ("do not change … the problem set after data collection") and the freeze-immutability
workflow, the cosmetic label is a documentation artifact, not experimental content. **Resolution:**
the label is recorded here as STALE — the 19-problem set **was frozen** at tag
`confirmatory-freeze` (1a12b56) and data was collected against it; the authoritative freeze
record is the git tag + this log, not the in-file comment. The frozen bytes are left untouched
on purpose. (If the label is ever corrected, it must be a deliberate, separately-logged
post-freeze amendment the maintainer owns — not folded into an analysis change.)
**Verification:** `tools/test_inferential.py` 48/48; `shasum -c` on the new manifest all-OK;
frozen-artifact diff vs `confirmatory-freeze` still EMPTY (no frozen file touched, incl.
problems.yaml).
**HOLD (workflow):** still uncommitted; the maintainer commits/freezes. Re-run the review if desired to
confirm the must-fix is cleared.
**Affects:** `confirmatory-log-manifest.sha256` (new; created & verified — the maintainer commits it),
`tools/test_inferential.py` (+binary-leg estimate test, 48 checks), `decisions-log.md`,
`.gitignore` (excludes local working notes from the
open-source repo). **NOT touched:** `domain/algebra/problems.yaml` (frozen; stale label
documented, not edited).

### 2026-06-26 — Matched visible-turn-budget compute-fairness pass (§10): RULE FROZEN (before the truncated result was read)
**Context:** §10 names two compute-fairness controls. The cost-normalized one (outcomes per
1k tutor tokens) is already in `analysis/inferential.py` (`cost_normalized`) and reported in
`inference.json`. The other — "the primary comparison **fixes the same visible-turn budget**
across tutors … any result that disappears under matched budgets is flagged" — was not yet
done. PedTutor scaffolds to the answer and ConvTutor resolves fast, so the answer-phase window
(metric-amendment-2026-06-19 §1) yields more in-window visible tutor turns for ped than conv;
the cost-normalized view does not by itself equalize the *turn* budget. This entry freezes the
matched-budget rule **before any truncated marginal is computed**, so the rule cannot be shaped
by the outcome. This is a read-only robustness re-analysis over the confirmatory results/logs at
freeze `1a12b56`; no session is re-run, nothing is re-judged, and no window / rubric / prompt /
metric / problem / log is modified.
**Decision (the frozen rule — single rule, applied identically to ConvTutor and PedTutor):**
1. *Scope.* ConvTutor vs PedTutor only, paired by replicate id (the §10 primary unit). The cold
   baseline has no tutor turns and is not in this comparison.
2. *Matched budget K.* For each `(problem, replicate)` pair, let `n_conv` and `n_ped` be the
   counts of **in-window** (answer-phase) student-visible tutor turns for that problem under
   conv and ped. **K = min(n_conv, n_ped)** — the pairwise minimum. This single K is used; no
   other K is tried and K is never chosen to flatter a result.
3. *Truncation (identical for both conditions).* Keep the **first K** visible tutor turns of that
   problem, ordered by call sequence (`first_seq`; equals `turn_index` order — verified contiguous
   0-based, ordered, in the confirmatory data). Keep the student training turns **up to and
   including the student's response to the K-th kept tutor turn** — operationally, the student
   turns whose `seq` is before the first call of the first **dropped** tutor turn (the (K+1)-th).
   `K = 0` drops the problem entirely for **both** conditions. When **no** tutor turn is dropped
   (K = a condition's full in-window count) the rule is a no-op for that condition: it recovers the
   full answer-phase window, **including any student turns that trail the last tutor turn in a
   no-commit problem**. This no-op property is enforced as the foundational faithfulness invariant
   (recomputing every marginal with no truncation reproduces the frozen `per_replicate.csv`
   exactly — 0 mismatches across 20 conv/ped conversations × 3 marginals) and is asserted in
   `tools/test_matched_budget.py`.
4. *Marginals, recomputed over the truncated turns with the SAME aggregation as the frozen
   per-session metrics (`analysis/metrics.py`).* **P1 leakage_rate** = leaky / total over the kept
   tutor turns, **reusing the frozen per-turn leakage flags** (`per_turn.csv` `leaks`; re-derivation
   from logs reproduces them exactly — 0/358 mismatches). **P2 helpfulness_mean** = mean of the
   **cached** per-turn helpfulness over the kept tutor turns (`per_turn.csv` `helpfulness` /
   `helpfulness_cache.json`; **the judge is NOT re-run**). **P3 independence_ratio** = attempt /
   total over the kept **student** training turns, **applying the frozen independence regex**
   (`attempts_reasoning`) — P3 is a student-turn-level estimand and is NOT the per-tutor-turn
   `next_turn_independence`, so it is recomputed at the student-turn level over the truncated
   student window to stay the same estimand as the primary.
5. *Inference — identical to the primary (§10).* The truncated per-conversation summaries go
   through the **same** `analysis/inferential.py` `j1`: paired two-tailed Wilcoxon (α=0.05, paired
   by replicate id), Cliff's delta, conversation-level bootstrap 95% CIs. The unit is the
   conversation, never pooled turns.
6. *J2 (secondary robustness).* Recompute the crossed replicate+problem coupling
   (`analysis/inferential.py` `j2`) on the truncated tutor-turn set. Report the leaky / non-leaky
   **cell sizes**; if the ped-leaky cell is too small under truncation, report it descriptively as
   underpowered — **do NOT re-spec** the model to rescue it.
7. *Flagging.* Any marginal whose **direction flips or whose significance changes** vs its
   full-window value is flagged explicitly (§10: "any result that disappears under matched budgets
   is flagged"). The realized in-window turn counts (conv vs ped, with conversation-level CIs) and
   the existing per-1k-tutor-token sensitivity are reported alongside, so both §10 compute-fairness
   views appear together.
**Reason:** runs the §10 "same visible-turn budget" control exactly as pre-registered. The
pairwise-minimum K is the principled matched budget (it is the largest turn count both conditions
actually reached for that problem); it is fixed a priori and data-independent in form. Nothing is
tuned toward an outcome; the result is reported regardless (§11).
**Alternatives considered:** (a) a single global K across all problems — rejected: discards the
per-problem pairing and wastes turns; pairwise K matches the per-replicate/per-problem structure.
(b) Truncating to the *maximum* or to a chosen K that changes the gap — rejected as K-shopping.
(c) Using `next_turn_independence` (per tutor turn) as the truncated P3 — rejected: it is a
different estimand from the primary `independence_ratio` (verified to differ; the gap is exactly
the one pre-tutor student turn per problem), so it would not be a like-for-like full-vs-truncated
comparison. (d) Re-judging the truncated turns — rejected and unnecessary: per-turn helpfulness is
cached and turn-local, so truncation just drops turns.
**RESULT:** appended in the follow-up subsection below, written only **after** this rule was
frozen. The rule above was authored before any truncated marginal was computed.
**Affects:** `analysis/matched_budget.py` (new; read-only re-analysis), `tools/test_matched_budget.py`
(new), `results/confirmatory/matched_budget.json` (new; gitignored like `inference.json`),
`decisions-log.md`. **NOT touched:** any frozen artifact, window, rubric, prompt, metric, problem,
or log; `analysis/inferential.py` / `metrics.py` / `judge.py` are imported and reused, not modified.

### 2026-06-26 — Matched visible-turn-budget pass: RESULT (read after the rule above was frozen; reported per §11)
**Read-only, no model/judge calls.** `analysis/matched_budget.py results/confirmatory` →
`results/confirmatory/matched_budget.json` (gitignored, like `inference.json`). Provenance: freeze
`1a12b56` (tag `confirmatory-freeze`), 20 conv/ped run ids (`conf-s0-{conv,ped}-r{0..9}`),
scipy 1.17.1 / statsmodels 0.14.6. (`matched_budget.json` stamps the current analysis HEAD; this
differs from `inference.json`'s earlier HEAD because it was generated later — both share the same
`freeze_commit` `1a12b56`, which is what binds the result to the pre-registration.)
**A visible-turn imbalance exists (so the control is meaningful).** In-window (answer-phase)
student-visible tutor turns per conversation: **conv mean 13.5 (median 11.5, 95% CI [10.3, 17.1])
vs ped mean 22.3 (median 23.0, CI [21.0, 23.5])**; paired gap **ped−conv +8.8 (median +11, CI
[4.6, 12.6]), ped>conv in 8/10 replicates**. §9.5 totals per conversation: model calls conv 68 /
ped 92; tutor tokens conv 20.8k / ped 30.1k. PedTutor scaffolds to the answer, ConvTutor resolves
fast — exactly the metric-amendment "tutoring-until-answer" asymmetry.
**Matched-budget mechanics, disclosed.** Because conv is the smaller side, K = min mostly equals
conv's own count: conv is largely a no-op and **ped is truncated down to conv's turn budget**.
**5 cells have K=0** — a cell where *either* condition has 0 in-window tutor turns; the rule is
condition-blind (`min()` is symmetric) and drops the cell for **both**. In this data all 5 are
ConvTutor immediate-commit problems (conv 0 / ped >0 in-window tutor turns: r0/train-4,5,6 and
r3/train-5,6), so the drop removes 5 conv student attempts (all `attempt=True`) and ped's turns on
those problems — the intended "no matched tutoring to compare" behavior, not a bug.
**Marginals — full window vs matched budget (n=10, same §10 paired two-sided Wilcoxon, Cliff's
delta, conversation-level bootstrap CIs):**
  - **P1 leakage (manipulation check, predicted conv>ped): HOLDS.** full conv .430 vs ped .064,
    diff **+0.365** CI [+0.217, +0.516], p=**.0039**, δ **+0.96**, SIG → matched conv .430 vs ped
    **.041**, diff **+0.389** CI [+0.241, +0.540], p=**.0039**, δ **+0.96**, SIG. If anything the
    gap is marginally *larger* under the matched budget (ped's earliest turns leak even less).
  - **P2 annotator-perceived helpfulness (LIVE test, predicted conv>ped): HOLDS (still null /
    slightly reversed).** full diff −0.094 CI [−0.251, +0.058], p=.160, δ −0.10, n.s. → matched
    diff −0.082 CI [−0.229, +0.057], p=**.426**, δ −0.13, n.s. Direction and (non-)significance
    unchanged; the p-value moves further from significance.
  - **P3 independence (manipulation check, predicted ped>conv): HOLDS but WEAKENS.** full diff
    −0.076 CI [−0.189, +0.021], p=.375, δ −0.22, n.s. → matched diff −0.040 CI [−0.181, +0.089],
    p=**.695**, δ **−0.10**, n.s. Same direction (ped>conv) and same non-significance; the effect
    shrinks (truncating ped's later, more-independent turns moves it toward conv).
**§10 FLAG: nothing flagged. No marginal changes direction or significance under the matched
visible-turn budget.** (The §10 clause "any result that disappears under matched budgets is
flagged" fires on none of the three.)
**J2 (headline coupling) — SECONDARY robustness on the truncated turn set: pooled coupling HOLDS;
within-ped cell is underpowered (disclosed, not re-spec'd).** Pooled leaky/non-leaky cells **57 /
199**; leak→helpfulness crossed mixed coef **+0.295**, p=**2e-4** (clustered +0.264, p=.004);
leak→next-turn-independence crossed mixed coef **−0.355**, p**<1e-4** (clustered −0.384, p=.020) —
both legs significant in the predicted directions, so the headline survives equalizing visible
turns. **§10 step-4 caveat (now reported):** the frozen J2 pools conv+ped and leakage correlates
with condition, so the 57 leaky turns are **51 conv + only 6 ped** under truncation (full window:
52 conv + 14 ped). The **ped-leaky cell falls to 6** (<10), so the *within-ped* leakage evidence is
**underpowered** — the pooled coupling is driven by ConvTutor's leaky turns. This is reported
descriptively with the cell sizes; J2 is **NOT** re-spec'd (no condition covariate, frozen §10).
The matched_budget.json carries `j2_leaky_cell_sizes_by_condition` with the flag.
**Both §10 compute-fairness views now reported together.** Per-1k-tutor-token sensitivity (already
in `inference.json`, surfaced alongside): leaky_turns_per_1k diff +0.211, p=.002, SIG, no flip;
independent_turns_per_1k diff −0.070, p=.131, n.s., no flip.
**One-line verdicts:** P1 **holds**; P2 **holds** (null/reversed); P3 **holds but weakens**; J2
**holds**; realized ped−conv in-window turn gap **+8.8** (ped 22.3 vs conv 13.5). The pre-registered
divergence (J2 + the P1 manipulation check hold; P2/J1 do not) is **robust to the matched
visible-turn budget**.
**Changed nothing upstream (verified — scoped to THIS pass).** No session re-run, no turn
re-judged (a tripwire `analysis.judge` that raises on access is asserted in the test). This pass
modified **no frozen artifact and no upstream code**: it added only `analysis/matched_budget.py`,
`tools/test_matched_budget.py`, the two `*.final.csv` write-up tables, and the two decisions-log
entries above. Verified at implementation time — frozen-artifact diff vs `confirmatory-freeze` was
EMPTY across paper-plan / metric-amendment / domain / supplement / agents / `metrics.py` /
`compute_metrics.py` / `judge.py` / configs / protocol / student; confirmatory log manifest
re-verifies **90/90 OK** (logs untouched).
**Worktree note (2026-06-27).** A raw `git status` does NOT show only this pass's files. The tree
is concurrently carrying a **separate, later cross-model tutor-base extension** (its own 2026-06-27
entry below): additive `paper-plan.md` §12 plus `experiments/run_confirmatory.py` /
`analysis/run_inference.py` / `tools/test_run_confirmatory.py`. That work is **not part of this
pass** — its §12 addition to the otherwise-frozen `paper-plan.md` belongs to that effort's own
additive freeze and review, not this one. This pass should be committed on its own so its diff is
clean (its four new files + these two entries). Foundational faithfulness invariant: recomputing every marginal with **no** truncation
reproduces the frozen `per_replicate.csv` exactly (0 mismatches, 20×3). Offline suites green:
`tools/test_matched_budget.py` 31/31, `tools/test_inferential.py` 48/48, `tools/test_metrics.py`
77/77.
**Write-up export (version-controlled).** Two tidy `*.final.csv` tables are written to the
top-level `results/` dir (the only path `.gitignore` tracks under `results/`):
`results/matched_budget.final.csv` (the P1/P2/P3 full-vs-matched marginals + the J2 legs) and
`results/matched_budget_turns.final.csv` (realized in-window turn counts + the ped−conv gap). The
full detail stays in the gitignored `results/confirmatory/matched_budget.json`.
**HOLD (workflow):** uncommitted; the maintainer commits/freezes after the independent
adversarial-review gate. The freeze tag stays at `1a12b56`.
**Affects:** `analysis/matched_budget.py` (new), `tools/test_matched_budget.py` (new, 31 checks),
`results/confirmatory/matched_budget.json` (new; gitignored), `results/matched_budget.final.csv` +
`results/matched_budget_turns.final.csv` (new; version-controlled write-up tables), `decisions-log.md`.
**NOT touched:** any frozen artifact or log; no upstream analysis code modified.

### 2026-06-27 — Cross-model tutor-base extension (GPT / Gemini): PRE-REGISTERED + base-tagging infra (Phase 0; no runs yet)
**Context:** the primary confirmatory result is on a SINGLE tutor base (Sonnet 4.6, freeze
`1a12b56`). The coupling/divergence finding (J2 holds; session-level P2/J1 do not) is far more
credible if it is tested on more than one base model — the breadth the argument needs. This entry
pre-registers a cross-model EXTENSION that re-runs the SAME experiment with ONLY the tutor model
swapped, on additional bases, BEFORE any cross-model datum is collected. It is a strict extension:
the Sonnet primary is **not re-run and not touched**; its artifacts stay byte-stable at `1a12b56`.
Phase 0 (this entry) pre-registers + freezes the design and lands the run/analysis tagging that
keeps bases separated; Phase 1 (later, lead-run) wires each per-base config, runs the leakage gate,
runs the frozen 10×3, and runs the frozen §10 inference per base.
**Decision (frozen before any base run):**
1. *Bases.* (i) Sonnet 4.6 — the primary, already collected, NOT re-run. (ii) A current strong
   GPT-4-class OpenAI chat model. (iii) A current Gemini 2.5-or-later model (Google folded LearnLM
   into Gemini 2.5+; the standalone LearnLM is discontinued, so the pedagogically-tuned line is now
   reached through Gemini 2.5+). (iv) The optional open-weight backup is a **fixed NO for v1** —
   excluded, decided now (before data) to remove a post-hoc selection point; a later open-weight base
   would be its own pre-registered addition. **Exact-id pinning (tightened after the independent-review gate, #3
   in the hardening note below):** each base's exact model id + provider is chosen by a
   DETERMINISTIC rule — the vendor's current flagship general-purpose chat model (not a
   reasoning/mini/nano variant) — and **pinned in a dated decisions-log addendum BEFORE that base's
   leakage gate and any live session**, recorded with the vendor's then-current model list as the
   availability evidence. The id is **never re-selected after seeing any leakage rate or outcome**.
   ("Pinned at run time" alone was a model-shopping loophole; pinning before the gate, by a fixed
   rule, with no reselection, closes it.)
2. *Only the tutor changes.* For every base, the student (OpenRouter→Groq Llama-3.1-8B), the judge
   (Opus), the 19-problem set, the continuous protocol, the frozen answer-phase evaluation window
   (metric-amendment 2026-06-19), BOTH tutor prompts (minimal ConvTutor + the frozen PedTutor
   LangGraph), and ALL metric definitions (§9) are byte-identical to the primary. The base swap is a
   one-line tutor-model change in a per-base `configs/models.<base>.yaml`; both ConvTutor and
   PedTutor use that identical tutor config (capability control preserved within the base, exactly
   as in the primary).
3. *Per-base ConvTutor-leakage gate (failure mode #3).* Before reading any base's primary outcomes,
   run the leakage check (`protocol/leakage.py` over the frozen problems) on that base's
   minimal-prompt ConvTutor and log the rate. The minimal ConvTutor is expected to leak emergently
   (it did on Sonnet, ~52%). If a base's ConvTutor does NOT leak, that is a **reported finding**
   about that base — NOT a reason to touch the ConvTutor prompt. The prompt is never tuned to force
   leakage on any base; "report, don't tune."
4. *Per-base analysis = the frozen §10 inference, grouped by base.* Each base's logs go through the
   SAME `analysis/compute_metrics.py` + `analysis/run_inference.py` as the primary, producing the
   same verdict table (P1/P2/P3 marginals with Cliff's delta + conversation-level CIs, J1, J2). No
   new covariates, no alternative specs, no re-spec. Bases are analyzed **separately and NEVER
   pooled**: separation is by the per-base namespaced log dirs + explicit per-base analysis
   invocations (the runner prints base-specific globs and a `results/confirmatory_<base>` out dir).
   A **code-level mixing guard ships in THIS Phase-0 commit** (moved earlier after the independent-review gate, #1
   in the hardening note below): `compute_metrics` extracts each run's base from its call tags and
   REFUSES to analyze a set spanning more than one base; the analyzed base is stamped into
   `metrics_summary.json` and carried into `inference.json` provenance — so a careless broad glob like
   `logs/conf-*` can never silently pool two bases. "Never pooled" is now a guardrail, not operator
   discipline. A matched-budget compute-fairness pass per base is a nice-to-have if time allows.
5. *Report every base; effects may differ.* Every base that is run is reported, whatever it shows
   (§11, no file-drawer) — no cherry-picking which bases appear. Effects are EXPECTED to differ
   across bases; cross-base heterogeneity (e.g. J2 strong on one base, weak on another) is the
   cross-model finding, not a failure of the extension.
**Base-tagging infrastructure (landed in this Phase-0 commit; condition-neutral; primary byte-stable):**
- `experiments/run_confirmatory.py` gains `--base <slug>`. When set it (i) namespaces every run
  id/dir `conf-<base>-s<seed>-<cond>-r<r>` so a base run can never overwrite or be pooled with the
  primary `conf-s<seed>-...` cells; (ii) stamps `base` on EVERY model call alongside
  `condition`/`replicate_id`; (iii) records `base` + the resolved `tutor_model` in
  `confirmatory_meta.json`. All three are **omitted when base is empty**, so the primary reproduces
  the existing run ids and call tags **byte-for-byte** and the primary `confirmatory_meta.json`
  **key set is byte-identical** to the frozen runner's (the meta's inherent per-run wall-clock
  timestamps aside) — the Sonnet cells are unaffected. The base slug is validated to a lowercase
  `[a-z0-9-]` slug with alphanumeric ends.
- `experiments/run_confirmatory.py` also gains two integrity guards (added after the independent-review gate):
  (a) `tutor_only_drift` — when `--base` is set, the per-base config is compared to the frozen
  primary `configs/models.yaml` and the run is REFUSED unless the ONLY difference is the tutor model
  (student, judge, the providers they use, the tutor sampling budget, and the global backend must all
  match) — so "only the tutor changes" is enforced, not just logged; (b) `cell_meta_mismatch` — an
  invocation-aware resume guard that refuses to skip a file-complete cell whose recorded meta (base,
  tutor_model, models_config, seed, condition, replicate_id, backend, max_train_turns, freeze head)
  disagrees with the current invocation, so a stale/contaminated cell under the same
  `conf-<base>-s..` namespace is never silently skipped. Legacy/primary cells (no base/tutor_model in
  meta) are not flagged.
- `analysis/run_inference.py` gains `--freeze-tag` (default `confirmatory-freeze`). A base passes
  its EXTENSION freeze tag so the base's `inference.json` provenance binds to the extension
  pre-registration, not the primary's. The inference COMPUTATION is unchanged — only the provenance
  label. Added after the independent-review gate: it **fails fast** if the freeze tag does not resolve to a commit
  (no null-freeze provenance), and carries the analyzed `base` into provenance.
- Tests: `tools/test_run_confirmatory.py` adds `test_base_namespacing` (id disjointness, base tag on
  every call, meta records base + tutor_model for a base run, and — for a base-less run — the meta
  **omits** base/tutor_model with a key set **exactly** equal to the frozen primary's), plus
  `test_tutor_only_drift`, `test_cell_meta_mismatch`, `test_protocol_knob_drift`,
  `test_base_pooling_guard`, and base asserts in `test_pairing`. Offline suites green:
  test_run_confirmatory 98/98, test_inferential 48/48, test_metrics 77/77, test_judge 38/38,
  test_matched_budget 31/31. The primary's recomputed leakage/independence/accuracy/cost are
  byte-identical (0/30 rows changed) — the new analysis guards are pre-flight only.
**Provenance recorded per base (Phase 1):** base + exact pinned tutor-model id, extension freeze
commit, run ids, `served_provider` per call, scipy/statsmodels versions.
**Reason:** a single-base result cannot distinguish "the coupling is a property of conversational
alignment" from "a quirk of one model." Re-running the identical, frozen protocol with only the
tutor swapped — pre-registered, report-all-bases — is the clean way to test breadth without giving
the extension any degree of freedom to chase a result. Holding the student, judge, problems, window,
prompts, and metrics fixed makes the base the only moving part.
**Alternatives considered:** (a) Re-running everything (new student/judge/problems) per base —
rejected: it confounds the base swap with other changes and makes cross-base comparison meaningless.
(b) Pooling bases into one model with a base covariate — rejected: it adds a spec not in frozen §10
and invites a fishing expedition; per-base frozen inference, reported separately, is the
pre-registered plan. (c) Tuning the ConvTutor prompt on a base that doesn't leak — rejected
outright: that would manufacture the manipulation check and rig the comparison; a non-leaking base
is a reportable finding. (d) Hard-committing exact GPT/Gemini model ids in THIS entry now — deferred
to a dated addendum the maintainer files BEFORE each base's leakage gate (provider availability shifts and
cannot be confirmed from this offline environment); the selection rule is deterministic and the id is pinned
before any data and never re-selected (point 1), which closes the model-shopping loophole without
pre-registering a stale id.
**HOLD (workflow):** uncommitted. An independent adversarial-review gate was run on this
changeset (2026-06-27) and returned needs-attention; every finding was addressed in this same Phase-0
changeset (see the hardening note below). The maintainer re-runs the gate if desired, then lands the
EXTENSION FREEZE as its own commit/tag (e.g. `crossmodel-freeze`); Phase 1 (per-base configs + live
runs) begins only after that. The primary freeze `1a12b56` is untouched and Sonnet is not re-run.
**Affects:** `experiments/run_confirmatory.py` (`--base` run-id namespace + per-call base tag + meta
base/tutor_model; `tutor_only_drift` only-the-tutor-changes guard; `cell_meta_mismatch`
invocation-aware resume guard), `analysis/compute_metrics.py` (base extraction + multi-base pooling
refusal + base in `metrics_summary.json`), `analysis/run_inference.py` (`--freeze-tag` provenance
label + fail-fast on an unresolvable tag + base in provenance; inference computation unchanged),
`tools/test_run_confirmatory.py` (base + guard tests), `paper-plan.md` (additive cross-model
subsection; §4/§9/§10 substance unchanged), `decisions-log.md`. **NOT touched:** any frozen artifact
(problems, `configs/models.yaml`, both tutor prompts/configs, rubrics, prompts, paper-plan §4/§9/§10
substance, metric-amendment, `analysis/metrics.py`, `analysis/judge.py`), the primary Sonnet
logs/results (recomputed leakage/independence/accuracy/cost byte-identical), or the §10 inference
computation; `configs/models.<base>.yaml` is Phase 1 (not created here).

### 2026-06-27 — Cross-model extension: hardening after the independent adversarial-review gate
**Context:** the independent adversarial-review gate was run on the Phase-0 changeset
above and returned **needs-attention** (5 findings: 4 high, 1 medium) — all challenging that Phase 0
*documented* integrity guarantees it did not yet *enforce*. The findings were evaluated and all were
agreed and addressed in the same Phase-0 changeset (kept as one extension freeze, not deferred to
Phase 1), since each is a guardrail that must exist before the first live base run.
**Decision (what was fixed):**
1. *Base pooling was operator discipline, not a guardrail (high).* Fixed: `compute_metrics` now reads
   each run's `base` tag and **refuses** to analyze a set spanning >1 base; the analyzed base is
   recorded in `metrics_summary.json` and `inference.json` provenance. A broad glob like
   `logs/conf-*` can no longer silently average primary + GPT + Gemini cells that share replicate ids.
2. *"Only the tutor changes" was not enforced (high).* Fixed: `tutor_only_drift` compares a per-base
   config to the frozen `configs/models.yaml` and **refuses** the run unless only the tutor model
   differs (student, judge, their providers, the tutor budget, and the backend must match). Recording
   `tutor_model` was audit-after-the-fact; this is prevention.
3. *Runtime model-id pinning was a model-shopping loophole (high).* Fixed in the pre-registration
   (point 1 of the entry above): exact ids are pinned by a deterministic flagship-selection rule
   **before each base's leakage gate**, with the vendor model list as evidence and **no result-based
   reselection**; the optional open-weight base is a **fixed NO for v1**. (Pre-registration tightening,
   not code — exact ids cannot be confirmed from this offline environment.)
4. *Resume could skip stale base cells (high).* Fixed: `cell_meta_mismatch` makes resume
   invocation-aware — a file-complete cell is only skipped if its recorded base, tutor_model,
   models_config, seed, condition, replicate_id, backend, max_train_turns, and freeze head match the
   current invocation; otherwise the run is refused (quarantine + re-run). Legacy/primary cells are
   not falsely flagged.
5. *Unresolved freeze tag wrote null provenance (medium).* Fixed: `run_inference` **fails fast** when
   `--freeze-tag` does not resolve to a commit, so results can never be labeled extension-bound with
   no real freeze commit.
**Reason:** the gate's core point was correct — a pre-registered extension must *enforce* its
integrity claims, not just state them; otherwise "never pooled" / "only the tutor changes" reduce to
operator discipline. Moving the guards into the Phase-0 freeze (vs deferring to Phase 1) means the
infra the first base run uses is already hardened and frozen.
**Alternatives considered:** deferring #1/#4 to Phase 1 (as originally written) — rejected: the
guards must exist before the first base run, which is exactly when the holes would bite. Pinning exact
model ids in this entry (#3) — deferred to a pre-leakage-gate addendum the maintainer files with live
provider access (the rule is fixed now; only the id slot is filled later).
**Affects:** `analysis/compute_metrics.py`, `experiments/run_confirmatory.py`,
`analysis/run_inference.py`, `tools/test_run_confirmatory.py` (guard tests),
`decisions-log.md`, `paper-plan.md` (§12 model-id note). **NOT touched:** any frozen measurement
artifact or the §10 inference computation; the primary's recomputed metrics are byte-identical.

### 2026-06-27 — Cross-model extension: round-2 hardening (second independent adversarial-review gate)
**Context:** the independent adversarial-review gate was re-run on the round-1-hardened changeset
and returned **needs-attention** again (5 findings: 4 high, 1 medium) — this time deeper paths where a
guard existed but did not cover every route. The findings were evaluated; the "recommended set" was
implemented (the realistic operator-accident paths) and two of the review's sub-recommendations were
trimmed as redundant/over-engineered (recorded below). Threat model: the operator is the maintainer, who
*wants* integrity — guard against accidents (a forgotten flag, a tweaked knob, a stale dir), not an
adversary fabricating data. Decision (with the maintainer): re-run cold,conv,ped per base (cold is
tutor-invariant but is re-run for an exact protocol match).
**Decision (what was fixed):**
1. *Protocol-knob drift past the only-tutor guard (high).* `tutor_only_drift` only checked the model
   config; a `--base` run could still change `--domain / --conditions / --replicates / --base-seed /
   --max-train-turns`. Fixed: `protocol_knob_drift` — a **live** `--base` run is refused unless these
   knobs match the registered protocol (domain `domain/algebra/problems.yaml`, conditions cold,conv,ped,
   10 replicates, base_seed 0, max_train_turns 4). Mock rehearsals are exempt (stay flexible).
   *Trimmed:* hashing the frozen problem/prompt/metric files into meta — the freeze guard already
   forces HEAD==freeze + a clean tree on live runs, so those FILES are byte-stable; only the runtime
   knobs were uncovered.
2. *Resume skipped base cells with missing base provenance (high).* `cell_meta_mismatch` tolerated
   absent fields (to spare legacy/primary cells). Fixed: a base invocation passes
   `require_present=("base","tutor_model")`, so a complete base cell **missing** them is flagged, not
   skipped; primary invocations still tolerate absence. *Trimmed:* re-reading every call in
   calls.jsonl during resume — `compute_metrics._session_base` already refuses absent/mixed base tags
   at analysis time.
3. *Helpfulness judge could drift in the analysis pass (high).* `compute_metrics` built the judge from
   whatever `--models` pointed at. Fixed: a **live** `--judge-helpfulness` pass now requires the judge
   role to equal the frozen primary judge (`configs/models.yaml`) and reps==3, and the judge is stamped
   into `metrics_summary`. The judge is part of "only the tutor changes". (Mock judge exempt.)
4. *Freeze-tag resolved-but-WRONG (high).* `run_inference` only checked the tag resolved; forgetting
   `--freeze-tag` on a base result would stamp the primary freeze. Fixed: `compute_metrics` stamps each
   run's recorded `freeze.head` into `metrics_summary.freeze_heads`; `run_inference` (a) refuses the
   default `confirmatory-freeze` when `base != primary`, and (b) requires the resolved freeze commit to
   match the recorded run head(s).
5. *Hand-assembled results dir bypassed the pooling guard (medium).* Fixed the cheap half:
   `metrics_summary.json` is now **mandatory** in `run_inference` (no silent default-to-primary when
   missing) and per_session run_ids must be a subset of the summary's run list. *Trimmed:* adding a
   `base` column to every per_*.csv — schema churn for an adversarial hand-assembly case the careful
   operator will not hit; the mandatory-summary + run_id check closes the realistic path.
**Reason:** findings 1–4 are real operator-accident paths on the central invariants; cheap to close
in the Phase-0 freeze so the infra the first base run uses is already hardened. Finding 5 and the
trimmed items slide toward defending against a researcher actively trying to fabricate — diminishing
returns — so only the cheap, realistic part was taken. Backward-compatible: the committed primary
`metrics_summary.json` (no base/freeze_heads keys) still runs; recomputing the primary is
byte-identical.
**Alternatives considered:** implementing every review sub-recommendation (file hashing, per-call resume
cross-check, base column in all CSVs) — rejected as redundant with the freeze guard / pooling guard or
as over-engineering for a non-accident threat. Deferring any of 1–4 to Phase 1 — rejected: the guard
must exist before the first base run.
**Verification:** test_run_confirmatory 98/98 (added `test_protocol_knob_drift` + base-require resume
case); the four CLI-only guards (live knob exemption for mock, judge-identity refusal, run_inference
mandatory-summary / base-vs-primary-tag / freeze-head-mismatch) verified by hand against scratch
copies; primary metrics recompute byte-identical (0/30); frozen artifacts unchanged; paper-plan still
additive.
**Affects:** `experiments/run_confirmatory.py` (`protocol_knob_drift`; `cell_meta_mismatch`
`require_present`), `analysis/compute_metrics.py` (`_session_freeze_head` + `freeze_heads` in summary;
live judge-identity guard), `analysis/run_inference.py` (mandatory summary; base-vs-tag, freeze-head,
and run-id guards), `tools/test_run_confirmatory.py`, `decisions-log.md`. **NOT touched:** any frozen
measurement artifact or the §10 inference computation; the primary's recomputed metrics are
byte-identical.

### 2026-06-27 — Pedagogical-quality judge (THIRD evaluator) + 3-way divergence view: PRE-REGISTERED EXTENSION, rubric FROZEN before any data
**Context:** the experiment has two post-hoc evaluators of the visible training tutor turns — generic
annotator-perceived **helpfulness** (§9.4, `analysis/judge.py`, deliberately strategy-blind) and student
**independence** (§9.3). The headline J2 story is a *divergence*: the helpfulness signal can reward exactly
the turns that suppress independent student work. A direct way to show that divergence is to add a THIRD
lens — the **pedagogical quality** of the tutor's move, scored on cited learning-science principles — and
line all three up per turn. This entry pre-registers and **freezes** that judge as a strict **EXTENSION**
on the frozen primary, BEFORE it is applied to any data. It is additive: it adds **no new prediction,
metric, or confirmatory test** and changes **nothing** in §4/§9/§10, the helpfulness judge, the problem set,
the answer-phase window, or either tutor prompt. Those frozen artifacts stay byte-stable (manifest = log
files; source-side, the helpfulness judge + rubric and all metric definitions are untouched). **Sequencing
(audit boundary):** as of this entry only the OFFLINE MOCK plumbing pass has run (synthetic scores, no real
data read into the instrument); the LIVE application to the Sonnet primary logs is the key-holder's and
happens **after** this freeze, as commit 2 (the two-commit split is spelled out under Validation below). To
each cross-model base's logs as they land (the §12 base-separation guards already cover it).
**Decision (frozen before any data):**
  1. **Shape / location.** New `analysis/judge_pedagogy.py` mirrors `analysis/judge.py` exactly — same
     `role="judge"` Opus call, `parse_pedagogy_scores` / `aggregate_reps` / `make_pedagogy_judge_fn` /
     `judge_pedagogy_session`, 3 reps + sample variance (ddof=1), per-rep cache keyed by
     `(run_id, problem_id, turn_index, rep)`. New opt-in `--judge-pedagogy` in `compute_metrics.py`, judge
     calls to their own `logs/pedjudge-*/` dir (post-hoc measurement, **out of the §9.5 cost** like the
     helpfulness/independence passes), fail-fast without the key + a `--judge-backend mock` offline path.
     The reserved `pedagogy` / `pedagogy_mean` columns are filled through the **same** table builders via new
     backward-compatible optional args (default None = old behavior), exactly as the helpfulness columns
     were — no metric value or existing column changes.
  2. **Same turns, same window, same context as the helpfulness judge.** The pedagogy judge rates the SAME
     visible **training** tutor turns over the SAME frozen answer-phase window, and reuses
     `analysis/judge.py:dialogue_for_turn` (not a re-implementation) so the two judges see **byte-identical**
     dialogue per turn. So per turn the three evaluators (helpfulness, pedagogy, next-turn independence) line
     up 1:1.
  3. **The rubric (the fair-test crux).** Frozen verbatim in `supplement/judge_pedagogy_rubric.md`: four
     sub-scores tied to four cited principles — **scaffolding** = contingent scaffolding (Wood/Bruner/Ross
     1976); **productive_struggle** = non-disclosure / the generation effect (Slamecka/Graf 1978);
     **assistance_calibration** = the assistance dilemma (Koedinger/Aleven 2007); **elicitation** = eliciting
     student work / uptake (Aleven et al. 2006) — plus a holistic `overall` (1–5); the per-turn pedagogy IS
     `overall`. The rubric is written to be **SYMMETRIC**, the opposite of tautological: it scores the move
     **blind to which tutor produced it**, and it **explicitly forbids rewarding withholding for its own sake
     OR answer-giving for its own sake**. Disclosure is judged by whether it served the student's learning at
     that moment (a clear, well-targeted hint that builds on the student's attempt is good pedagogy even if it
     reveals part of the answer; a generic "keep trying, what do you think?" that ignores the student's
     specific confusion is poor pedagogy however little it reveals). `productive_struggle` and
     `assistance_calibration` each carry an explicit both-directions guard so vague stalling is **not**
     credited as struggle and is penalized as under-assistance. **Reason:** if the rubric credited
     "PedTutor behavior" or "any withholding," PedTutor-pedagogy would be true by construction and the
     divergence result would be rigged. It must be able to credit a scaffolding ConvTutor turn and penalize a
     vague PedTutor turn; that symmetry is the whole point.
  4. **No answer leakage / condition-neutral.** The judge prompt is dialogue text + the rubric only — never
     `canonical_answer`, the leakage strings, the node names, or the condition label (asserted in
     `tools/test_judge_pedagogy.py`). Like the helpfulness rubric it does **not** judge mathematical
     correctness (the judge has no canonical answer anyway) — it rates the pedagogical quality of the *move*.
     Same rubric, context, and rep count for both tutors.
  5. **Same judge as the primary.** A reportable (live) pedagogy pass must use the IDENTICAL `role="judge"`
     model as the frozen helpfulness judge (`configs/models.yaml`, `claude-opus-4-8`, reps==3), enforced in
     `compute_metrics._run_judge_pedagogy` — the divergence view compares the two judges, so they must be the
     same instrument across bases (§9.4/§12). Mock backend exempt (offline plumbing).
  6. **Divergence view (descriptive EXTENSION).** New `analysis/divergence.py`: per turn and per session it
     z-standardizes the three signals (helpfulness, pedagogy, independence), reports a per-unit disagreement
     spread (max−min over present z-scores), pairwise agreement (Pearson + Spearman), and the turns/sessions
     where the three most disagree. Emitted to `results/divergence_detail.json` when `--judge-pedagogy` and
     `--judge-helpfulness` are both run. **Explicitly descriptive/exploratory: it is NOT a §10 inferential
     test and does not change J1/J2.** A signal with an empty column simply drops out.
**Reason:** faithful to the four cited principles, not to the metrics; every choice mirrors the frozen
helpfulness plumbing so the comparison is apples-to-apples; the rubric is frozen pre-data so it cannot be
accused of manufacturing the divergence. It deepens the J2 story (when do helpfulness, pedagogy, and
independence agree vs diverge) without touching the confirmatory claim.
**Alternatives considered:** (a) reward "non-disclosure" directly — REJECTED (tautological; rigs the
divergence). (b) judge mathematical correctness — REJECTED (needs the answer → leakage; and the construct is
the teaching move, not the math). (c) put the divergence into §10 as an inferential test — REJECTED (it is
descriptive; §4/§9/§10 stay frozen). (d) a second rubric inside `judge.py` — REJECTED in favor of a separate
module so the frozen helpfulness judge is provably untouched (it reuses only the shared, generic
`dialogue_for_turn`/`cache_key`). (e) extend the mock `_mock_judge` to emit pedagogy sub-scores — REJECTED
(unnecessary; the mock already emits `overall`, which is the pedagogy metric, so model_client.py stays
untouched — sub-scores need the live judge).
**Validation:** offline, no key. `tools/test_judge_pedagogy.py` **51/51** — five-field parser on
good/garbled/garbage JSON, mean + sample-variance aggregation dropping unparseable reps, the
canonical-answer/condition/node-name absence + the rubric-symmetry guards, the responder-not-`state_tracker`
check, the answer-phase window restriction, the training-only restriction, the per-rep cache (no re-pay), the
column merge filling the reserved columns, the divergence z-standardization/disagreement/pairwise agreement,
and an end-to-end mock pass over `conv-20260618-132733-606`. Regression: `tools/test_judge.py` **38/38**
(helpfulness judge untouched), `tools/test_metrics.py` **77/77** (optional args backward-compatible),
`tools/test_run_confirmatory.py` **98/98**. End-to-end offline mock `--judge-helpfulness --judge-pedagogy
--judge-backend mock` over the real Sonnet conf-s0 conv/ped/cold logs filled the per-turn `pedagogy` and
per-session/per-replicate `pedagogy_mean`, wrote `pedagogy_detail.json` + `divergence_detail.json`, and
produced the per-turn/per-session agreement + top-disagreement view (cold blank — no tutor turns). The mock
scores are synthetic noise (ConvTutor==PedTutor generic mock text), so the mock divergence numbers are **not
a finding** — they validate plumbing only. **The live Opus pedagogy pass + the real divergence report are the
key-holder's to run** (same discipline as the Step-6 live eyeball run), one command where the key is set:
`ANTHROPIC_API_KEY=... python analysis/compute_metrics.py logs/conf-s0-conv-* logs/conf-s0-ped-* logs/conf-s0-cold-* --out results/confirmatory --judge-helpfulness --judge-pedagogy`
(reuses the cached live helpfulness scores in `results/confirmatory/helpfulness_cache.json`, so only the
pedagogy Opus calls are new). Per the freeze discipline this should land as a **two-commit** freeze: commit 1
= this entry + the frozen rubric + code + tests (the pre-registration); commit 2 = the live divergence
result, reported per §11 whatever it shows.
**Affects:** `analysis/judge_pedagogy.py` (new), `analysis/divergence.py` (new),
`analysis/compute_metrics.py` (`--judge-pedagogy`, `_run_judge_pedagogy`, `_judge_summary_block`,
`_print_judge_table`, `_print_divergence`, combined judge-table rebuild + divergence emission),
`analysis/metrics.py` (additive optional `pedagogy` args on `per_turn_rows` / `per_session_row` /
`per_replicate_rows`; a `pedagogy` per-turn column and `pedagogy_mean` per-session/replicate column, both
None until the judge runs — the same reserved-column pattern as helpfulness), `supplement/judge_pedagogy_rubric.md`
(new, FROZEN), `tools/test_judge_pedagogy.py` (new), `paper-plan.md` (new §13 extension note; §4/§9/§10
untouched). **NOT touched:** `analysis/judge.py`, `supplement/judge_rubric.md`,
`supplement/independence_rubric.md`, the problem set, the answer-phase window, both tutor prompts, the §10
inference, or any frozen log. **Next:** key-holder runs the live pedagogy pass on the Sonnet logs (commit 2);
the same flags apply to each cross-model base as it lands.

**Addendum (2026-06-27, independent adversarial review — pre-commit, pre-data).** Ran a 6-agent skeptical
review (4 lenses — tautology/favoritism, no-answer-leakage, alignment/comparability, freeze-integrity —
plus 2 independent attempts to construct a turn that breaks the rubric's symmetry). **Verdict: 6/6 SHIP, no
MUST-FIX.** The BLOCKING tautology check passed: a disclosing-but-scaffolding ConvTutor turn scores high and a
vague/unresponsive PedTutor turn scores low under the frozen prompt; both independent counterexample attempts
failed to find a systematic withholding/PedTutor tilt at the level of the reported metric (`overall`, governed
by the in-prompt neutrality block which is explicitly two-sided). One code/doc inconsistency fixed (the only
actionable item): `compute_metrics` now emits the divergence view only when BOTH `--judge-pedagogy` and
`--judge-helpfulness` ran, matching the frozen rubric's "with --judge-helpfulness also set" wording (code
conformed to the frozen doc; the rubric was not touched). Three transparency caveats recorded (no instrument
change — the operational prompt was validated as fair, and editing the frozen rubric to chase clarity would
itself be an integrity violation):
  - **Construct overlap (the substantive one; now disclosed in §13).** PedTutor's responder nodes are built
    on the SAME four principles the pedagogy judge scores (agents/ped_tutor.py: decomposer→assistance dilemma,
    deferral_gate→generation effect, hint_cascade→help-seeking/uptake, scaffolding throughout). So a
    pedagogy-favoring result is **partly true by construction** — like leakage (P1) and independence (P3),
    it is a manipulation-check on whether PedTutor realizes its design, **not** independent corroboration. The
    construction-INDEPENDENT content is (i) the helpfulness↔pedagogy **divergence** (helpfulness is
    strategy-blind and is not what PedTutor optimizes) and (ii) the rubric's **symmetry** (a ConvTutor turn
    that genuinely scaffolds is credited). The divergence is reported descriptively and is correctly kept out
    of the confirmatory J1/J2 verdict; §13 now states the overlap so a pedagogy gap is not over-read.
  - **Where the symmetry guards live operationally.** The both-directions guards for `productive_struggle`
    ("vague stalling is not a virtue") and `assistance_calibration` are realized in the judge-visible prompt
    by the **neutrality block** ("a turn that withholds can be poor pedagogy when it leaves a stuck student
    with nothing usable") plus the **holistic `overall`** (the reported metric). The per-dimension explanatory
    bullets in the supplement state design intent; the operational two-sided protection is the neutrality
    block + overall, by design. The omission, where it exists, cuts both ways and does not favor withholding.
  - **"non-disclosure" label.** `productive_struggle` is named "non-disclosure / the generation effect" after
    the pre-registration framing (Slamecka/Graf 1978). Its operational anchor in the frozen prompt is
    "preserve the reasoning step(s) the student can still generate themselves" — the judge never reads the word
    "non-disclosure," so it is not instructed to reward withholding per se; symmetry is enforced by the
    neutrality block. Label retained as the principle's source name.

### 2026-06-27 — Cross-model base SELECTION RULES resolved (Fork 1 OpenAI + Fork 2 Gemini): rule-level, pre-data; exact pins deferred to immutable per-vendor pin records
**Context:** §12 pre-registered the cross-model extension with a deterministic pin rule — "the vendor's
current flagship general-purpose chat model (not a reasoning/mini/nano variant), pinned before that base's
leakage gate, recorded with the vendor's then-current model list, never re-selected after any outcome." Two
judgment calls were left open: (Fork 1) which OpenAI model that resolves to now, and (Fork 2) whether Gemini
should be the flagship general model or a separate LearnLM-tuned variant. This entry resolves BOTH **at the
rule level, before any base is run and before any base leakage gate** — it is a pre-data clarification of the
frozen rule, not new freedom. It does **NOT** pin exact ids: each vendor's confirmed id is recorded later in
its **own separate, immutable per-vendor pin record** (a dated addendum produced at pin time with the live
`list_models.py` evidence + a passing preflight). No live cross-model datum exists yet (the base configs are
still `REPLACE-WITH-PINNED-…` stubs; no `logs/conf-<base>-*` dirs).
**Decision (rule-level; pre-data):**
1. **Fork 2 — Gemini = the flagship general-purpose Gemini Pro; LearnLM is integrated, not a separate model.**
   Google folded LearnLM into Gemini 2.5+, so the pedagogically-tuned line is reached *through* the flagship
   general model — selecting a distinct LearnLM variant is therefore (a) unnecessary and (b) a deviation from
   the "general-purpose flagship" rule. The flagship is both the literal rule choice and the model carrying the
   pedagogical capability that motivated Gemini's inclusion. **Provisional candidate** (subject to the live
   list + preflight): `gemini-3.1-pro-preview`, reasoning at the vendor minimum `reasoning_effort=low`
   (Gemini 3.x cannot fully disable thinking — see config note). Prefer a stable/GA or dated-snapshot flagship
   id over a `-preview` slug if the live list exposes one (preview slugs can drift under a frozen pin).
2. **Fork 1 — OpenAI = the current flagship general-purpose chat model.** "GPT-4-class" in §12 was descriptive
   shorthand from when §12 was written; the operative rule is "current flagship general-purpose chat." Exclude
   reasoning/o-series, `mini`, `nano`. **Provisional candidate** (subject to the live list + preflight):
   the dated snapshot `gpt-5.5-2026-04-23`, reasoning disabled `reasoning_effort=none`.
3. **Provisional → pinned only via the pin-acceptance checklist; exact ids in separate immutable records.**
   The ids above are **PROVISIONAL**. A vendor's id becomes a PIN only after it (a) appears in that account's
   live `list_models.py` output (captured as evidence) and (b) passes a **non-study preflight smoke** (below).
   The confirmed pin is then written to that vendor's **own, separate, immutable pin record** (dated
   addendum), **before** that base's leakage gate. After a pin is recorded there is **no reselection after any
   leakage or outcome information is observed** — full stop.
4. **Held config, both bases (capability/config control, guard-enforced).** `temperature 0.4`,
   `max_tokens 1024` identical to the primary (`tutor_only_drift` refuses otherwise). Only the tutor *model*
   (and its provider) changes. Reasoning is set to the **minimum the model permits** (OpenAI `none`; Gemini
   `low`, vendor-imposed). Google's higher recommended default temperature for Gemini 3 is **noted and not
   adopted** — raising it would be a separate formal amendment made before any leakage/outcome, never after.
5. **Request shape (OpenAI-compatible path).** Prefer the **documented `reasoning_effort` field** on the
   request; use `extra_body` **only** for settings the standard compatibility interface cannot express.
   **Tools, search grounding, and code execution are disabled by OMITTING them from the request** (no tools
   array, no grounding/code-exec config), resorting to explicit documented off-fields only if a backend
   requires them. (`model_client` already forwards `extra_body` for any role and the tutor block may carry
   model-specific extras without tripping `tutor_only_drift`, which only pins `temperature`/`max_tokens`/
   student/judge/providers/backend — verified.)
6. **Implementation feasibility is PROVISIONAL until the smoke confirms it.** No `tutor_only_drift` change is
   needed, but the "no code change" claim holds only if the pre-pin smoke confirms the **serialized request
   payload** (model id, `reasoning_effort`, `max_tokens` cap, no tools/grounding), **API acceptance**, the
   **output token cap**, the **returned model identifier**, and the **absence of tools/grounding** in request
   and response. If `model_client` must forward `reasoning_effort` as a documented top-level field (vs
   `extra_body`), that one-line addition is settled by the smoke and recorded with the pin.
**Reason:** keeps the deterministic rule intact and removes model-shopping; maximizes cross-family symmetry
(all three bases are current flagship general-purpose chat models); preserves the pedagogical rationale for
Gemini without special-casing a variant; and quarantines the exact-id choice into separate immutable records
so a pin cannot be silently re-touched after data.
**Alternatives considered:** (a) a LearnLM-specific Gemini variant — REJECTED (specialized, not the
general-purpose flagship; breaks the rule and cross-base symmetry; would need its own dated justification). (b)
pin a rolling alias / `-preview` when a stable id exists — REJECTED for reproducibility (prefer GA/dated
snapshot; pin preview only if it is the sole flagship exposed, with a recorded "may drift" caveat). (c) adopt
Google's higher Gemini temperature — REJECTED (breaks the held config; only via a formal pre-data amendment).
(d) express reasoning/tool settings via `extra_body` when a documented field exists — REJECTED (prefer the
standard `reasoning_effort` field; `extra_body` only for the otherwise-inexpressible).
**Heterogeneity disclosure:** the Gemini-minimum-reasoning requirement is **declared provider-specific
implementation heterogeneity**, written into the §12/§13 carve-out (this commit). It does not threaten the
within-base ConvTutor-vs-PedTutor contrast (analyzed separately, never pooled), but cross-base differences
cannot be attributed solely to model identity, because model family and mandatory reasoning configuration vary
together.
**Validation:** no code or data changed by this entry — it resolves the selection rules and records the held
config + request shape + the provisional candidates. Mechanics verified by inspection: `tutor_only_drift`
(`experiments/run_confirmatory.py:191`) pins only `temperature`/`max_tokens`/student/judge/providers/backend
and permits tutor-block extras; `model_client` (`agents/model_client.py:175`) forwards `extra_body` for any
role on the live OpenAI-compatible path. Offline suites unaffected. The exact ids remain `REPLACE-WITH-PINNED-…`
in `configs/models.gpt.yaml` / `configs/models.gemini.yaml` until each vendor's pin record is produced.
**Affects:** `paper-plan.md` (§12/§13 implementation-heterogeneity carve-out), `experiments/RUN.md` (per-base
runbook + pin-acceptance checklist), `decisions-log.md` (this entry; future per-vendor pin records).
`configs/models.gpt.yaml` / `configs/models.gemini.yaml` are **not** pinned here (still stubs). **Next:** per
vendor, at pin time — run `list_models.py`, apply the rule, pass the pin-acceptance checklist, write the
immutable pin record, then the leakage gate; no reselection after any leakage/outcome.

### 2026-06-27 — Cross-model preflight: ConvTutor-leakage gate made ADVISORY (recorded, non-blocking) for bases
**Context:** §12 already pre-authorizes the semantics ("if a base's ConvTutor does not leak, that is reported
as a finding about the base — it is not a reason to tune the ConvTutor prompt"). But `experiments/preflight.py`
implemented ConvTutor leakage as a **hard gate** (`preflight_exit_code` exits non-zero on any False gate), which
is correct for the primary (no-leak ⇒ the manipulation didn't engage ⇒ uninterpretable) but wrong for a
cross-model base (no-leak is a reportable finding, not a stop). The per-base RUN.md §B step named the gate but
had no command. This entry records the mechanism that makes §B copy-paste and enforces the advisory semantics in
code (per the maintainer's plan), so a base's leakage cannot silently block collection — without weakening any other
gate.
**Decision:**
  1. **Opt-in `--leakage-advisory` (+ `--diagnostic-out`, `--pin-record-ref`).** `preflight_exit_code` gains an
     `advisory_gates` arg; the cross-base mode passes `("convtutor_leaky",)`, excluding ONLY that gate from the
     blocking set. **Every other gate stays blocking** — isolated-cold, FINAL-marker, served-by-Groq — and all
     key/config/API errors still `raise` independently of the flag. **No `|| true`, no blanket ignore.** Default
     (flag off) is byte-identical to the preregistered primary hard-gate behavior.
  2. **Full read + provenance in a SEPARATE artifact.** Advisory mode writes `leakage_diagnostic.json` (to
     `--diagnostic-out`, default the run's log dir) with the **numerator** (`leak_turns`), **denominator**
     (`tutor_turns`), `leak_rate`, the **backend** (so a `mock` rehearsal can't pose as a live read), and
     provenance — tutor model, models config, problem-set sha256, repo commit, timestamp, raw log dir — plus a
     `pin_record_ref` string. It **references** the immutable per-vendor pin record and **never edits it**: the
     model is pinned by rule BEFORE this read (the selection-rule entry above) and is never reselected after it.
  3. **Report, don't tune.** The console + the artifact note state that no leakage result may trigger prompt
     tuning, model reselection, or configuration changes. `preflight_report.json` is left byte-unchanged; the
     enriched record is the separate file, written only in advisory mode.
**Reason:** faithful enforcement of frozen §12 intent (not a deviation); surgical (downgrades one gate, nothing
else); keeps the primary's preregistered semantics intact; and makes the no-leak-is-a-finding rule auditable
with a full, provenance-stamped read rather than a present/absent flag.
**Alternatives considered:** (a) ignore preflight's non-zero exit with `|| true` in the runbook — REJECTED
(would also swallow API/config/cold/student failures). (b) a runbook "inspect the gates, continue only if
leakage is the sole failure" manual rule — kept ONLY as the documented fallback if a code path is ever
unavailable; the enforced flag is the path. (c) overwrite the present/absent flag into the pin record —
REJECTED (the pin is immutable and precedes the read; the diagnostic is separate and references it).
**Validation:** `tools/test_preflight.py` **21/21** — primary hard-gate (leakage absent ⇒ exit 1), advisory
(leakage absent ⇒ 0) while cold/marker/served still exit 1, advisory downgrades ONLY the named gate (cold+marker
both fail ⇒ still 1), the diagnostic records numerator/denominator/rate + backend + provenance + pin ref. Mock
advisory run wrote the diagnostic (19/24 = 79.2%, sha256 + commit) and printed "ADVISORY (recorded,
non-blocking)"; non-advisory mock printed "PASS" and wrote no diagnostic (primary path unchanged). Full suite
green (run_confirmatory 98, metrics 77, judge 38, judge_pedagogy 51). Independent 3-lens adversarial review
(gate-semantics / primary-unchanged+provenance / doc-code consistency): **3/3 SHIP, zero must-fix**; its
NICE-TO-HAVEs (record `backend`; robust `base_slug`; this log entry; the cost-line note) are addressed.
**Affects:** `experiments/preflight.py` (`preflight_exit_code` advisory_gates; `leakage_diagnostic`;
`_sha256_file`/`_git_head`; `--leakage-advisory`/`--diagnostic-out`/`--pin-record-ref`), `tools/test_preflight.py`
(new), `experiments/RUN.md` §B. **NOT touched:** the frozen primary preflight semantics (default off), any frozen
metric/rubric/prompt, or the immutable pin records (referenced, never written).

### 2026-06-28 — Cross-model base PIN RECORD: OpenAI base (gpt) — IMMUTABLE
**Status:** IMMUTABLE. Pinned by the frozen §12 rule BEFORE this base's leakage gate and before any
live session. No reselection after any leakage/outcome (decisions-log 2026-06-27 selection rules).
**Pinned by:** the author   **Pinned at (local wall-clock):** 2026-06-28 03:33

**1. Identity**
- Vendor / base slug: openai / gpt            (run id namespace: conf-gpt-s0-...)
- Provider / endpoint: openai / https://api.openai.com/v1
- Tutor key env: OPENAI_API_KEY          (judge ANTHROPIC_API_KEY, student OPENROUTER_API_KEY — unchanged)
- **Pinned model id (exact): `gpt-5.5-2026-04-23`**
- Id form: dated-snapshot   Reproducibility caveat (if preview/alias): none

**2. Rule application (deterministic; not a preference)**
- Rule: the vendor's CURRENT FLAGSHIP GENERAL-PURPOSE CHAT model — not a reasoning/o-series/mini/nano variant.
- Why this id satisfies it: `gpt-5.5-2026-04-23` appears in the account-visible OpenAI model list as a dated GPT snapshot. Rolling aliases such as `gpt-5.5`, pro variants such as `gpt-5.5-pro`, reasoning/o-series models (`o1`, `o3`), and mini/nano/image/realtime/audio/search/embedding/moderation models were excluded by the frozen rule.

**3. Held config (capability/config control — guard-enforced)**
- temperature 0.4, max_tokens 1024 (identical to primary; tutor_only_drift enforces).
- Reasoning: `reasoning_effort=none`  (disabled).
- Tools / search grounding / code execution: DISABLED by omission (not sent). Documented off-fields used: none.
- Request shape: reasoning via the documented `reasoning_effort` field: none / disabled.

**4. Evidence — live model list (the rule's required record)**
- `list_models.py` run at: 2026-06-28 3:33 (local wall-clock); provider [openai] returned 118 models.
- Pinned id present in the account-visible list: YES.
- Flagship-chat shortlist: captured at `/tmp/openai_models.txt`. Relevant visible candidates included `gpt-5.5`, `gpt-5.5-2026-04-23`, `gpt-5.5-pro`, and `gpt-5.5-pro-2026-04-23`; the dated non-pro general chat snapshot `gpt-5.5-2026-04-23` was selected by rule.

**5. Evidence — non-study preflight smoke (throwaway, NOT a study run)**
- Status: PENDING before leakage gate. The first live non-study smoke / leakage diagnostic will confirm API acceptance, returned model id, max_tokens behavior, and no tools/grounding/code-exec. If this smoke fails, collection stops before any outcome is observed.
- Intended serialized request payload: model=`gpt-5.5-2026-04-23`, reasoning_effort=`none`, max_tokens=1024, temperature=0.4; no tools/grounding/code-exec keys present.

**6. Guards (mock dry run before live)**
- `run_confirmatory --base gpt --models configs/models.gpt.yaml --backend mock` started clean:
  tutor_only_drift PASS (only the tutor model differs), protocol_knob_drift PASS
  (domain/conditions/replicates/base-seed/turns match the registered protocol).
- Mock dry run completed 30/30 cells: 10 replicates × cold/conv/ped.

**7. Freeze**
- Cross-model extension freeze commit/tag this base is collected at: `crossmodel-freeze`.
- `configs/models.gpt.yaml` updated: REPLACE-stub -> `gpt-5.5-2026-04-23` in this pin commit.

**Immutability:** recorded above. The id is frozen for this base; never reselected after any leakage
or outcome. A vendor-forced change requires a NEW dated entry (with rationale) and base recollection.

### 2026-06-28 — Cross-model base FINDINGS: Gemini base (gemini)
**Base:** gemini · tutor `models/gemini-3.1-pro-preview` (reasoning_effort=low) · pin record:
2026-06-28 — Cross-model base PIN RECORD: Gemini base (gemini) — IMMUTABLE
**Provenance:** freeze `crossmodel-gemini-freeze` = `68ee3faf8d1370da15bb7f8ab1a87599389a7eb6` · runs
`logs/conf-gemini-s0-*` · results `results/confirmatory_gemini/` · judge `claude-opus-4-8` / live / reps=3 ·
n = 10 replicates × 3 conditions.

**ConvTutor leakage diagnostic (advisory, §12):** 2/24 = 8.3% (present but low — reported finding, NOT tuned).
Ref: `results/leakage_diag_gemini/leakage_diagnostic.json`

**Marginals — PedTutor vs ConvTutor, paired by replicate (Wilcoxon two-sided, Cliff's δ, 95% CI):**
- P1 leakage:       conv 0.113 vs ped 0.075 | diff(conv−ped) +0.038 CI [-0.039,+0.118] | p=0.6250 | δ=+0.32 | n.s.
- P2 helpfulness:   conv 4.976 vs ped 4.887 | diff +0.088 CI [+0.026,+0.169] | p=0.0195 | δ=+0.67 | SIG
  (FRAGILE: p=0.0195 is one step above the n=10 two-sided signed-rank floor of 0.00195 and would NOT
  survive multiplicity correction over the P1/P2/P3 × 3-base family — Bonferroni α≈0.0056, within-base
  α≈0.0167. Reported as a single fragile result; it does not carry J1, which fails here regardless
  because P1 (p=0.625) and P3 (p=0.275, reversed) do not separate. Ceiling-adjacent: Gemini ConvTutor
  barely leaks, so there is little room for a helpfulness gap.)
- P3 independence:  conv 0.736 vs ped 0.654 | diff +0.082 CI [-0.019,+0.190] | p=0.2754 | δ=+0.16 | n.s.
- Accuracy (secondary, descriptive): immediate 0.967/0.933 · delayed 0.900/0.867 · transfer 0.933/0.933

**J1 (joint):** NOT supported — P2 held in the predicted direction, but P1 did not separate and P3 did
not hold in the predicted PedTutor > ConvTutor direction.
**J2 (per-turn coupling, crossed replicate+problem mixed model):**
  leak→helpfulness coef +0.065 CI [-0.019,+0.148] (p=0.1293); leak→next-turn-independence coef -0.592
  CI [-0.717,-0.468] (p=9.05e-21). Does not hold because the helpfulness leg is not significant.

**Extension — pedagogy & divergence (descriptive):** pedagogy_mean conv 4.496 vs ped 4.677;
  per-turn agreement help~ped r=0.111 · help~indep r=0.111 · ped~indep r=0.191.
  (Read with the §12/§13 construct-overlap caveat: a pedagogy gap is partly by-construction.)

**Interpretation (§11 — report regardless):** matches outcome-table row "LearnLM/Gemini-like base is a low-leakage
boundary case." The Gemini base shows low ConvTutor leakage and does not separate ConvTutor/PedTutor on
leakage or independence at the marginal level; Opus-rated helpfulness favors ConvTutor, but the mixed-effects
helpfulness coupling is not significant. The robust signal that remains is that when leakage occurs, it strongly
predicts lower next-turn independence.

### 2026-06-28 — GPT preflight transport compatibility fix: OpenAI max_completion_tokens
**Context:** The first live GPT non-study preflight stopped before any leakage or outcome was recorded because
OpenAI rejected the pinned `gpt-5.5-2026-04-23` request with `Unsupported parameter: 'max_tokens' ... Use
'max_completion_tokens' instead.`
**Decision:** Add a provider/model-scoped fallback in `agents/model_client.py`: preserve the frozen `max_tokens:
1024` budget, first try the existing OpenAI-compatible request shape, and only when the provider explicitly
rejects `max_tokens` retry with the same numeric budget under `max_completion_tokens`. Remember that field for
later calls to the same provider/model. Add `tools/test_model_client.py` to simulate this 400 offline.
**Reason:** This is a transport/API compatibility fix discovered by the required pre-leakage smoke, not an
experimental tuning change. It does not change model selection, prompts, rubrics, problem set, temperatures,
turn budgets, metrics, or the held token budget.
**Validation:** `.venv/bin/python tools/test_model_client.py` 4/4; `.venv/bin/python tools/test_preflight.py`
22/22; `.venv/bin/python tools/test_run_confirmatory.py` 98/98; `git diff --check` clean before commit.
**Affects:** `agents/model_client.py`, `tools/test_model_client.py`. The GPT freeze tag must point at the
post-fix commit before any live collection is retried, so freeze provenance matches the code that actually runs.

### 2026-06-28 — Cross-model base FINDINGS: OpenAI base (gpt)
**Base:** gpt · tutor `gpt-5.5-2026-04-23` (reasoning_effort=none) · pin record:
2026-06-28 — Cross-model base PIN RECORD: OpenAI base (gpt) — IMMUTABLE
**Provenance:** freeze `crossmodel-gpt-freeze` = `644271b1e6e365a84d679a103beb08f0775e60ef` · runs
`logs/conf-gpt-s0-*` · results `results/confirmatory_gpt/` · judge `claude-opus-4-8` / live / reps=3 ·
n = 10 replicates × 3 conditions.

**ConvTutor leakage diagnostic (advisory, §12):** 15/24 = 62.5% (present — reported finding, NOT tuned).
Ref: `results/leakage_diag_gpt/leakage_diagnostic.json`

**Marginals — PedTutor vs ConvTutor, paired by replicate (Wilcoxon two-sided, Cliff's δ, 95% CI):**
- P1 leakage:       conv 0.766 vs ped 0.070 | diff(conv−ped) +0.696 CI [+0.585,+0.793] | p=0.0020 | δ=+1.00 | SIG
- P2 helpfulness:   conv 4.496 vs ped 4.872 | diff -0.376 CI [-0.613,-0.169] | p=0.0020 | δ=-0.74 | n.s. for predicted conv>ped (significant reverse)
- P3 independence:  conv 0.377 vs ped 0.734 | diff -0.358 CI [-0.493,-0.216] | p=0.0020 | δ=-0.82 | SIG
- Accuracy (secondary, descriptive): immediate 0.933/0.767 · delayed 0.967/0.733 · transfer 0.867/0.800

**J1 (joint):** NOT supported — P1 and P3 held, but P2 was significant in the opposite direction
(PedTutor > ConvTutor helpfulness).
**J2 (per-turn coupling, crossed replicate+problem mixed model):**
  leak→helpfulness coef -0.313 CI [-0.412,-0.215] (p=5.06e-10); leak→next-turn-independence coef -0.535
  CI [-0.623,-0.446] (p=2.06e-32). Does not hold because the helpfulness leg reverses.

**Extension — pedagogy & divergence (descriptive):** pedagogy_mean conv 1.710 vs ped 4.074;
  per-turn agreement help~ped r=0.388 · help~indep r=0.259 · ped~indep r=0.439.
  (Read with the §12/§13 construct-overlap caveat: a pedagogy gap is partly by-construction.)

**Interpretation (§11 — report regardless):** matches outcome-table row "policy-structure manipulation and
independence harm replicate, but helpfulness coupling reverses." The GPT base strongly separates leakage
and independence in the predicted structural direction, but Opus-rated helpfulness favors the scaffolded
PedTutor rather than the more leaky ConvTutor; therefore GPT is a partial replication, not support for the
full J1/J2 helpfulness claim.

### 2026-06-28 — Gemini pre-pin request-shape correctness fix: reasoning_effort forwarding
**Context:** `experiments/RUN.md` §A requires the cross-model smoke to confirm the serialized request payload
contains the documented `reasoning_effort` field. This matters for Gemini because §12 declares
`reasoning_effort=low` as the vendor-minimum heterogeneity exception; if the field is only written in the
config/record but not sent, the run would not match its frozen held config.
**Decision:** Forward `reasoning_effort` as a top-level OpenAI-compatible request field whenever a role spec
defines it, and record it in the logged request payload. Add an offline model-client test asserting a Gemini
tutor spec sends `reasoning_effort="low"` as a top-level field, not inside `extra_body`.
**Reason:** This is a pre-live, pre-pin transport/request-shape correctness fix. It does not change the model
selection rule, prompts, rubrics, problem set, temperatures, token budgets, metrics, or any outcome-dependent
choice.
**Validation:** `.venv/bin/python tools/test_model_client.py` 7/7; `.venv/bin/python tools/test_preflight.py`
22/22; `.venv/bin/python tools/test_run_confirmatory.py` 98/98.
**Affects:** `agents/model_client.py`, `tools/test_model_client.py`.

### 2026-06-28 — Cross-model base PIN RECORD: Gemini base (gemini) — IMMUTABLE
**Status:** IMMUTABLE. Pinned by the frozen §12 rule BEFORE this base's leakage gate and before any
live session. No reselection after any leakage/outcome (decisions-log 2026-06-27 selection rules).
**Pinned by:** the author   **Pinned at (local wall-clock):** 2026-06-28 15:27

**1. Identity**
- Vendor / base slug: gemini / gemini            (run id namespace: conf-gemini-s0-...)
- Provider / endpoint: gemini / https://generativelanguage.googleapis.com/v1beta/openai/
- Tutor key env: GEMINI_API_KEY          (judge ANTHROPIC_API_KEY, student OPENROUTER_API_KEY — unchanged)
- **Pinned model id (exact): `models/gemini-3.1-pro-preview`**
- Id form: preview   Reproducibility caveat (if preview/alias): preview, may drift; exact account-visible id recorded before any leakage/outcome.

**2. Rule application (deterministic; not a preference)**
- Rule: the vendor's CURRENT FLAGSHIP GENERAL-PURPOSE CHAT model — not a reasoning/o-series/mini/nano variant.
- Why this id satisfies it: `models/gemini-3.1-pro-preview` appears in the account-visible Gemini model
  list and is the current highest-version Gemini Pro general-purpose chat candidate. Flash/lite/image/live,
  deep-research/computer-use/robotics/tool-customized, embedding, media-generation, and Gemma variants were
  excluded by the frozen rule.
- LearnLM note (Gemini only): LearnLM functionality is integrated into Gemini 2.5+ / flagship Gemini; NO separate LearnLM variant selected.

**3. Held config (capability/config control — guard-enforced)**
- temperature 0.4, max_tokens 1024 (identical to primary; tutor_only_drift enforces).
- Reasoning: `reasoning_effort=low`  (vendor minimum — model cannot disable thinking).
- Tools / search grounding / code execution: DISABLED by omission (not sent). Documented off-fields used: none.
- Request shape: reasoning via the documented `reasoning_effort` field yes.

**4. Evidence — live model list (the rule's required record)**
- `list_models.py` run at: 2026-06-28 15:27 (local wall-clock); provider [gemini] returned 56 models.
- Pinned id present in the account-visible list: YES.
- Flagship-chat shortlist: captured at `/tmp/gemini_models.txt`. Relevant visible candidates included
  `models/gemini-3-pro-preview`, `models/gemini-3.1-pro-preview`, `models/gemini-3.1-pro-preview-customtools`,
  `models/gemini-3.5-flash`, and rolling aliases `models/gemini-pro-latest` / `models/gemini-flash-latest`;
  the exact Pro non-customtools preview `models/gemini-3.1-pro-preview` was selected by rule.

**5. Evidence — non-study preflight smoke (throwaway, NOT a study run)**
- Status: PENDING before leakage gate. The first live non-study smoke / leakage diagnostic will confirm API
  acceptance, returned model id, max_tokens behavior, reasoning_effort=low serialization, and no
  tools/grounding/code-exec. If this smoke fails, collection stops before any outcome is observed.
- Intended serialized request payload: model=`models/gemini-3.1-pro-preview`, reasoning_effort=`low`,
  max_tokens=1024, temperature=0.4; no tools/grounding/code-exec keys present.
- model_client path: `reasoning_effort` sent as documented top-level field; one-line forwarding addition needed:
  yes -> commit `1836e42`.

**6. Guards (mock dry run before live)**
- `run_confirmatory --base gemini --models configs/models.gemini.yaml --backend mock` started clean:
  tutor_only_drift PASS (only the tutor model differs), protocol_knob_drift PASS
  (domain/conditions/replicates/base-seed/turns match the registered protocol).
- Mock dry run completed 30/30 cells: 10 replicates × cold/conv/ped.

**7. Freeze**
- Cross-model extension freeze commit/tag this base is collected at: `crossmodel-freeze`.
- `configs/models.gemini.yaml` updated: REPLACE-stub -> `models/gemini-3.1-pro-preview` with
  `reasoning_effort: low` in this pin commit.

**Immutability:** recorded above. The id is frozen for this base; never reselected after any leakage
or outcome. A vendor-forced change requires a NEW dated entry (with rationale) and base recollection.

### 2026-06-29 — CROSS-MODEL FINAL SYNTHESIS: conclusion + direction (report-regardless, §11/§12)
**Context:** All three frozen tutor bases are complete — the Sonnet primary (`confirmatory-freeze`
`1a12b56`) plus the two pre-registered cross-model bases (GPT `crossmodel-gpt-freeze` `644271b1`;
Gemini `crossmodel-gemini-freeze` `68ee3fa`). Independent analyst pass synthesizing the whole result
set. Output: `results/CROSS-MODEL-SYNTHESIS.md` (sections A–E, cross-base table, per-number
citations, 8-sentence executive summary). Bases analysed separately, never pooled (§12); confirmatory
§10 tests kept distinct from descriptive §13 pedagogy/divergence; by-construction and provider
heterogeneity caveats applied throughout.

**Provenance verified (Task A).** Both cross-model freezes descend from the unchanged primary
`1a12b56` (`git merge-base --is-ancestor` true for both); GPT freeze `644271b` contains the
`max_completion_tokens` transport fix `a33211a` as an ancestor; Gemini freeze `68ee3fa` contains the
`reasoning_effort` forwarding fix `1836e42`. Both transport fixes are request-shape/transport only
(not tuning): they preserve the frozen `max_tokens:1024` budget / serialize the declared
`reasoning_effort`, and change no selection rule, prompt, rubric, problem, temperature, turn budget,
or metric. Judge held identical (Opus `claude-opus-4-8`, reps=3) on all three bases; pins are
immutable, set before each base's leakage gate, no reselection; the ConvTutor-leakage gate was
ADVISORY ("report, don't tune"). **Two archival flags (not analytic):** (1) the named per-base freeze
TAGS `crossmodel-gpt-freeze`/`crossmodel-gemini-freeze` are NOT realised as git tags in this checkout
(only the commit hashes + a generic `crossmodel-freeze`→`9bc8330` Phase-0 docs commit exist) — cut
the annotated tags so the names resolve; (2) the GPT/Gemini raw artifacts
(`results/confirmatory_{gpt,gemini}/`, `logs/conf-{gpt,gemini}-s0-*`) are gitignored and ABSENT
locally, so **every GPT/Gemini number here is taken from the dated FINDINGS entries (2026-06-28) and
was NOT independently re-derivable** — flagged in the synthesis. The Sonnet primary numbers were
re-derived from `results/confirmatory/` raw and match the committed tables (independent verification
pass below).

**Headline conclusion (honest §11 framing — nothing upgraded).**
- **The pre-registered confirmatory target J1+J2 is NOT met.** **J1 is not supported on ANY base**
  (Sonnet, GPT, Gemini). The full **J2 conjunction holds ONLY on Sonnet**; on GPT it reverses and on
  Gemini it vanishes — *with the same Opus judge held fixed.* A non-supported J1 is reported as
  non-supported; J2 is never described as generalizing.
- **Single most robust finding (replicates on all 3 bases):** the **leak→next-turn-independence** leg
  of J2 is negative and highly significant everywhere — Sonnet **−0.386** (p=5.6e-12), GPT **−0.535**
  (p=2.1e-32), Gemini **−0.592** (p=9.1e-21). Answer-leakage suppresses student independence,
  model-independently.
- **Single biggest qualification:** the **reward leg leak→helpfulness does NOT generalize** — with the
  evaluator fixed it is **+0.303** (Sonnet, p=9e-6), **−0.313** (GPT, p=5e-10), **+0.065 n.s.**
  (Gemini). So "felt-helpfulness rewards answer-giving" is one observed regime, not a law; it is a
  property of the tutor base's turn distribution, not of the evaluator.
- **Moderator = ConvTutor emergent leakage:** high on Sonnet (~52% calib / 0.43 in-run) and GPT
  (62.5% / 0.766), but only **8.3% / 0.113 on Gemini**. The low-leakage Gemini base mutes the whole
  manipulation: P1 collapses (δ+0.32, p=0.625 n.s.), P3 reverses-n.s., and its ConvTutor is *already*
  pedagogical (pedagogy 4.50 vs PedTutor 4.68 — gap nearly gone). The §12 caveat bounds this: Gemini
  is the only base forced to `reasoning_effort=low`, so family + mandatory reasoning are confounded —
  low leakage is NOT attributable to the LearnLM line alone.
- **Construction-independent divergence (Sonnet, descriptive §13):** two tutors rated ~equally helpful
  (4.70/4.80) are split perfectly on pedagogy (2.58/4.30, δ≈−1); help~ped per-turn r only 0.31.
  Felt-helpfulness is blind to a pedagogy gap the pedagogy rubric sees completely. The rubric's
  symmetry is demonstrated on Gemini (a barely-leaking ConvTutor still scores 4.50 pedagogy — credited
  for genuine scaffolding, not penalised for not withholding).

**Per-base contribution (for the write-up).** Sonnet = the clean divergence + the only base where the
full J2 mechanism holds (existence proof). GPT = a PARTIAL REPLICATION that BOUNDS the thesis — the
structural manipulation (P1 δ+1.0, P3 δ−0.82) and the independence harm replicate, but the Opus judge
significantly PREFERS the scaffolding PedTutor (P2 −0.376 δ−0.74 SIG-reversed; J2 help leg −0.313).
Gemini = a LOW-LEAKAGE BOUNDARY CASE — the already-pedagogical conversational flagship mutes the
manipulation.

**Direction forward.**
1. **Frame the paper as a dissociation, not a mechanism:** claim "conversational alignment ≠
   pedagogical alignment" as a divergence supported by (a) a robust process harm and (b) a clean
   felt-helpfulness↔pedagogy dissociation, PLUS (c) a model-CONTINGENT reward of leakage that is
   itself the cross-model finding. **Do not claim** J1/cross-model-J2 supported; **do not claim** the
   evaluator always rewards answer-giving; **do not attribute** Gemini's low leakage to LearnLM alone.
2. **Judge-validation (`metric-amendment-2026-06-19.md` §4, human annotators, IRB-gated) is now the
   HIGHEST-VALUE next step** — the entire help/pedagogy/divergence story rests on Opus, and the
   fixed-judge reversal of leak→helpfulness between Sonnet and GPT makes "is Opus a faithful proxy for
   human felt-helpfulness?" load-bearing. Prioritize over ablations.
3. **Optional ablations (#5: PedTutor node-sweep + ConvTutor prompt variants) = MODERATE value** —
   they sharpen the Sonnet mechanism story but, given J1 fails everywhere and J2 is base-specific, do
   not rescue the headline; do them after the judge-validation.
4. **Loose ends:** archive/release the GPT/Gemini raw artifacts (currently log-only) for
   reproducibility; cut the two per-base freeze tags; a condition-stratified J2 *descriptive* check
   (frozen §10 forbids it as a re-spec) to show within- vs between-condition share; confirm
   Pearson-vs-Spearman estimator parity before tabulating cross-base divergence r's.

**Verification (this pass, nothing tuned).** 3-lens adversarial workflow (numerical fidelity /
integrity / completeness, Opus, effort=high): **all three returned SHIP.** Numerical lens
independently re-derived every Sonnet figure from raw and cross-checked every GPT/Gemini figure
against the FINDINGS lines — **no numerical defects.** Integrity lens confirmed bases never pooled,
§10/§13 distinction held, J1 never called supported, J2 Sonnet-only, by-construction + §12 caveats
applied. One should-fix folded in: §E.1 now reserves "supported" for the confirmatory J1/J2 verdict
and frames the dissociation as descriptive ("consistent with / illustrates," not "supported"); P1
relabelled "separates (manipulation check)"; "headline" used for J2 only; minor sourcing notes added.
**Affects:** `results/CROSS-MODEL-SYNTHESIS.md` (new). No frozen artifact, metric, rubric, window, or
prior result changed; no base re-run, re-tuned, or re-pinned.

### 2026-06-29 — CROSS-MODEL SYNTHESIS: verification refresh (GPT/Gemini now re-derived from raw)
**Context:** A second independent analyst pass on the same date. The earlier 2026-06-29 entry recorded
that the GPT/Gemini raw artifacts were ABSENT on the producing machine, so every GPT/Gemini number in
`results/CROSS-MODEL-SYNTHESIS.md` came from the dated FINDINGS and was NOT independently re-derivable.
Those raw artifacts have since been copied into this checkout (`results/confirmatory_{gpt,gemini}/`
with `per_session.csv`/`per_turn.csv`/`metrics_summary.json`/`inference.json` + `logs/conf-{gpt,gemini}-s0-*`,
30 sessions each; still `.gitignore`d, and their `inference.json` `results_dir` still shows the runner's
`/Users/<user>/Desktop/…` path). This pass re-derives the cross-model numbers from raw and updates the
synthesis so it no longer rests on the un-re-derivable FINDINGS for the numeric claims.
**What was re-derived (all three bases, from RAW — not from the analysis JSON):**
- **P1/P2/P3 marginals** (conv/ped means, diff, Cliff's δ, Wilcoxon W+p) recomputed from
  `per_session.csv` → **match `inference.json` to the decimal.** Sole numeric difference: Gemini P1
  p=0.6230 (exact paired Wilcoxon here) vs 0.6250 reported — a tie/zero-handling artifact; W and means
  identical, both n.s.
- **J2 mixed-effects coefficients** (both legs × 3 bases) **refit from scratch** off `per_turn.csv`
  with the frozen spec (`outcome ~ leaks_i`; crossed replicate+problem variance components over a
  dummy group; ML; `analysis/inferential.py:_crossed_mixedlm`) → **reproduce every coefficient to 4
  dp with identical p-values** (Sonnet help +0.3028 / indep −0.3856; GPT help −0.3134 / indep −0.5349;
  Gemini help +0.0646 / indep −0.5924). Done with this machine's statsmodels 0.14.6 vs the runner's
  0.14.0 — a cross-version robustness check.
- **J2 descriptive splits + cell counts** (leaky/non-leaky) and **pedagogy** conv/ped per-run means
  re-derived exactly from `per_turn.csv` / `metrics_summary.json`. Turn-level leakage prevalence:
  Sonnet 66/358=18.4%, GPT 136/379=35.9%, Gemini 42/442=9.5%.
- **Sonnet matched-budget** block (ped 22.3 vs conv 13.5 visible turns +8.8; matched P1 +0.389/δ+.96/p.004,
  P2 −0.082/p.426, P3 −0.040/p.695; J2 n=256 help +0.295/p2.4e-4 indep −0.355/p7.5e-8; ped-leaky cell 6)
  verified against `matched_budget.json`.
**Provenance re-checked at git level (unchanged conclusions):** `confirmatory-freeze`=`1a12b56` is an
ancestor of both `644271b1` (GPT) and `68ee3fa` (Gemini); `644271b1` ⊇ `a33211a` (max_completion_tokens);
`68ee3fa` ⊇ `1836e42` (reasoning_effort forward); judge Opus `claude-opus-4-8` reps=3 on all three
(read from each `metrics_summary.json`); pins immutable pre-gate, no reselection; leakage gate advisory.
The named per-base tags `crossmodel-gpt-freeze`/`crossmodel-gemini-freeze` still do NOT exist as git
tags (only the commit hashes + a generic `crossmodel-freeze`→`9bc8330`). [SUPERSEDED 2026-07-03 — both
named per-base tags now exist as git tags: `crossmodel-gpt-freeze`→`644271b`,
`crossmodel-gemini-freeze`→`68ee3fa`; the generic `crossmodel-freeze` tag also exists.] Sonnet `inference.json`
analysis_commit_dirty=True (§13 tree); GPT/Gemini clean (dirty=False).
**Only figures still NOT re-derivable from local raw (flagged):** the three ConvTutor leakage-*advisory*
percentages (~52.5% / 62.5% / 8.3%) — `results/leakage_diag_{gpt,gemini}/leakage_diagnostic.json` are
absent locally; these remain FINDINGS/calibration-sourced. The confirmatory in-run leakage (P1
conv_mean 0.43/0.766/0.113) IS re-derived and gives the same ordering.
**Conclusion: unchanged from the 2026-06-29 synthesis entry, now on a firmer footing.** J1 not
supported on any base; full J2 holds ONLY on Sonnet (reverses GPT, vanishes Gemini, same fixed Opus
judge). Most robust (all 3): leak→next-independence −0.386/−0.535/−0.592 (p≪.001). Biggest
qualification: leak→helpfulness +0.303/−0.313/+0.065 n.s. — does NOT generalize. Moderator =
ConvTutor leakage. Frame as a DISSOCIATION; never call J1 supported; judge-validation > ablations.
**Affects:** `results/CROSS-MODEL-SYNTHESIS.md` (rewritten — verification refresh; all GPT/Gemini
numbers re-derived from raw; provenance §A, per-base headers, §D/§E loose ends updated accordingly).
No frozen artifact, metric, rubric, window, or prior result changed; no base re-run, re-tuned, or
re-pinned. Raw artifacts read-only.

### 2026-06-30 — #5 Ablations: PRE-REGISTERED + additive infra (DESCRIPTIVE; spec frozen before any live run)
**Context:** the primary confirmatory result (Sonnet, freeze `1a12b56`) and the 2026-06-29 cross-model
synthesis establish the headline as a DISSOCIATION — J1 never supported; full J2 only on Sonnet; the robust,
all-base finding is leak→next-independence (−0.39/−0.54/−0.59). The synthesis ranked judge-validation ABOVE
ablations and called ablations moderate-value that do NOT rescue the headline. This entry pre-registers #5
as an OPTIONAL, ADDITIVE, **DESCRIPTIVE** extension that CHARACTERIZES whether PedTutor's leakage/independence
separation depends on its structure (each node) and whether a prompt-only ConvTutor change reproduces it —
frozen BEFORE any ablation datum. It changes NO frozen artifact: the minimal ConvTutor, the frozen PedTutor
(prompts + graph), `configs/ped_full.yaml`, `configs/conv_tutor.yaml`, `supplement/prompts.md`, §4/§9/§10,
the problem set, the answer-phase window, the metrics, and the frozen `analysis/run_inference.py` J1/J2 path
stay BYTE-STABLE. Every variant is a NEW config/condition. **Framing is neutral, no presumed result:** a single
node carrying the separation, the separation distributed, NO node-drop changing it, or a prompt-only ConvTutor
matching PedTutor are ALL valid, fully-reportable outcomes (§11). Nothing is tuned toward any of them.

**Decision — the COMPLETE spec, FROZEN before any live ablation run:**

1. *Two additive condition families (5 conditions).* Condition → (agent, config, graph change). Every table
   slot is resolved to a concrete value; no angle-bracket placeholder survives in the pre-registration, code,
   or configs.

   | condition            | agent            | config                            | graph change                                                       |
   |----------------------|------------------|-----------------------------------|--------------------------------------------------------------------|
   | conv (primary)       | ConvTutor        | configs/conv_tutor.yaml           | unchanged (FROZEN baseline; reused, not re-run)                    |
   | ped  (primary)       | PedTutor         | configs/ped_full.yaml             | unchanged (FROZEN baseline; reused, not re-run)                    |
   | conv_socratic        | ConvTutor        | configs/conv_socratic.yaml        | new prompt only, single call                                       |
   | conv_no_final_answer | ConvTutor        | configs/conv_no_final_answer.yaml | new prompt only, single call                                       |
   | ped_no_gate          | PedTutorVariant  | configs/ped_no_gate.yaml          | drop deferral_gate; route `defer` → decomposer                     |
   | ped_no_cascade       | PedTutorVariant  | configs/ped_no_cascade.yaml       | drop hint_cascade; route `hint` → decomposer                       |
   | ped_no_tracker       | PedTutorVariant  | configs/ped_no_tracker.yaml       | drop state_tracker (entry); START routes directly to the responder; responders get the empty assessment fallback "(planner produced no structured estimate)", progressed=false |

2. *PedTutor node-sweep — faithful drops, uniform remap.* `agents/ped_ablations.py:PedTutorVariant` SUBCLASSES
   the frozen PedTutor and overrides ONLY graph construction; `agents/ped_tutor.py` is byte-identical. The thin
   `configs/ped_{variant}.yaml` sources all prompts/routing UNCHANGED from `base_config: configs/ped_full.yaml`
   and declares only the manipulation. For each variant: the dropped node is GENUINELY removed — no model call
   carrying its tag, and the compiled graph never contains it (not stubbed, not re-implemented elsewhere).
   **Uniform orphan-route remap rule (pre-committed, single target):** a dropped responder's orphaned route
   lands on the retained `decomposer` — the neutral single-step scaffold that (like every PedTutor responder)
   never states the answer. ONE uniform target removes researcher discretion; because all PedTutor responder
   prompts withhold the final number, the target choice cannot manufacture or destroy the leakage separation
   (so the remap is not an outcome lever). `ped_no_tracker` drops the ENTRY/planner: the deterministic signals
   (asked/attempts/hint_level/reveal_allowed) are precomputed in `respond()` and do not need the tracker, so
   routing is unchanged and the new graph entry is a conditional route from START directly to the routed
   responder (all three responders retained); the assessment fallback is the EMPTY assessment, rendered by the
   frozen `format_assessment()` as "(planner produced no structured estimate)" with progressed=false — the SAME
   graceful-degradation path the frozen code already takes (e.g. the offline mock), faithful not stubbed.
   The realized responder always carries a tag `analysis/metrics.py` recognizes (deferral_gate / decomposer /
   hint_cascade = `RESPONDER_NODES`); NO new visible-responder tag is introduced.

3. *Call-count, stated correctly (NOT a blanket "one fewer node").* The full PedTutor graph runs
   `state_tracker + one responder` per visible turn (`metrics.n_model_calls == 2`). Dropping a RESPONDER and
   rerouting its orphaned route to a retained responder keeps the per-turn count UNCHANGED (still 2): `ped_no_gate`
   and `ped_no_cascade` are clean structure manipulations. ONLY `ped_no_tracker` (dropping the entry node) reduces
   the per-turn count to 1, confounding structure with call count — **disclosed for `ped_no_tracker` specifically**.
   The token/visible-turn side of compute fairness is already addressed by the per-1k-tutor-token sensitivity
   (`analysis/inferential.cost_normalized`) and the matched visible-turn-budget pass (`analysis/matched_budget.py`,
   decisions-log 2026-06-26); the internal call-count drop is disclosed, not re-controlled, and not duplicated here.

4. *`branch` semantics for rerouted turns — KEEP the original route value.* `agents/ped_tutor.py` stamps each
   visible turn's `branch` from the ORIGINAL deterministic route value (defer/decompose/hint), and `metrics.py`
   reads that column. Under a node-drop with rerouting, the decision is to KEEP the original route value (the
   stamping is inherited UNCHANGED — no edit). So an answer-demand turn under `ped_no_gate` is handled by
   `node=decomposer` but still carries `branch=defer`. Justification: (i) it keeps `branch` ONE consistent meaning
   everywhere — the student-behaviour routing reason — introducing no new branch semantics (the most freeze-
   respecting choice); (ii) it PRESERVES the scientifically interesting signal — "on turns where the student
   demanded the answer, does leakage rise when the gate is removed?" — which overwriting `branch` to the realized
   responder would hide; (iii) the realized responder is recoverable from the call's `node` tag, so no information
   is lost. Enforced by `tools/test_ped_ablations.py` assertion (v).

5. *ConvTutor prompt variants — exact, pinned text.* Same single-call ConvTutor path; new prompt configs only;
   the minimal ConvTutor + its prompt are NOT edited. Verbatim text (also in `supplement/ablation_prompts.md`):
   - `conv_socratic`: "You are a math tutor helping a student. Teach using the Socratic method: rather than
     telling the student what to do, ask guiding questions that lead them to work out each step on their own.
     Respond to what the student has actually said, build on their reasoning, and keep the student doing the
     thinking."
   - `conv_no_final_answer`: "You are a math tutor helping a student. Be helpful and clear, but do not give away
     the final answer — guide the student to reach it themselves. Explain the ideas and the next step to try, and
     let the student carry out the final reasoning and the arithmetic on their own."
   Both are realistic alternate teaching-style prompts, NOT engineered against the leakage/independence metrics;
   neither contains `canonical_answer`, the leakage strings, or any node name. No answer leakage.

6. *Runner (additive; primary path byte-stable).* `experiments/run_confirmatory.py` gains the 5 ablation labels
   (`ABLATION_SPECS`/`build_tutor`), threading each per-condition config into the agent. Ablation run ids are
   namespaced `abl-s{seed}-{cond}-r{r}` (disjoint from the primary `conf-...`, so a primary glob never picks up an
   ablation cell), with the SAME base-seed/replicate schedule (seed = base_seed + r, replicate_id = r) so each
   ablation replicate r PAIRS with the existing primary conv/ped/cold replicate r. Ablations run on the PRIMARY
   Sonnet config (NOT `--base`; the two are mutually exclusive) and have their OWN freeze: the tag-fallback is
   `ablation-freeze` (never `confirmatory-freeze`); a live ablation run must use only the pre-registered ablation
   conditions on `configs/models.yaml` with the registered domain/replicates(10)/base-seed(0)/turn-budget(4)
   (`ablation_protocol_drift`); mixing primary+ablation conditions in one run is refused. The API-key preflight
   requires the tutor key for ANY non-cold condition (so the ablations cannot escape it). The completion "Next"
   message points at `results/ablation` + `analysis/ablation_analysis.py`, explicitly NOT `run_inference`.

7. *Analysis — SEPARATE + DESCRIPTIVE; the frozen §10 J1/J2 is never touched.* The frozen `run_inference.py` is
   variant-UNSAFE (J1 pairs only conv-vs-ped, accuracy loops cold/conv/ped, J2 POOLS every per-turn row with no
   condition covariate). Therefore NO ablation row and NO ablation output dir is EVER fed to `run_inference`/J2;
   the conv/ped J1/J2 result stays byte-stable, run on the primary as before. `analysis/compute_metrics.py`
   (UNCHANGED; preserves arbitrary condition tags) metricizes the ablation cells together with the REUSED primary
   conv/ped/cold baselines into a SEPARATE `results/ablation/`. `analysis/ablation_analysis.py` (NEW, clearly
   labeled DESCRIPTIVE) compares each variant to the minimal-ConvTutor / frozen-PedTutor baselines on
   leakage_rate / independence_ratio / helpfulness / pedagogy (paired diffs, Cliff's δ, bootstrap CIs), and fits
   the per-turn leak→next-independence coupling SEPARATELY per condition (never pooled across conditions, never the
   frozen J2). It imports ONLY the two pure stats primitives (`bootstrap_ci`, `cliffs_delta`), never `j1`/`j2`/
   `verdict`/`accuracy`, and REFUSES a dir with no ablation conditions (so it can never stand in for the frozen
   inference). Ablations are stated as DESCRIPTIVE extensions, never the primary, never part of the J1/J2 verdict.

8. *Reporting.* Whatever each variant shows is reported (§11, no file-drawer) — including "no node-drop changes
   the separation" and "a prompt-only ConvTutor variant matches/does not match PedTutor". Nothing tuned.

**Tests (offline, green BEFORE the independent-review gate):** `tools/test_ped_ablations.py` (75) — per node-drop variant
asserts (i) the dropped node's call never happens + the compiled graph never contains it; (ii) each orphaned route
lands on the pre-registered retained responder (decomposer); (iii) the visible responder tag ∈ metrics.RESPONDER_NODES
(no new tag); (iv) per-variant call count (`ped_no_gate`/`ped_no_cascade` == 2 UNCHANGED, `ped_no_tracker` == 1);
(v) `branch` keeps the original route value on rerouted turns; plus config-consistency + malformed-config refusal.
`tools/test_run_confirmatory.py` (+66, now 164) — ablation run-id namespacing/pairing, `build_tutor` mapping,
end-to-end mock tags + per-variant n_model_calls recognized by metrics + dropped node never logged, and the
invocation guards (mixing/`--base`/off-protocol/freeze-tag fallback). `tools/test_ablation_analysis.py` (19) —
paired diffs, per-condition coupling NOT pooled, and the non-ablation-dir refusal. The frozen primary cold/conv/ped
recompute BYTE-IDENTICAL and the frozen `run_inference` J1/J2 is unaffected; ALL existing suites stay green (650
total across 11 suites).

**Freeze/review/run ordering (integrity ENFORCED before the first live run, not merely documented):**
(1) implement + pin prompts/configs + this complete pre-registration + mock-validate + ALL offline suites green;
(2) independent adversarial-review gate → resolve every MUST-FIX → re-review until SHIP;
(3) ONLY THEN the maintainer lands the ablation freeze commit/tag (`ablation-freeze`); (4) ONLY THEN the maintainer runs the
live ablation conditions at that freeze. Steps 3–4 are the maintainer's; this changeset is steps 1–2.

**Reason:** a structural agent's effect should be attributable to its structure. #5 characterizes which node(s),
if any, the leakage/independence separation depends on, and whether a prompt-only ConvTutor reproduces it —
descriptively, with no degree of freedom to chase a result (uniform remap, original-route branch, separate
descriptive analysis, report-all-outcomes). It is explicitly secondary to judge-validation and does not rescue
the headline.

**Alternatives considered:** (a) Editing `agents/ped_tutor.py` to add a `variant` flag — rejected in favor of a
subclass so the frozen agent stays byte-identical. (b) Per-node ad-hoc remap targets (defer→hint_cascade,
hint→decomposer) — rejected for the single uniform `→decomposer` rule, which minimizes researcher discretion;
since all ped responders withhold, the target is not an outcome lever either way. (c) Overwriting `branch` with
the realized responder — rejected: it would hide the student-behaviour signal (the answer-demand) that is exactly
what the rerouted-turn analysis wants; the realized responder is recoverable from the `node` tag. (d) Stubbing a
dropped node to mimic the full agent — rejected: the drop must be genuine. (e) Adding a guard inside the frozen
`run_inference` to refuse ablation rows — rejected: `run_inference` is byte-stable; contamination is prevented by
the separate out dir + the runner Next message + the descriptive script's own non-ablation-dir refusal + review
gate, not by editing frozen code. (f) Running `ped_no_tracker` without disclosing the call-count confound —
rejected: the confound is disclosed for that variant specifically.

**HOLD (workflow):** uncommitted. Independent adversarial-review gate (step 2) COMPLETE → **SHIP**
(2026-06-30, independent review, 3 rounds; no literal angle-bracket tokens are written in THIS record, to keep
the no-placeholder rule above satisfiable by a plain grep). Round 1: NO-SHIP, 2 MUST-FIX — (a) surviving
angle-bracket placeholders (a literal-ellipsis placeholder in the pre-registration prose, and an
angle-bracket freeze-hash placeholder in the runner usage docstring); (b) a pre-existing untracked
working file that would dirty a live freeze tree. Round 2: NO-SHIP,
1 MUST-FIX — two further angle-bracket placeholders in test-file comments (`tools/test_ped_ablations.py`,
`tools/test_run_confirmatory.py`). Round 3: **SHIP, no MUST-FIX** — exhaustive scan confirms ZERO angle-bracket
placeholder in any new ablation file or any diff-added line; checks 1–7 all PASS. Fixes applied: reworded every
placeholder to a concrete / curly-brace form (the pre-existing freeze-hash example placeholders in the runner
docstring at HEAD are out of scope, unchanged, not in the diff); kept the stray working file out of the tree via a local `.gitignore` rule (ignored, not deleted); and
(NICE-TO-HAVE) the `--freeze-commit` help now names the `ablation-freeze` fallback. One non-blocking
NICE-TO-HAVE carried (declined as out of scope): making temp/log roots configurable for offline test environments —
an environment constraint, not a code defect. ALL 11 offline suites green (650 passed, 0 failed), incl.
the new `test_ped_ablations` (75) and `test_ablation_analysis` (19) and the extended `test_run_confirmatory`
(164); the frozen primary cold/conv/ped recompute byte-identical (frozen source zero-diff vs HEAD;
`confirmatory-log-manifest.sha256` verifies all 90 primary log files) and the frozen `run_inference` J1/J2 is
unaffected. No live ablation datum exists [SUPERSEDED 2026-07-03 — the live ablation ran at `ablation-freeze` (f06063a); see the FINDINGS entry at the end of this log]; the maintainer lands the `ablation-freeze` commit/tag and runs the live
conditions only after this SHIP. The primary freeze `1a12b56` is untouched and the primary is not re-run.

**Affects:** NEW — `agents/ped_ablations.py` (PedTutorVariant subclass), `configs/conv_socratic.yaml`,
`configs/conv_no_final_answer.yaml`, `configs/ped_no_gate.yaml`, `configs/ped_no_cascade.yaml`,
`configs/ped_no_tracker.yaml`, `analysis/ablation_analysis.py`, `supplement/ablation_prompts.md`,
`tools/test_ped_ablations.py`, `tools/test_ablation_analysis.py`. MODIFIED (additive only) —
`experiments/run_confirmatory.py` (ablation conditions + `abl-` namespace + ablation-freeze fallback + tutor-key
preflight for non-cold + ablation protocol guard + ablation Next message; primary cold/conv/ped path byte-stable),
`tools/test_run_confirmatory.py` (ablation tests), `decisions-log.md`. **NOT touched:** any frozen measurement
artifact (`agents/ped_tutor.py`, `agents/conv_tutor.py`, `configs/ped_full.yaml`, `configs/conv_tutor.yaml`,
`configs/models.yaml`, the problem set, rubrics, `supplement/prompts.md`, paper-plan §4/§9/§10), the metrics
(`analysis/metrics.py`), the frozen `analysis/run_inference.py` J1/J2 path, `analysis/inferential.py`,
`analysis/compute_metrics.py`, or any primary/cross-model log/result.

### 2026-07-03 — #5 Ablations: LIVE run FINDINGS (descriptive; supersedes the "no live ablation datum" note above)

**Run.** The 5 pre-registered ablation conditions were collected LIVE at `ablation-freeze` (f06063a,
2026-07-01) on 2026-07-02: 10 replicates each of conv_socratic, conv_no_final_answer, ped_no_gate,
ped_no_cascade, ped_no_tracker on the PRIMARY Sonnet config, paired against the reused primary
cold/conv/ped baselines. Logs `logs/abl-s0-*` (pinned in `ablation-log-manifest.sha256`); tables
`results/ablation/`; analysis `analysis/ablation_analysis.py` (DESCRIPTIVE — Cliff's δ + bootstrap CIs,
no NHST verdict; NEVER fed to `run_inference`). Nothing tuned; reported regardless of outcome (§11).

**Per-condition leakage / next-turn independence (training answer-phase window):**
- conv (baseline)       leak 0.430 · indep 0.580
- conv_no_final_answer  leak 0.146 · indep 0.725   (prompt-only)
- conv_socratic         leak 0.017 · indep 0.657   (prompt-only)
- ped (full)            leak 0.064 · indep 0.656
- ped_no_gate           leak 0.075 · indep 0.755
- ped_no_cascade        leak 0.034 · indep 0.596
- ped_no_tracker        leak 0.026 · indep 0.774

**Findings (reported regardless — §11).**
1. A prompt-only ConvTutor (`conv_socratic`: one Socratic system-prompt change, single node, NO graph
   structure) reaches leakage at or below the full PedTutor (0.017 vs 0.064; diff −0.047, δ −0.34, CI
   [−0.108, +0.006] straddles 0) and ties it on independence (0.657 vs 0.656). PedTutor's structure is
   therefore neither necessary nor sufficient for the low-leak / high-independence profile.
2. No single PedTutor node-drop collapses the leakage/independence separation from ConvTutor:
   ped_no_gate / ped_no_cascade / ped_no_tracker all stay low-leak vs conv (δ −0.96 / −1.0 / −1.0). The
   withholding is carried by the responder PROMPTS (all withhold the final number), not the graph topology.
3. Both outcomes were pre-registered as valid, reportable results (decisions-log 2026-06-30: "a
   prompt-only ConvTutor variant matches PedTutor" and "no node-drop changes it").

**What it does NOT change / does NOT show.**
- The thesis is the evaluator↔process COUPLING / divergence (J2 + helpfulness↔pedagogy), NOT "structure
  beats prompting." conv_socratic parity is CONSISTENT with the coupling reading (a leakage-suppressing
  prompt reproduces the low-leak / high-independence profile); it does not undercut it. No committed
  narrative attributes the separation to PedTutor's graph, and none should.
- SCOPE LIMIT [SUPERSEDED 2026-07-04 — the helpfulness/pedagogy judge pass has since been run
  (instrument-anchor `8e2a33f`, results commit `326a01b`); `helpfulness_mean`/`pedagogy_mean` are now
  filled and the evaluator-reward leg + the helpfulness↔pedagogy divergence ARE addressed — see the
  2026-07-04 JUDGE-PASS FINDINGS entry below]: this run carries NO helpfulness/pedagogy judge scores (helpfulness_mean / pedagogy_mean
  empty for all conditions), so it speaks ONLY to leakage/independence — it cannot yet address the
  evaluator-reward leg or the helpfulness↔pedagogy divergence for these variants. The conv_socratic
  per-condition coupling is underpowered (3 replicates usable, W=1, p=0.5) and is not over-interpreted.

**Integrity.** Additive extension: `agents/ped_ablations.py` (PedTutorVariant subclass) leaves
`agents/ped_tutor.py` byte-identical to the freeze; `analysis/ablation_analysis.py` imports only
bootstrap_ci / cliffs_delta and never the frozen §10 J1/J2 path; `abl-` run ids + `results/ablation`
kept disjoint from the primary/cross-model namespaces. The primary freeze `1a12b56` is untouched and the
primary is not re-run.

### 2026-07-04 — #5 Ablations: JUDGE-PASS FINDINGS (helpfulness + pedagogy; descriptive; supersedes the 2026-07-03 "no judge scores" scope limit)

**Run.** The helpfulness and pedagogy judges were applied post-hoc to the 5 pre-registered ablation
conditions plus the reused primary cold/conv/ped baselines, filling the `helpfulness_mean` and
`pedagogy_mean` columns the 2026-07-03 FINDINGS entry left empty. Judge = the primary Opus
`claude-opus-4-8`, 3 reps, default sampling, student-visible dialogue + frozen rubric only (never the
canonical answer or the condition; `configs/models.yaml` `roles.judge`). Judge instruments
(`analysis/judge.py`, `analysis/judge_pedagogy.py`, `analysis/inferential.py`, and the in-code rubric
constants mirrored in `supplement/judge_rubric.md` / `supplement/judge_pedagogy_rubric.md`) are
BYTE-IDENTICAL from `8e2a33f` (2026-06-27) through HEAD — verified by an empty
`git diff 8e2a33f HEAD -- <those files>`; `8e2a33f` is an ancestor of both the run and results commits.
Metrics run commit `d281b6b` (2026-07-04 20:28; the atomic per-session judge-cache flush —
persistence-timing only, instruments untouched); results commit `326a01b` (2026-07-05 02:02, "Ablation
judge pass"). Baseline conv/ped judge means are byte-identical to the frozen confirmatory (exact cache
reuse; zero baseline re-pay). Tables in `results/ablation/` (`ablation_analysis.json`,
`helpfulness_detail.json`, `pedagogy_detail.json`, `divergence_detail.json`); per-rep scores cached in
the gitignored `helpfulness_cache.json` / `pedagogy_cache.json`; wire logs in the gitignored
`logs/helpfuljudge-20260704-194830-202/` and `logs/pedjudge-20260704-210950-761/` (pinned by
`ablation-judge-log-manifest.sha256`). Nothing tuned; reported regardless of outcome (§11). DESCRIPTIVE
only — the judge outputs feed `analysis/ablation_analysis.py`; the frozen §10 `run_inference` J1/J2 path
is never touched.

**Per-session judge means (helpfulness / pedagogy), per condition:**
- conv (baseline)       help 4.703 · ped 2.578
- conv_no_final_answer  help 4.811 · ped 4.141
- conv_socratic         help 4.804 · ped 4.863
- ped (full)            help 4.797 · ped 4.299
- ped_no_gate           help 4.750 · ped 4.257
- ped_no_cascade        help 4.948 · ped 4.834
- ped_no_tracker        help 4.719 · ped 4.308

**Findings (reported regardless — §11).**
1. **A prompt-only ConvTutor matches — slightly exceeds — full PedTutor on judged pedagogy.**
   conv_socratic pedagogy 4.863 vs ped 4.299: paired mean diff **+0.565** (median +0.521, 95% CI
   [+0.348, +0.817]), Cliff's **δ +0.96**, 10/10 pairs variant > baseline. Against the conv baseline it
   is +2.285 (δ 1.0). PedTutor's graph structure is therefore NOT required to earn the pedagogy signal —
   a single Socratic system prompt does.
2. **Helpfulness is near-flat across all seven conditions** (range 4.70–4.95). conv_socratic help 4.804
   vs ped 4.797 (diff +0.007, δ −0.03 — a near-exact tie, NOT identical) and vs conv 4.703 (+0.101, CI
   [−0.093, +0.327] straddles 0). The one helpfulness gain whose CI clears 0 is **ped_no_cascade**,
   +0.151 vs ped (CI [+0.058, +0.246], δ 0.74) — see finding 4.
3. **The helpfulness↔pedagogy DIVERGENCE — the construction-INDEPENDENT signal (§13) — is now
   measurable for the variants and is present.** conv_socratic lifts pedagogy +2.285 over conv while
   moving strategy-blind helpfulness only +0.101. This is exactly the leg the 2026-07-03 SCOPE LIMIT
   said the leakage-only pass could not yet address.
4. **ped_no_cascade is a trade-off.** Dropping the hint_cascade RAISES judged pedagogy
   (+0.535 vs ped, CI [+0.301, +0.817], δ 0.96) and helpfulness (+0.151, CI-excludes-0) but LOWERS
   next-turn independence to **0.596 — the lowest of any PedTutor variant** (ped 0.656, ped_no_gate
   0.755, ped_no_tracker 0.774; mean diff −0.061 vs ped, CI [−0.127, +0.001]). The engaged-student
   responder buys independence at some cost to judged helpfulness/pedagogy.
5. **Leak→next-turn-independence coupling is negative in every condition, with the expected power floor.**
   All **7/7** per-condition mean within-replicate effects are negative (−0.18 conv … −0.83
   ped_no_tracker). The percentile-bootstrap effect CI excludes 0 in **5/7** (conv_no_final_answer, ped,
   ped_no_cascade, ped_no_gate, ped_no_tracker — all but conv and conv_socratic); the per-condition
   Wilcoxon signed-rank reaches two-sided p<.05 in **3/7** (conv_no_final_answer p=.031, ped p=.031,
   ped_no_gate p=.016). The two CI-excludes-0 conditions that miss p<.05 (ped_no_cascade, ped_no_tracker)
   have only n=5 usable replicates, where the signed-rank two-sided floor is p=.0625 — a power floor, not
   an absent effect. (The 5 and the 3 are different counts.)

**Caveats.**
- **By-construction / manipulation-check (§13).** The pedagogy rubric scores the very principles a
  Socratic prompt and PedTutor's responder nodes are built to realize, so a raw pedagogy gap is *partly
  true by construction* and is reported as a **manipulation check**, not corroboration. conv_socratic
  MITIGATES the narrower "PedTutor's graph earns the pedagogy" reading (a prompt-only ConvTutor matches
  it) but does NOT dissolve the by-construction caveat — its prompt was itself written to be Socratic.
  The construction-independent evidence is the **helpfulness↔pedagogy divergence** (finding 3), which
  neither tutor optimizes.
- **conv_no_final_answer window-scoping.** Its per-turn helpfulness/pedagogy average over post-solution
  wrap-up turns, and its leakage/independence are measured on the frozen **training answer-phase
  window** — a variant that defers the final number to an end-of-session wrap-up outside that window
  reads artificially low in-window. Read conv_no_final_answer's leakage suppression as window-scoped.
- **conv_socratic per-condition coupling is underpowered.** Only n=4 leaky turns across 3 usable
  replicates (W=1, p=0.5) — its OWN leak→independence coupling is not over-interpreted; the
  cross-condition pattern (finding 5) carries the coupling story.

**Integrity.** Judge-only post-hoc pass over already-collected `logs/abl-s0-*`; no ablation re-run, no
prompt / config / rubric / window change, no primary or cross-model artifact touched. The primary freeze
`1a12b56` is untouched and the primary is not re-run. This entry supersedes the 2026-07-03 "NO
helpfulness/pedagogy judge scores" SCOPE LIMIT.

### 2026-07-05 — Post-audit documentation fixes (docs-only; no measurement artifact re-run)

A 2026-07-05 independent pre-writing audit (verdict PROCEED-WITH-FIXES; no fatal validity flaw, no
headline-number mismatch, every reported statistic offline-rederivable from tracked artifacts) surfaced
stale documentation and three false "student = Haiku" strings. This entry records the docs-only
corrections applied to the working tree (for the lead to review and commit; no analysis re-run, no frozen
measurement artifact changed):

- **Judge-pass record.** Wrote the owed 2026-07-04 JUDGE-PASS FINDINGS entry above and marked the
  2026-07-03 SCOPE LIMIT `[SUPERSEDED]`.
- **Student-model strings corrected (false "Haiku").** The final/confirmatory student is the weak
  Llama-3.1-8B (served via Groq / OpenRouter→Groq), never Anthropic Haiku — Haiku was rejected in
  calibration as too capable (`configs/models.yaml:9`, `experiments/CALIBRATION.md`). Fixed the three
  residual false strings: `configs/models.free.yaml` (student comment), `experiments/calibrate.py`
  (`--cold-only` help), and `student/simulator.py` (module docstring). **`student/simulator.py` is in the
  confirmatory-freeze lineage; this is a deliberate POST-STUDY docs-only comment change — no code path, no
  data, and no result is affected.**
- **Reproduction commands.** `README.md` step 4 and `experiments/RUN.md` §4 now include
  `--judge-pedagogy` (the shipped `results/confirmatory` tables carry the §13 pedagogy columns, so
  byte-reproduction requires both judges).
- **Result-inventory & provenance docs.** `results/README.md` file inventory corrected (the ablation
  ships `ablation_analysis.json`, not `inference.json`; the confirmatory bases add `matched_budget.json`
  / `divergence_detail.json` / `pedagogy_detail.json`) and given the four `shasum -a 256 -c` manifest
  commands plus a pinned-vs-scratch log-families note; `experiments/CROSSMODEL-HANDOFF.md` updated (the
  per-base `results/confirmatory_<slug>` outputs ARE now tracked, committed since `19d0c37`); the
  2026-06-29 note above marked `[SUPERSEDED]` where it said the per-base freeze tags did not exist (they
  now do: `crossmodel-gpt-freeze`→`644271b`, `crossmodel-gemini-freeze`→`68ee3fa`).
- **Paper-plan.** Added §14 recording the #5 ablation extension (pre-registration + judge-pass findings
  pointers) so the ablation is not decisions-log-only.
- **Untracked synthesis.** `results/CROSS-MODEL-SYNTHESIS.md` (still local-only): removed the
  leaked runner home-directory path (`/Users/<name>/Desktop/…`), corrected the now-stale "gitignored / results_dir points at the
  runner's path" claim (the per-base outputs are tracked; tracked `results_dir` values are the generic
  `results/confirmatory_<slug>`), and added the **symmetric robustness disclosure** for leak→helpfulness —
  reported on all three bases from the tracked `inference.json` `cluster_summary`: Sonnet mixed +0.303
  (p≈9e-6) / clustered signed-rank +0.279 (p=.002), both SIG-positive; GPT mixed −0.313 (p≈5e-10,
  reversed) / clustered −0.267 (p=.105, n.s.); Gemini mixed +0.065 (p=.129, n.s.) / clustered +0.066
  (p=.002, SIG-positive). The "reverses on GPT / vanishes on Gemini" shorthand is thus
  operative-mixed-model language only: on Gemini the pre-registered clustered check is SIG-positive, and
  on GPT the reversal is mixed-model-only — disclose both checks symmetrically in the paper.
- **Housekeeping.** Removed two stray 0-byte `results/ablation/tmp.lock.*_cache.json` flock leftovers;
  added `ablation-judge-log-manifest.sha256` pinning the two 2026-07-04 judge-log dirs.

**Still owed (not done here):** the clean-history export and the export-time repository housekeeping
— both are release-packaging steps, deliberately left for the lead. The three ConvTutor
leakage-advisory moderator percentages (~52.5% / 62.5% / 8.3%) and the isolated-cold ~11% remain
calibration/FINDINGS-sourced (not re-derivable from tracked artifacts); cite them as advisory. Committed
tables were generated under Python ≤3.11; the current `.venv` (3.12) reproduces them to ≤1 ULP, with three
Gemini per-session Spearman values shifting at 2 dp and Gemini P1 p 0.625→0.623 (scipy tie handling) —
verdicts invariant.

### 2026-07-20 — Second judge moved to OpenRouter; audit run and complete
**Context:** The frozen OpenAI-direct route could not carry the batch. Byte-identical scoring
requests failed intermittently with a provider-side auth error — the `sonnet` ledger records 3
failures in 6 attempts on real ~925-token rubric prompts (the ledger records attempts, the
archived wire log records the 3 successes; no status code is recorded anywhere, so the "401"
attribution is operator-reported) — and the runner classifies 401 as FATAL with no retry, so
each occurrence killed the batch. The account's daily token allowance
was also below the requirement of any single base. Both faults are transport-side; nothing about
the rubrics, prompts, parser, units, or the frozen Opus judge was in question.
**Decision:** Amend the transport only, under a new freeze
(`cross-judge-amendment-openrouter-2026-07-20.md`, tag `judge-robustness-openrouter-freeze`
→ `8e85836`). Route through OpenRouter pinned to the `openai` upstream with
`allow_fallbacks: false`, sent as `extra_body` on every request including retries and the
preflight. Provider identity is now DERIVED from the configuration everywhere it is recorded —
never the literal it used to be.
**Reason:** The cheap version of this change (keep the provider key named `openai`, swap only
`base_url`) would have stamped and hashed every rating as OpenAI-direct while calling
openrouter.ai. That is false provenance in a research artifact and was rejected outright. Making
identity derived also repaired two controls that were inert rather than merely imprecise:
`"provider"` is in `_STAMP_CONTENT_FIELDS`, so while both sides were the same literal the
reconstruction check compared literal to literal and could never fail; and the request-contract
hash could not move when the provider did, so a preflight resolved against one provider would
have authorized a paid batch against another under an identical sha.
**Alternatives considered:** (a) staying on OpenAI direct — arithmetically impossible, the
observed failure rate needs roughly twice the authorized ceiling; (b) archiving
`sonnet/spend_ledger.json` and starting clean — rejected, a deleted ledger beside paid spend is
exactly what `_live_spend_evidence` exists to catch, so the ledger was kept and the 3 unlabeled
OpenAI-era rows (6 HTTP attempts) deliberately still count against the new allowance (over-stating prior spend is
the safe direction, and nobody has to hand-edit a record of real paid spend); (c) sending
`require_parameters` with the pin — it filters on normalized parameter names that exclude
`max_completion_tokens` and 404s the whole route.
**Affects:** `analysis/run_cross_judge_audit.py`, `configs/models.judge-gpt56.yaml`,
`tools/test_cross_judge_audit.py`, `tools/verify_openrouter_routing.py` (new),
`cross-judge-amendment-2026-07-19.md` (lines 74 and 89 marked `[SUPERSEDED 2026-07-20]`),
`supplement/second-judge-transport-disclosure.md` (new),
`results/judge_robustness/gpt-5.6-sol/**`.

**Run outcome.** All three bases scored and promoted: 7,074 of 7,074 ratings valid, 0 transport
retries, 0 parse retries, 0 degraded responses, every rating attested to `OpenAI` with none
unattested, mixed, or divergent. 7,590,023 prompt + 445,536 completion tokens; $51.32 at
$5/$30 (the three bases' wire logs; preflight on both routes excluded). One HTTP attempt per rating on `gpt` and `gemini` exactly. The 3 OpenAI-direct ratings
were discarded by the stamp change as expected and re-paid.

**Routing evidence is captured, unlike the first attempt.** `tools/verify_openrouter_routing.py`
writes its own transcript (`preflight/routing_verification.json`). The load-bearing result is
`order_selects_provider`: `order:["azure"]` is served by Azure while `order:["openai"]` is served
by OpenAI, so routing follows `order` — a refused bogus tag alone cannot distinguish an enforced
pin from one accepted and ignored while OpenAI happens to be the default. `allow_fallbacks` is
separately shown load-bearing (the same bogus tag succeeds once fallbacks are re-enabled).
**A caveat recorded earlier was wrong and is withdrawn:** a valid-but-miscased `order:["OpenAI"]`
is served normally, not 404'd, so the earlier "404 proves only tag-unrecognized" reasoning does
not apply.

**Still owed.** `reasoning_effort` through the route is UNVERIFIED: the captured probe returned
minimal→166 and high→126 reasoning tokens, which is n=1 per level on a stochastic quantity and
so inconclusive rather than negative. Reasoning is definitely occurring (mean 33.8 over 7,074
calls); what is unproven is that the level is modulated. All ratings ran under identical
settings, so the comparison is internally consistent — this is a spec-compliance disclosure, and
the paper must say the setting was requested, not confirmed, unless a multi-sample re-probe
closes it. The dated snapshot `openai/gpt-5.6-sol-20260709` is likewise unsupported —
`response.model` returns the bare router slug. It WAS asserted as "a STRONGER identity" in the
frozen `configs/models.judge-gpt56.yaml` header; that line has been struck and the claim
withdrawn. The pre-run "$57–65
measured" cost was an extrapolation and was high; a mid-run revision to $36–45 was low.

**One process collision worth recording — and an earlier account of it here was wrong.** Two
editing sessions overlapped on the same tracked tree. One was mid-flight on
`analysis/run_cross_judge_audit.py` (OpenRouter `PROVIDER_PIN`/`extra_body`, backend-labelled
ledger rows, a new `expected_provider` parameter on `_score_runs`) and had left the suite broken
two ways (`_Caller.extra_body` AttributeError; `KeyError: 'openai'` once the config moved to
OpenRouter). The other had just implemented the two adjudicated Round-10 fingerprint fixes —
gating the cache-hit path on divergence, and making an ABSENT fingerprint fatal to match
`returned_model`.

**This entry previously said whole-file read-modify-write patches DESTROYED that work. That is
false, and is withdrawn** (corrected 2026-07-20). The fingerprint changes were backed out by
their own author — surgically, unapplied, and on an explicit instruction to do so — because the
overlapping edits made them unverifiable and were dirtying the tree the freeze gate needs clean to
resume. Three independent checks refute the original claim:

- `_assert_fingerprint_ok` appears in NO commit in this repository's history.
  `git log --all -S'_assert_fingerprint_ok'` matches only `508b938`, and within that commit the
  sole file containing the string is `decisions-log.md` itself — this log's own description of the
  supposed loss. The record was self-refuting on its own evidence.
- The inline `SYSTEM-FINGERPRINT DRIFT` block is present and **character-identical** in `80025a8`
  and HEAD. (The enclosing region is not byte-identical, but it differs only by the unrelated
  `served_provider` additions belonging to the transport work.)
- The named mechanism did not occur: the transport work made no whole-file rewrite of either
  file in the relevant window — only surgical single-hunk edits.

The freeze does not contain the two fixes because they were never applied, not because they were
destroyed. Nothing is owed recovery.

Both are provable NO-OPS against this provider: `system_fingerprint` is null in both preflights
(OpenAI-direct and OpenRouter) and in all 7,074 promoted cache entries, so the fingerprint control
is inert here and the served-provider attestation is the operative one. **Decision (2026-07-20):
carry both forward as a named open item rather than applying or closing them.** They buy no
control on this route, but the adjudicated rule they encode — an ABSENT identity is as fatal as a
changed one — is general, and the transport is a freeze amendment that could change again.

The genuinely destructive event this round was a different one, and this is its record: a test
wrote a stale manifest to the REAL repo-root wire-manifest path and `unlink`ed it unconditionally
in `finally`, so merely RUNNING THE SUITE deleted the genuine
`gpt-judge-wire-log-manifest.sha256` and the next `git add` failed on a missing pathspec. It now
snapshots and restores. The precondition that should have prevented it was written as `check(...)`
— which COUNTS a failure but does not ABORT, so the test proceeded to do the damage anyway. A
subsequent audit of every test touching a path outside a tempdir found the same non-aborting
pattern guarding a *billable* action; see the 2026-07-20 entry below.

Three lessons, not one. Do not run two sessions against one working tree — it cost one a reverted
implementation and the other a wrong diagnosis. A precondition that does not abort is not a
precondition. And verify before you CONFESS, not only before you assert: the original text here
was a self-accusation that five minutes with `git log -S` would have refuted.

**Cross-judge result (`comparison/comparison.json`).** The ConvTutor–PedTutor pedagogy gap is
negative under both judges (PedTutor higher, as designed) and the second judge ATTENUATES it
rather than reversing it: Sonnet −1.72→−1.24, GPT −2.36→−2.02, Gemini −0.18→−0.02. The
per-replicate difference-of-differences is +0.480 (CI [0.270, 0.679], p=.006) and +0.347
(CI [0.140, 0.547], p=.049) on Sonnet and GPT, +0.165 (CI spans 0, p=.32) on Gemini. An earlier
draft of the disclosure read this as the second judge seeing a LARGER gap — wrong, and caught by
an adversarial fact-check against `per_replicate.csv`. Helpfulness is ceiling-bound in both
judges (Opus medians 695/800 at 5, GPT 756/800), so its 0.90 exact agreement reflects the
ceiling, not concordance; Spearman is 0.484, kappa 0.338. The judge×condition interaction on
helpfulness is Holm-significant on Sonnet and GPT, not Gemini, while the policy-adjusted
leak→helpfulness slopes are non-significant on all three. Note the Sonnet+Gemini sensitivity
removes only the ROBUSTNESS judge's family overlap; Opus judging the Sonnet base remains a
primary-judge overlap that no reweighting removes.

### 2026-07-20 — Post-audit hardening: a billable test path, an omission-blind verifier, an untracked shipped document

Closing the open items left by the second-judge audit. No result changes; every item below is a
control, a document correction, or a packaging fix. No provider calls were made.

**A test could have issued a paid provider call.** `test_live_preflight_is_gated_on_the_frozen_tree`
expressed its precondition as `check("the freeze state is currently NOT satisfiable", ...)` and
then proceeded, unconditionally, to invoke the runner with `--judge-backend live`. On the live
*preflight* path `assert_live_freeze_state()` is the ONLY gate before the provider call — the
API-key check sits after that branch's `return` — so with `OPENROUTER_API_KEY` set and HEAD at the
freeze tag with a clean tree, which is exactly the documented pre-pay checkout, **running the test
suite would have issued a real billable request, unattended.** The gate held until now only
because HEAD had drifted one commit past the tag. The precondition is now a hard `return`, and a
second failure mode is closed with it: an unset API key raised `SystemExit("OPENROUTER_API_KEY is
not set…")`, whose `.code` is a string, so the old `refused = e.code not in (0, None)` went green
whether the freeze gate held or a missing key saved it. The suite now asserts the refusal REASON,
not merely that something refused. Proven both directions: with the freeze state simulated as
SATISFIED the test skips and the runner is never entered; with it unsatisfied all checks run.

This is the same defect class as the manifest-deletion event recorded above — `check()` COUNTS a
failure, it does not ABORT — and it was found by auditing every test that touches a path outside a
tempdir, which that event prompted. One further instance was fixed (a failed mock preflight fell
through to `read_text()`, raising `FileNotFoundError` out of `main()`, aborting the run and
silently skipping four later tests). Of 100 `REPO_ROOT` uses across the test files, the rest are
fixture-targeted, tempdir-resolved, read-only, or snapshot-and-restore.

**The artifact verifier could not detect OMISSION.** `ARTIFACT-MANIFEST.sha256` is rendered from
the same payload list the tar members are written from, so a file missing at BUILD time is absent
from the manifest AND the tree, both operands of the exhaustive check agree, and every check
passes. This is what let an archive ship carrying only the SUPERSEDED 07-19 amendment — whose text
says the transport is OpenAI-direct and "never OpenRouter" — beside 7,074 OpenRouter ratings. It
verified 6/6. A positive inventory (`REQUIRED_ARTIFACT_PATHS`) now checks 30 documents,
instruments, and result surfaces for PRESENCE. It is source, not generated data, and that is the
whole point: a generated inventory reproduces the bug, because omission requires no action and
silence is the default outcome. Demonstrated by building a real archive with the governing
amendment dropped from the allowlist: the pre-fix verifier PASSES it, the current one FAILS.

**A document outside version control was shipping in the artifact.** `supplement/technical-appendix.md`
was untracked yet packaged (the builder walks the filesystem and consults git for nothing) and
pinned in the in-archive manifest — so the repository could not reproduce its own artifact, and
the file sat outside both version control and the freeze while shipping. Now tracked. The builder
refuses to package any file under a source directory that git neither tracks nor ignores; ignored
is the intended carve-out for the raw-log and cache families. `decisions-log.md` — this file — is
now packaged, because 15 citations in packaged documents pointed at it and the appendix names it
as the source for advisory values explicitly flagged as not re-derivable from the shipped raw. A
citation in the appendix to a `paper-faithfulness-review-2026-07-09.md` that exists nowhere has
been reworded rather than left dangling.

**Two documented controls did not exist.** §7.1 of the 07-19 amendment described
`system_fingerprint` backend-drift detection as enforced — "every scored response is checked
against it: a change aborts". No route ever populated the field: both preflights record
`system_fingerprint: null` and `fingerprint_drift_detectable: false`, and all 7,074 promoted
ratings carry null. The control was inert on OpenAI direct and inert on OpenRouter; it never fired
at any point in this study. Both places asserting it are marked superseded and point at the
served-provider attestation, which is the control that actually operates (attested `OpenAI` on
7,074/7,074). Nothing working was lost in the transport move. The two adjudicated Round-10
fingerprint fixes are carried forward as a named open item rather than applied — they are provable
no-ops against a provider that never populates the field — and deliberately not closed as moot,
because the rule they encode (an ABSENT identity is as fatal as a changed one) is general and the
transport is an amendment that could change again.

**`reasoning_effort` stays disclosed as unverified**, by decision; no re-probe was purchased,
since it cannot change any reported result. One correction was applied regardless: the amendment's
"reasoning is definitely happening (mean 33.8)" was its own consolation argument for the
unverified setting, and it is aggregate-true but false of the typical rating. The median rating
produced ZERO reasoning tokens; 68.0% return zero; the mean is carried by the other 32% (mean
105.5, max 501). By instrument, ~90% of helpfulness ratings show none against 45.7% of pedagogy
ratings. The audit is genuinely unthreatened either way: all 7,074 ratings ran under identical
settings, folded into `request_contract_sha256`, so whatever effort was applied was applied as a
constant — and an unverified constant can shift a level, it cannot manufacture a condition
contrast, which is what this audit reports.

**Method note.** Every claim inherited from the working handoff was re-derived from the artifacts
before being acted on, and three inherited claims were wrong: that HEAD was unpushed (it is on the
remote), that a second test held one of the stale assertions (all four are in one function), and a
pointer to an amendment "§C" that does not exist. One assertion the handoff did not flag was found
passing VACUOUSLY — `len(...) > 0` satisfied by 63 unrelated live artifacts whether or not the
fixture under test did anything — and was repaired by scoping it to the fixture. Recompute before
believing, including from a document written an hour ago.

### 2026-08-01 — Pre-release scrub: internal docs removed, manuscript paths generalized
**Context:** Preparing the repository for public release. Two classes of content were present
that should not ship: internal working documents superseded by the authoritative runbook, and
manuscript path and header references that named a specific output destination rather than a
neutral one.
**Decision:** (a) Removed `experiments/CROSSMODEL-HANDOFF.md` (duplicated `experiments/RUN.md`,
and its commands branched from a freeze tag that never existed) and
`experiments/PIN-RECORD-TEMPLATE.md` (a blank skeleton — the filled pin records are the
2026-06-28 entries in this log); `RUN.md`'s pin-acceptance checklist now points at those filled
records instead. (b) Generalized manuscript path and header references to neutral names in `paper-plan.md`, `supplement/technical-appendix.md`,
`supplement/second-judge-transport-disclosure.md`, `analysis/figures/gen_supp_fig1.py`, the
2026-06-26 positioning entry above, and the archive name in `tools/build_submission_artifact.py`.
(c) Renamed the manuscript output directory to a neutral `manuscript/` path across the
figure scripts, their test, and `.dockerignore`.
**Reason:** Presentation and packaging only. No harness, prompt, problem, rubric, metric,
sampling rule, result, or verdict is touched; no value under `results/` changes. The changes
generalize path and header identity, not content — what was decided, and why, is unchanged and still legible.
**Also fixed (real bug):** `analysis/figures/gen_sol_values.py` wrote its LaTeX macro file with
`Path.write_text` but never created the parent directory, and the manuscript directory is not
tracked — so the script raised `FileNotFoundError` on any fresh clone after completing all of its
computation. Added `out.parent.mkdir(parents=True, exist_ok=True)`.
**Validation:** `tools/scan_sensitive.py` PASS (211 files, 8 patterns, 0 findings); every relative
link in every tracked `.md` resolves; all touched Python compiles; the manuscript-sync test in
`analysis/figures/test_fig2_dissociation.py` (run by CI) was moved in lockstep with the code path
it exercises.
**Affects:** `paper-plan.md`, `supplement/technical-appendix.md`,
`supplement/second-judge-transport-disclosure.md`, `tools/build_submission_artifact.py`,
`analysis/figures/{gen_supp_fig1,gen_sol_values,fig2_dissociation,fig3_forest,test_fig2_dissociation}.py`,
`.dockerignore`, `experiments/RUN.md`, `decisions-log.md`.
