# Cross-judge robustness amendment — GPT-5.6 Sol second judge (2026-07-19)

**Status: prospectively specified, pre-live-run.** This document freezes a *strictly
additive* second-judge robustness audit. It amends nothing in the frozen confirmatory
pre-registration (`paper-plan.md` §§9–11, `metric-amendment-2026-06-19.md`); it does not
touch any frozen metric, window, rubric, tutor, student, training protocol, or the Opus
judge. It is frozen together with `analysis/run_cross_judge_audit.py`,
`analysis/compare_judges.py`, `configs/models.judge-gpt56.yaml`, and the two focused test
suites once their offline tests pass and the freeze tag is created.

## 1. Scientific status and wording (the epistemic boundary)

> **Prospectively specified post hoc cross-judge robustness analysis over frozen
> transcripts.**

Claude Opus 4.8 remains the frozen **primary** judge. GPT-5.6 Sol is a prospectively
specified, **post hoc robustness** judge applied to the already-collected transcripts and
the already-frozen Opus outcomes. This is **not** part of the original confirmatory
pre-registration — the transcripts and Opus scores already exist.

A two-model panel **can** support:
- "replicated across Claude Opus 4.8 and GPT-5.6 Sol" (if the prespecified results warrant);
- "directionally consistent across two specified judges";
- "judge-contingent" (if material disagreement appears).

It **cannot** support: "generalizable across LLM judges"; "judge-independent"; "universally
helpful"; "comprehensive judge validation"; any human-preference or human-validity claim.
Human annotation remains a separate IRB-gated study (`metric-amendment-2026-06-19.md` §4).

The two instruments are **reported separately**. Opus and GPT scores are **never** averaged
into a consensus headline — disagreement is a result, not noise. No training experiment is
added; no training claim is enlarged. This concerns evaluation robustness only.

## 2. Frozen inputs (no sampling)

All existing confirmatory answer-phase tutor turns, over the frozen answer-phase window and
the frozen training-turn restriction (`analysis.metrics` / `analysis.judge.dialogue_for_turn`,
reused verbatim):

| Base (source results dir)          | ConvTutor | PedTutor | Total |
|------------------------------------|----------:|---------:|------:|
| Sonnet (`results/confirmatory`)    |       135 |      223 |   358 |
| GPT-5.5 (`results/confirmatory_gpt`)   |   161 |      218 |   379 |
| Gemini 3.1 Pro (`results/confirmatory_gemini`) | 215 | 227 |   442 |
| **Total**                          |   **511** |  **668** | **1179** |

The 90 confirmatory sessions include 30 cold sessions; cold contributes **no** tutor turns
and receives **no** judge calls. Unit identity is `(base, run_id, condition, replicate_id,
problem_id, turn_index)`; exact key equality with the frozen Opus `*_detail.json` and
`*_cache.json` records is asserted before any paid batch (verified offline 2026-07-19:
reconstruction keys == Opus keys on all three bases).

Both instruments are scored: (1) annotator-perceived **helpfulness**
(`analysis/judge.py`), (2) judged **pedagogy** (`analysis/judge_pedagogy.py`). Helpfulness
alone would not test whether the helpfulness–pedagogy dissociation survives a second judge.

For each instrument: the exact existing dialogue reconstruction, answer-phase window,
training-turn restriction, frozen system prompt / user template / rubric / neutrality
language / output fields, existing parser, **three calls per turn**, per-turn score = mean
of the three valid `overall` ratings, per-turn variance = sample variance over the three.
The prompt constants and `dialogue_for_turn` are **imported** from the existing judge
modules — never rewritten, shortened, "improved", or adapted for GPT. The frozen
deterministic leakage and independence measures remain authoritative; the optional
independence LLM verifier is **not** re-run.

The prompt sent to GPT contains no condition, tutor policy name, base/model identity,
canonical answer, leakage label/strings, PedTutor node names, hidden state-tracker content,
or reference solutions (asserted in `tools/test_cross_judge_audit.py`).

## 3. GPT-5.6 Sol configuration (`configs/models.judge-gpt56.yaml`)

| Field | Value |
|---|---|
| provider | ~~`openai` (OpenAI directly — **not** OpenRouter or any intermediary)~~ **[SUPERSEDED 2026-07-20 → `cross-judge-amendment-openrouter-2026-07-20.md` §3]** The transport is now `openrouter`, pinned to the `openai` upstream with fallbacks disabled, forced by an intermittent provider-side 401 and a daily token cap below the batch size. The *general* prohibition stands: exactly one provider/endpoint pair is allow-listed and the pair must agree with itself. |
| base URL | `https://api.openai.com/v1` |
| API key env | `OPENAI_API_KEY` |
| requested model | `gpt-5.6-sol` — the **explicit Sol model ID**, not the movable `gpt-5.6` alias. It is *not* an immutable dated snapshot (OpenAI exposes none beyond the Sol ID), so the **served** model is captured from `response.model` at preflight, frozen into the cache stamp, and re-checked on every call — drift aborts the batch. ~~Because a backend can also be updated *in place* under an unchanged ID, `system_fingerprint` is frozen at preflight and checked per call as well (see §7.1).~~ **[SUPERSEDED 2026-07-20 → `cross-judge-amendment-openrouter-2026-07-20.md` §4.2]** Read now as: no route ever populated `system_fingerprint`, so that control is inert and the in-place-update case is covered instead by the per-rating served-provider attestation (§7.1 as corrected). |
| API surface | Chat Completions |
| `reasoning_effort` | `medium` (explicitly supplied, top-level Chat field) |
| temperature | **omitted entirely** from the request (config `temperature: null`; the client drops a null temperature) |
| `max_completion_tokens` | 2048 |
| tools / web / file / code | none |
| Pro mode | off |
| provider fallback / model fallback / prompt rewrite | none |

The config is **judge-only** (no tutor/student role), so `agents.config.load_models_config`
refuses it — it can never drive the confirmatory runner or `analysis/compute_metrics.py`.
If the account cannot access `gpt-5.6-sol`, the runner **stops**; it never substitutes
~~GPT-5.5, GPT-5.6 Terra, the `gpt-5.6` alias, or an OpenRouter route.~~
**[SUPERSEDED 2026-07-20 → `cross-judge-amendment-openrouter-2026-07-20.md` §1]** Read now as:
it never substitutes GPT-5.5, GPT-5.6 Terra, the `gpt-5.6` alias, or any provider/endpoint pair
other than the single allow-listed one. That pair is now OpenRouter pinned to the `openai`
upstream; changing it again requires a further amendment, not a config edit.

**Model-client change (minimal):** `agents/model_client.py` now treats an explicit
`temperature: null` as *omit the parameter* rather than sending JSON null (mirroring the
Anthropic path). All non-null temperature behavior is preserved (`tools/test_model_client.py`).

## 4. Transport preflight (before any confirmatory dialogue)

`--preflight` runs one **synthetic**, non-study tutoring dialogue through both frozen rubrics
to establish: model access, accepted endpoint, accepted reasoning field, **seed support**,
temperature omission, returned model identity, parser compatibility, finish reason, usage
logging, OpenAI SDK version, UTC timestamp. The output-token field is a **fixed constant** for
the pinned OpenAI Chat Completions contract — `max_completion_tokens` (2048), sent directly,
not probed (`resolved_config.json` records `token_field` as provenance, not as a resolved
variable). The preflight writes `preflight/preflight.json` and `preflight/resolved_config.json`;
production scoring **requires** this resolved config (found at
`<base_out>/../preflight/resolved_config.json`) and freezes the **seed policy** from it.
Confirmatory/ablation text is never used at preflight. If Chat Completions is unexpectedly
incompatible, the runner stops and reports the exact error (it does not silently migrate to
Responses).

## 5. Repetitions and failure policy (frozen)

Three repetitions are three calls to **one** judge model — not three judges — and do not
multiply the inferential sample size. Seed + repetition index is used **only if** the
synthetic preflight confirms seed support; otherwise seed is omitted for all production calls
and the three reps are recorded as separate unseeded calls.

- Transport failures before a response (transient 429 / timeout / connection / 5xx):
  bounded exponential backoff (≤5 attempts). Authentication, permission, unavailable-model,
  and exhausted-quota errors: **fail fast**, no retry.
- A returned-but-unparseable response: record the raw text and retry the **identical**
  request at most twice more (≤3 attempts). No repair prompt, no parameter change.
- If no valid score after three parse attempts: keep the audit resumable, do **not** publish
  final tables. Require `n_valid == 3` for every planned turn and rubric before the score
  pass is complete.
- Transport retries, parse retries, missingness, and valid-repetition rates are reported by
  judge, rubric, tutor base, and condition (`completeness.json`).

## 6. Cache and resumability

A GPT-specific cache (`<base>/cache/{helpfulness,pedagogy}_cache.json`) that never reuses or
replaces an Opus cache. The stamp binds: schema version, backend, provider, endpoint,
requested + returned model, reasoning effort, temperature behavior, output-token limit, seed
policy, repetition count, instrument, SHA-256 of the rubric text / system prompt / user
template, parser code hash, and the second-judge-plan freeze. Each entry records the full
unit identity, repetition, dialogue SHA-256, parsed scores, returned-model metadata, and
usage. The cache key includes unit identity **and** dialogue hash, so distinct study units
with coincidentally identical text are never deduplicated and a changed dialogue invalidates.
Writes are atomic (flock + `os.replace`), flushed per conversation (crash-resumable). A rerun
makes zero provider calls for complete valid entries. `--offline-cache-only` reconstructs
from the released cache with a **hard tripwire**: any cache miss aborts (no provider call, no
synthetic score).

## 7. Two-stage freeze and the required commands

1. Commit the plan (this file), config, `analysis/run_cross_judge_audit.py`,
   `analysis/compare_judges.py`, the two test suites, and the `agents/model_client.py`
   change, with passing offline tests.
2. Tag that commit `judge-robustness-gpt56-freeze`.
3. Only then run the live GPT judge pass.
4. Commit results and manifests separately. Do not stage unrelated untracked files.

Offline (no key): protected-primary hashes + input manifests are already generated for all
three bases via `--manifest-only`.

### 7.1 Gates the runner ENFORCES before a paid batch (not just records)

A live scoring run aborts unless **all** of the following hold. These are hard gates, added
after an independent review found that recording a violation is not the same as refusing it:

- **Frozen tree.** `judge-robustness-gpt56-freeze` resolves, `HEAD` **is** that commit, and no
  tracked file is modified or staged (untracked scratch is ignored). A paid batch never binds
  to an unfrozen tree.
- **Plan re-validation.** `input_manifest.jsonl` + `plan.json` must exist and still match the
  reconstruction exactly — same unit set, same per-unit `dialogue_sha256`, same rubrics and
  reps. Any post-planning drift in the frozen inputs stops the batch instead of silently
  becoming the new baseline.
- **Plan-to-freeze binding.** Re-validation against the reconstruction is not sufficient on its
  own: a plan minted *after* tagging would also be self-consistent, and the namespace accepts
  arbitrary subdirectories while the clean-tree check ignores untracked files. A paid batch
  therefore additionally requires (`assert_plan_frozen`) the **canonical** `--out` and
  `--source-results` path for the base being scored, **exactly** both frozen rubrics and
  **exactly** three repetitions, and `plan.json`, `input_manifest.jsonl`, and
  `protected-primary.sha256` **byte-for-byte identical** to their versions inside
  `judge-robustness-gpt56-freeze` (`git show <tag>:<path>`). Offline reconstruction is
  deliberately exempt — it must keep working inside an extracted artifact with no `.git`.
- **Transactional output promotion.** Every scoring attempt first flips `run_state.json` away
  from `complete`, so previously published outputs are invalid while an attempt is in flight.
  A complete attempt is built in a staging directory and promoted atomically (whole set
  verified present, `os.replace`d into place, `run_state.json` written **last**). An attempt
  that ends incomplete **deletes** the prior run's detail files, CSVs, `judge_inference`,
  `policy_adjusted`, `completeness`, and `provenance` instead of leaving them reportable beside
  a new partial cache. `compare_judges` and `verify_artifact` both require `state == "complete"`
  plus cache stamps that agree across `run_state.json`, each `*_detail.json`, and each packaged
  per-rep cache.
- **One run per reconstruction.** `--offline-cache-only` requires every rubric's cache stamp to
  agree on returned model, seed policy, plan freeze, backend, and repetition count, and reports
  those validated values. Run-level provenance is never defaulted (no hardcoded `unseeded`) and
  never taken from whichever rubric loaded last.
- **Protected-primary baseline is VERIFIED, never rewritten.** The baseline written at plan
  time is checked before scoring and again after; the runner does not re-snapshot it (a
  write-then-verify would be tautological).
- **Preflight is a gate, and is itself frozen.** A **live** preflight is a real provider call
  that freezes the transport contract the paid batch inherits, so it now requires the same
  frozen-tree state a paid run does — tag resolves, `HEAD` is that commit, clean tracked tree.
  (The mock preflight is offline plumbing and stays ungated.) It aborts on parser failure,
  inconsistent or **absent** returned models, any non-`stop` finish reason, or missing usage,
  applying the *same* `_degraded_reason` predicate production applies — previously the preflight
  discarded falsy finish reasons and checked only `completion_tokens`, so it could certify a
  contract that made every production response invalid. Scoring refuses a **stale** preflight
  whose recorded model / endpoint / reasoning / token limit / temperature-omission disagree with
  the current config, and additionally requires the preflight to have been resolved under the
  same **request-contract hash**, the same **plan freeze commit**, and the same **OpenAI SDK
  version** — so a contract tested by a different checkout or dependency cannot authorize the
  batch.
- **Backend drift under an unchanged model ID.** `gpt-5.6-sol` is not an immutable dated
  snapshot, so the model string alone cannot detect an in-place backend update.
  ~~The preflight freezes `system_fingerprint` when the provider supplies a consistent one, and
  every scored response is checked against it: a change aborts, because ratings either side of it
  come from different scoring regimes. `--allow-fingerprint-drift` continues deliberately, records
  every fingerprint observed in `completeness.json` and `provenance.json`, and marks the run
  `spans_multiple_backends` — which must then be disclosed with the results.~~
  **[SUPERSEDED 2026-07-20 → `cross-judge-amendment-openrouter-2026-07-20.md` §4.2]** Read now as:
  this control is **INERT, and was inert on both transports** — it never operated at any point in
  this study, and the text above described an enforced gate that never fired. No route ever
  populated the field: `preflight/resolved_config.json` and
  `preflight.openai-direct.superseded/resolved_config.json` both record `system_fingerprint: null`
  and `fingerprint_drift_detectable: false`, and all **7,074** promoted ratings carry
  `system_fingerprint: null`. The preflight therefore freezes nothing, the per-call comparison is
  vacuous, and `--allow-fingerprint-drift` can never fire. The operative identity control below
  the model ID is the per-rating **served-provider attestation** (§4.2): enforced on every fresh
  call, required at preflight, aggregated on cache hits, and asserted at completeness — attested
  `OpenAI` on 7,074/7,074 ratings, with none unattested, mixed, or divergent. **Nothing working
  was lost in the transport move**: the fingerprint control was already inert on OpenAI direct, so
  routing through OpenRouter did not weaken it. The fingerprint is
  deliberately **not** part of the cache stamp: putting it there would invalidate every cached
  rating on a backend rotation and force a full re-spend, which is a worse outcome than
  per-entry recording plus a run-level flag. When the provider returns no fingerprint at all,
  the run says so explicitly rather than implying drift was ruled out.
- **Per-call model drift.** Every call's `response.model` is compared with the model frozen at
  preflight; a mid-batch change aborts rather than mixing two served models. An **absent**
  identity is equally fatal — a response with no model field cannot satisfy the check, so it
  aborts instead of silently skipping it. Scoring also refuses to start if the resolved
  preflight recorded no returned model at all.
- **Degraded responses are not ratings.** A reply is only a valid rating if `finish_reason ==
  "stop"` and token usage is present. A truncated or unaccounted reply that nevertheless parses
  is retried under the frozen ≤3-attempt policy and, failing that, leaves the repetition
  invalid so completeness blocks publication. Previously these were gated only at preflight, so
  the check applied to exactly one synthetic call and never to the paid batch.
- **One run per base.** Every scoring attempt holds a non-blocking exclusive per-base lock
  (`tmp.lock.run`) from invalidation through promotion. Two concurrent invocations for one base
  would otherwise duplicate paid calls, clobber each other's run state, sweep each other's
  staging directories, and interleave their promotions into a mixed output set.
- **The declared retry bound is the real one.** The OpenAI client is constructed with
  `max_retries=0`. The SDK retries internally by default, which would have multiplied the
  frozen ≤5-attempt bound to as many as 45 unlogged HTTP requests per rated repetition; all
  retrying now happens in the outer loop, where it is counted and written to the wire log.
- **Full unit identity + frozen transcripts.** Plan re-validation compares the complete frozen
  tuple — including `condition` and `replicate_id` — and verifies each source transcript against
  the `source_log_sha256` recorded in the manifest. `logs/` is gitignored, so neither the
  clean-tree gate nor `protected-primary.sha256` covers it; without this a run could be
  relabelled `conv`→`ped` without changing a byte of dialogue and every per-policy result would
  be misclassified.
- **Transactional comparison, bound to ALL of its inputs.** `compare_judges` publishes the same
  way the runner does: the previous report is invalidated first, the new one is built in staging
  and promoted atomically, and `run_state.json` — recording the report's own hash plus the hashes
  of every input it was computed from — is written last. Those bindings cover **both** sides: the
  Opus `per_turn.csv` and both Opus detail files as well as the GPT surfaces. They are snapshotted
  *before* the analysis reads anything and re-hashed immediately before promotion; if any input
  moved while the analysis ran, publication is refused rather than binding new inputs to a report
  computed from old ones. Artifact verification requires the report and its promotion record to
  exist together, a matching non-empty report hash, bindings for exactly the three declared bases,
  and every required input label present and matching. A failed recomputation removes the superseded report
  rather than leaving it publishable; `verify_artifact` checks those bindings.
- **Output isolation.** The `--out` leaf must name the base being scored, so a Sonnet command
  cannot write into `gpt/`.
- **Synthetic provenance is per-ENTRY.** Mock runs mark every cache entry `synthetic: true`, so
  relabelling a cache stamp's `backend` cannot promote mock scores into a reconstruction;
  `--offline-cache-only` additionally requires `backend == "live"` and a recorded
  `returned_model`.
- **Cross-judge alignment.** `compare_judges` aborts on any Opus/GPT disagreement in
  `condition`/`replicate_id`, any GPT `dialogue_sha256` that disagrees with the frozen input
  manifest, or any turn whose leakage row fails to join — never a silent drop. It also refuses
  a mock/do-not-report GPT detail and any `--out` outside `results/judge_robustness/`.
- **Artifact completeness.** Packaging live GPT artifacts without
  `gpt-judge-wire-log-manifest.sha256` is refused; with it, verification requires all three
  bases' per-rep caches and wire logs **and the entire promoted output set** — the three CSVs,
  `metrics_summary.json`, `judge_inference.json`, `policy_adjusted.json`, `completeness.json`
  (with `complete: true`), `provenance.json`, and both `*_detail.json`. The required list is
  cross-checked against each base's `run_state.promoted_outputs`, so the runner and the verifier
  cannot drift apart. Requiring only caches, details, and wire logs previously let an archive
  drop any of the analysis outputs and still verify as complete, because the manifests only
  inventory the files that remain.
- **Live provenance, at every packaging link.** Detection of "live GPT judge artifacts" is per
  output directory by recorded provenance: a directory's files require the manifest unless the
  directory proves it is MOCK (only `"mock"` is positively unpaid — live, `offline-cache-only`,
  missing, unknown, and unreadable all fail closed; the live preflight's outputs count).
  Certification is symmetric: `build_gpt_judge_manifest` refuses to pin mock rehearsal output;
  the post-live verifier requires every base's promoted stamps to record `backend: "live"` and
  every wire log to record at least one live request; the wire manifest must pin every packaged
  second-judge file (both directions), and the artifact builder verifies the manifest's hashes
  and coverage before packaging instead of trusting its presence. The post-live verifier also
  refuses any file anywhere in the layer that records `backend: "mock"` (the per-base checks
  iterate only the three known bases; contamination outside them was checked by nothing).
  Before these gates, a three-base mock rehearsal plus a built manifest verified as a paid
  second-judge layer.
- **The spend ledger is regime-labeled.** The mock rehearsal prescribed by §7 runs on the
  canonical base directories and persists its simulated charges into the same
  `spend_ledger.json` the paid run reads, so the first live batch used to start with most of
  its lifetime allowance consumed by spend that was never billed. Ledger invocation rows now
  record their backend; a LIVE ledger charges against live and unlabeled rows only (unlabeled
  legacy rows count for both regimes — over-stating prior spend is the safe direction), and
  `http_attempts_total` remains the all-rows sum so the file-integrity invariant is unchanged.

```
# preflight (resolves + freezes the transport contract)
OPENAI_API_KEY=... .venv/bin/python analysis/run_cross_judge_audit.py \
  --preflight --models configs/models.judge-gpt56.yaml \
  --out results/judge_robustness/gpt-5.6-sol/preflight

# per-base scoring (Sonnet / GPT / Gemini) — 2×3×units calls each
OPENAI_API_KEY=... .venv/bin/python analysis/run_cross_judge_audit.py \
  --source-results results/confirmatory --models configs/models.judge-gpt56.yaml \
  --rubrics helpfulness,pedagogy --reps 3 \
  --out results/judge_robustness/gpt-5.6-sol/sonnet
OPENAI_API_KEY=... .venv/bin/python analysis/run_cross_judge_audit.py \
  --source-results results/confirmatory_gpt --models configs/models.judge-gpt56.yaml \
  --rubrics helpfulness,pedagogy --reps 3 \
  --out results/judge_robustness/gpt-5.6-sol/gpt
OPENAI_API_KEY=... .venv/bin/python analysis/run_cross_judge_audit.py \
  --source-results results/confirmatory_gemini --models configs/models.judge-gpt56.yaml \
  --rubrics helpfulness,pedagogy --reps 3 \
  --out results/judge_robustness/gpt-5.6-sol/gemini

# cross-judge comparison (Opus vs GPT), after all three bases score
.venv/bin/python analysis/compare_judges.py \
  --out results/judge_robustness/gpt-5.6-sol/comparison
```

Post-scoring assertions (checked by `completeness.json` per base and by `compare_judges`):
1,179 helpfulness turn rows, 1,179 pedagogy turn rows, 3,537 valid helpfulness ratings,
3,537 valid pedagogy ratings, **7,074** total GPT ratings; exact unit-key and dialogue-hash
agreement with the Opus surfaces; **zero** tutor / student / Anthropic / Gemini-judge calls.

## 8. Cost gate

### 8.1 The authorization is ENFORCED, not merely documented

The call counts below were, until an adversarial review said so plainly, an *expectation written
in this document* — nothing in the runner bounded them. Because the frozen retry policy permits
up to three attempts per rating, a systematic production failure (a parser that never matches, a
served model that always truncates) could have issued **21,222** completed billable responses
across the corpus before completeness was ever evaluated. Two controls now make the
authorization real, both enforced inside the scoring loop:

- **Hard ceiling, CUMULATIVE across invocations.** `--max-provider-calls` is a **lifetime**
  authorization for the base, persisted in `spend_ledger.json` and charged immediately before
  **every HTTP request, transport retries included** — inside the retry loop, not around it.
  A per-invocation ceiling is not an authorization: resuming used to hand the run a fresh full
  allowance, so the canary-then-resume workflow recommended below silently re-authorized itself
  every time. Raising the lifetime cap is an explicit, recorded act; a cap below what has already
  been spent is refused outright. (Charging once per logical
  rating attempt was measured to under-count by 5×, since the transport loop can issue five real
  requests per attempt.) It defaults to the planned calls plus a 10% allowance covering parse and
  transport retries together. The run cannot exceed it however the provider behaves. On hitting
  it the run aborts, publishes nothing, and **flushes the cache** — so re-running with a higher
  ceiling pays only for what is still missing.
- **Circuit breaker.** After 60 *responses*, if fewer than 50% have produced a usable rating the
  run stops. A total production failure therefore costs ~60 requests instead of ~21,000. The
  breaker deliberately reads responses, not HTTP attempts: a rate-limit storm is a spend problem
  (the ceiling's job) and says nothing about whether the served model still answers usefully.

`provenance.json` and `completeness.json` record `http_attempts_used`, `responses_evaluated`,
`accepted_ratings`, and `attempts_per_response`, so retry amplification is visible after the fact
rather than inferred.

The ceiling doubles as the **canary**: set it to a small tranche (e.g. `--max-provider-calls 60`)
for the first real-dialogue run, inspect the wire log, then re-run with the full authorization.
No separate mode is needed, and no work is paid for twice. `completeness.json` and
`provenance.json` both record the ceiling, the calls used, and the accept rate.

### 8.2 Authorized volume

The required first live phase is the 1,179-turn confirmatory corpus under both rubrics:
**7,074 calls** (Sonnet 2,148; GPT 2,274; Gemini 2,652). The implementation can extend to the
ablation corpus (five unique policies, +1,040 turns; 2,219 unique turns across confirmatory +
ablation; 13,314 calls for both rubrics reusing the cached Sonnet baseline), but the ablation
is **not** launched without a separate cost authorization. If the ablation is not scored by
GPT, the manuscript identifies all seven-policy helpfulness/pedagogy claims as **Opus-only**
and does not imply the ablation dissociation was cross-judge validated.

## 9. Analyses (per base; reusing the frozen fitting logic)

Per base, `judge_inference.json` re-runs the frozen §10 tests over the GPT-filled tables:
session-level helpfulness contrast (paired Conv−Ped over ten replicate pairs: means, mean
paired diff, replicate bootstrap 95% CI, two-sided paired Wilcoxon, Cliff's δ, exact n);
session-level pedagogy contrast (same summaries, a **manipulation check**, not independent
validation); turn-level `helpfulness ~ leaks_i` crossed replicate+problem MixedLM (ML, frozen
optimizer sequence). `policy_adjusted.json` fits `helpfulness ~ leaks_i + C(condition)` (and
the deterministic independence leg) with the same crossed spec. The leakage and independence
legs are deterministic (judge-invariant) and equal the Opus values (verified offline); only
helpfulness/pedagogy are GPT-specific.

`analysis/compare_judges.py` aligns Opus and GPT by exact turn identity (never pairing rep 0
with rep 0; comparing per-turn means and integer medians): Spearman of per-turn means +
conversation-clustered bootstrap 95% CI; quadratic-weighted κ on median integers + clustered
CI; mean signed diff (GPT−Opus), mean absolute diff, exact and within-one agreement,
distributions, valid-rep rates, within-turn rep variance. Judge-interaction:
`score_difference ~ leaks_i + C(condition)` crossed (leaks_i = judge×leakage; C(condition) =
judge×policy), plus a within-judge/base standardized refit and the replicate-level
`[(Conv−Ped)_GPT − (Conv−Ped)_Opus]` (ten values, mean, bootstrap CI, paired signed-rank).
Holm within three declared families (3 policy-adjusted leakage slopes; 3 judge×leakage
interactions; 3 judge×condition interactions); raw and adjusted p reported; a nonsignificant
interaction is **not** read as equivalence. Each family size is **fixed at three**: the
multiplicity denominator is the *declared* number of tests, not the number that happened to
return a p-value. A missing `policy_adjusted.json`, a failed fit, a non-converged fit, or a
non-finite p is a **blocking analysis error** — the comparison is not published. (Otherwise one
available p = .04 beside two failed tests would be reported as Holm-adjusted .04 at m = 1, i.e.
a degraded run manufacturing a significant result.)

**Same-family caveat:** GPT-5.6 Sol judges the GPT-5.5 tutor base in one arm — explicitly
flagged; every base is reported separately and a sensitivity summary restricted to the Sonnet
and Gemini bases is added. The three bases are never pooled into a single causal
model-family claim.

## 10. Interpretation branches (frozen; followed regardless of outcome)

1. Same direction, compatible magnitude → "The finding replicated across Claude Opus 4.8 and
   GPT-5.6 Sol."
2. Same direction, wide interaction CIs / material scale differences → "directionally
   consistent across two specified judges."
3. Material difference or reversal → "The evaluator response was judge-contingent." Report the
   disagreement prominently; do not average it away.
4. Helpfulness agrees but pedagogy does not → restrict robustness language to helpfulness; do
   not claim the dissociation replicated.
5. Pedagogy agrees but helpfulness does not → treat helpfulness judge sensitivity as the
   central result.

Under every branch retain: the human-validation limitation; judge-rated vs actual
helpfulness; the deterministic status of leakage/independence; the observational limitation
of turn-level leakage; the GPT-judge/GPT-tutor same-family sensitivity.

## 11. Live-run status (2026-07-19)

`OPENAI_API_KEY` is **not set** in this environment and the live-run budget has not been
authorized, so no paid call has been made. Everything that can be completed offline is
complete: the runner, comparator, config, amendment, and both test suites are implemented and
pass; input manifests, protected-primary hashes, and expected call counts are generated for
all three bases; the mock/offline pipeline reproduces the exact 358/379/442 unit counts and
the deterministic legs match Opus exactly. The live commands are in §7.
