# Analysis artifact

The archive packages raw transcripts, cached judge scores, metric tables, and analysis code.
It supports reconstruction of the metric tables and inference without provider calls.
The three confirmatory bases contain 90 run directories and 270 raw files in total.

The GPT-5.6 Sol robustness pass is complete in the tracked results for all three bases.
Reconstructing that layer also requires an archive containing its score caches and wire
logs under `results/judge_robustness/`, pinned by `gpt-judge-wire-log-manifest.sha256`.
`analysis/run_cross_judge_audit.py --offline-cache-only` reconstructs its tables;
`analysis/compare_judges.py` computes the comparison. Check the received archive with
`verify_artifact.py`: older, manifests-only archives lack the completed scoring layer.

Offline reconstruction reuses the released scores and aborts on a missing cache entry.
New tutor responses or judge evaluations require provider access. Opus is the primary judge;
Sol is a post hoc robustness judge, reported separately. The policy-adjusted sensitivity
accompanies the pre-registered pooled J2 analysis.

## Pinned environment

Use Python 3.12.8 and the exact direct dependency versions in
`artifact/requirements-pinned.txt`. Hardware, operating system, package versions, and the
three freeze commits are recorded in `artifact/pinned-environment.json`.

The reference environment is macOS on Apple silicon. Linux/BLAS reruns have shown
small mixed-model coefficient and variance differences while retaining coefficient signs
and significance decisions. Docker and CI use portable comparisons; exact numeric checks
require the recorded environment. For inference comparisons on Linux, use
`tools/compare_inference.py --science-only --rel-tol 0.05`, as Docker does.

Only direct dependencies are pinned. Docker records the resolved dependency set in
`/work/pip-freeze.txt` for comparisons between builds.

## 1. Verify the archive

From the extracted artifact root:

```bash
python artifact/verify_artifact.py
```

This command checks every packaged file against the payload manifest, verifies
both cross-model log manifests, confirms the expected run and cache inventory,
and scans for credentials, email addresses, home-directory paths, and provider
account identifiers.

## 2. Raw GPT/Gemini logs plus cached scores to metric CSVs

Create fresh output directories and unset provider credentials:

```bash
rm -rf reproduced
mkdir -p reproduced/gpt reproduced/gemini
cp results/confirmatory_gpt/helpfulness_cache.json results/confirmatory_gpt/pedagogy_cache.json reproduced/gpt/
cp results/confirmatory_gemini/helpfulness_cache.json results/confirmatory_gemini/pedagogy_cache.json reproduced/gemini/

env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u OPENROUTER_API_KEY \
  python analysis/compute_metrics.py logs/conf-gpt-s0-* \
  --out reproduced/gpt --models configs/models.gpt.yaml \
  --judge-helpfulness --judge-pedagogy --offline-cache-only

env -u ANTHROPIC_API_KEY -u GEMINI_API_KEY -u OPENROUTER_API_KEY \
  python analysis/compute_metrics.py logs/conf-gemini-s0-* \
  --out reproduced/gemini --models configs/models.gemini.yaml \
  --judge-helpfulness --judge-pedagogy --offline-cache-only

python tools/compare_reconstruction.py results/confirmatory_gpt reproduced/gpt
python tools/compare_reconstruction.py results/confirmatory_gemini reproduced/gemini
```

The comparator requires the same row and column order. Non-numeric fields must
match exactly; numeric fields may differ by at most `1e-12` to accommodate
floating-point formatting. The generated `helpfulness_detail.json` and
`pedagogy_detail.json` files record
`score_source: released live-score cache` and omit a judge wire-log path. If a
cached score is missing, reconstruction stops without contacting a provider.

## 3. CSVs to frozen inference

Copy the primary result directory so the packaged reference remains untouched, then run
the three frozen analyses. GPT/Gemini use the reconstructed directories from step 2.

```bash
cp -R results/confirmatory reproduced/sonnet

python analysis/run_inference.py reproduced/sonnet \
  --freeze-tag confirmatory-freeze \
  --freeze-commit 1a12b566bb825ff91359fb7c526e24b161ae38d3
python analysis/run_inference.py reproduced/gpt \
  --freeze-tag crossmodel-gpt-freeze \
  --freeze-commit 644271b1e6e365a84d679a103beb08f0775e60ef
python analysis/run_inference.py reproduced/gemini \
  --freeze-tag crossmodel-gemini-freeze \
  --freeze-commit 68ee3faf8d1370da15bb7f8ab1a87599389a7eb6

python tools/compare_inference.py results/confirmatory/inference.json reproduced/sonnet/inference.json
python tools/compare_inference.py results/confirmatory_gpt/inference.json reproduced/gpt/inference.json
python tools/compare_inference.py results/confirmatory_gemini/inference.json reproduced/gemini/inference.json
```

The comparator checks the scientific result blocks only; paths and Git metadata
may differ after extraction. Categorical and verdict fields must match exactly.
Numeric fields use `abs_tol=1e-8` and `rtol=1e-2` because the packaged references
were generated with SciPy 1.11.4 and statsmodels 0.14.0, whereas the pinned rerun
uses SciPy 1.17.1 and statsmodels 0.14.6. In the pinned rerun, Gemini P1 changes
from `.625` to `.623` but remains nonsignificant; mixed-model fixed effects differ
by less than `1e-8`, and no inferential conclusion changes.

## 4. Post hoc policy-adjusted sensitivity

```bash
python analysis/condition_adjusted_sensitivity.py \
  --output reproduced/condition-adjusted.json \
  --latex-output reproduced/condition-adjusted-values.tex
python tools/compare_condition_adjusted.py \
  results/condition_adjusted_sensitivity/analysis.json reproduced/condition-adjusted.json
```

The comparator checks convergence, coefficient signs, significance at alpha, and coefficient
agreement within its absolute tolerance (default `0.05`). Add `--strict` for exact numeric
comparison inside the pinned environment.

The command reads only the three packaged `per_turn.csv` files, fits
`outcome ~ leaks_i + C(condition)` with crossed replicate/problem variance components and
maximum likelihood, and regenerates both the machine-readable report and manuscript values.
