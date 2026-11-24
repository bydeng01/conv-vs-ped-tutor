# Tutor ablations

Five variants test which parts of the tutor policy affect answer disclosure and student independence. The June 30 plan specified the variants before their runs. Each was paired by replicate with its original Sonnet baseline. [Study decisions](../decisions-log.md) · [Ablation estimates](../results/ablation/ablation_analysis.json)

## ConvTutor prompts

Both variants use the same conversational tutor and make one call per turn. Each changes only the system prompt.

### Socratic questioning

[Prompt configuration](../configs/conv_socratic.yaml)

```text
You are a math tutor helping a student. Teach using the Socratic method: rather
than telling the student what to do, ask guiding questions that lead them to work
out each step on their own. Respond to what the student has actually said, build on
their reasoning, and keep the student doing the thinking.
```

### Withholding the final answer

[Prompt configuration](../configs/conv_no_final_answer.yaml)

```text
You are a math tutor helping a student. Be helpful and clear, but do not give away
the final answer — guide the student to reach it themselves. Explain the ideas and
the next step to try, and let the student carry out the final reasoning and the
arithmetic on their own.
```

## PedTutor node removals

All three variants use the original [PedTutor prompts](prompts.md). When a responder is removed, its route goes to the decomposer. The `branch` field records the route selected from the dialogue, and the call's `node` field identifies the responder that produced the reply. [Ablation implementation](../agents/ped_ablations.py)

| Variant | Removed node | Effect on the tutor | Model calls per visible turn |
|---|---|---|---:|
| [No gate](../configs/ped_no_gate.yaml) | `deferral_gate` | The decomposer handles answer requests. | 2 |
| [No cascade](../configs/ped_no_cascade.yaml) | `hint_cascade` | The decomposer handles turns that would receive a graduated hint. | 2 |
| [No tracker](../configs/ped_no_tracker.yaml) | `state_tracker` | The router sends each turn directly to its responder, which receives an empty assessment and a false progress flag. | 1 |

Removing the tracker also removes one model call per turn, so this comparison changes both planning and compute. The ablation analysis reports descriptive paired differences and estimates the association between answer disclosure and next-turn independence separately for each policy.
