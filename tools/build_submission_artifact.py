"""Build the deterministic analysis archive.

The archive includes ignored GPT/Gemini logs and judge-score caches, which
``git archive`` would omit.

Run:
  python tools/build_submission_artifact.py
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import platform
import tarfile
from importlib.metadata import version
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_ROOT = "conv-vs-ped-tutor-artifact"
DEFAULT_OUTPUT = Path("dist/conv-vs-ped-tutor-artifact.tar.gz")
TOP_LEVEL = (
    "LICENSE",
    "README.md",
    "requirements.txt",
    "paper-plan.md",
    "metric-amendment-2026-06-19.md",
    "cross-judge-amendment-2026-07-19.md",
    # Records the transport used for the released second-judge scores.
    "cross-judge-amendment-openrouter-2026-07-20.md",
    # Records pre-registration deviations and advisory diagnostics absent from raw logs.
    "decisions-log.md",
    # All three transcript families are needed to reconstruct second-judge prompts.
    "confirmatory-log-manifest.sha256",
    "crossmodel-gpt-log-manifest.sha256",
    "crossmodel-gemini-log-manifest.sha256",
)
# Present only after the live GPT judge pass has produced wire logs / score caches.
OPTIONAL_TOP_LEVEL = (
    "gpt-judge-wire-log-manifest.sha256",
)
SOURCE_DIRS = ("agents", "analysis", "configs", "domain", "experiments", "protocol", "student", "supplement", "tools", "artifact")
RESULT_DIRS = (
    "results/confirmatory",
    "results/confirmatory_gpt",
    "results/confirmatory_gemini",
    "results/condition_adjusted_sensitivity",
    "results/ablation",
    # Second-judge robustness outputs: input manifests + protected-primary hashes now;
    # after the live run, also the GPT detail/CSV/analysis, per-rep score caches, and wire
    # logs (all rglob'd here and pinned again by gpt-judge-wire-log-manifest.sha256).
    "results/judge_robustness",
)
# All three confirmatory raw-log families (30 run dirs each). Sonnet was previously omitted.
RAW_FAMILIES = {"sonnet": "conf-s0-*", "gpt": "conf-gpt-s0-*", "gemini": "conf-gemini-s0-*"}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache"}
EXCLUDED_NAMES = {".DS_Store"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def acceptable(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT)
    return (
        path.is_file()
        and not path.is_symlink()
        # analysis/figures holds both the figure GENERATORS (.py -- analysis code, so a
        # reader needs them) and their rendered outputs (.pdf/.png/.svg/.tiff -- the
        # manuscript already carries those, and they are megabytes). Ship the source only,
        # minus the `.prev-` snapshots of superseded designs, which would leave a reader
        # guessing which script drew the shipped figure.
        and not (relative.parts[:2] == ("analysis", "figures")
                 and (path.suffix != ".py" or ".prev-" in path.name))
        and not (set(relative.parts) & EXCLUDED_PARTS)
        and path.name not in EXCLUDED_NAMES
        # `tmp.`-prefixed DIRECTORIES too, not just file names: the cross-judge runner stages an
        # unpromoted scoring attempt in `<base>/tmp.staging.<pid>/`, whose members have ordinary
        # names. Packaging a staging directory would ship exactly the unpromoted results the
        # transactional promotion exists to withhold.
        and not any(part.startswith("tmp.") for part in relative.parts)
    )


# A pre-live base carries ONLY these: the frozen plan, the input manifest, and the
# protected-primary hashes. None of them is produced by contacting a provider, so none is ever
# evidence of a paid run. Everything else under an output directory was written by a scoring or
# preflight attempt and is classified by the backend that attempt recorded.
PRE_LIVE_NAMES = frozenset({"plan.json", "input_manifest.jsonl", "protected-primary.sha256"})


def _transient(path: Path, root: Path) -> bool:
    """A `tmp.`-prefixed file OR a file inside a `tmp.`-prefixed directory, relative to the
    tree being scanned. Mirrors the `tmp.` clause of acceptable(), which already keeps both out
    of the payload. Relative to `root`, not REPO_ROOT, so the helper cannot raise ValueError on
    a tree outside the repo (an extracted artifact, a test fixture)."""
    return any(part.startswith("tmp.") for part in path.relative_to(root).parts)


def _backends_in(obj) -> list[str]:
    """Every value recorded under a "backend" key, at any depth.

    Read generically rather than at fixed paths because the runner stamps the backend into many
    shapes -- `stamp.backend` in a cache, top-level in a detail file, `cache_stamps.<rubric>.
    backend` in run_state.json, `resolved.backend` in preflight.json, per record in a wire log.
    Every "backend" key the runner writes denotes the JUDGE backend, so a generic scan cannot
    pick up an unrelated field."""
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


def _file_backends(path: Path) -> list[str] | None:
    """Backends recorded in one file, or None if the file cannot be read as provenance.

    None is NOT "no backend" -- it means unknown, which is treated as not-provably-mock by the
    caller. A `.jsonl` is read line by line and short-circuits on the first non-mock marker, so
    a live wire log costs one line and never loads a large log into memory.

    A file under `wire/` that records NO backend at all is UNKNOWN, not vouching-nothing: the
    scoring runner stamps `backend` into every wire record, but the LIVE preflight's records
    carry none -- and the preflight writes them DURING its call loop, then aborts on a contract
    violation BEFORE rewriting `resolved_config.json`. A live preflight aborting over an
    earlier mock one therefore leaves PAID wire records beside stale mock provenance, and the
    stale siblings must not vouch the directory mock. Only wire/ gets this rule --
    `input_manifest.jsonl` lines legitimately record no backend."""
    try:
        if path.suffix == ".jsonl":
            found = []
            with path.open(encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001 - a truncated tail is still a real request
                        return None
                    got = _backends_in(rec)
                    if any(b != "mock" for b in got):
                        return got
                    found.extend(got)
            if path.parent.name == "wire" and not found:
                return None
            return found
        if path.suffix == ".json":
            return _backends_in(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - unreadable provenance is UNKNOWN, never "mock"
        return None
    return []          # any other file type (CSV, .sha256) records no backend of its own


def _output_dir_of(path: Path, jr: Path) -> Path:
    """The scoring/preflight output directory a file belongs to -- its nearest ancestor that is
    not one of the runner's per-directory subfolders. One attempt writes one such directory, so
    the backend is a property of the directory, not of each file in it."""
    d = path.parent
    while d != jr and d.name in ("cache", "wire"):
        d = d.parent
    return d


def live_gpt_artifacts(jr: Path) -> list[Path]:
    """Files under `jr` that must be pinned by the wire/score manifest before they may ship.

    Classification is per OUTPUT DIRECTORY and by recorded PROVENANCE, not by filename:

        a directory's files are evidence UNLESS the directory proves it is MOCK.

    Two earlier shapes of this gate both failed, in opposite directions:

    * Globbing `cache/*_cache.json` + `wire/*.jsonl` + `*_detail.json` matched the zero-byte
      `cache/tmp.lock.<instrument>_cache.json` that `_flush_cache` leaves behind and never
      unlinks, and checked no backend at all -- so the mock rehearsal the handoff prescribes on
      all three bases BEFORE paying made this gate refuse to package.
    * Narrowing it to those three EXACT per-instrument filenames with `backend == "live"` then
      failed OPEN in several ways: `--offline-cache-only` output records
      `backend: "offline-cache-only"` though its scores are reconstructed FROM paid caches
      (the runner refuses to reconstruct anything else); the live PREFLIGHT writes
      `wire/preflight_<instrument>.jsonl`, `preflight.json` and `resolved_config.json`, none of
      which matched; and a file with a missing, unrecognized, or malformed backend read as
      not-live. The caches are gitignored, so a tree can legitimately carry live-derived detail
      files with no cache beside them to trip the gate.

    Only "mock" is positively unpaid. Live, offline-cache-only, "cache", an unknown value, a
    missing marker, and an unreadable file all fail CLOSED -- the remedy is to build the
    manifest, which is cheap, whereas shipping unpinnable judge scores is not recoverable."""
    if not jr.is_dir():
        return []
    # The scan applies the same exclusions as acceptable(): a file this builder would never
    # package can never be evidence that requires a manifest. Without this, a Finder-created
    # .DS_Store in a provenance-free pre-live base read as an unpinned paid artifact, and the
    # refusal's own remedy (build the manifest) would have manufactured the forbidden
    # pre-live-manifest state.
    files = [p for p in jr.rglob("*")
             if p.is_file() and not p.is_symlink() and not _transient(p, jr)
             and p.name not in EXCLUDED_NAMES
             and not (set(p.relative_to(jr).parts) & EXCLUDED_PARTS)]
    by_dir: dict[Path, list[Path]] = {}
    for p in files:
        by_dir.setdefault(_output_dir_of(p, jr), []).append(p)

    evidence = []
    for out_dir, members in by_dir.items():
        payload = [p for p in members if p.name not in PRE_LIVE_NAMES]
        if not payload:
            continue                      # a pre-live base: plan + manifest + hashes only
        backends: list[str] = []
        unknown = False
        for p in members:
            got = _file_backends(p)
            if got is None:
                unknown = True
            else:
                backends.extend(got)
        provably_mock = bool(backends) and not unknown and all(b == "mock" for b in backends)
        if not provably_mock:
            evidence.extend(payload)
    return sorted(evidence)


def verify_wire_manifest(manifest: Path, jr_payload: list[Path]) -> list[str]:
    """The wire/score manifest must be CURRENT before it may license packaging.

    `manifest.is_file()` used to be the whole check, which fails both ways: a stale manifest
    (built before a later scoring pass, or before a sweep) packages cleanly and then fails
    verification after extraction; and a manifest that OMITS newer live files licenses exactly
    the unpinned-score packaging it exists to prevent. Every entry must exist with a matching
    hash, and every judge-robustness payload file must be an entry."""
    problems = []
    entries: dict[str, str] = {}
    try:
        for line in manifest.read_text().splitlines():
            if not line.strip():
                continue
            digest, relative = line.split(None, 1)
            relative = relative.strip()
            if relative in entries:
                # A dict would silently keep the LAST line, while the documented consumer
                # check (`shasum -a 256 -c`) fails the same manifest -- the two verdicts on
                # one file must never diverge.
                problems.append(f"duplicate manifest entry for {relative}")
            entries[relative] = digest
    except Exception as exc:  # noqa: BLE001 - an unreadable manifest licenses nothing
        return [f"unreadable {manifest.name}: {type(exc).__name__}: {exc}"]
    payload_rel = {p.relative_to(REPO_ROOT).as_posix() for p in jr_payload}
    for relative, digest in sorted(entries.items()):
        parts = Path(relative).parts
        # Scope before hashing: an entry the archive will never contain must not license
        # packaging. ".." segments would also defeat the prefix rule below.
        if ".." in parts:
            problems.append(f"manifest entry {relative} contains a '..' path segment")
            continue
        if not relative.startswith("results/judge_robustness/"):
            problems.append(f"manifest entry {relative} lies outside results/judge_robustness")
            continue
        if (any(part.startswith("tmp.") for part in parts)
                or (set(parts) & EXCLUDED_PARTS) or Path(relative).name in EXCLUDED_NAMES):
            problems.append(f"manifest entry {relative} pins a transient/excluded file the "
                            "archive will not contain")
            continue
        target = REPO_ROOT / relative
        if not target.is_file():
            problems.append(f"manifest entry {relative} is missing from the tree")
        elif sha256_path(target) != digest:
            problems.append(f"manifest hash for {relative} does not match the file")
    problems.extend(f"payload file {rel} is not pinned by the manifest"
                    for rel in sorted(payload_rel - set(entries)))
    return problems


def untracked_payload_paths(paths) -> list[Path]:
    """Find payload files under SOURCE_DIRS that Git neither tracks nor ignores.

    The filesystem-based builder includes ignored raw logs and caches. This check
    catches untracked source files that would otherwise enter the archive without
    a versioned source in the repository.
    """
    import subprocess

    def git(*args, stdin=None):
        return subprocess.run(("git", "-C", str(REPO_ROOT)) + args, input=stdin,
                              capture_output=True, text=True)

    if git("rev-parse", "--git-dir").returncode != 0:
        print("  NOTE: not a git checkout -- skipping the tracked-or-ignored payload check")
        return []

    tracked = {line for line in git("ls-files").stdout.splitlines() if line}
    candidates = []
    for p in sorted(paths):
        try:
            rel = p.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            continue
        if rel.split("/", 1)[0] in SOURCE_DIRS and rel not in tracked:
            candidates.append((rel, p))
    if not candidates:
        return []
    # `git check-ignore --stdin` prints only the paths it DOES ignore.
    ignored = set(git("check-ignore", "--stdin",
                      stdin="\n".join(rel for rel, _ in candidates) + "\n").stdout.splitlines())
    return [p for rel, p in candidates if rel not in ignored]


def collect_payload() -> list[Path]:
    paths = {REPO_ROOT / name for name in TOP_LEVEL}
    paths.update(REPO_ROOT / name for name in OPTIONAL_TOP_LEVEL
                 if (REPO_ROOT / name).is_file())
    for directory in SOURCE_DIRS + RESULT_DIRS:
        root = REPO_ROOT / directory
        if root.is_dir():
            paths.update(p for p in root.rglob("*") if acceptable(p))

    strays = untracked_payload_paths(paths)
    if strays:
        raise SystemExit(
            "refusing to package: {} file(s) under {} are neither git-tracked nor git-ignored, "
            "so the archive would ship content no commit records:\n  - {}\n"
            "Track them (git add), or move them out of the packaged source directories."
            .format(len(strays), "/".join(SOURCE_DIRS),
                    "\n  - ".join(str(p.relative_to(REPO_ROOT)) for p in strays[:10])
                    + ("\n  - ..." if len(strays) > 10 else "")))

    raw_dirs = []
    for family, pattern in RAW_FAMILIES.items():
        family_dirs = sorted((REPO_ROOT / "logs").glob(pattern))
        if len(family_dirs) != 30:
            raise SystemExit(f"expected 30 {family} run directories, found {len(family_dirs)}")
        raw_dirs.extend(family_dirs)
    expected_names = {"calls.jsonl", "confirmatory_meta.json", "full_session_result.json"}
    for directory in raw_dirs:
        files = [p for p in directory.iterdir() if acceptable(p)]
        if {p.name for p in files} != expected_names:
            raise SystemExit(
                f"{directory.relative_to(REPO_ROOT)} does not contain exactly "
                f"{sorted(expected_names)}"
            )
        paths.update(files)
    n_expected = 30 * len(RAW_FAMILIES)
    if len(raw_dirs) != n_expected:
        raise SystemExit(f"expected {n_expected} confirmatory run directories, found {len(raw_dirs)}")

    # If the live second-judge layer is being packaged, its wire/score manifest is MANDATORY --
    # shipping GPT scores that nothing pins would make them unverifiable in the artifact. And a
    # manifest that merely EXISTS licenses nothing: it must be current (every entry present and
    # hash-matching) and complete (every judge-robustness payload file pinned), or the built
    # archive would fail verification after extraction -- or worse, verify with live scores
    # unpinned.
    jr = REPO_ROOT / "results" / "judge_robustness"
    if jr.is_dir():
        manifest = REPO_ROOT / "gpt-judge-wire-log-manifest.sha256"
        if manifest.is_file():
            stale = verify_wire_manifest(manifest, [p for p in paths if jr in p.parents])
            if stale:
                raise SystemExit(
                    f"refusing to package: {manifest.name} is stale or incomplete "
                    f"({len(stale)} problem(s)):\n  - " + "\n  - ".join(stale[:10])
                    + ("\n  - ..." if len(stale) > 10 else "")
                    + "\nRebuild it from the current tree:\n"
                    "  python tools/build_gpt_judge_manifest.py")
        else:
            live_gpt = live_gpt_artifacts(jr)
            if live_gpt:
                raise SystemExit(
                    f"refusing to package {len(live_gpt)} live GPT judge artifact(s) without "
                    "gpt-judge-wire-log-manifest.sha256. Build it first:\n"
                    "  python tools/build_gpt_judge_manifest.py")

    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise SystemExit(f"missing required payload files: {missing}")
    return sorted(paths, key=lambda p: str(p.relative_to(REPO_ROOT)))


def check_environment() -> None:
    pinned = json.loads((REPO_ROOT / "artifact/pinned-environment.json").read_text())
    failures = []
    if platform.python_version() != pinned["python"]:
        failures.append(f"python {platform.python_version()} != {pinned['python']}")
    for package, expected in pinned["packages"].items():
        observed = version(package)
        if observed != expected:
            failures.append(f"{package} {observed} != {expected}")
    if failures:
        raise SystemExit("pinned environment mismatch: " + "; ".join(failures))


def tar_info(relative: Path, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(f"{ARCHIVE_ROOT}/{relative.as_posix()}")
    info.size = size
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mode = 0o644
    return info


def build(output: Path) -> None:
    check_environment()
    payload = collect_payload()
    manifest_lines = [
        f"{sha256_path(path)}  {path.relative_to(REPO_ROOT).as_posix()}"
        for path in payload
    ]
    manifest = ("\n".join(manifest_lines) + "\n").encode()

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for path in payload:
                    relative = path.relative_to(REPO_ROOT)
                    data = path.read_bytes()
                    tar.addfile(tar_info(relative, len(data)), io.BytesIO(data))
                relative = Path("ARTIFACT-MANIFEST.sha256")
                tar.addfile(tar_info(relative, len(manifest)), io.BytesIO(manifest))

    digest = sha256_path(output)
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_text(f"{digest}  {output.name}\n")
    n_raw_dirs = 30 * len(RAW_FAMILIES)
    try:
        shown = output.relative_to(REPO_ROOT)
    except ValueError:                    # an out-of-repo --output is explicitly supported
        shown = output
    print(f"wrote {shown} ({output.stat().st_size} bytes)")
    print(f"sha256 {digest}")
    print(f"payload files {len(payload) + 1}; raw run directories {n_raw_dirs}; "
          f"raw files {n_raw_dirs * 3}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    build(output)


if __name__ == "__main__":
    main()
