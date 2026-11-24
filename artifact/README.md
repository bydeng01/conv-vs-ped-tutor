# Reconstructing the metric tables from transcripts

The [repository quickstart](../README.md) recomputes the confirmatory analyses from the published tables. To rebuild the tables themselves, you need the full study archive. It includes 90 confirmatory sessions, the cached Opus ratings for both rubrics, and the GPT-5.6 Sol robustness scores and request records. The GitHub checkout provides the tables and individual ratings for all three tutor models.

## Verify the archive

From the root of a freshly extracted archive, before generating any new files, run

```bash
python artifact/verify_artifact.py
```

The verifier checks each file against the archive manifest, checks the 270 transcript files against the original run manifests, and matches the second judge's results to the recorded score caches and comparison inputs.

## Pinned environment

The [environment record](pinned-environment.json) specifies Python 3.12.8, direct dependency versions, and the original hardware. To install the recorded package versions in a Python 3.12.8 environment, run

```bash
python -m pip install -r artifact/requirements-pinned.txt
```

Mixed-model fits can vary across operating systems and numerical libraries. The exact policy-adjusted regression checks use the recorded macOS 14.6.1 arm64 environment because macOS supplies its Accelerate math library. Other environments check coefficient magnitudes, directions, and significance using portable tolerances. The [inference comparator](../tools/compare_inference.py) checks the verdicts and numerical results with cross-platform tolerances when used by the quickstart, CI, or Docker.

## Rebuild the three confirmatory tables for each tutor model

Activate the analysis environment, then run these commands from the extracted archive root. Each reconstruction uses one tutor model's sessions and cached ratings. A missing rating stops the computation before it can make a provider call.

```bash
set -e
out=$(mktemp -d)
rebuild_tables() {
    reference=$1
    models=$2
    shift 2
    mkdir "$out/$reference"
    cp "results/$reference/helpfulness_cache.json" "results/$reference/pedagogy_cache.json" "$out/$reference/"
    python analysis/compute_metrics.py "$@" --out "$out/$reference" --models "$models" \
        --judge-helpfulness --judge-pedagogy --offline-cache-only
    python tools/compare_reconstruction.py "results/$reference" "$out/$reference"
}
rebuild_tables confirmatory configs/models.yaml logs/conf-s0-conv-* logs/conf-s0-ped-* logs/conf-s0-cold-*
rebuild_tables confirmatory_gpt configs/models.gpt.yaml logs/conf-gpt-s0-*
rebuild_tables confirmatory_gemini configs/models.gemini.yaml logs/conf-gemini-s0-*
```

The comparator checks the order of the rows and columns in the turn, session, and replicate CSVs. Text fields must match exactly. Numeric fields have an absolute tolerance of `1e-12`. The Sonnet command lists the three conditions in their published row order.

## Build an archive

From a study checkout containing the transcripts and score caches, use the pinned environment and run

```bash
python tools/build_submission_artifact.py
```

The builder writes `dist/conv-vs-ped-tutor-artifact.tar.gz` with a manifest for the verifier. It also includes the descriptive ablation tables and the policy-adjusted sensitivity analysis.
