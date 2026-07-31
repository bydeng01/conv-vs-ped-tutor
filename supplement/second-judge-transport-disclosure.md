# Second-judge transport — manuscript disclosure (draft, 2026-07-20)

Draft text for the methods and limitations sections, covering the second-judge robustness
audit's transport. Companion to `cross-judge-amendment-openrouter-2026-07-20.md`.

**Claim discipline applies** (see the AAAI-27 framing decision): state what held without
understating it, and state what weakened without softening it. Both directions are accuracy
failures.

---

## A. Methods — one paragraph, at the point the second judge is introduced

> The second-judge robustness audit was served through OpenRouter rather than by calling the
> model provider directly. We moved to an intermediary after the direct route proved unusable
> for a batch of this size: byte-identical scoring requests failed intermittently — the spend
> ledger records six attempts against the three ratings the superseded wire log preserves, so
> three failures in six — and the account's daily token allowance was below the
> token requirement of even a single one of the three corpora. Routing was pinned to the
> intended upstream with provider fallback disabled, sent on every request including transport
> retries. We verified that the pin is enforced rather than advisory: pinning a different
> upstream routes to that upstream, an unrecognised upstream is refused outright, and the same
> unrecognised upstream succeeds once fallback is re-enabled, which isolates the fallback
> setting as the mechanism. The pin is also folded into the request-contract hash, so routing
> cannot change between corpora without invalidating the frozen preflight. Every rating records
> the upstream that served it, taken from the response body; the runner verifies this against
> the upstream frozen at preflight on every call, and a corpus is not publishable unless all of
> its ratings agree on it. Across 7,074 ratings the recorded upstream was the intended one in
> every case, with no transport retries and no failed requests. The primary judge (Claude Opus
> 4.8), the rubrics, prompts, parsers, units, and repetition count are unchanged.

## B. Limitations — one paragraph

> Because the second judge was reached through an intermediary, the served-model string returned
> by the API is the router's label for the model rather than an attestation from the upstream
> deployment that produced the tokens. We compensate by recording, for every individual rating,
> the upstream identity reported in the response body, and by refusing to publish a corpus whose
> ratings do not agree on it; the routing pin is enforced rather than advisory. The residual
> limitation is the intermediary itself — one additional hop that could in principle misroute —
> which the pin and the per-rating attestation mitigate but do not eliminate. We note that the
> direct route offered no stronger guarantee at this level: the provider returned no
> `system_fingerprint` on any call, so the backend-drift control available in principle was
> already inert there, and no working control was given up in the move. Readers who decline to
> extend trust to the intermediary should discount the second-judge audit accordingly; it is a
> robustness check on the primary analysis, not a component of it.

---

## C. Claims that must NOT appear

Two items remain unevidenced. Neither affects the internal validity of the comparison, and both
must stay out of the manuscript unless a captured test closes them.

**The served model is not a dated snapshot.** The live preflight returns the router's slug for
the model, not a dated build identifier. An earlier working note claimed the route resolves to a
dated snapshot and treated that as a provenance improvement over the direct route; no artifact
supports it. Say nothing about snapshot dating.

**The reasoning-effort setting was requested, not confirmed.** The configuration specifies a
medium effort level and the model does emit reasoning tokens (mean 33.8 per rating across the
batch), but a captured probe comparing a minimal and a high setting returned counts in the wrong
order on a single draw each — too few samples to show anything either way. Every rating ran
under identical settings, so the comparison between judges is unaffected; the manuscript should
say the setting was requested and not claim it was verified.

**On the direct route's failure rate**, cite the ledger figure (three failures in six attempts)
or say "intermittent". The ledger records no status codes, so do not attribute those failures to
a specific error. Do not quote the 10–30% range from working notes.

**On the daily cap**, say it fell below the requirement of a single corpus — which follows from
the corpus size. Do not quote the 1.35M/day figure: it appears only in the config header as an
uncaptured working note, with no measurement behind it.

## D. Numbers that are safe to cite

| Figure | Source |
|---|---|
| 1,179 units x 2 instruments x 3 reps = 7,074 ratings | input manifests, re-derivable offline |
| 7,074 of 7,074 ratings valid; 0 transport retries, 0 parse retries, 0 degraded responses | the three `completeness.json` |
| every rating attested to the intended upstream; 0 unattested, 0 mixed | `completeness.json → served_provider_attestation` |
| three failures in six attempts on the direct route | `sonnet/openai-direct.superseded/` + the archived ledger |
| no `system_fingerprint` returned on either route | frozen and current `resolved_config.json` |
| 7,590,023 prompt + 445,536 completion tokens ($51.32 at $5/$30) | the three bases' wire logs; excludes preflight on both routes |
| routing pin verified enforced (positive control, negative control, fallback isolation) | `preflight/routing_verification.json` |

## E. Cross-judge results as they stand

For the results sections, not the transport disclosure. Pooled over the two corpora that remove
the *robustness* judge's same-family confound (Sonnet and Gemini, n = 800 turns). Note this
removes only one of two overlaps: the Sonnet corpus still carries the *primary* judge's own
same-family overlap (Claude Opus judging a Claude Sonnet tutor base), which no reweighting
removes.

- **Helpfulness**: Spearman 0.484, quadratic-weighted kappa 0.338, mean signed difference
  +0.103. Both judges sit near the ceiling — Opus assigns a median of 5 to 695 of 800 turns,
  the second judge to 756 — so the 0.90 exact agreement reflects that ceiling rather than
  concordance.
- **Pedagogy**: Spearman 0.641, kappa 0.600, mean signed difference +0.562. The second judge is
  systematically more lenient (4.72 vs 4.16) and uses less of the scale.
- **The ConvTutor–PedTutor pedagogy gap holds in direction and is ATTENUATED in size.**
  PedTutor scores higher than ConvTutor on pedagogy under both judges, so the gap is negative
  throughout: Sonnet −1.72 (Opus) vs −1.24 (second judge), GPT corpus −2.36 vs −2.02, Gemini
  −0.18 vs −0.02. The per-replicate difference-of-differences is therefore positive — +0.480 on
  Sonnet (95% CI [0.270, 0.679], signed-rank p = .006) and +0.347 on the GPT corpus (CI [0.140,
  0.547], p = .049), both excluding zero; +0.165 on Gemini with a CI spanning zero (p = .32).
  The second judge **shrinks** the effect, it does not reverse it — consistent with its leniency
  and compressed scale use noted above. Do not describe this as the second judge seeing a larger
  gap.
- **Judge x condition interaction on helpfulness** is significant on Sonnet and the GPT corpus
  after Holm adjustment within its declared family, and not on Gemini; the policy-adjusted
  leak-to-helpfulness slopes are non-significant on all three.

Wording constraints the comparison module enforces, and which the manuscript must respect: two
judges support "replicated across Opus and GPT-5.6 Sol" or "judge-contingent", never
"judge-independent" or "generalises across LLM judges"; a non-significant interaction is not
equivalence; and the two judges are never averaged into a consensus score.
