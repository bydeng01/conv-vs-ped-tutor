# Research record

The primary plan was amended after calibration and the pilot, before the Sonnet confirmatory run. Sections 12–14 were added later. The dated source files retain the predictions and status statements made at each stage.

| Document | What it establishes |
|---|---|
| [Pre-registration and analysis plan](../paper-plan.md) | The original session-level and turn-level predictions (J1 and J2), outcomes, unit of inference, and criteria for support in sections 4 and 9–11. |
| [June 19 metric amendment](../metric-amendment-2026-06-19.md) | The first parseable answer closes the evaluation window. The amendment defines the boundary for each measure and records the pilot finding that prompted it. |
| [Study design decisions](../decisions-log.md) | Dated evidence for problem and answer review, student selection, calibration, matched turn budgets, and the timing of the cross-model, pedagogy, and ablation studies. |
| [July 19 second-judge plan](../cross-judge-amendment-2026-07-19.md) | A post hoc comparison specified before GPT-5.6 Sol scoring, with transcripts and primary Opus ratings already available. |
| [July 20 transport amendment](../cross-judge-amendment-openrouter-2026-07-20.md) | The route used for all second-judge ratings and the limits on identifying the upstream deployment. |

## Reading the original materials

- The judge saw the dialogue without condition labels, internal node names, or canonical answers. Its wording could still reveal how the tutor was prompted. [Helpfulness rubric](judge_rubric.md) · [Pedagogy rubric](judge_pedagogy_rubric.md)
- The frozen primary configuration contains an early reference to a Groq key. The experiment accessed Groq through OpenRouter using `OPENROUTER_API_KEY`. The record supports a difference in student performance across serving providers. The role played by quantization is unknown. [Model configuration](../configs/models.yaml) · [Calibration record](../decisions-log.md)
- The manuscript measures turn-level reasoning in a simulated learner with the conversation still in context. The June amendment proposed a separate study of agreement with human annotators. The published tables in this release contain model ratings. [Metric amendment](../metric-amendment-2026-06-19.md) · [Results](../results/README.md)
