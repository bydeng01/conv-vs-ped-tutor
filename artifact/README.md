# Analysis artifact

The archive supports these offline workflows:

1. **Reconstruct the GPT and Gemini metric tables** (Section 2). All three
   confirmatory raw-log families are now packaged — 90 run directories (30 per
   base), 270 raw files — because the GPT-5.6 Sol judge reconstructs prompts from
   every base; the Sonnet family reconstructs analogously (its Opus caches are
   included) and its base is copied directly in Section 3. `--offline-cache-only`
   disables provider calls and fails if a required score is missing.
2. **Recompute inference for all three bases.** The required CSV tables and
   analysis code are included. Because the archive omits `.git`, the recorded
   freeze commit is supplied with `--freeze-commit`.
3. **Reconstruct the second-judge (GPT-5.6 Sol) robustness tables** — *only once
   the live GPT pass has been run and re-packaged.* The archive then also carries
   `results/judge_robustness/` (input manifests, per-rep GPT score caches, wire
   logs, and the GPT detail/CSV/analysis), pinned by
   `gpt-judge-wire-log-manifest.sha256`. `analysis/run_cross_judge_audit.py
   --offline-cache-only` rebuilds the GPT tables from the released caches with a
   hard tripwire on any miss; `analysis/compare_judges.py` rebuilds the cross-judge
   comparison. Before that live pass the archive carries only the input manifests
   and protected-primary hashes, and `verify_artifact.py` reports the GPT layer as
   "manifests only, live run pending".

The archive reproduces neither tutor responses nor uncached judge scores; those
require provider access and the recorded model identifiers. Reusing a cached score
reproduces the released scoring output; it is not a new judge evaluation. The
GPT-5.6 Sol layer is a post hoc robustness audit — the Opus results remain
primary, and the two judges are always reported separately (never averaged).

The post hoc policy-adjusted sensitivity is reported alongside, not in place of,
the pre-registered pooled J2 analysis.

## Pinned environment

Use Python 3.12.8 and the exact direct dependency versions in
`artifact/requirements-pinned.txt`. Hardware, operating system, package versions, and the
three freeze commits are recorded in `artifact/pinned-environment.json`.

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

`cmp` was used here previously. It asserts byte equality, which holds only on macOS/arm64:
the mixed-effects fits are not bit-portable across BLAS implementations, so a reader
following these steps on Linux saw a failure that meant nothing about the analysis. The
comparator asserts convergence, coefficient signs, significance at alpha, and agreement
within an absolute tolerance. Add `--strict` for exact comparison inside the pinned
environment.

The command reads only the three packaged `per_turn.csv` files, fits
`outcome ~ leaks_i + C(condition)` with crossed replicate/problem variance components and
maximum likelihood, and regenerates both the machine-readable report and manuscript values.
