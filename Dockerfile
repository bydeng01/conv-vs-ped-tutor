# Offline analysis with Python 3.12.8 and pinned direct dependencies.
# Linux/BLAS fits can differ numerically from the macOS reference; the default command
# uses portable comparisons. See artifact/README.md for tolerances and reference hardware.
#
#   docker build -t conv-vs-ped-tutor .
#   docker run --rm conv-vs-ped-tutor
#   docker run --rm -it conv-vs-ped-tutor bash
#
# The default command needs no provider credentials and makes no model calls.

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

# Record resolved transitive dependencies, which can vary between builds.
# Inspect with: docker run --rm IMAGE cat /work/pip-freeze.txt
RUN pip freeze > /work/pip-freeze.txt

COPY . /work

# Check the interpreter and direct dependencies against the recorded environment.
# OS and CPU differences are reported; portable comparisons handle numerical drift.
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
