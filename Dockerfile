# A fixed environment for the offline analysis. Read this before trusting it.
#
# WHAT THIS IMAGE DOES: makes the analysis reproducible BETWEEN USERS. Everyone who builds
# it gets the same Python, the same package versions, and the same BLAS, so two readers
# comparing notes are comparing the same computation rather than two different ones.
#
# WHAT IT DOES NOT DO: reproduce the numbers in the paper bit-for-bit. The reported analyses
# were run on macOS 14.6.1 / Apple M3 Pro, where NumPy and SciPy link against Accelerate.
# This image is Linux/OpenBLAS. The crossed mixed-effects fits in analysis/inferential.py
# and analysis/condition_adjusted_sensitivity.py are sensitive to that difference: with the
# SAME pinned package versions, coefficients move in the third decimal and random-effect
# variances by up to ~0.007, and one boundary variance estimate moves from 1.1e-10 to
# 6.5e-3. Every verdict label, coefficient sign, and significance call is unchanged.
#
# That is worth stating plainly, because pinning packages is widely assumed to be
# sufficient and here it is not: the OS and CPU are part of the pin, which is why
# artifact/pinned-environment.json records them. On Apple silicon this image runs under
# emulation and still will not match; reproducing the exact published values requires
# macOS/arm64 with the package set in artifact/requirements-pinned.txt.
#
# So: use `--science-only` / the portable comparators inside this image, which assert the
# conclusions and the numbers behind them. The exact checkpoints are not disabled; they
# detect their own environment and skip outside it.
#
#   docker build -t conv-vs-ped-tutor .
#   docker run --rm conv-vs-ped-tutor                  # re-derive and compare, ~1 min
#   docker run --rm -it conv-vs-ped-tutor bash         # poke around
#
# No API key is needed and none is accepted: nothing in the default command contacts a
# provider. Re-running the experiment itself is out of scope for this image.

FROM python:3.12.8-slim

# Pinned in artifact/pinned-environment.json alongside the OS and CPU it was recorded on.
LABEL org.opencontainers.image.title="conv-vs-ped-tutor"
LABEL org.opencontainers.image.description="Offline analysis environment for the tutor-agent \
helpfulness/pedagogy audit. Reproduces verdicts, not bit-identical mixed-model coefficients."
LABEL org.opencontainers.image.source="https://github.com/bydeng01/conv-vs-ped-tutor"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /work

# Dependencies first, so edits to the analysis code do not invalidate the wheel layer.
COPY artifact/requirements-pinned.txt artifact/requirements-pinned.txt
RUN pip install --no-cache-dir -r artifact/requirements-pinned.txt

# The direct dependencies are pinned exactly; the transitive set is whatever pip resolves at
# build time. `docker build` on two different days can therefore differ in a transitive
# package. The resolved set is written into the image so that a discrepancy between two
# builds is diagnosable rather than mysterious: `docker run --rm IMAGE cat /work/pip-freeze.txt`
RUN pip freeze > /work/pip-freeze.txt

COPY . /work

# Fail the BUILD if the interpreter or the pinned direct dependencies are not what
# artifact/pinned-environment.json records. A silently drifted image is worse than no image,
# because it looks authoritative. The OS/CPU mismatch documented above is expected and is
# reported, not enforced.
RUN python - <<'PY'
import json, platform, importlib.metadata as md
rec = json.load(open("artifact/pinned-environment.json"))
problems = []
if platform.python_version() != rec["python"]:
    problems.append(f'python {rec["python"]} pinned, image has {platform.python_version()}')
for name, want in sorted(rec["packages"].items()):
    have = md.version(name)
    if have != want:
        problems.append(f"{name} {want} pinned, image has {have}")
if problems:
    raise SystemExit("pinned-environment drift:\n  " + "\n  ".join(problems))
print(f'pinned interpreter and direct dependencies OK ({rec["python"]})')
print(f'NOTE: reference analyses were fit on {rec["analysis_hardware"]["operating_system"]}')
print(f'      this image is {platform.system()} {platform.machine()} -- see the Dockerfile header')
PY

# matplotlib is not in the pinned set: it is needed only to regenerate Figure 2, which is not
# part of the offline reproduction. Add it inside the container if you want the figures:
#   pip install 'matplotlib>=3.8' && python analysis/figures/fig2_dissociation.py

CMD ["bash", "-lc", "\
set -euo pipefail; \
rm -rf reproduced && mkdir -p reproduced; \
cp -R results/confirmatory reproduced/sonnet; \
cp -R results/confirmatory_gpt reproduced/gpt; \
cp -R results/confirmatory_gemini reproduced/gemini; \
python analysis/run_inference.py reproduced/sonnet --freeze-tag confirmatory-freeze --freeze-commit 1a12b566bb825ff91359fb7c526e24b161ae38d3; \
python analysis/run_inference.py reproduced/gpt --freeze-tag crossmodel-gpt-freeze --freeze-commit 644271b1e6e365a84d679a103beb08f0775e60ef; \
python analysis/run_inference.py reproduced/gemini --freeze-tag crossmodel-gemini-freeze --freeze-commit 68ee3faf8d1370da15bb7f8ab1a87599389a7eb6; \
for b in sonnet:confirmatory gpt:confirmatory_gpt gemini:confirmatory_gemini; do \
  python tools/compare_inference.py results/${b#*:}/inference.json reproduced/${b%%:*}/inference.json --science-only --rel-tol 0.05; \
done; \
python analysis/condition_adjusted_sensitivity.py --output reproduced/condition-adjusted.json --latex-output reproduced/condition-adjusted-values.tex; \
python tools/compare_condition_adjusted.py results/condition_adjusted_sensitivity/analysis.json reproduced/condition-adjusted.json; \
python analysis/ablation_analysis.py results/ablation > /dev/null && echo 'ablation OK'; \
echo; echo 'All published verdicts re-derived offline. Coefficients differ from the paper in'; \
echo 'the third decimal (Linux/OpenBLAS vs macOS/Accelerate) -- see the Dockerfile header.'"]
