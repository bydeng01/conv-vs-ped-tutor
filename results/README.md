# results/

`analysis/compute_metrics.py` writes four standard tables for confirmatory and
ablation runs (`paper-plan.md` §9):

- `per_turn.csv` — one row per training tutor turn (the J2 input). Columns:
  leaks, helpfulness (per-turn judge mean; filled by `--judge-helpfulness`, else
  empty), next_turn_independence, n_model_calls, tutor_tokens, branch.
- `per_session.csv` — one row per session: leakage rate, independence ratio,
  accuracy by role, full cost accounting, and the cost-normalized
  (per-1k-tutor-token) view. A `backend` column keeps mock plumbing data from
  being mistaken for live output.
- `per_replicate.csv` — one row per (condition, replicate_id), the unit of the
  primary tests (§10).
- `metrics_summary.json` — the same tables plus a **descriptive-only** J1 paired
  preview (conv minus ped differences; no p-values, since inference is a separate
  step).

## Tracked run outputs

The confirmatory and ablation directories contain the tables, metric summaries,
and judge details behind the paper's results. Each confirmatory directory also
contains `inference.json`; the Sonnet directory includes `matched_budget.json`,
and the ablation directory includes `ablation_analysis.json`. The
`*_cache.json` files are gitignored here but included in the submission artifact
for offline score reuse.

- `confirmatory/` — the primary Sonnet base (10 replicates x {cold, conv, ped}).
- `confirmatory_gpt/`, `confirmatory_gemini/` — the two cross-model tutor bases,
  using the same protocol and analyzed separately.
- `ablation/` — prompt-only ConvTutor variants and PedTutor node-drops against
  the primary baselines.

`condition_adjusted_sensitivity/` contains the post hoc crossed MixedLM results
adjusted for tutoring policy and the generated manuscript values. The
pre-registered pooled analyses remain in each base's `inference.json`.

## `judge_robustness/` — second-judge (GPT-5.6 Sol) robustness audit

The post hoc GPT-5.6 Sol analysis re-scores the same 1,179 confirmatory answer-phase tutor
turns with the frozen helpfulness and pedagogy rubrics. Its plan was specified before Sol
scoring, after collection of the transcripts and primary Opus scores.
`analysis/run_cross_judge_audit.py` scores the turns; `analysis/compare_judges.py` compares
the judges. See the [research record](../supplement/research-record.md) for the amendments.

Layout — `judge_robustness/gpt-5.6-sol/{sonnet,gpt,gemini}/`:

- **tracked always:** `input_manifest.jsonl` (one line per planned unit recording the
  dialogue **SHA-256** and the source-log SHA-256 — hashes only, never the dialogue text,
  which stays in the pinned raw logs), `protected-primary.sha256` (the frozen files whose
  bytes must not change across the run), `plan.json` (expected unit/call counts).
- **tracked after the live run:** `helpfulness_detail.json`, `pedagogy_detail.json`,
  `per_turn.csv`, `per_session.csv`, `per_replicate.csv`, `metrics_summary.json`,
  `judge_inference.json` (the frozen §10 tests re-run on the GPT scores — **not**
  `inference.json`, which stays the Opus primary), `policy_adjusted.json`,
  `completeness.json`, `provenance.json`; plus `preflight/` and `comparison/comparison.json`.
- **gitignored (shipped in the artifact):** `cache/` (per-rep score caches, for
  `--offline-cache-only` reconstruction) and `wire/` (raw provider wire logs), pinned by the
  top-level `gpt-judge-wire-log-manifest.sha256`.

Opus and Sol scores are reported separately. The comparison concerns these two judges;
human validation remains outside this analysis. The GPT-judge/GPT-tutor arm is flagged
as same-family, with a Sonnet+Gemini-only sensitivity. Live Sol scoring uses
`OPENROUTER_API_KEY` and a completed transport preflight. Routing and identity limitations
are described in [the transport disclosure](../supplement/second-judge-transport-disclosure.md).

See the repository README for [offline inference commands](../README.md#quickstart).

## Verifying the raw-log manifests

Raw transcripts under `logs/` are gitignored but SHA-256-pinned by the four top-level
manifests. From the repo root, each verifies its family of pinned log files:

```
shasum -a 256 -c confirmatory-log-manifest.sha256       # Sonnet primary  (logs/conf-s0-*)
shasum -a 256 -c crossmodel-gpt-log-manifest.sha256     # GPT base        (logs/conf-gpt-s0-*)
shasum -a 256 -c crossmodel-gemini-log-manifest.sha256  # Gemini base     (logs/conf-gemini-s0-*)
shasum -a 256 -c ablation-log-manifest.sha256           # ablation        (logs/abl-s0-*)
```

Each prints `OK` for every pinned file. These four manifests cover exactly the raw-log
families behind the tracked results (the ablation manifest pins only the five `abl-s0-*`
ablation conditions; their reused conv/ped/cold baselines are pinned by the confirmatory
manifest). A fifth manifest pins the judge wire-logs behind the 2026-07-04 ablation judge
pass (the provenance of its helpfulness/pedagogy scores):

```
shasum -a 256 -c ablation-judge-log-manifest.sha256  # ablation judge wire-logs
                                                      # (logs/helpfuljudge-2026*, logs/pedjudge-2026*)
```

Every other `logs/` subdirectory — pilots, smokes, mock plumbing, and any un-manifested
judge-log scratch — is unpinned working scratch.

## Independence LLM-verification (Opus)

Off by default; the regex is primary. To add the verification pass where a judge
key is available:

```
ANTHROPIC_API_KEY=... python analysis/compute_metrics.py <run_dirs> --verify-independence
```

This writes `independence_verify.json` (agreement rate plus logged
disagreements). The frozen regex is authoritative; the LLM pass is a documented
robustness check whose disagreements default to the regex result (`paper-plan.md`
§9.3, `supplement/independence_rubric.md`).

## Perceived-helpfulness judge (Opus)

Off by default. To fill the reserved `helpfulness` (per-turn) and
`helpfulness_mean` (per-session and per-replicate) columns with the judge pass,
where a key is available (`paper-plan.md` §9.4, `supplement/judge_rubric.md`):

```
ANTHROPIC_API_KEY=... python analysis/compute_metrics.py <run_dirs> --judge-helpfulness
```

Each visible **training** tutor turn (the same turn leakage scores) is rated 1–5
on clarity, responsiveness, helpfulness, and overall, three reps at the judge
model's default sampling (`claude-opus-4-8` rejects a `temperature` parameter;
`decisions-log.md` 2026-06-18). The per-turn helpfulness is the mean of the reps'
`overall`; per-turn variance and sub-scores go to `helpfulness_detail.json`. The
judge sees only the student-visible dialogue and the frozen rubric, never the
canonical answer or the condition. Judge calls go to their own `logs/helpfuljudge-*/`
directory and are excluded from the §9.5 cost accounting; per-rep scores are
cached in `helpfulness_cache.json` so re-runs do not re-pay. For an offline
plumbing run with no key (synthetic scores, do not report), add
`--judge-backend mock`. This fills the helpfulness input for P2 and J2; the P2
paired Wilcoxon and the J2 coupling are computed by the inferential step (§10).
