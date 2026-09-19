# Conversational vs. Pedagogical Alignment: A Controlled Tutor-Agent Experiment

[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/bydeng01/conv-vs-ped-tutor/ci.yml?branch=main&label=CI)](https://github.com/bydeng01/conv-vs-ped-tutor/actions/workflows/ci.yml)
[![arXiv](https://img.shields.io/badge/arXiv-2607.28128-b31b1b.svg)](https://arxiv.org/abs/2607.28128)
[![Docker](https://img.shields.io/badge/Docker-supported-2496ED.svg?logo=docker&logoColor=white)](Dockerfile)

Code and data for [*Rethinking LLM-Judged Helpfulness as a Pedagogy Signal: A Pre-Registered
Audit Across Tutor Models*](https://arxiv.org/abs/2607.28128).

Two tutoring agents wrap the **same frozen base model** and differ **only in policy
structure** — `ConvTutor` is a single LangGraph node, `PedTutor` is a multi-node state
machine (state tracker, decomposer, deferral gate, hint cascade). A cold baseline with no
tutoring establishes the floor. The experiment measures whether an LLM helpfulness judge
rewards the answer-leakage that reduces the student's later independent work.

The pre-registration is [`paper-plan.md`](./paper-plan.md); dated amendments and implementation decisions are recorded
in [`decisions-log.md`](./decisions-log.md). The [research record](supplement/research-record.md)
indexes the main decisions and clarifies historical wording.

## Quickstart

Recompute the confirmatory inference for all three tutor bases from the tracked tables,
without an API key:

```bash
pip install -r requirements.txt

python analysis/run_inference.py results/confirmatory \
  --freeze-tag confirmatory-freeze \
  --freeze-commit 1a12b566bb825ff91359fb7c526e24b161ae38d3        # primary base
python analysis/run_inference.py results/confirmatory_gpt \
  --freeze-tag crossmodel-gpt-freeze \
  --freeze-commit 644271b1e6e365a84d679a103beb08f0775e60ef
python analysis/run_inference.py results/confirmatory_gemini \
  --freeze-tag crossmodel-gemini-freeze \
  --freeze-commit 68ee3faf8d1370da15bb7f8ab1a87599389a7eb6
```

The commands supply the recorded freeze commits because the freeze tags are not published.
The commits are also recorded in `metrics_summary.json` (`freeze_heads`) and
`inference.json` (`provenance.freeze_commit`).

Each command prints verdicts and writes `inference.json` in its input directory. To keep the
reference files intact, follow the copy-based workflow in [artifact/README.md](artifact/README.md).

## Repository layout

```
agents/          tutoring policies and model clients
  conv_tutor.py      single-node graph
  ped_tutor.py       multi-node state machine
  ped_ablations.py   node-knockout variants (no tracker / no gate / no cascade)
  cold_baseline.py   no-tutor harness
  model_client.py    mock + live backends (Anthropic, OpenAI-compatible)
  base.py state.py config.py extraction.py logging_utils.py

student/simulator.py    weak student model with a knowledge frontier
domain/algebra/         problems.yaml (+ canonical answers), checker.py, calibration.yaml
protocol/               session.py, full_session.py (train→immediate→interfere→delayed→
                        transfer), leakage.py (the frozen answer-leakage matcher)

configs/         models.yaml (primary roles), models.{gpt,gemini,free}.yaml (tutor bases),
                 models.judge-gpt56.yaml (second judge), {conv,ped}_*.yaml (ablation arms)

experiments/     run_confirmatory.py  the 10×3 runner (--base for cross-model)
                 preflight.py         live go/no-go gates before spending budget
                 run.py               single-condition smoke test
                 calibrate.py run_pilot.py ped_smoke.py learnability_check.py
                 RUN.md               authoritative runbook

analysis/        metrics.py compute_metrics.py     post-hoc metrics from logs
                 judge.py judge_pedagogy.py        the two LLM-judge evaluators
                 inferential.py run_inference.py   J1/J2 (Wilcoxon, Cliff's δ, mixed-effects)
                 matched_budget.py                 compute-fairness control
                 condition_adjusted_sensitivity.py post hoc, additive
                 ablation_analysis.py divergence.py compare_judges.py
                 run_cross_judge_audit.py          second-judge robustness audit
                 figures/                          figure generators + their test

tools/           test_*.py            the test suite (standalone scripts — see Tests and CI)
                 verify_problems.py   re-solves problems.yaml symbolically
                 compare_*.py         reproduction comparators
                 scan_sensitive.py    credential/PII scan over the tracked tree
                 build_submission_artifact.py, make_mock_logs.py, …

supplement/      frozen rubrics (helpfulness, pedagogy, independence) and prompts
results/         per-base tables + inference verdicts (tracked); judge caches gitignored
logs/            full per-session transcripts (gitignored, ~100 MB; sha256-pinned by the
                 *-log-manifest.sha256 files at the repo root)
artifact/        pinned environment + the archive verifier
```

## Setup

Python 3.11 or 3.12. CI runs both; 3.12.8 is the pinned analysis version recorded in
[`artifact/pinned-environment.json`](./artifact/pinned-environment.json).

```bash
git clone https://github.com/bydeng01/conv-vs-ped-tutor.git
cd conv-vs-ped-tutor
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Collecting new runs or scoring with a live judge requires the relevant provider keys:

| Variable | Used for |
|---|---|
| `ANTHROPIC_API_KEY` | Sonnet tutor + Opus judge (`configs/models.yaml`) |
| `OPENROUTER_API_KEY` | Llama-3.1-8B student (Groq upstream); GPT-5.6 Sol robustness judge (OpenAI upstream) |
| `OPENAI_API_KEY` | GPT tutor base (`configs/models.gpt.yaml`) |
| `GEMINI_API_KEY` | Gemini tutor base (`configs/models.gemini.yaml`) |

Per-role model strings are in `configs/models.yaml`; the roles use separate configurations
by design. `ANTHROPIC_API_KEY` alone covers only the single-condition smoke test.

## Running the experiment

[`experiments/RUN.md`](./experiments/RUN.md) is the authoritative runbook, including the
per-base cross-model procedure. The confirmatory entry point is `run_confirmatory.py`; the
canonical order is:

```bash
# 1. Preflight gates — exits non-zero before any budget is spent.
python experiments/preflight.py --pilot-results results/pilot_groq

# 2. Freeze the tree. The runner refuses to start unless HEAD is the freeze commit and
#    `git status --porcelain` is empty.
git rev-parse HEAD && git status --porcelain && git tag confirmatory-freeze

# 3. Collect: 10 replicates × {cold, conv, ped}. Re-run to resume; --status for progress.
python experiments/run_confirmatory.py --replicates 10 --freeze-commit <hash>

# 4. Metrics + both judges, post-hoc from the logged transcripts.
python analysis/compute_metrics.py logs/conf-s0-{cold,conv,ped}-r* \
    --out results/confirmatory --judge-helpfulness --judge-pedagogy

# 5. Inference.
python analysis/run_inference.py results/confirmatory
```

Cross-model bases re-run the identical protocol with `--base <slug> --models
configs/models.<base>.yaml`, once per base, **never pooled**.

## Tests and CI

The files in `tools/test_*.py` are **standalone scripts, not pytest modules** — each calls
`sys.exit()` at module scope, so `pytest tools/` aborts during collection. Run them directly:

```bash
for f in tools/test_*.py; do python "$f" || echo "FAILED: $f"; done
python tools/verify_problems.py                                  # symbolic problem-set check
python -m pytest analysis/figures/test_fig2_dissociation.py -q   # the one pytest-style test
```

Tests that require the gitignored transcripts report `SKIP` on a fresh clone.
The test summary counts these separately from passed checks.

[`.github/workflows/ci.yml`](./.github/workflows/ci.yml) runs the tests, offline inference
comparisons, and `tools/scan_sensitive.py` on Python 3.11 and 3.12. It uses no provider
credentials and checks that no wire log was produced.

For an offline pipeline demonstration with synthetic scores:

```bash
python tools/make_mock_logs.py --seed 0 --conditions cold,conv,ped
python analysis/compute_metrics.py logs/cold-* logs/conv-* logs/ped-* --out results/mock_triple \
    --judge-helpfulness --judge-backend mock
```

The mock tutor produces identical text for ConvTutor and PedTutor; this checks pipeline
execution, not behavioral differences.

## Reproducing the published analyses

After the [confirmatory inference](#quickstart), these commands compute the post hoc
policy-adjusted sensitivity and descriptive ablation analysis from tracked tables:

```bash
python analysis/condition_adjusted_sensitivity.py
python analysis/ablation_analysis.py results/ablation
```

Each `results/confirmatory*/` holds the per-turn, per-session, and per-replicate tables, the
metric summary, and the judge details behind its `inference.json`. Raw transcripts are not
committed, but the `*-log-manifest.sha256` files verify a released copy.

`python tools/build_submission_artifact.py` packages the full archive — the transcripts and
judge caches that are too large to track — and `python artifact/verify_artifact.py` checks a
received copy against its manifest. See [`artifact/README.md`](./artifact/README.md) for
construction, integrity checks, and offline reconstruction.

### Docker

```bash
docker build -t conv-vs-ped-tutor .
docker run --rm conv-vs-ped-tutor
```

The image pins Python 3.12.8 and the direct dependencies and runs offline inference
comparisons. Its Linux/BLAS environment can produce different mixed-model coefficients
from the macOS reference. See [environment and comparison details](artifact/README.md#pinned-environment).

## Citation

```bibtex
@misc{fan2026rethinkingllmjudgedhelpfulnesspedagogy,
      title={Rethinking LLM-Judged Helpfulness as a Pedagogy Signal: A Pre-Registered Audit Across Tutor Models},
      author={Shuyi Fan and Boyuan Deng and Mengyu Xu and Jiale Liu and Hongyang Zhang and Qiaoxin Yang and Chongyang Gao},
      year={2026},
      eprint={2607.28128},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2607.28128},
}
```

`CITATION.cff` carries the same entry in machine-readable form.

## License

MIT — see [`LICENSE`](./LICENSE).
