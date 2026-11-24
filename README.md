# Rethinking LLM-Judged Helpfulness as a Pedagogy Signal

Can a helpfulness rating distinguish a tutor that gives away the answer from one that helps a student work it out? We tested two tutoring policies on each of three language models. ConvTutor's only tutoring instruction is to be helpful and clear. PedTutor tracks the student's progress, offers increasingly specific hints, and asks the student to supply the final answer. Each pair of tutors used the same underlying model. A third condition gave the student no tutor.

One simulated student worked through algebra word problems. We recorded when a tutor disclosed the answer and whether the student's next turn contained independent work. Claude Opus 4.8 rated the tutor turns for helpfulness and pedagogy without seeing the policy labels. A post hoc analysis used GPT-5.6 Sol to rate the same 1,179 turns. [Paper and authors](https://arxiv.org/abs/2607.28128v2) · [Study plan and amendments](supplement/research-record.md)

## What we found

On the primary tutor model, Claude Sonnet 4.6, Opus gave both policies high helpfulness scores. On a pedagogy rubric added after the Sonnet sessions were collected, every PedTutor replicate scored above every ConvTutor replicate. Scores range from 1 to 5.

| Opus rating on Sonnet | ConvTutor mean | PedTutor mean | Paired Wilcoxon *p* |
| --- | ---: | ---: | ---: |
| Helpfulness | 4.70 | 4.80 | .160 |
| Pedagogy | 2.58 | 4.30 | .002 |

The judges ranked the policies in opposite orders on mean helpfulness for two of the three tutor models. On GPT-5.5, Opus favored PedTutor and Sol favored ConvTutor. This was the only reversal where both differences were significant. Both judges favored PedTutor on pedagogy for Sonnet and GPT-5.5. Neither detected a pedagogy difference on Gemini. [Results and scoring tables](results/README.md)

None of the three tutor models showed the full preregistered policy-level pattern of more disclosure, higher helpfulness, and less independent work under ConvTutor. Across all three tutor models, the simulated student was less likely to show independent work immediately after the tutor revealed an answer. Only on Sonnet did answer-revealing turns also receive significantly higher Opus helpfulness ratings in the preregistered analysis. Whether this pattern extends to human learners remains open.

## Reproduce the results

Use Python 3.11 or 3.12. After setup, the analyses run locally without API keys.

```bash
git clone https://github.com/bydeng01/conv-vs-ped-tutor.git
cd conv-vs-ped-tutor
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python tools/reproduce_inference.py
```

The last command recomputes the three confirmatory analyses from the published tables, compares them with the reference results, and prints the location of the new files under `reproduced/`.

Figure 2 shows the judge comparisons and the seven-policy Sonnet ablation. Regenerate it with the same tables.

```bash
python analysis/figures/fig2_dissociation.py --output-dir reproduced/figures
```

Run `python tools/verify_problems.py` to check all 19 [reference answers](domain/algebra/problems.yaml) symbolically. The [design record](decisions-log.md) documents the review of the problems and answer-matching rules. For the exact tutor prompts and judge instructions, see the [study materials](supplement/prompts.md).

The [archive guide](artifact/README.md) covers reconstruction from raw transcripts and cached ratings for readers who have the full archive. The [experiment runbook](experiments/RUN.md) covers collecting new sessions with provider credentials.

[Citation](CITATION.cff) · [MIT license](LICENSE)
