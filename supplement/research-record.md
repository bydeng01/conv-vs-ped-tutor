# Research record

The dated plans and decisions below document how the study developed. Their status statements
refer to the date of each entry: the confirmatory runs and Sol robustness scoring have since
completed. The original records remain unchanged.

| Record | Contents |
|---|---|
| [Pre-registration](../paper-plan.md) | Predictions, metrics, analysis plan, and outcome interpretation; amended after calibration and before confirmatory collection. |
| [Metric amendment, 2026-06-19](../metric-amendment-2026-06-19.md) | Answer-phase evaluation window, metric definitions, and inferential units. |
| [Decisions log](../decisions-log.md) | Dated design changes, calibration observations, model pins, collection, and analysis decisions. |
| [Second-judge plan, 2026-07-19](../cross-judge-amendment-2026-07-19.md) | Sol robustness analysis specified after the transcripts and primary scores existed, before Sol scoring. |
| [Transport amendment, 2026-07-20](../cross-judge-amendment-openrouter-2026-07-20.md) | Move from OpenAI direct to OpenRouter, routing checks, and transport evidence. |

The main decisions in the log are:

- **2026-06-15:** student and domain calibration; shift from accuracy to process measures.
- **2026-06-19:** isolated cold baseline and answer-phase metric amendment.
- **2026-06-26:** confirmatory collection, inference, and matched visible-turn-budget rule.
- **2026-06-27–28:** cross-model selection rules, model pins, and pedagogy-rubric extension.
- **2026-06-30:** descriptive ablation plan; results follow on July 3–4.
- **2026-07-20:** completed second-judge scoring through OpenRouter.

## Wording clarifications (2026-09-19)

Some historical comments make stronger claims than the recorded controls establish:

- Judge inputs omit condition labels, internal node names, and canonical answers. This
  establishes label masking; dialogue style may still reveal the tutoring policy. References
  in the frozen judge files to a judge being unable to identify the tutor should be read with
  this distinction.
- Sol requests used the same configured reasoning effort. Upstream enforcement was not
  established. The transport amendment's assertions that this cannot affect a condition
  contrast are not established by identical requested settings. The
  [transport disclosure](second-judge-transport-disclosure.md) states the supported scope.
- The frozen primary config's header mentions `GROQ_API_KEY`, but its student role routes
  through OpenRouter and uses `OPENROUTER_API_KEY`. Its claim attributing the serving
  difference specifically to quantization is not established by the calibration comparison;
  the config itself records Groq's quantization as unknown.
- The returned Sol model slug does not identify a dated deployment. Historical generated
  provenance prose mentioning a dated snapshot should be read against the captured model
  identifiers and the transport amendment's withdrawal of that claim.

Primary judge modules, protected model configs, and frozen rubric files retain their original
bytes because the released protection manifests bind whole files, including comments.
Documentation edits leave those manifests, results, caches, logs, and pre-registration records
unchanged. Current usage is described in the [repository README](../README.md),
[runbook](../experiments/RUN.md), and [artifact instructions](../artifact/README.md).
