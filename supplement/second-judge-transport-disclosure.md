# Second-judge scoring and provenance

GPT-5.6 Sol produced three helpfulness ratings and three pedagogy ratings per turn. All 7,074 ratings were valid and reported OpenAI as the upstream. The completed batch required no transport or parsing retries. [Routing and model identity](../cross-judge-amendment-openrouter-2026-07-20.md)

| Tutor transcripts | Turns scored | Ratings | Completion record |
|---|---:|---:|---|
| Sonnet | 358 | 2,148 | [Sonnet](../results/judge_robustness/gpt-5.6-sol/sonnet/completeness.json) |
| GPT | 379 | 2,274 | [GPT](../results/judge_robustness/gpt-5.6-sol/gpt/completeness.json) |
| Gemini | 442 | 2,652 | [Gemini](../results/judge_robustness/gpt-5.6-sol/gemini/completeness.json) |

Each request specified medium reasoning effort. Across the batch, mean reported reasoning-token use was 33.8 tokens per rating, and 68% of ratings reported zero. The available probe used one draw at each of two effort levels, which leaves upstream enforcement uncertain. [Reasoning-token evidence](https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/cross-judge-amendment-openrouter-2026-07-20.md?plain=1#L249-L273)

## Agreement across judges

On the 800 Sonnet and Gemini turns, the judges gave the same median helpfulness rating on 90% of turns. Their scores clustered at the ceiling. Opus gave a median of 5 on 695 turns and Sol did so on 756. Spearman correlation of the per-turn means was 0.484 and quadratic-weighted kappa on median ratings was 0.338. For pedagogy, the corresponding values were 0.641 and 0.600. The two-base summary excludes the GPT tutor because it shares a model family with Sol. The Sonnet tutor shares a family with Opus. [Complete comparison](../results/judge_robustness/gpt-5.6-sol/comparison/comparison.json)
