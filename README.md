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

The pre-registration is [`paper-plan.md`](./paper-plan.md); every deviation from it is dated
in [`decisions-log.md`](./decisions-log.md). Findings, limitations, and the falsification
rule are in the paper — this README covers how to run the code.

## Quickstart

Every published number re-derives from the tracked tables offline, **with no API key**, in
about a minute:

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

Each pre-registration freeze commit is passed explicitly, matching what CI, the Dockerfile,
and [`artifact/README.md`](./artifact/README.md) already do. The freeze tags themselves are
not published, so `--freeze-tag` alone would not resolve in a clone; the commit is the
authoritative binding and is also recorded in every `metrics_summary.json` (`freeze_heads`)
and `inference.json` (`provenance.freeze_commit`). Do not drop these flags.

Verdicts print to stdout and land in each directory's `inference.json`. CI runs exactly this
on every push. Collecting *new* runs is the only thing that needs provider access — see
[Running the experiment](#running-the-experiment).

## Repository layout

```
agents/          the manipulated variable
  conv_tutor.py      single-node graph
  ped_tutor.py       multi-node state machine — the only file that differs in kind
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

Keys are needed **only to collect new runs or re-score with a live judge**, never to
reproduce the published analyses:

| Variable | Used for |
|---|---|
| `ANTHROPIC_API_KEY` | Sonnet tutor + Opus judge (`configs/models.yaml`) |
| `OPENROUTER_API_KEY` | Llama-3.1-8B student, pinned OpenRouter → Groq |
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

Checks whose input is the gitignored transcript set report `SKIP` on a fresh clone and are
tallied separately, so a clone cannot be mistaken for having exercised them.

[`.github/workflows/ci.yml`](./.github/workflows/ci.yml) runs the above plus the full
offline re-derivation and `tools/scan_sensitive.py`, on Python 3.11 and 3.12. It needs no
secrets and has none: nothing in CI contacts a provider, and a final step asserts that no
wire log was produced.

## Reproducing the published analyses

The tracked per-base tables are sufficient; no model calls:

```bash
python analysis/run_inference.py results/confirmatory \
  --freeze-tag confirmatory-freeze \
  --freeze-commit 1a12b566bb825ff91359fb7c526e24b161ae38d3   # and _gpt / _gemini per Quickstart
python analysis/condition_adjusted_sensitivity.py                  # post hoc, additive
python analysis/ablation_analysis.py results/ablation              # descriptive
```

Each `results/confirmatory*/` holds the per-turn, per-session, and per-replicate tables, the
metric summary, and the judge details behind its `inference.json`. Raw transcripts are not
committed, but the `*-log-manifest.sha256` files verify a released copy.

`python tools/build_submission_artifact.py` packages the full archive — the transcripts and
judge caches that are too large to track — and `python artifact/verify_artifact.py` checks a
received copy against its manifest. See [`artifact/README.md`](./artifact/README.md) for
construction, integrity checks, and offline reconstruction.

### Numerical portability

The re-derivation reproduces every **verdict**, coefficient **sign**, and **significance**
call on any machine. It does not reproduce every **digit**, and pinning package versions does
not make it.

The crossed mixed-effects fits in `analysis/inferential.py` and
`analysis/condition_adjusted_sensitivity.py` depend on which BLAS NumPy and SciPy link
against. Published analyses ran on macOS 14.6.1 / Apple M3 Pro (Accelerate). The *same*
pinned package set on Linux/x86_64 (OpenBLAS) gives:

| | published (macOS/arm64) | rerun (Linux/x86_64) | conclusion changes? |
|---|---|---|---|
| GPT base, J2 helpfulness coefficient | −0.313 | −0.321 | no |
| GPT base, J2 helpfulness *p* | 5.06e−10 | 2.42e−10 | no |
| Sonnet policy-adjusted helpfulness *p* | 9.6e−10 | 1.2e−11 | no |
| GPT policy-adjusted problem variance | 1.1e−10 (boundary) | 6.5e−3 | no |

Random-effect variances are the least portable numbers here — several sit near the zero
boundary, where a different optimizer path lands somewhere else entirely. The fixed effects
that carry the argument move in the third decimal. This is why
`artifact/pinned-environment.json` records the OS and CPU alongside the package versions, and
why the comparators have two modes:

- **`--science-only`** (`tools/compare_inference.py`) and `tools/compare_condition_adjusted.py`
  assert the conclusions and the numbers behind them. **Use these off the pinned platform.**
  CI and Docker run these.
- **Without those flags** they assert bit equality — correct only inside the pinned
  environment. `tools/test_condition_adjusted_sensitivity.py` detects the environment and
  skips its exact checkpoints outside it rather than failing.

### Docker

```bash
docker build -t conv-vs-ped-tutor .
docker run --rm conv-vs-ped-tutor
```

Pins Python 3.12.8 and the exact direct dependencies, and fails the build if either drifted.
It makes the analysis reproducible **between users**; it does **not** reproduce the paper's
digits, for the reason above — it is Linux/OpenBLAS. Matching the published values exactly
requires macOS on Apple silicon with `artifact/requirements-pinned.txt`.

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
