# Student and tutor calibration

Before freezing the algebra set, we checked whether the simulated student struggled with unfamiliar problems and whether ConvTutor disclosed answers. The calibration uses a separate [problem set](../domain/algebra/calibration.yaml). The confirmatory preflight tests the final student on the [study problems](../domain/algebra/problems.yaml).

From the repository root, set `CEREBRAS_API_KEY` for the tutor and `GROQ_API_KEY` for the student, then run the original [calibration configuration](../configs/models.free.yaml).

```bash
python experiments/calibrate.py --models configs/models.free.yaml
```

Each problem is attempted first without a tutor and then with ConvTutor. The report gives unaided accuracy, the proportion of tutor turns that disclosed an answer, student requests for answers, restatements, and use of the `FINAL ANSWER` marker. The design targets were 20–40% unaided accuracy on test probes and disclosure on at least 20% of tutor turns. The runner prints its run directory and saves `calibration_report.json` and the transcripts there.

To measure unaided accuracy on these same calibration problems with the final Llama student, set `OPENROUTER_API_KEY` and run the student alone.

```bash
python experiments/calibrate.py --models configs/models.yaml --cold-only
```

The published study used a separate preflight threshold of at most 30% correct on the frozen, isolated test probes. The [live run instructions](RUN.md) describe that check.
