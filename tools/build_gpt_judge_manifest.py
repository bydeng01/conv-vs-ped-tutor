"""Build (and optionally verify) the GPT-5.6 Sol judge wire-log / score-artifact manifest.

The second-judge robustness caches and raw provider WIRE logs are gitignored (like logs/),
so they need their own SHA-256 manifest to enter the submission artifact and to be checkable
after extraction. This pins every file under ``results/judge_robustness/`` -- the input
manifests, protected-primary hashes, the per-rep score caches, the raw wire logs, and the GPT
detail/CSV/analysis outputs -- so the whole second-judge score provenance is verifiable with
``shasum -a 256 -c gpt-judge-wire-log-manifest.sha256``.

Run (after the live GPT judge pass):
  python tools/build_gpt_judge_manifest.py
  shasum -a 256 -c gpt-judge-wire-log-manifest.sha256
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROBUSTNESS_DIR = REPO_ROOT / "results" / "judge_robustness"
DEFAULT_MANIFEST = REPO_ROOT / "gpt-judge-wire-log-manifest.sha256"
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache"}
EXCLUDED_NAMES = {".DS_Store"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _acceptable(p: Path) -> bool:
    relative = p.relative_to(REPO_ROOT)
    return (p.is_file() and not p.is_symlink()
            and not (set(relative.parts) & EXCLUDED_PARTS)
            and p.name not in EXCLUDED_NAMES
            # `tmp.`-prefixed DIRECTORIES as well as file names, matching
            # tools/build_submission_artifact.py:acceptable(). The cross-judge runner stages an
            # unpromoted attempt in `<base>/tmp.staging.<pid>/` whose members have ordinary
            # names (per_turn.csv, provenance.json, ...). A name-only filter would pin those
            # files here while the artifact builder correctly drops them from the payload --
            # the manifest would then reference files the artifact does not contain, and
            # verify_artifact would fail on a legitimately complete run. It would also publish
            # hashes of exactly the unpromoted outputs transactional promotion withholds.
            and not any(part.startswith("tmp.") for part in relative.parts))


def collect() -> list[Path]:
    if not ROBUSTNESS_DIR.is_dir():
        raise SystemExit(f"no {ROBUSTNESS_DIR.relative_to(REPO_ROOT)} -- run the cross-judge "
                         "audit first (analysis/run_cross_judge_audit.py).")
    return sorted((p for p in ROBUSTNESS_DIR.rglob("*") if _acceptable(p)),
                  key=lambda p: str(p.relative_to(REPO_ROOT)))


def _backends_in(obj) -> list[str]:
    """Every value under a "backend" key, at any depth. A compact copy of the classifier shared
    by tools/build_submission_artifact.py and artifact/verify_artifact.py (every "backend" key
    the runner writes denotes the JUDGE backend); tools/test_cross_judge_audit.py pins the
    three to the same verdicts."""
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "backend" and isinstance(value, (str, int, float)):
                found.append(str(value).strip().lower())
            else:
                found.extend(_backends_in(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_backends_in(item))
    return found


def refuse_mock_artifacts(files: list[Path]) -> None:
    """A manifest must never certify rehearsal output.

    This builder is backend-blind by construction (it pins whatever exists), and the artifact
    verifier's post-live branch is entered on manifest PRESENCE -- so building the manifest
    after the prescribed three-base mock rehearsal was the first step of a chain that packaged
    and verified an all-synthetic "second-judge layer". Refuse while any collected file records
    backend="mock". Unreadable files are fine to PIN (hashing needs no parse); only a positive
    mock marker refuses."""
    offending = set()
    for p in files:
        # Parse per LINE, skipping only the unparseable line, and stop at the first mock
        # marker. One whole-file try/except used to skip the ENTIRE file on a single torn
        # tail or stray byte -- so a truncated mock wire log hid every mock marker it held
        # and the rehearsal got pinned. Streaming also never loads a post-live wire log
        # (the largest files in the tree, one raw model response per record) into memory.
        found_mock = False
        try:
            if p.suffix == ".jsonl":
                with p.open(encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:  # noqa: BLE001 - skip the line, not the file
                            continue
                        if "mock" in _backends_in(rec):
                            found_mock = True
                            break
            elif p.suffix == ".json":
                found_mock = "mock" in _backends_in(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 - unreadable file: nothing provable, still pinnable
            continue
        if found_mock:
            offending.add(_rel(p.parent))
    if offending:
        raise SystemExit(
            "refusing to build the manifest: MOCK rehearsal output is present under\n  - "
            + "\n  - ".join(sorted(offending))
            + "\nA manifest would certify synthetic scores as the packaged second-judge layer."
            " Sweep the rehearsal's outputs in the listed directories: cache/, wire/, the"
            " detail/CSV/analysis files, run_state.json, spend_ledger.json, and -- in the"
            " preflight directory -- preflight.json and resolved_config.json (mock preflight"
            " files are tracked-pattern, so committing them at the freeze would let the later"
            " PAID preflight dirty the frozen tree and deadlock live scoring). KEEP plan.json,"
            " input_manifest.jsonl, and protected-primary.sha256. Then rebuild.")


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(p)


def build(manifest: Path) -> None:
    files = collect()
    refuse_mock_artifacts(files)
    lines = [f"{_sha256(p)}  {p.relative_to(REPO_ROOT).as_posix()}" for p in files]
    manifest.write_text("\n".join(lines) + "\n")
    n_wire = sum(1 for p in files if p.parent.name == "wire")
    n_cache = sum(1 for p in files if p.parent.name == "cache")
    print(f"wrote {_rel(manifest)}  ({len(files)} files: "
          f"{n_wire} wire logs, {n_cache} score caches)")
    if n_wire == 0 and n_cache == 0:
        print("  NOTE: no wire logs or score caches yet -- this is the pre-live-run state "
              "(only input manifests / protected hashes are pinned). Re-run after the live "
              "GPT judge pass to pin the full wire-log/score provenance.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = ap.parse_args()
    manifest = args.manifest if args.manifest.is_absolute() else REPO_ROOT / args.manifest
    build(manifest)


if __name__ == "__main__":
    main()
