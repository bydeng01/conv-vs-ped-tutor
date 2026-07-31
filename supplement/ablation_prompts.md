# Ablation prompts & graph variants (verbatim) — #5 extension

This file mirrors, verbatim, the ADDITIVE #5 ablation conditions (pre-registered in
`decisions-log.md` 2026-06-30, frozen before any live run). It is the ablation counterpart
to `supplement/prompts.md`, which is left **byte-stable** — the minimal ConvTutor and the
frozen PedTutor prompts/graph are NOT edited; every ablation is a NEW config/condition.
Canonical sources are the configs listed; this file must be kept in sync. No ablation prompt
contains `canonical_answer`, the leakage strings, the node names, or the condition.

## ConvTutor prompt variants (single call; same path as the minimal ConvTutor)

Both reuse the minimal ConvTutor agent (`agents/conv_tutor.py`) UNCHANGED — one model call
per turn — and differ from it ONLY in the system prompt. They test whether a **prompt-only**
change (no structural scaffolding, no deterministic attempt-gate) moves a conversational
tutor toward PedTutor's leakage/independence behavior. Neither is tuned against the metrics;
whatever they show is reported.

### conv_socratic (source: `configs/conv_socratic.yaml`)

> You are a math tutor helping a student. Teach using the Socratic method: rather
> than telling the student what to do, ask guiding questions that lead them to work
> out each step on their own. Respond to what the student has actually said, build on
> their reasoning, and keep the student doing the thinking.

### conv_no_final_answer (source: `configs/conv_no_final_answer.yaml`)

> You are a math tutor helping a student. Be helpful and clear, but do not give away
> the final answer — guide the student to reach it themselves. Explain the ideas and
> the next step to try, and let the student carry out the final reasoning and the
> arithmetic on their own.

## PedTutor structural variants (node drops; no prompt changes)

The three PedTutor ablations source ALL prompts and routing UNCHANGED from the frozen
`configs/ped_full.yaml` (mirrored in `supplement/prompts.md`); a thin
`configs/ped_{variant}.yaml` declares only the structural manipulation, consumed by
`agents/ped_ablations.py:PedTutorVariant` (a subclass overriding ONLY graph construction, so
`agents/ped_tutor.py` is byte-identical). No node prompt is edited.

**Remap rule (uniform, pre-committed).** When a responder node is dropped, its orphaned
deterministic route lands on the retained **`decomposer`** — the neutral single-step scaffold
that (like every PedTutor responder) never states the answer. A single uniform target removes
researcher discretion; because all PedTutor responder prompts withhold the final number, the
target choice cannot manufacture or destroy the leakage separation.

**`branch` semantics (pre-registered).** Each visible turn keeps its ORIGINAL deterministic
route value (`defer` / `decompose` / `hint`, the student-behaviour routing reason). A rerouted
turn is handled by the `decomposer` but still carries its original `branch` (e.g. an
answer-demand under `ped_no_gate` is `branch=defer`, handled by `node=decomposer`); the
realized responder is recoverable from the call's `node` tag. The visible responder tag stays
one `analysis/metrics.py` recognizes (`deferral_gate` / `decomposer` / `hint_cascade`) — no
new visible-responder tag is introduced.

| variant (config)                 | drops          | orphaned route → retained responder | per-visible-turn calls |
|----------------------------------|----------------|-------------------------------------|------------------------|
| `ped_no_gate` (ped_no_gate.yaml)       | `deferral_gate`  | `defer` → `decomposer`            | 2 (state_tracker + 1; UNCHANGED) |
| `ped_no_cascade` (ped_no_cascade.yaml) | `hint_cascade`   | `hint`  → `decomposer`            | 2 (state_tracker + 1; UNCHANGED) |
| `ped_no_tracker` (ped_no_tracker.yaml) | `state_tracker`  | (entry/planner; START routes directly to the responder) | 1 (responder only; one fewer) |

- **`ped_no_gate`** — drop the deferral_gate (the answer-demand responder). The `defer` route
  is handled by the decomposer; `decompose`→`decomposer` and `hint`→`hint_cascade` are
  unchanged. state_tracker still runs.
- **`ped_no_cascade`** — drop the hint_cascade (the engaged-student responder). The `hint`
  route is handled by the decomposer; `defer`→`deferral_gate` and `decompose`→`decomposer`
  are unchanged. state_tracker still runs.
- **`ped_no_tracker`** — drop the state_tracker ENTRY/planner. The deterministic signals do
  not depend on it, so routing is unchanged and START routes directly to the routed responder
  (all three responders retained). With no planner, responders receive the **empty assessment
  fallback**, which the frozen `format_assessment()` renders as `"(planner produced no
  structured estimate)"` with `progressed=false` — the SAME graceful-degradation path the
  frozen code already takes when the planner yields no structured estimate. **Disclosed
  confound:** this is the only variant that reduces the per-turn call count (2 → 1), so it
  confounds structure with call count; the per-1k-tutor-token sensitivity
  (`analysis/inferential.cost_normalized`) and the matched visible-turn-budget pass
  (`analysis/matched_budget.py`) bound the token / visible-turn side of compute, but the
  internal call-count drop is disclosed, not controlled.

**Analysis.** Ablations are DESCRIPTIVE only and NEVER enter the frozen §10 J1/J2: they are
metricized by `analysis/compute_metrics.py` (which preserves arbitrary condition tags) into a
SEPARATE `results/ablation/` dir alongside the reused primary baselines, then summarized by
`analysis/ablation_analysis.py` (paired diffs / Cliff's δ / CIs; per-condition
leak→next-independence coupling fit separately, never pooled). They are never passed to
`analysis/run_inference.py`. "No node collapses the leakage/independence separation" is an
explicitly allowed, fully-reportable result.
