"""Recompute and compare the three confirmatory analyses from the released tables."""

import json
from pathlib import Path
from shutil import copyfile
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASES = (
    ("sonnet", "confirmatory", "confirmatory-freeze"),
    ("gpt", "confirmatory_gpt", "crossmodel-gpt-freeze"),
    ("gemini", "confirmatory_gemini", "crossmodel-gemini-freeze"),
)
INPUTS = ("per_replicate.csv", "per_session.csv", "per_turn.csv", "metrics_summary.json")


def main():
    pins = json.loads((ROOT / "artifact/pinned-environment.json").read_text())["freeze_commits"]
    parent = ROOT / "reproduced"
    parent.mkdir(exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="inference-", dir=parent))
    print(f"Writing results to {output}", flush=True)

    for base, directory, tag in BASES:
        source = ROOT / "results" / directory
        target = output / base
        target.mkdir()
        for filename in INPUTS:
            copyfile(source / filename, target / filename)

        subprocess.run(
            [sys.executable, ROOT / "analysis/run_inference.py", target,
             "--freeze-tag", tag, "--freeze-commit", pins[tag]], check=True,
        )
        subprocess.run(
            [sys.executable, ROOT / "tools/compare_inference.py",
             source / "inference.json", target / "inference.json",
             "--science-only", "--rel-tol", "0.05"], check=True,
        )


if __name__ == "__main__":
    main()
