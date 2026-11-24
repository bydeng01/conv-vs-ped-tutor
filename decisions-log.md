# Study design decisions

The entries below identify changes that affect interpretation or replication. The dated source links preserve the wording and timing of each decision.

| Decision | Rationale and source |
|---|---|
| **June 15–16 · Algebra problems and reference answers** | In calibration, the simulated student could often set up linear relationship problems but made arithmetic errors. The authors chose mixture problems to test equation setup. A second reviewer checked the earlier problem set and the final leakage strings. The authors replaced a familiar transfer example with an octane blend and checked all 19 reference answers symbolically. [Problem review][review] · [Domain revision][domain] · [Final leakage review][matcher] |
| **June 15 · Primary outcome** | When worked examples remained in context, the simulated student reached 100% on delayed and transfer probes in calibration. The authors made accuracy secondary and selected answer disclosure, judged helpfulness, and student reasoning as the primary measures before confirmatory collection. [Outcome amendment][outcomes] |
| **June 18–19 · Student and cold baseline** | The authors used Llama-3.1-8B served by Groq through OpenRouter for all three tutor bases. Its accuracy on isolated probes was about 11%. In continuous sessions the student's earlier attempts remained in context, so the authors used fresh-context problems to measure baseline ability. The calibration runs did not establish the effect of provider quantization. [Provider comparison][student] · [Cold-baseline decision][cold] |
| **June 19 · Answer phase** | ConvTutor often added encouragement after the student had given an answer. The authors restricted tutor measures to turns before the first parseable answer. The pilot helpfulness contrast still favored PedTutor after applying the rule. [Metric amendment](metric-amendment-2026-06-19.md) |
| **June 26 · Matched turn budget** | After primary collection and before calculating the truncated contrasts, the authors specified a sensitivity analysis that retained the first *K* visible tutor turns per problem and replicate. *K* was the smaller of the two policy counts. A zero count excluded both sides. [Timing and full rule][budget] · [Sonnet results](results/confirmatory/matched_budget.json) |
| **June 27–28 · Additional tutor bases** | Before collecting either replication, the authors selected each vendor's flagship general-purpose chat model and recorded its exact identifier before measuring leakage. They ran GPT-5.5 with reasoning disabled and Gemini 3.1 Pro preview at its lowest reasoning setting. This difference limits attribution of cross-base effects to model family alone. [Selection rule][selection] · [GPT selection][gpt] · [Gemini selection][gemini] |
| **June 27–30 · Secondary analyses** | The pedagogy rubric was specified after Sonnet collection and before its pedagogy scoring. The five ablation variants were specified before collecting their runs. Both analyses were descriptive. [Rubric decision][pedagogy] · [Ablation plan][ablation] |
| **July 19–20 · Second judge** | With the transcripts and primary ratings already available, the authors specified a robustness analysis using GPT-5.6 Sol. The completed batch used OpenRouter with OpenAI as the sole permitted upstream. [Analysis plan](cross-judge-amendment-2026-07-19.md) · [Transport amendment](cross-judge-amendment-openrouter-2026-07-20.md) |

The preliminary ConvTutor disclosure rates quoted in the paper were 52.5% for Sonnet during calibration, 15/24 (62.5%) for GPT, and 2/24 (8.3%) for Gemini. These readings come from the dated observations. The cross-model diagnostics were advisory. [Sonnet observation][sonnet-read] · [GPT observation][gpt-read] · [Gemini observation][gemini-read]

[Full historical record](https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md)

[review]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L423-L471
[domain]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L473-L544
[matcher]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L648-L666
[outcomes]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L563-L646
[student]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L1235-L1300
[cold]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L1302-L1324
[budget]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L1862-L1933
[selection]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L2379-L2453
[gpt]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L2500-L2542
[gemini]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L2644-L2699
[pedagogy]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L2242-L2345
[ablation]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L2838-L2903
[sonnet-read]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L383-L391
[gpt-read]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L2597-L2605
[gemini-read]: https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/decisions-log.md?plain=1#L2544-L2552
