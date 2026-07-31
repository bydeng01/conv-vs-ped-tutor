# Technical appendix — details moved out of the main paper in the 2026-07-09 page-limit revision

The 2026-07-09 revision trimmed AnonymousSubmission2027.tex to the AAAI-27 page limit.
Nothing below changes a result; every item is either a value relocated from the main text
(with its provenance) or a disclosure that the 7-page version compresses. Sources are the
frozen `results/` outputs and `decisions-log.md`, both packaged in this artifact; every value
below re-derives from them except where a line says otherwise.

## 1. Pre-run advisory leakage diagnostics (values referenced in the Cross-Model section)

The main text now says the advisory diagnostics "anticipated this leakage ordering (values
in the supplement)." The values, quoted from the project log (decisions-log.md; advisory,
report-but-do-not-tune, and NOT re-derivable from local raw — the
results/leakage_diag_{gpt,gemini}/leakage_diagnostic.json files are absent by design of the
log entry):

- Sonnet 4.6 (calibration): ConvTutor leakage ~52.5%
- GPT-5.5 (pre-run diagnostic): ~62.5% (15/24 turns)
- Gemini 3.1 Pro preview (pre-run diagnostic): ~8.3% (2/24 turns)

Realized confirmatory ConvTutor leakage — .430 / .766 / .113 (results/*/inference.json,
`j1.P1_leakage.conv_mean`) — reproduces the same ordering.

## 2. Matched visible-turn budget: K=0 dropped cells

The truncation rule (K = per-(problem, replicate) pairwise minimum of in-window visible
tutor-turn counts; frozen 2026-06-26 before results were read) drops a (problem, replicate)
cell for BOTH conditions when one side has zero in-window turns. In the confirmatory data
this happened in 5 of 60 cells, all ConvTutor immediate-commit problems (conv 0 in-window
turns, ped 4): replicate 0 × train-4/5/6 and replicate 3 × train-5/6. Full detail:
results/confirmatory/matched_budget.json `k0_dropped_cells`. The rule is condition-blind;
the matched-budget statistics in the paper (n=256; +0.295, p=2.4e-4; -0.355, p=7.5e-8;
ped-leaky cell 6 < adequacy floor 10) already reflect these drops.

## 3. Per-policy coupling power notes (Figure 3 companion)

Per-condition leaky-vs-nonleaky next-turn-independence effects
(results/ablation/ablation_analysis.json `leak_to_next_independence_coupling_per_condition`):

| policy | mean within-replicate effect | usable replicates | leaky turns | signed-rank p |
|---|---|---|---|---|
| conv | -0.181 | 10 | 52 | .31 |
| conv_no_final_answer | -0.495 | 7 | 32 | .031 |
| conv_socratic | -0.517 | 3 | 4 | .50 |
| ped (full) | -0.626 | 6 | 14 | .031 |
| ped_no_cascade | -0.725 | 5 | 8 | .0625 (floor) |
| ped_no_gate | -0.763 | 7 | 14 | .016 |
| ped_no_tracker | -0.834 | 5 | 5 | .0625 (floor) |

All seven point estimates negative; bootstrap CI excludes zero in 5/7 (exceptions: conv,
conv_socratic); with five usable replicates the smallest attainable two-sided signed-rank
p is 2/2^5 = .0625.

## 4. Items compressed in the 7-page version (full statements preserved here)

- Table 1's "Observed" column now gives qualitative verdicts only; every underlying
  statistic (means, deltas, exact p-values, CIs) remains in Table 2 and the Results text,
  and re-derives from results/confirmatory{,_gpt,_gemini}/inference.json.
- The next-step sentence formerly closing Limitations: randomized reveals within otherwise
  identical tutoring would make the coupling causal; human raters, and human learners
  assessed outside the carried context, would make rubric validity and durability
  measurable; the released artifact makes wider replication data collection rather than
  redesign.
- Figure 2's caption formerly ended: "A helpfulness-only evaluation would have detected
  none of these differences." The claim stands (it appears in the Introduction) and is
  supported by the 4.70-4.95 helpfulness band vs the 2.58-4.86 pedagogy span.
- The four tutoring-principle citations (Wood/Bruner/Ross 1976; Slamecka & Graf 1978;
  Koedinger & Aleven 2007; Aleven et al. 2006) are now cited once, in Related Work; the
  PedTutor stage-to-principle mapping in the Design section references them there.

## 5. Wording corrections folded into the revision (from the faithfulness review)

A 2026-07-09 faithfulness review checked the manuscript line by line against the frozen
outputs; the trim also fixes the mismatches it found. The no-final-answer variant's caveat
now describes the actual mechanism
(post-solution confirmation turns; window-scoped suppression; in-window judging on
no-commit problems) instead of an "end-of-session wrap-up"; "dated model versions" became
"model identifiers are pinned" (only the GPT pin id carries a date); "several model calls
per visible turn" became "two model calls"; the extensions sentence now distinguishes the
descriptive extensions (pedagogy rubric, ablation) from the cross-model replications,
which rerun the frozen per-base inference; "one-line Socratic instruction" became
"prompt-only Socratic instruction"; and the intro's "the reward for causing it" causal
phrasing was removed.

## 6. Post hoc condition-adjusted leakage sensitivity

The pre-registered J2 models pool ConvTutor and PedTutor answer-phase rows within each
tutor base and remain the primary analysis. Because leakage prevalence differs by tutoring
policy, we additionally fit a **post hoc sensitivity analysis** with condition as a fixed
effect while retaining the same crossed replicate/problem random-intercept structure,
maximum-likelihood fit, and pinned optimizer sequence:

`outcome ~ leaks_i + C(condition)`

The additive output is `results/condition_adjusted_sensitivity/analysis.json`, generated by
`analysis/condition_adjusted_sensitivity.py`; it does not replace or rewrite any
`results/confirmatory*/inference.json` file.

| Tutor base | Adjusted leakage -> helpfulness | Adjusted leakage -> next-turn independence |
|---|---:|---:|
| Sonnet | +0.500 (SE 0.082, 95% CI [0.340, 0.661], p=9.64e-10) | -0.302 (SE 0.067, 95% CI [-0.433, -0.170], p=7.42e-06) |
| GPT | -0.041 (SE 0.070, 95% CI [-0.178, 0.097], p=.564) | -0.295 (SE 0.062, 95% CI [-0.415, -0.174], p=1.67e-06) |
| Gemini | +0.053 (SE 0.042, 95% CI [-0.030, 0.136], p=.208) | -0.604 (SE 0.067, 95% CI [-0.735, -0.472], p=1.99e-19) |

Thus GPT's negative pooled helpfulness coefficient is not robust to policy adjustment.
Leakage retains a negative adjusted association with next-turn independence on all three
bases, while its adjusted helpfulness association is positive on Sonnet and not detectably
different from zero on GPT or Gemini. These are observational associations, not causal
effects of leakage or demonstrated reward-training outcomes.

## 7. Reproducibility details (environment, sampling parameters, seeds, instrument selection)

Added 2026-07-27 alongside the AAAI-27 reproducibility checklist. Nothing here changes a
result; every value is read from `configs/models*.yaml`, `artifact/pinned-environment.json`,
`paper-plan.md` §6, or `decisions-log.md`, all packaged in this artifact.

### 7.1 Computing infrastructure

No model was trained, fine-tuned, or served locally, so the study uses no GPU. Every tutor,
student, and judge call is a request to a hosted provider (Anthropic; OpenAI via OpenRouter;
Google), and the recorded model identifiers in Section 7.2 are the reproducibility anchor for
that layer. Orchestration and all offline analysis ran on one machine, recorded in
`artifact/pinned-environment.json`:

- Apple M3 Pro, 11 cores; 18 GB memory; macOS 14.6.1 (arm64)
- Python 3.12.8
- anthropic 0.109.2, openai 2.41.1, langgraph 1.2.5, PyYAML 6.0.3, numpy 2.4.6,
  scipy 1.17.1, pandas 3.0.3, statsmodels 0.14.6 (`artifact/requirements-pinned.txt`)

The packaged reference tables were generated with SciPy 1.11.4 and statsmodels 0.14.0, whereas
the pinned rerun uses the versions above. `artifact/README.md` §3 records the full delta: Gemini
P1 moves from `.625` to `.623` and stays nonsignificant, mixed-model fixed effects differ by less
than `1e-8`, and no inferential conclusion changes.

### 7.2 Final sampling parameters

Held identical across ConvTutor and PedTutor within every base; only the tutor model changes
across bases.

| Role | Model identifier | temperature | max tokens | other |
|---|---|---|---|---|
| Tutor, primary base | `claude-sonnet-4-6` | 0.4 | 1024 | — |
| Tutor, GPT base | `gpt-5.5-2026-04-23` | 0.4 | 1024 | `reasoning_effort: none` (vendor minimum) |
| Tutor, Gemini base | `models/gemini-3.1-pro-preview` | 0.4 | 1024 | `reasoning_effort: low` (vendor minimum) |
| Student, all bases | `meta-llama/llama-3.1-8b-instruct` | 0.8 | 512 | OpenRouter pinned to Groq: `order: ["Groq"]`, `allow_fallbacks: false` |
| Primary judge | `claude-opus-4-8` | omitted | 512 | 3 ratings per turn per rubric |
| Second judge | `openai/gpt-5.6-sol` | omitted | 2048 | `reasoning_effort: medium`; 3 ratings per turn per rubric |

"Omitted" means the parameter is absent from the request, not sent as null: `claude-opus-4-8`
rejects `temperature` outright, so `agents/model_client.py` drops it and the model's default
sampling applies. The three ratings per turn are therefore genuine stochastic samples, by design
(decisions-log.md, 2026-06-18). GPT-5.x `max_tokens` is sent as `max_completion_tokens`.

Tutor temperature 0.4 (low but nonzero, so replicates vary) and student temperature 0.8 (so the
student behaves like a real learner) were fixed by design before data collection and never
searched: one value each, no sweep, no tuning against any outcome. The only respect in which the
tutor configuration differs across bases is the vendor-minimum reasoning setting, which the paper
declares as a caveat on cross-base comparison.

### 7.3 Seeds and what is reproducible

`experiments/run_confirmatory.py` assigns replicate *r* the seed `base_seed + r`. All three
conditions inside a replicate share that seed and carry `replicate_id = r`, which is the
pre-registered pairing key; run ids are deterministic and seed-namespaced. The seed fixes problem
order, condition order, and the student's initial context.

The seed is forwarded as the `seed` request field to OpenAI-compatible providers (student, GPT
base, Sol judge) and is dropped permanently for any provider that rejects it. The Anthropic
Messages API exposes no seed field, so the Sonnet tutor and the Opus judge run at provider
sampling. Confirmatory *generation* is therefore not bit-reproducible, which the pre-registration
anticipated: the replicate, not the individual call, is the unit of pairing, and residual sampling
stochasticity is within-replicate noise.

Everything downstream of generation is bit-reproducible from the released artifact, and
`artifact/README.md` gives the commands: raw transcripts plus released score caches to metric
tables under `--offline-cache-only` (which fails rather than contacting a provider on a cache
miss), and metric tables to the frozen inference and verdicts. Reusing a cached score reproduces
the released scoring output; it is not a new judge evaluation.

### 7.4 Instrument selection and its criterion

The student model is the one component that was selected rather than fixed a priori. Successive
candidates were screened on *isolated* cold accuracy over the calibration batch in force at the
time (each batch, date, and measurement is in `decisions-log.md`):

| Candidate | Isolated cold | Outcome |
|---|---|---|
| Haiku-tier Claude (the design brief's student) | 100% | rejected: role-plays being stuck yet commits correct answers |
| `openai/gpt-oss-20b` | 100% | rejected: too capable |
| `meta-llama/llama-3.1-8b-instruct`, reference-precision serving (DeepInfra fp8/bf16) | ~89% | rejected: too capable |
| `meta-llama/llama-3.1-8b-instruct`, OpenRouter pinned to Groq | ~11% on the frozen 19 | **accepted** |

The acceptance criterion was fixed in `paper-plan.md` §6 before confirmatory collection: isolated
cold accuracy low, with failures verified in transcripts to be genuine setup failures rather than
arithmetic slips; the domain learnable from tutoring (learnability gate); and a parseable
`FINAL ANSWER:` marker rate of at least 95%. `experiments/preflight.py` re-checked these gates
live and cleared them immediately before the confirmatory run (isolated cold ~11%, marker rate
≥95%, ConvTutor leakage present at ~52% at calibration, student confirmed served by Groq).

The frozen problem set is 19 authored problems: 6 training, 3 immediate, 4 interference, 3
delayed, and 3 transfer (`domain/algebra/problems.yaml`, with per-problem canonical answers and
the declared numeric and solution forms that the leakage matcher keys on).
