# Second-judge transport and provenance

GPT-5.6 Sol scored the frozen confirmatory transcripts through OpenRouter, pinned to the
`openai` upstream with provider fallback disabled. The transport change is recorded in
[`cross-judge-amendment-openrouter-2026-07-20.md`](../cross-judge-amendment-openrouter-2026-07-20.md).
Claude Opus 4.8 remains the primary judge; the Sol scores form a post hoc robustness analysis.

The direct route recorded six attempts for three successful ratings. Its failure status codes
were not captured. The daily token allowance was reported by the operator as below the batch
requirement; the exact cap was not captured. These observations prompted the transport change.

The routing pin is sent on every request, including retries, and included in the request-contract
hash. Captured probes tested a different upstream, an invalid upstream, and fallback behavior.
Each rating records the upstream reported in the response body; completion requires agreement
with the upstream recorded at preflight. All 7,074 completed ratings report OpenAI, with no
transport or parse retries.

## Identity and parameter limits

`response.model` returns the router slug `openai/gpt-5.6-sol`. It does not establish a dated
upstream deployment. The recorded provider field supplies upstream identity as reported by
OpenRouter; neither route returned a `system_fingerprint` for detecting deployment changes.

All ratings requested `reasoning_effort: medium`. Upstream enforcement of the setting was not
established: the captured minimal/high probe used one draw per level. Across the batch, mean
reasoning-token usage was 33.8, the median was zero, and 68.0% of ratings returned zero reasoning
tokens. A common requested setting does not establish that its implementation has no effect on
condition contrasts. These limits qualify the transport evidence; the historical amendment and
recorded outputs are retained unchanged. See the [dated clarification](research-record.md#wording-clarifications-2026-09-19).

## Recorded evidence

| Figure | Source |
|---|---|
| 1,179 units x 2 instruments x 3 reps = 7,074 ratings | input manifests, re-derivable offline |
| 7,074 of 7,074 ratings valid; 0 transport retries, 0 parse retries, 0 degraded responses | the three `completeness.json` |
| every rating attested to the intended upstream; 0 unattested, 0 mixed | `completeness.json → served_provider_attestation` |
| three failures in six attempts on the direct route | `sonnet/openai-direct.superseded/` + the archived ledger |
| no `system_fingerprint` returned on either route | frozen and current `resolved_config.json` |
| 7,590,023 prompt + 445,536 completion tokens ($51.32 at $5/$30) | the three bases' wire logs; excludes preflight on both routes |
| routing pin verified enforced (positive control, negative control, fallback isolation) | `preflight/routing_verification.json` |

## Cross-judge comparison

The following summary uses the Sonnet and Gemini corpora (800 turns), excluding the
GPT-judge/GPT-tutor overlap. The Sonnet corpus retains the primary Opus judge's same-family
overlap. Full outputs are in
[`comparison.json`](../results/judge_robustness/gpt-5.6-sol/comparison/comparison.json).

- **Helpfulness**: Spearman 0.484, quadratic-weighted kappa 0.338, mean signed difference
  +0.103. Both judges sit near the ceiling — Opus assigns a median of 5 to 695 of 800 turns,
  the second judge to 756 — so the 0.90 exact agreement should be read alongside the
  ceiling concentration.
- **Pedagogy**: Spearman 0.641, kappa 0.600, mean signed difference +0.562. The second judge is
  systematically more lenient (4.72 vs 4.16) and uses less of the scale.
- **The pedagogy gap is smaller under Sol.**
  PedTutor scores higher than ConvTutor on pedagogy under both judges, so the gap is negative
  throughout: Sonnet −1.72 (Opus) vs −1.24 (second judge), GPT corpus −2.36 vs −2.02, Gemini
  −0.18 vs −0.02. The per-replicate difference-of-differences is therefore positive — +0.480 on
  Sonnet (95% CI [0.270, 0.679], signed-rank p = .006) and +0.347 on the GPT corpus (CI [0.140,
  0.547], p = .049), both excluding zero; +0.165 on Gemini with a CI spanning zero (p = .32).
- **Judge x condition interaction on helpfulness** is significant on Sonnet and the GPT corpus
  after Holm adjustment within its declared family, and not on Gemini; the policy-adjusted
  leak-to-helpfulness slopes are non-significant on all three.

The comparison describes these two judges. It does not establish human validity or equivalence
from a nonsignificant interaction. Judge scores are reported separately.
