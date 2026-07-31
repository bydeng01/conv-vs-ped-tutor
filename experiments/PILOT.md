# Pilot runbook (M2 go/no-go)

How to produce a **paired** live read for the pilot and run the perceived-helpfulness
judge over it. The pilot is the **non-inferential** gate before the confirmatory run
(paper-plan.md §10, §11). It exists to check that the policies
separate and that P2 points the right way **directionally** — it does **not** produce
p-values, and no stop/scale decision is taken from it.

Read alongside `paper-plan.md` §11 (the outcome table) and `supplement/judge_rubric.md`
(the frozen judge).

## Why a paired run, not a single Opus run

P2 (ConvTutor judged more helpful than PedTutor) is a **paired conv−ped** quantity. The
only stored live tutored session today is ConvTutor (`learn-20260617-154007-344`); there
is **no live PedTutor session**. So running the judge on what exists gives ConvTutor's
helpfulness alone, with nothing to contrast. The informative pilot step is therefore:
generate a paired cold/conv/ped live read, then judge the conv and ped sides.

## Prerequisites

- `langgraph` installed (both tutors import it) and the keys the models config needs.
  For the default `configs/models.yaml`: `ANTHROPIC_API_KEY` (tutor + judge),
  `OPENROUTER_API_KEY` (student). The all-free option is `configs/models.free.yaml`
  (caveat: re-verify the cold and leakage gates on the **final** model before the
  confirmatory run — decisions-log 2026-06-15).
- Frozen inputs: `domain/algebra/problems.yaml`, the tutor configs, and the frozen
  `supplement/judge_rubric.md` / `supplement/independence_rubric.md`. Do not edit these
  during the pilot.

## Pin the student serving (OpenRouter) — do before the cold gate

Unpinned OpenRouter routing produced cold 100% (a too-strong serving; decisions-log
2026-06-18). The student is now pinned via `extra_body.provider` in `configs/models.yaml`,
and the serving provider is logged per call (`served_provider`). Pick a **weak**
(low-precision) serving and verify it:

```
OPENROUTER_API_KEY=... python experiments/list_endpoints.py meta-llama/llama-3.1-8b-instruct
```

Set `order`/`quantizations` under the student role to the chosen endpoint
(`allow_fallbacks: false`). fp16/bf16 is the strongest (was too strong); fp8/int4 is
weaker. Then run the cold gate (Gate 2 below) and adjust precision until cold reads low.
If no serving lands in the cold band, fall back to Groq Dev tier
(`llama-3.1-8b-instant`, the calibrated-weak option).

## Step 0 — validate the judge instrument first (cheap, do this once)

Before reading any conv−ped gap, confirm the judge itself is sane on real Opus. Run it
over the existing live ConvTutor session and eyeball a few turns:

```
ANTHROPIC_API_KEY=... python analysis/compute_metrics.py \
    logs/learn-20260617-154007-344 --out results/judge_smoke --judge-helpfulness
```

Look in `results/judge_smoke/helpfulness_detail.json`: do the scores track the text (a
full worked answer vs a terse hint), are there 3 reps per turn, and what is the rep
variance? (The judge runs at claude-opus-4-8's default sampling — it rejects a
`temperature` parameter — so the reps are genuine samples; near-zero variance is a
finding to report, not a bug — §9.4.) This validates the instrument; it is **not** P2.

## Step 1 — generate a paired pilot read (live)

```
ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... \
    python experiments/run_pilot.py --replicates 1 --conditions cold,conv,ped
```

This writes one `logs/<cond>-<ts>/` per condition; within a replicate the three share a
seed, which is the replicate id the metrics pipeline pairs on. Use `--replicates 2` for
two paired replicates (still non-inferential). `--backend mock` does an offline plumbing
rehearsal only (synthetic — not a result).

## Step 2 — judge + metrics over the pair

```
ANTHROPIC_API_KEY=... python analysis/compute_metrics.py \
    logs/cold-* logs/conv-* logs/ped-* --out results/pilot --judge-helpfulness
```

(Point the globs at the specific pilot run dirs if `logs/` holds older runs.) This fills
`helpfulness` / `helpfulness_mean`, writes `results/pilot/helpfulness_detail.json`, and —
because conv and ped now share a replicate id — the descriptive J1 preview in
`results/pilot/metrics_summary.json` carries `helpfulness_conv_minus_ped` alongside the
leakage and independence diffs. Judge calls are cached, so re-runs don't re-pay Opus.

Rough cost: ~ (visible training turns) × 3 reps × (#conv + #ped sessions) Opus calls
(≈ 100+ for one paired replicate), plus the session-generation tutor/student calls.

## Step 3 — read the M2 gates

From the per-session / per-replicate tables and the J1 preview (paper-plan.md §11):

- **Cold ~0%** — `acc_*` on the cold row near the floor (the student can't solve unaided).
- **P1 separates** (manipulation check) — `leakage_rate` conv ≫ ped.
- **P3 separates** (manipulation check) — `independence_ratio` ped > conv.
- **P2 directional** (the live test) — `helpfulness_mean` conv > ped, i.e.
  `helpfulness_conv_minus_ped > 0` in the J1 preview.
- **Costs acceptable** — `tutor_tokens` / `n_model_calls` per session within budget for
  the planned 10×3 run.

## Decision (paper-plan.md §11) — and the rigor guardrails

- If a **manipulation check fails** (P1≈0 or P3≈0): the policies didn't separate — fix
  PedTutor (the `deferral_gate` is the lever) and re-run. **Do not** tune toward the
  result.
- If **P2 is null or reversed**: that is a real outcome. Report it as the negative result
  (§11). **Do not** edit `supplement/judge_rubric.md` or the judge temperature to move
  the gap — they are frozen pre-data. At the pilot stage, eyeball the judge's *sanity*
  (Step 0), not the conv−ped gap.
- On a **clean pilot**: freeze `paper-plan.md` and proceed to the confirmatory run.

## Scope notes

- This runbook + `experiments/run_pilot.py` are the **pilot** (R2). The **confirmatory**
  10×3 run is R1's runner, which additionally tags `condition`/`replicate_id` on every
  call (the pipeline reads those when present; otherwise it infers condition from the
  tutor component and pairs by seed, which is what the pilot relies on).
- The inferential P2 test (paired Wilcoxon + Cliff's delta) and the J2 mixed-effects
  coupling are Week 3 (paper-plan.md §10) — not part of the pilot.
