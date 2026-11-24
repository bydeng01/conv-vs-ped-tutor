# Second-judge analysis plan · July 19, 2026

The authors added GPT-5.6 Sol to ask whether changing the judge changed the ranking of the tutoring policies. They specified the comparison after collecting the transcripts and Claude Opus 4.8 ratings, before obtaining the Sol ratings. Opus was the primary judge. [Full dated specification](https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/cross-judge-amendment-2026-07-19.md)

## Turns and ratings

Sol scored every answer-phase tutor turn that Opus had rated, using the same dialogue prefix, prompts, scoring rubrics, and parsers. Cold sessions contained no tutor turns. The unit of comparison was the same turn rated by both judges.

| Tutor base | ConvTutor turns | PedTutor turns | Total |
|---|---:|---:|---:|
| Sonnet 4.6 | 135 | 223 | 358 |
| GPT-5.5 | 161 | 218 | 379 |
| Gemini 3.1 Pro | 215 | 227 | 442 |
| **All bases** | **511** | **668** | **1,179** |

Each turn received three ratings from Sol for each of two rubrics, helpfulness and pedagogy. Each per-turn score was the mean of three valid overall ratings. Repetitions quantified rating variability. The analysis required a complete set of ratings for each turn before producing results. [Helpfulness rubric](supplement/judge_rubric.md) · [Pedagogy rubric](supplement/judge_pedagogy_rubric.md)

## Planned comparisons

- Within each tutor base, compare policies on helpfulness and pedagogy using ten paired replicates. Report the mean paired contrast, a 95% bootstrap interval, a two-sided Wilcoxon signed-rank test, and Cliff's delta.
- Estimate the association between answer disclosure and judged helpfulness using crossed random intercepts for replicate and problem. Repeat with tutoring policy as a fixed effect. The deterministic indicators of disclosure and subsequent student reasoning are common to both judges.
- Compare judges on matched turns using Spearman correlation of mean scores and quadratic-weighted kappa on median scores, with intervals clustered by conversation. Report score differences, agreement rates, and score distributions. Estimate how the difference between judges varies by disclosure and policy. Apply Holm correction within each of the three declared families of three tests.
- Report both judges separately, including reversals in policy ranking. Report a sensitivity summary excluding the GPT tutor to assess the same-family pairing with the Sol judge. Sonnet retains a same-family pairing with the primary Opus judge.

The study treats rubric scores as judgments of the dialogue and disclosure as an observed tutor behavior. Agreement between two judges cannot establish human validity. [Recorded transport](cross-judge-amendment-openrouter-2026-07-20.md) · [Comparison results](results/judge_robustness/gpt-5.6-sol/comparison/comparison.json)
