# Paired pilot

The pilot checked that the two tutoring policies differed in answer disclosure and student independence. It also estimated session costs and gave a descriptive first comparison of helpfulness ratings. Each replicate used the same seed for a session without tutoring, a ConvTutor session, and a PedTutor session.

Run from the repository root with `ANTHROPIC_API_KEY` for the tutor and judge and `OPENROUTER_API_KEY` for the student. In a fresh clone, these commands collect and score one replicate.

```bash
python experiments/run_pilot.py --replicates 1 --conditions cold,conv,ped
python analysis/compute_metrics.py logs/cold-* logs/conv-* logs/ped-* \
  --out reproduced/pilot --judge-helpfulness
```

If `logs/` already contains other pilot runs, give `compute_metrics.py` the three directories printed by this invocation. The metrics script pairs sessions by seed and requests three helpfulness ratings per eligible tutor turn. It caches completed ratings under `reproduced/pilot/`.

In `per_session.csv`, inspect `leakage_rate`, `independence_ratio`, `helpfulness_mean`, and `total_tokens`. The paired ConvTutor minus PedTutor differences appear in `metrics_summary.json`. The June 19 [metric amendment](../metric-amendment-2026-06-19.md) documents how observations from the original pilot informed the turn window used in the confirmatory analysis. For new confirmatory sessions, follow the [live run instructions](RUN.md).
