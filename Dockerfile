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
helpfulness and pedagogy study. Recomputes inference from published tables."
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

# Reproduce the three confirmatory fits, the sensitivity model and the ablation.
CMD ["bash", "-lc", "\
set -euo pipefail; \
python tools/reproduce_inference.py; \
python analysis/condition_adjusted_sensitivity.py --output reproduced/condition-adjusted.json --latex-output reproduced/condition-adjusted-values.tex; \
python tools/compare_condition_adjusted.py results/condition_adjusted_sensitivity/analysis.json reproduced/condition-adjusted.json; \
cp -R results/ablation reproduced/ablation; \
python analysis/ablation_analysis.py reproduced/ablation"]
