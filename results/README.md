# Results

The three confirmatory datasets contain 90 sessions and 1,179 answer-phase tutor turns. Each tutor model contributed 10 matched replicates across the conversational, scaffolded, and no-tutor conditions. The study analyzed each tutor model separately. The [repository README](../README.md) gives the commands to reproduce the inference from these tables.

| Tutor model | Answer-phase tutor turns | Turn-level observations | Registered tests |
|---|---:|---|---|
| Claude Sonnet 4.6 | 358 | [per_turn.csv](confirmatory/per_turn.csv) | [inference.json](confirmatory/inference.json) |
| GPT-5.5 | 379 | [per_turn.csv](confirmatory_gpt/per_turn.csv) | [inference.json](confirmatory_gpt/inference.json) |
| Gemini 3.1 Pro Preview | 442 | [per_turn.csv](confirmatory_gemini/per_turn.csv) | [inference.json](confirmatory_gemini/inference.json) |

Each row of `per_turn.csv` represents a tutor reply during training before the student's first parsed answer. If the student gave no answer, the window spans the full problem. The table records whether the tutor disclosed the answer, the judge's helpfulness and pedagogy ratings, and whether the student's next turn showed independent work. The no-tutor condition has session and replicate records only.

In each model directory, `per_session.csv` gives accuracy on the immediate, delayed, and transfer probes, process measures, and token and call counts. `per_replicate.csv` contains the condition means used for the paired tests. `helpfulness_detail.json` and `pedagogy_detail.json` preserve the individual ratings behind the turn means.

## Additional analyses

| Analysis | Where to find it |
|---|---|
| Equal numbers of visible tutor turns per problem and replicate, primary Sonnet comparison | [Matched-budget estimates and excluded pairs](confirmatory/matched_budget.json) |
| Two ConvTutor prompt variants and three PedTutor node removals, compared with the original policies | [Ablation estimates](ablation/ablation_analysis.json) and [variant definitions](../supplement/ablation_prompts.md) |
| Post hoc check of the association between disclosure and each outcome after adjustment for tutoring policy | [Effect estimates by tutor model](condition_adjusted_sensitivity/analysis.json) |
| Second judge, GPT-5.6 Sol, scoring the same turns and rubrics as Claude Opus 4.8 | [Paired judge comparisons and same-family sensitivity](judge_robustness/gpt-5.6-sol/comparison/comparison.json) |

The second-judge plan was specified after the primary Opus scores were available and before Sol scored any study turns. Each tutor model has a separate `judge_inference.json` under [judge_robustness/gpt-5.6-sol](judge_robustness/gpt-5.6-sol). The comparison also reports results with the GPT tutor excluded because it shares a model family with Sol. The [transport disclosure](../supplement/second-judge-transport-disclosure.md) documents what the provider records establish about the model that scored the turns.

The public tables support offline inference. Rebuilding them from individual dialogues also requires the transcript and score-cache archive. See the [archive instructions](../artifact/README.md).
