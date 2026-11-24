# Technical appendix

## 1. Answer disclosure before and during the confirmatory runs

Before the confirmatory runs, the authors recorded how often ConvTutor disclosed an answer. The Sonnet estimate came from calibration and the GPT and Gemini estimates came from pre-run checks. The original diagnostic files are unavailable. The [dated study decisions](../decisions-log.md) give the sources for these observations.

| Tutor model | Pre-run ConvTutor disclosure | Confirmatory ConvTutor disclosure |
|---|---:|---:|
| Sonnet 4.6 | 52.5% | [43.0%](../results/confirmatory/inference.json) |
| GPT-5.5 | 62.5% (15/24 turns) | [76.6%](../results/confirmatory_gpt/inference.json) |
| Gemini 3.1 Pro Preview | 8.3% (2/24 turns) | [11.3%](../results/confirmatory_gemini/inference.json) |

The confirmatory values are mean disclosure rates across replicates (`j1.P1_leakage.conv_mean`).

## 2. Matching the number of visible tutor turns

For each Sonnet training problem and replicate, the analysis kept the first *K* tutor turns in each condition, where *K* is the smaller of the two answer-phase turn counts. Five of 60 pairs had *K* = 0. The student committed before ConvTutor spoke but saw four PedTutor turns on those problems (replicate 0, training problems 4–6, and replicate 3, problems 5–6).

The remaining 256 turns yielded a leakage coefficient of +0.295 for helpfulness (*p* = 2.4 × 10⁻⁴) and −0.355 for next-turn independence (*p* = 7.5 × 10⁻⁸). Only six PedTutor turns disclosed an answer after matching, below the adequacy threshold of ten for a PedTutor-only estimate. [Matched-budget analysis](../results/confirmatory/matched_budget.json)

## 3. Disclosure and next-turn independence by policy

Within each Sonnet replicate, the analysis compared the proportion of independent student turns after replies that disclosed the answer with the proportion after replies that withheld it. Only replicates containing both types of reply contributed to the mean difference for a policy. [Ablation estimates](../results/ablation/ablation_analysis.json)

| Policy | Mean difference (disclosed minus withheld) | Usable replicates | Tutor turns disclosing the answer | Two-sided signed-rank *p* |
|---|---:|---:|---:|---:|
| ConvTutor | −0.181 | 10 | 52 | .31 |
| ConvTutor, no final answer | −0.495 | 7 | 32 | .031 |
| ConvTutor, Socratic prompt | −0.517 | 3 | 4 | .50 |
| PedTutor | −0.626 | 6 | 14 | .031 |
| PedTutor, no hint cascade | −0.725 | 5 | 8 | .0625 |
| PedTutor, no deferral gate | −0.763 | 7 | 14 | .016 |
| PedTutor, no state tracker | −0.834 | 5 | 5 | .0625 |

All seven point estimates were negative. The 95% bootstrap intervals included zero for ConvTutor and its Socratic variant. With five usable replicates, the smallest possible two-sided exact signed-rank *p* is .0625.

## 4. What the outcomes measure

Next-turn independence records whether the simulated student attempted algebra or arithmetic in its next reply. The student retained the session dialogue across the immediate, delayed, and transfer probes. Testing the causal effect of disclosure would require randomizing when the tutor reveals an answer. Establishing durable human learning would require testing human learners outside the original conversation. [Independence rubric](independence_rubric.md) · [Session protocol](../protocol/full_session.py)

## 5. Answer-phase window

A tutor may continue speaking after the student has given an answer, for example to confirm the solution. The analysis includes tutor replies strictly before the first parseable student commitment in each training problem. When the student never commits, it includes all tutor replies. The same rule applies to each policy. [Metric amendment](../metric-amendment-2026-06-19.md)

## 6. Adjustment for tutoring policy

The registered turn-level analysis pooled ConvTutor and PedTutor turns within each tutor model. The post hoc analysis added a fixed effect for tutoring policy to account for differences in disclosure rates. It retained the crossed random intercepts for replicate and problem and the same maximum-likelihood fitting procedure. [Analysis code](../analysis/condition_adjusted_sensitivity.py) · [Recorded estimates](../results/condition_adjusted_sensitivity/analysis.json)

| Tutor model | Disclosure coefficient for helpfulness (SE, 95% CI, *p*) | Disclosure coefficient for next-turn independence (SE, 95% CI, *p*) |
|---|---|---|
| Sonnet | +0.500 (0.082, [0.340, 0.661], 9.64 × 10⁻¹⁰) | −0.302 (0.067, [−0.433, −0.170], 7.42 × 10⁻⁶) |
| GPT | −0.041 (0.070, [−0.178, 0.097], .564) | −0.295 (0.062, [−0.415, −0.174], 1.67 × 10⁻⁶) |
| Gemini | +0.053 (0.042, [−0.030, 0.136], .208) | −0.604 (0.067, [−0.735, −0.472], 1.99 × 10⁻¹⁹) |

After adjustment, disclosure was associated with less independent work on the next student turn for all three tutor models. For helpfulness, only the Sonnet interval excluded zero.

## 7. Model settings and reproducibility

All model calls used hosted services. The offline analysis ran on an Apple M3 Pro (11 cores, 18 GB RAM, macOS 14.6.1). The pinned environment uses Python 3.12.8, SciPy 1.17.1 and statsmodels 0.14.6. The original GPT and Gemini inference files record SciPy 1.11.4 and statsmodels 0.14.0. Package versions and BLAS implementations can affect numerical agreement, especially for mixed-effects models. [Environment](../artifact/pinned-environment.json) · [Comparison procedure](../artifact/README.md)

| Role | Model ID | Temperature | Output token limit | Other settings |
|---|---|---:|---:|---|
| Primary tutor | `claude-sonnet-4-6` | 0.4 | 1024 | |
| GPT tutor | `gpt-5.5-2026-04-23` | 0.4 | 1024 | Reasoning effort `none` |
| Gemini tutor | `models/gemini-3.1-pro-preview` | 0.4 | 1024 | Reasoning effort `low` |
| Student | `meta-llama/llama-3.1-8b-instruct` | 0.8 | 512 | OpenRouter routed to Groq with fallback disabled |
| Primary judge | `claude-opus-4-8` | Provider default | 512 | Three ratings per turn per rubric |
| Second judge | `openai/gpt-5.6-sol` | Provider default | 2048 | Requested `medium` reasoning effort, three ratings per turn per rubric |

The student and Opus judge settings were shared across tutor models. The tutor settings were identical across policies within each model. GPT and Gemini used different provider-specific reasoning settings. Both judges omitted temperature from the request. [Primary configuration](../configs/models.yaml) · [GPT configuration](../configs/models.gpt.yaml) · [Gemini configuration](../configs/models.gemini.yaml) · [Second-judge configuration](../configs/models.judge-gpt56.yaml)

### Paired replicates

All three conditions within replicate *r* used seed `base_seed + r` and the same problem sequence. The experiment runner uses `replicate_id` to pair conditions. Hosted generation varies even with shared inputs. The student and compatible tutor endpoints were sent a seed where supported. The Anthropic calls for the Sonnet tutor and Opus judge were unseeded. The Sol judge used its own repetition seeds. Offline inference reuses the released scores. [Runner](../experiments/run_confirmatory.py) · [Sol scoring record](../results/judge_robustness/gpt-5.6-sol/sonnet/provenance.json)

### Student and problem selection

Calibration sought a student that struggled to set up algebra problems unaided, could use help, and reliably returned a parseable final answer. On an early hard-algebra batch, both a Haiku-tier Claude model and GPT-OSS-20B achieved 100% unaided accuracy. The selected Llama 3.1 8B configuration used Groq through OpenRouter. On the frozen problem set the authors recorded about 11% unaided probe accuracy with a fresh context for each problem. An earlier pilot using the DeepInfra endpoint recorded about 89% unaided probe accuracy in a continuous session. The two measurements differ in both provider and available dialogue history. [DeepInfra pilot record](https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md#L1257-L1268) · [Groq calibration record](../decisions-log.md) · [Study plan](../paper-plan.md)

The final set contains six training, three immediate, four interference, three delayed, and three transfer problems. Each has a canonical answer and accepted forms for detecting disclosure. A second reviewer checked the earlier problem set and the final answer-matching rules. The symbolic checker independently derives all 19 final answers. [Problems and reference answers](../domain/algebra/problems.yaml) · [Answer checker](../tools/verify_problems.py)
