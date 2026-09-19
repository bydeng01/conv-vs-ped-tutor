"""Scan tracked files for credentials, home paths, emails, and account identifiers.

Uses the patterns from artifact/verify_artifact.py; CI runs this over the tracked tree.

Usage:
    python tools/scan_sensitive.py            # tracked files (requires git)
    python tools/scan_sensitive.py --all      # every file except .git and ignored dirs
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Allow documentation placeholders such as elisions, bracketed slots, and redaction markers.
PLACEHOLDER = re.compile(r"\.\.\.|<[^>]*>|redacted|your[-_]|YOUR[-_]|xxx|XXX|example", re.I)

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".pdf", ".gz", ".zip", ".tar", ".pyc",
                 ".bst", ".sty", ".bib", ".ttf", ".otf", ".woff", ".woff2"}
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "logs"}


def _patterns() -> dict[str, re.Pattern]:
    spec = importlib.util.spec_from_file_location(
        "_verify_artifact", REPO_ROOT / "artifact" / "verify_artifact.py")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        # The verifier runs checks at import time and exits when the archive layout is
        # absent, which is the normal state of a clone. The pattern table is defined at
        # module top level, so it is already bound by the time that happens.
        pass
    return module.SENSITIVE_PATTERNS


def _tracked_files() -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT,
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("not a git checkout -- pass --all to scan the working tree instead")
    return [REPO_ROOT / name for name in result.stdout.split("\0") if name]


def _all_files() -> list[Path]:
    out = []
    for path in REPO_ROOT.rglob("*"):
        if path.is_file() and not (SKIP_DIRS & set(path.relative_to(REPO_ROOT).parts)):
            out.append(path)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true",
                        help="scan the working tree instead of git-tracked files")
    args = parser.parse_args()

    patterns = _patterns()
    files = _all_files() if args.all else _tracked_files()
    findings: list[tuple[str, str, str]] = []
    allowed = 0
    scanned = 0

    for path in files:
        if path.suffix.lower() in SKIP_SUFFIXES or not path.exists():
            continue
        try:
            text = path.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        rel = str(path.relative_to(REPO_ROOT))
        for name, pattern in patterns.items():
            for match in pattern.findall(text):
                value = match if isinstance(match, str) else str(match)
                if PLACEHOLDER.search(value):
                    allowed += 1
                    continue
                findings.append((name, rel, value[:100]))

    print(f"scanned {scanned} files, {len(patterns)} patterns, "
          f"{allowed} documented placeholders allowed")
    if findings:
        print(f"\nFAIL: {len(findings)} sensitive-pattern hits")
        for name, rel, value in findings[:40]:
            print(f"  [{name}] {rel}: {value}")
        if len(findings) > 40:
            print(f"  ... and {len(findings) - 40} more")
        raise SystemExit(1)
    print("PASS no credentials, home paths, emails, or account identifiers in the tree")


if __name__ == "__main__":
    main()
