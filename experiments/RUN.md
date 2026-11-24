# Collect new tutoring sessions

Use this workflow to collect and score new model responses. To reproduce the published statistics from the released tables, start with the [repository README](../README.md).

Each tutor model was tested in ten replicates. Within a replicate, the student received the same algebra problems and seed in the no-tutor, ConvTutor, and PedTutor conditions. The [preregistration](../paper-plan.md) and [research record](../supplement/research-record.md) document the protocol and model choices.

Run the commands from the root of a fresh, clean clone with the project dependencies installed. Live collection and scoring require provider access and incur charges. The base configurations specify the model IDs and sampling settings used in the paper.

| Tutor | Configuration | Environment variables for collection and scoring |
|---|---|---|
| Claude Sonnet 4.6 | [models.yaml](../configs/models.yaml) | `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY` |
| GPT-5.5 | [models.gpt.yaml](../configs/models.gpt.yaml) | `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY` |
| Gemini 3.1 Pro Preview | [models.gemini.yaml](../configs/models.gemini.yaml) | `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY` |

All three use the same Llama 3.1 8B student served by Groq through OpenRouter, and the same Claude Opus 4.8 judge to score both rubrics. Hosted models, particularly preview endpoints, can change. The GPT and Gemini configurations also differ in their supported reasoning settings, which limits comparisons across tutor models.

## Sonnet

First run preflight. It checks that the student scores at most 30% on isolated test probes, emits the final-answer marker on at least 95% of problems, and is served by Groq. For Sonnet, it also requires at least one ConvTutor turn that discloses an answer. These checks make live model calls. To estimate collection tokens from a [paired pilot](PILOT.md), add `--pilot-results reproduced/pilot`.

```bash
python experiments/preflight.py --backend live
```

Once preflight passes, record the commit for **this collection**. The runner requires a clean working tree at that revision and writes a separate log directory per condition and replicate. Running the same command after an interruption resumes the collection. Add `--status` to inspect progress.

```bash
collection_commit=$(git rev-parse HEAD)
python experiments/run_confirmatory.py --replicates 10 --freeze-commit "$collection_commit"
```

Score the transcripts and compute the paired policy contrasts and turn-level associations. Both rubrics use three judge calls per eligible tutor turn. Outputs go into `reproduced/live/sonnet/`.

```bash
python analysis/compute_metrics.py logs/conf-s0-*-r* \
  --out reproduced/live/sonnet --judge-helpfulness --judge-pedagogy
python analysis/run_inference.py reproduced/live/sonnet --freeze-tag "$collection_commit"
```

## GPT and Gemini

Run the following commands for one tutor at a time. Set `base=gpt` for GPT or `base=gemini` for Gemini. These runs record ConvTutor disclosure as a diagnostic, so a low disclosure rate on a given base is itself an outcome. The student accuracy, marker, and provider checks still determine whether preflight passes.

```bash
base=gpt
collection_commit=$(git rev-parse HEAD)
python experiments/preflight.py --backend live --models "configs/models.$base.yaml" \
  --leakage-advisory --pin-record-ref "decisions-log.md (June 28, 2026, $base tutor selection)" \
  --diagnostic-out "reproduced/live/$base/preflight"
```

After preflight passes, collect, score, and analyze this base in its own directory. `run_inference.py` resolves the revision supplied to `--freeze-tag` and compares it with the revision recorded during collection.

```bash
python experiments/run_confirmatory.py --base "$base" --models "configs/models.$base.yaml" \
  --replicates 10 --freeze-commit "$collection_commit"
python analysis/compute_metrics.py logs/conf-"$base"-s0-*-r* \
  --out "reproduced/live/$base" --judge-helpfulness --judge-pedagogy
python analysis/run_inference.py "reproduced/live/$base" --freeze-tag "$collection_commit"
```

The [results guide](../results/README.md) describes the output tables, the ablation analysis, and the second-judge comparison.
