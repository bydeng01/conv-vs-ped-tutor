# Cross-judge transport amendment — GPT-5.6 Sol served via OpenRouter (2026-07-20)

**Status: transport amendment, prospectively specified. Live run COMPLETED 2026-07-20
(7,074 ratings, all three bases promoted). TRANSPORT ONLY.** This document amends the
**transport provisions** of `cross-judge-amendment-2026-07-19.md` and supersedes them. It
changes *how the second-judge requests reach GPT-5.6 Sol* and *nothing else*: not the rubrics,
prompts, parser, units, repetitions, aggregation, analyses, interpretation branches, or the
frozen primary judge.

It is frozen together with `analysis/run_cross_judge_audit.py`,
`configs/models.judge-gpt56.yaml`, and `tools/test_cross_judge_audit.py` under a **new** tag,
`judge-robustness-openrouter-freeze`. The previous tag `judge-robustness-gpt56-freeze` remains
in history as the record of the superseded route.

---

## 1. What is superseded, and where

Two provisions of `cross-judge-amendment-2026-07-19.md` explicitly forbade the route this
amendment now adopts. They are superseded, not deleted. The `.md` originals carry the full
inline `[SUPERSEDED 2026-07-20 → this document]` marker; the `.yaml` header was rewritten in
place instead, carrying a bare `[SUPERSEDED 2026-07-20]` on the provider line and no marker on
the no-substitution sentence:

| File | Line | Superseded text |
|---|---|---|
| `cross-judge-amendment-2026-07-19.md` | 74 | `| provider | `openai` (OpenAI directly — **not** OpenRouter or any intermediary) |` |
| `cross-judge-amendment-2026-07-19.md` | 89 | `GPT-5.5, GPT-5.6 Terra, the `gpt-5.6` alias, or an OpenRouter route.` |
| `configs/models.judge-gpt56.yaml` | 21, 55 | the `provider openai (OpenAI directly -- NOT OpenRouter or any intermediary)` header line and the matching no-substitution sentence |

The **prohibition those lines encoded remains in force in its general form**: the runner still
refuses every provider and endpoint except one allow-listed pair, and the pair must agree with
itself. What changed is *which* pair is allow-listed. Changing it again requires another
amendment; it is not reachable by editing a config.

---

## 2. Why the transport changed

Two faults on the OpenAI-direct route, both encountered during the live run of 2026-07-19/20.
**Evidentiary status is stated per item below and is not uniform — see §6.**

### 2.1 Intermittent provider-side auth failure

Byte-identical scoring requests intermittently returned `401 "insufficient permissions"` on a
key that was otherwise working. The runner classifies 401 as FATAL with no retry (correctly —
retrying a bad credential burns the ceiling), so each occurrence killed the batch.

**Artifact-backed:** `results/judge_robustness/gpt-5.6-sol/sonnet/spend_ledger.json` records
**6 HTTP attempts** across three invocations (pids 94090/96787/98560, 00:32:42Z–00:36:12Z) that
produced **3 completed ratings** (three `chatcmpl-*` ids, one unit × 3 reps). Both files were
archived to `sonnet/openai-direct.superseded/` before the OpenRouter batch; that directory and
`preflight.openai-direct.superseded/` are the surviving record of the abandoned route. That is **3 failures in 6 attempts — 50% — on real
~925-token rubric prompts**, not the 10–30% figure quoted informally. The ledger records no
status codes, so *the ledger alone does not attribute those 3 failures to 401 specifically*;
the 401 attribution is operator-reported (§6).

**Not artifact-backed:** the `openai-processing-ms` split (177–306 ms on failures vs
546–2083 ms on successes, claimed as non-overlapping edge rejection) and the
`GET /v1/models/gpt-5.6-sol → 200` control. No capture exists for either.

At the artifact-backed 50% rate, the 7,074 planned ratings would need ≈14,148 attempts against
a **7,783** authorized ceiling (2,363 + 2,502 + 2,918 across the three bases, at
`DEFAULT_RETRY_ALLOWANCE = 0.10`). Even at the informally-reported 30% the requirement exceeds
the authorization. The route is arithmetically unusable either way — which is the load-bearing
conclusion, and it holds under every rate on the table.

### 2.2 Daily token cap below the batch size

The account's tokens-per-day cap is reported as **1,350,000**, against a batch of ≈7.4M input
tokens; every base individually exceeds the daily cap. OpenRouter applies no TPD cap to paid
models. **Operator-reported, not artifact-backed** (§6): no capture records the cap value.

The batch-size side *is* re-derivable offline: 358 + 379 + 442 = 1,179 units × 2 rubrics ×
3 reps = **7,074 planned ratings**, and the frozen preflight records real prompt sizes
(628 and 864 tokens for the two instruments; 925 on the scored unit).

---

## 3. The frozen transport

```yaml
provider: openrouter
providers:
  openrouter:
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
roles:
  judge:
    provider: openrouter
    model: openai/gpt-5.6-sol   # the ROUTER slug; response.model returns it verbatim
    temperature: null           # OMITTED from the request (unchanged)
    max_tokens: 2048            # sent as max_completion_tokens (unchanged)
    reasoning_effort: medium    # unchanged
```

**Routing pin**, sent as `extra_body` on every request — scoring, transport retry, and
preflight alike:

```json
{"provider": {"order": ["openai"], "allow_fallbacks": false}}
```

- `order` takes the endpoint's **`tag`** (`openai`, `openai/flex`, `openai/priority`, `azure`,
  `azure/eu`), not `provider_name`. Plain `openai` is frozen; `flex`/`priority` are service
  tiers with different latency and capacity behaviour.
- `allow_fallbacks: false` because OpenRouter's default is *automatic failover to alternative
  providers when errors occur* — under the default, a transient upstream error would silently
  move ratings to another backend mid-batch.
- **`require_parameters` is deliberately NOT sent.** It filters endpoints by OpenRouter's
  *normalized* parameter names, which do not include `max_completion_tokens` (the endpoint
  advertises `max_tokens`), so including it 404s the route with "No endpoints found".

The entire `extra_body` value — including `order` — is folded into
`_request_contract_sha256`, so a routing change between the sonnet run and the gemini run
cannot happen silently: it changes the contract hash, and `_load_resolved` then rejects the
preflight as STALE. It is also part of the per-instrument cache stamp, so ratings collected
under different routing can never pool in one cache.

---

## 4. Provenance: what is recorded, what is gained, what is weakened

### 4.1 The rule the implementation now enforces

Provider identity is **derived from the configuration actually used**, never a literal. Before
this amendment `_instrument_stamp` wrote `"provider": "openai"` as a hardcoded string and
`_request_contract_sha256` folded the same literal into the contract hash. Those two literals
made the cheap version of this migration — keep the provider key named `openai`, swap only
`base_url` — **stamp and hash every rating as OpenAI-direct while actually calling
openrouter.ai**. That is false provenance in a research artifact and was rejected outright.

Two consequences worth stating plainly, because they mean a control that *looked* live was not:

- `"provider"` is in `_STAMP_CONTENT_FIELDS`, which `_load_cache_reconstruction` uses to prove
  a released cache was produced under this configuration. While both sides were the same
  literal the comparison was **tautological**: a cache produced against a different provider
  reconstructed as matching. It is now a real comparison.
- The contract hash could not move when the provider did, so a preflight resolved against one
  provider would have authorized a paid batch against another under an identical sha —
  defeating the STALE PREFLIGHT gate. It now moves.

`load_judge_cfg` allow-lists exactly one provider/endpoint pair and refuses a provider name
that disagrees with its own endpoint, **in both directions**. Two regression tests pin the
falsification trap specifically.

### 4.2 What is GAINED

Every response body carries a top-level **`provider`** field naming the upstream that served
it. This is recorded **per rating** — in the cache entry, the wire record, and
`provenance.json` — and:

- checked on **every fresh scored call** against the upstream frozen at preflight; drift *or
  absence* aborts the batch;
- aggregated from the **cache-hit path too**, so the claim covers reused ratings, not only the
  ones an invocation re-paid for;
- asserted at **completeness**: a promoted base must have one identified upstream for every
  rating. Mixed, rotated, or unattested sets set `complete = false` and are unpublishable.

The preflight refuses to freeze a contract whose responses carry no attestation, and
`score_base` refuses to spend when the preflight froze none — so the per-call check cannot be
silently vacuous.

**This is strictly more than the superseded route had.** The frozen OpenAI-direct
`resolved_config.json` records `system_fingerprint: null` and
**`fingerprint_drift_detectable: false`**. The backend-drift control was *already inert* on
OpenAI direct. Nothing that worked was given up.

### 4.3 What is WEAKENED — stated plainly

**`returned_model` now attests to the router's label, not to an upstream deployment.**
OpenRouter returns `response.model` as the router slug `openai/gpt-5.6-sol`. The runner still
freezes it at preflight and re-checks it on every call, and drift still aborts — but through a
router that check proves the *router* kept calling the same thing, not that the same upstream
deployment produced the tokens. The per-rating `provider` attestation (§4.2) is what carries
the upstream claim now.

**The residual caveat is the intermediary itself.** One additional hop sits between this code
and the model, and could in principle misroute. It is mitigated by the pin — which §6.1 shows
is *enforced*, not advisory: pinning a different upstream lands on that upstream, and disabling
fallbacks is what blocks substitution — by the per-rating attestation, and by the completeness
assertion. Mitigated, not eliminated. A reader who does not trust the intermediary should
discount the second-judge audit accordingly; that is a legitimate position and the paper says
so (§7).

**Not verified: the dated snapshot.** The live preflight returns `response.model` as the bare
router slug `openai/gpt-5.6-sol`, so the claim that the route resolves to
`openai/gpt-5.6-sol-20260709` has no support from any artifact (§6.3). The config header that
asserted it has been struck; the claim is withdrawn and must not enter the paper.

**Not verified: the effort setting.** `reasoning_effort: medium` is sent and reasoning tokens
are produced *in aggregate* (mean 33.8 across the batch), but no captured test shows the *level*
being modulated (§6.3). State the aggregate carefully: the **median rating produced ZERO
reasoning tokens** — 68.0% of ratings return 0, and the mean is carried by the 32% that do not
(mean 105.5 among those). Reasoning is also strongly instrument-dependent: ~90% of *helpfulness*
ratings show none at all, against 45.7% of *pedagogy* ratings (instrument means 8.5 vs 59.1).
"Reasoning is happening" is true of the batch and false of the typical rating, and must not be
written the second way. Every rating ran under identical settings, so nothing internal to the
comparison is at risk; the paper should say the setting was requested, not that it was
confirmed.

---

## 5. Error taxonomy (re-checked for this provider)

| Shape | Class | Why |
|---|---|---|
| `404 "No endpoints found"` | **fatal** | An unroutable pin fails on *every* call; retrying burns the ceiling on a route that can never work. Listed explicitly so a later edit cannot make it retryable. |
| `401 "Missing Authentication header"` | **transient** | Observed on a burst of unpaced requests; the same key authenticates before and after. Under the old taxonomy every 401 was fatal, so an edge-side throttle would kill a whole batch. |
| every other 401 / auth failure | **fatal** | Unchanged. The carve-out is a single exact substring and is tested against near-misses. |
| per-minute rate limit, timeout, 5xx | **transient** | Unchanged. |
| per-day cap / exhausted quota | **fatal** | Unchanged. |

---

## 6. Evidentiary status — read before citing any number

The original `verify_openrouter*.py` probes printed to stdout and were never saved, so for a
time every OpenRouter-side figure in this document existed only as prose. That gap is now
closed for the routing claims: `tools/verify_openrouter_routing.py` re-ran them and **writes
its own transcript** to `preflight/routing_verification.json` + `.log`. What remains
uncaptured is labelled as such below rather than laundered.

### 6.1 Captured 2026-07-20 (`preflight/routing_verification.json`)

| Verdict | Result |
|---|---|
| `order_selects_provider` | **PASS.** `order:["azure"]` served by **Azure**; `order:["openai"]` served by **OpenAI**. Routing FOLLOWS `order`. |
| `frozen_pin_stable` | **PASS.** 3/3 consecutive calls under the frozen pin served by `OpenAI`. |
| `bogus_tag_refused` | **PASS.** 404 `No endpoints found for openai/gpt-5.6-sol`. |
| `allow_fallbacks_is_load_bearing` | **PASS.** The same bogus tag with `allow_fallbacks: true` **succeeds** (served by `OpenAI`), so `allow_fallbacks: false` is what blocks the substitution. |
| `reasoning_effort_honored` | **FAIL — see §6.3.** |

`order_selects_provider` is the load-bearing one. A refused bogus tag cannot distinguish an
ENFORCED pin from one accepted and ignored while OpenAI happens to be the default route;
observing that a *different* pin lands on a *different* upstream can. The pin is enforced.

**A caveat previously recorded here was wrong and is withdrawn.** An earlier note claimed a
valid-but-miscased `order:["OpenAI"]` returned the same 404 as a bogus tag, and concluded that
a 404 shows only "tag unrecognized". The captured probe shows `order:["OpenAI"]` is **served
normally** — OpenRouter matches the tag case-insensitively. The negative control is therefore
cleaner than the earlier text allowed.

### 6.2 Established by the completed batch (7,074 ratings, 2026-07-20)

| Claim | Source |
|---|---|
| 0 transport failures, 0 transport retries, 0 parse retries in 7,074 ratings | the three `completeness.json` + wire logs |
| every rating served by `OpenAI`; 0 unattested, 0 spanning, 0 disagreeing | `completeness.json → served_provider_attestation` (all three bases) |
| 1 HTTP attempt per rating on gpt and gemini (2,274 / 2,652 exactly) | per-base `spend_ledger.json` |
| **actual cost 7,590,023 prompt + 445,536 completion tokens = $51.32 at $5/$30** | the three bases' wire logs, summed (EXCLUDES preflight on both routes) |
| `reasoning_tokens` mean **33.8** over 7,074 real calls (not 0, not 57.8) | wire logs |
| completion mean **63.0** (the pre-run estimate assumed 87.1) | wire logs |
| 0 failures here vs 3-in-6 on OpenAI direct | this batch vs `sonnet/openai-direct.superseded/` |

The contrast in that last row is the whole justification for the amendment, and both halves are
now artifact-backed.

### 6.3 Still not established

- **`reasoning_effort` through the route.** The captured probe returned `minimal` → 166
  reasoning tokens and `high` → 126, i.e. backwards. That is **n = 1 per level** on a
  stochastic quantity, so it is INCONCLUSIVE, not evidence the parameter is ignored. Reasoning
  occurs across the batch (mean 33.8) but **not on the typical rating**: the median is 0, 68.0%
  of the 7,074 ratings return zero reasoning tokens, and the aggregate is carried by the
  remaining 32% (mean 105.5, max 501). By instrument the split is sharp — ~90% zeros on
  helpfulness against 45.7% on pedagogy. An earlier version of this bullet read "reasoning is
  definitely happening", which is aggregate-true and per-rating false; corrected 2026-07-20.
  What is unproven is that the *level* is modulated. The frozen config specifies `medium`.
  **This does not threaten the audit:** all
  7,074 ratings ran under identical settings — `reasoning_effort: medium`,
  `max_completion_tokens: 2048`, `backend: live`, `finish_reason: stop`, with the setting folded
  into `request_contract_sha256` so it could not have drifted mid-batch without tripping the
  stale-preflight gate. Whatever effort the upstream actually applied was applied as a CONSTANT
  to both conditions and all three bases; an unverified constant can shift a level, it cannot
  manufacture a condition contrast, which is what this audit reports. It is
  a spec-compliance gap, and the paper must say the effort setting was requested but not
  verified unless a multi-sample re-probe closes it.
  **Decision (2026-07-20): no re-probe.** Closing this would cost ~30 provider calls; it was
  declined as spend that cannot change any reported result. The gap ships disclosed. Note for
  anyone who revisits it: a re-probe must use `max_completion_tokens: 2048`, not the existing
  probe's 256 — 30 of the 7,074 medium-effort draws exceeded 256 reasoning tokens (max 501), so
  a 256-cap can right-censor the high arm and reproduce the backwards result as an artifact of
  the probe's own budget. It must also sample `medium`, the level actually frozen, which the
  original two-level probe never did.
- **Dated snapshot `openai/gpt-5.6-sol-20260709`.** Uncaptured, and the live preflight shows
  `response.model` returns the bare router slug `openai/gpt-5.6-sol`. It IS asserted as "a
  STRONGER identity" in an earlier version of `configs/models.judge-gpt56.yaml`'s header --
  a file inside this freeze. That line has been STRUCK (see the config header); the claim is
  withdrawn and must not enter the paper.
- **`openai-processing-ms` 177–306 vs 546–2083** and the **1,350,000 TPD cap**: operator-
  reported, uncaptured. The TPD figure is not load-bearing — §2.2's conclusion follows from the
  offline-derivable batch size against any cap near that magnitude.
- **401 as the specific cause** of the 3 OpenAI-direct failures: the ledger records no status
  codes. The failure *count* is artifact-backed; the status code is not.
- The pre-run **"$57–65 measured cost"** was an extrapolation, not a measurement, and was high;
  a mid-run revision to $36–45 was low. Cite $51.32 (§6.2).

---

## 7. Spend ledger across the transport change

`spend_ledger.json` is keyed by **base directory**, not by provider, so the 6 attempts made
against OpenAI direct persist into the new regime. Rows now carry a `provider` label alongside
the existing `backend` label, and a run excludes rows explicitly labeled with a *different*
provider — the same rule, one level down, that keeps a mock rehearsal from consuming the paid
allowance.

**Decision, deliberate:** the 3 existing unlabeled rows (6 HTTP attempts) **still count**
against the OpenRouter allowance. Unlabeled rows count for every regime because over-stating
prior spend is the safe direction; the cost is 6 attempts out of thousands; and it means
**nobody has to hand-edit a record of real paid spend** to proceed. The rows also remain in
place as the evidence `_live_spend_evidence` exists to find — a deleted ledger beside paid
spend is exactly what that gate catches. The ledger was **not** archived and **not** rewritten.

---

## 8. Consequences for existing artifacts

- **The 3 paid ratings will be discarded and must be re-paid.** `_instrument_stamp` binds the
  provider, endpoint, routing, and requested model; all four changed, so `_load_cache` returns
  `{}` on the stamp mismatch — silently, by design. Cost: 3 ratings.
- **A new live preflight is mandatory.** The contract hash changed, so `_load_resolved` rejects
  the existing `resolved_config.json` as STALE PREFLIGHT. The new preflight must additionally
  freeze `served_provider`; `score_base` refuses to spend without it.
- **`PLAN_FREEZE_TAG` is now `judge-robustness-openrouter-freeze`.** `assert_live_freeze_state`
  requires `HEAD == tag` and a clean tracked tree.
- **Leftover live artifacts were resolved before the batch (done 2026-07-20).** The abandoned
  run had left a live-stamped cache, a live wire log, a `run_state.json` in state `scoring`,
  and a stale `tmp.lock.run` (pid 98560, dead) under `sonnet/`; eight artifacts tripped the
  packaging gate. They were ARCHIVED, not deleted, to
  `sonnet/openai-direct.superseded/` and `preflight.openai-direct.superseded/`. This mattered
  because `_write_wire` appends: left in place, the OpenAI-direct records would have been
  interleaved with OpenRouter records in one log.
- **Never point `--judge-backend mock` at a canonical `--out` directory.** `_write_wire` opens
  append-mode; mock records appended into a live wire log would block the release gate
  permanently. Rehearse only in a scratch directory.

---

## 9. What is unchanged

Same rubrics (byte-identical, imported not copied), same system and user prompts, same frozen
parsers, same aggregation, same 1,179 units, same 2 instruments, same 3 repetitions, same seed
policy, same `reasoning_effort: medium`, same omitted `temperature`, same
`max_completion_tokens: 2048`, same frozen transcripts and their freeze tags, same analyses,
same pre-committed interpretation branches. **Claude Opus 4.8 remains the frozen PRIMARY
judge**; GPT-5.6 Sol remains an additive robustness judge over already-collected transcripts.
