"""Verify archive contents, hashes, raw-log manifests, and sensitive-data patterns."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_NAMES = {"calls.jsonl", "confirmatory_meta.json", "full_session_result.json"}
# All three confirmatory raw-log families and the manifest that pins each. Sonnet was
# previously omitted; the GPT-5.6 Sol judge reconstructs prompts from all three bases.
RAW_FAMILIES = {"sonnet": "conf-s0-*", "gpt": "conf-gpt-s0-*", "gemini": "conf-gemini-s0-*"}
LOG_MANIFESTS = {
    "sonnet": "confirmatory-log-manifest.sha256",
    "gpt": "crossmodel-gpt-log-manifest.sha256",
    "gemini": "crossmodel-gemini-log-manifest.sha256",
}
CACHE_PATHS = [
    Path(f"results/{directory}/{instrument}_cache.json")
    for directory in ("confirmatory", "confirmatory_gpt", "confirmatory_gemini")
    for instrument in ("helpfulness", "pedagogy")
]
GPT_WIRE_MANIFEST = Path("gpt-judge-wire-log-manifest.sha256")
SENSITIVE_PATTERNS = {
    "absolute home path": re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/"),
    "email address": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "OpenAI-style secret": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"),
    "Anthropic-style secret": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b"),
    "Google-style secret": re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    "provider account identifier": re.compile(
        r"['\"](?:account|organization|project|tenant|user)_id['\"]\s*:\s*['\"][^'\"]+['\"]",
        re.IGNORECASE,
    ),
    # Bare account handles, not just "<key>_id": <value> pairs. Provider errors echo these
    # back inside free-text messages (OpenRouter's 404 body carries `user_...`), where the
    # keyed pattern above never sees them.
    "provider account handle": re.compile(
        r"\b(?:user|org|organization|account|proj|project|team)[-_][A-Za-z0-9]{12,}\b"),
    "assigned API key": re.compile(r"\b[A-Z][A-Z0-9_]*API_KEY\s*=\s*[^.\s<][^\s]*"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path) -> dict[Path, str]:
    entries = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(None, 1)
        entries[Path(relative.strip())] = digest
    return entries


def verify_manifest(path: Path, *, exhaustive: bool = False) -> list[str]:
    failures = []
    entries = read_manifest(path)
    for relative, expected in entries.items():
        target = ROOT / relative
        if not target.is_file():
            failures.append(f"missing {relative}")
        elif sha256(target) != expected:
            failures.append(f"hash mismatch {relative}")
    if exhaustive:
        actual = {
            p.relative_to(ROOT)
            for p in ROOT.rglob("*")
            if p.is_file() and p.name != path.name
        }
        if set(entries) != actual:
            for relative in sorted(set(entries) - actual):
                failures.append(f"manifest-only path {relative}")
            for relative in sorted(actual - set(entries)):
                failures.append(f"unmanifested file {relative}")
    return failures


def inventory_failures() -> list[str]:
    failures = []
    run_dirs = []
    for family, pattern in RAW_FAMILIES.items():
        family_dirs = sorted((ROOT / "logs").glob(pattern))
        if len(family_dirs) != 30:
            failures.append(f"{family}: expected 30 run directories, found {len(family_dirs)}")
        run_dirs.extend(family_dirs)
        for directory in family_dirs:
            names = {p.name for p in directory.iterdir() if p.is_file()}
            if names != RAW_NAMES:
                failures.append(f"{directory.relative_to(ROOT)} files: {sorted(names)}")
    raw_files = [p for d in run_dirs for p in d.iterdir() if p.is_file()]
    n_dirs = 30 * len(RAW_FAMILIES)
    if len(run_dirs) != n_dirs:
        failures.append(f"expected {n_dirs} confirmatory run directories, found {len(run_dirs)}")
    if len(raw_files) != n_dirs * 3:
        failures.append(f"expected {n_dirs * 3} confirmatory raw files, found {len(raw_files)}")
    for relative in CACHE_PATHS:
        if not (ROOT / relative).is_file():
            failures.append(f"missing released score cache {relative}")
    return failures


GPT_BASES = ("sonnet", "gpt", "gemini")
GPT_INSTRUMENTS = ("helpfulness", "pedagogy")
RUN_STATE_FILE = "run_state.json"
# The EXACT file set a complete promoted GPT base must ship. Checking only the caches, details,
# and wire logs let an archive drop `judge_inference.json`, the CSVs, `metrics_summary.json`,
# `policy_adjusted.json`, `provenance.json`, or even `completeness.json` and still verify as a
# complete promoted set -- the manifests only inventory files that remain, so deleting one and
# rebuilding them left no trace. This list is deliberately duplicated here rather than imported
# from analysis.run_cross_judge_audit (the verifier must stay dependency-free inside an extracted
# artifact); the duplication is guarded by cross-checking it against `run_state.promoted_outputs`
# below, and by a test asserting it equals the runner's own final_output_names().
# A published comparison is declared over exactly these three bases, and must bind every input
# it read -- including the OPUS surfaces, which the earlier bindings omitted entirely.
COMPARISON_BASES = ("sonnet", "gpt", "gemini")
REQUIRED_COMPARISON_INPUTS = (
    "opus/per_turn.csv",
    "opus/helpfulness_detail.json",
    "opus/pedagogy_detail.json",
    "gpt/helpfulness_detail.json",
    "gpt/pedagogy_detail.json",
    "gpt/policy_adjusted.json",
    "gpt/run_state.json",
    # The frozen dialogue manifest is what proves the GPT ratings were produced from the
    # planned inputs. It was previously treated as optional on both sides, so an archive could
    # drop it and still verify while the comparison's central identity claim went unbacked.
    "gpt/input_manifest.jsonl",
)
REQUIRED_BASE_OUTPUTS = (
    "per_turn.csv",
    "per_session.csv",
    "per_replicate.csv",
    "metrics_summary.json",
    "judge_inference.json",
    "policy_adjusted.json",
    "completeness.json",
    "provenance.json",
    "helpfulness_detail.json",
    "pedagogy_detail.json",
)

# ---------------------------------------------------------------- positive presence inventory
# WHY THIS EXISTS. Every other check in this file detects CORRUPTION or CONTAMINATION -- never
# OMISSION. `ARTIFACT-MANIFEST.sha256` is rendered from the same `payload` list the tar members
# are written from, so a file missing at BUILD time is absent from the manifest AND from the
# tree, both operands of the exhaustive check agree, and all checks PASS. That is not
# hypothetical: an archive once shipped carrying only the SUPERSEDED 07-19 amendment -- whose
# text says the transport is OpenAI-direct and "never OpenRouter" -- beside 7,074 OpenRouter
# ratings, with that document's [SUPERSEDED] markers pointing at a file that was not present.
# It verified 6/6. A human asking "what is this file?" caught what six automated PASSes could not.
#
# WHERE THE TRUST ANCHOR SITS -- the crux. This inventory is CODE, deliberately, not a generated
# data file. A generated inventory reproduces the bug exactly: omission requires NO action, since
# a file absent from `payload` is absent from the inventory too, and silence is the default
# outcome. A hardcoded constant inverts that -- the builder has no code path that writes, edits,
# or filters this file, so dropping an entry takes a deliberate, reviewable source edit, and
# silence stops being free. Three anchor layers, outermost first:
#   (A) OUTSIDE the archive: `dist/<archive>.tar.gz.sha256` and the freeze tag. Published in
#       README.md, this is the only check that survives a wholly substituted archive.
#   (B) PRE-BUILD, repo-side: tools/test_cross_judge_audit.py asserts
#       REQUIRED_ARTIFACT_PATHS <= collect_payload(), so a defective archive fails at TEST time
#       and is never built.
#   (C) IN-ARCHIVE: the presence check below, which is what a recipient actually runs.
#
# IT IS A FLOOR, NOT AN EQUALITY. Gaining an ordinary file requires no edit here; only promoting
# something to load-bearing does. An exact match against the payload would put this list in the
# path of every routine addition, which is how lists rot into being rubber-stamped -- and a
# rubber-stamped list is precisely the failure mode that produced this bug.
REQUIRED_ARTIFACT_PATHS = (
    # -- the verifier's own inputs and the manifest it checks -------------------------------
    "ARTIFACT-MANIFEST.sha256",
    "artifact/verify_artifact.py",
    # -- documents a recipient must receive --------------------------------------------------
    "LICENSE",
    "README.md",
    "requirements.txt",
    "paper-plan.md",
    "metric-amendment-2026-06-19.md",
    "cross-judge-amendment-2026-07-19.md",
    # Transport specification for the released second-judge scores.
    "cross-judge-amendment-openrouter-2026-07-20.md",
    # The only record of deviation from pre-registration, and the cited source for the advisory
    # leakage values in supplement/technical-appendix.md §1, which are NOT re-derivable from the
    # shipped raw logs.
    "decisions-log.md",
    # -- raw-log manifests -------------------------------------------------------------------
    "confirmatory-log-manifest.sha256",
    "crossmodel-gpt-log-manifest.sha256",
    "crossmodel-gemini-log-manifest.sha256",
    # -- frozen instruments: the rubrics and prompts the ratings were produced under ----------
    "supplement/judge_rubric.md",
    "supplement/judge_pedagogy_rubric.md",
    "supplement/independence_rubric.md",
    "supplement/prompts.md",
    "supplement/ablation_prompts.md",
    "supplement/second-judge-transport-disclosure.md",
    # Overflow from the 2026-07-09 length trim; the paper points readers at it, and its
    # sections 2 and 6 exist in no other packaged document.
    "supplement/technical-appendix.md",
    # -- headline result surfaces every reported number re-derives from ----------------------
    "results/confirmatory/inference.json",
    "results/confirmatory/metrics_summary.json",
    "results/confirmatory/per_turn.csv",
    "results/confirmatory/matched_budget.json",
    "results/confirmatory_gpt/inference.json",
    "results/confirmatory_gemini/inference.json",
    "results/condition_adjusted_sensitivity/analysis.json",
    "results/ablation/ablation_analysis.json",
    # -- the code that produced them ---------------------------------------------------------
    "analysis/run_cross_judge_audit.py",
)

# Surfaces that exist only AFTER the paid second-judge pass. Requiring these unconditionally
# would make every pre-live checkout fail, so they are tiered the same way the rest of this
# file already tiers pre- and post-live state (see `gpt_judge_layer`). Once the layer exists
# they are as mandatory as anything above: a published comparison whose own output is missing
# is exactly the kind of hole this check was added to close.
REQUIRED_AFTER_LIVE_JUDGE_PASS = (
    "results/judge_robustness/gpt-5.6-sol/comparison/comparison.json",
)


def live_judge_pass_present(root: Path = None) -> bool:
    """True once the paid second-judge layer exists, keyed on the same signal `gpt_judge_layer`
    uses to choose its post-live branch."""
    return ((root or ROOT) / "gpt-judge-wire-log-manifest.sha256").is_file()


def missing_required_failures() -> list[str]:
    """Files a recipient MUST receive, checked for PRESENCE.

    This is the only check here that can detect a build-time omission. Note it deliberately
    tests the extracted TREE, not the manifest: a file absent from both (the exact defect this
    guards) is invisible to any manifest-derived check."""
    required = list(REQUIRED_ARTIFACT_PATHS)
    if live_judge_pass_present():
        required += list(REQUIRED_AFTER_LIVE_JUDGE_PASS)
    missing = [rel for rel in required if not (ROOT / rel).is_file()]
    return [f"REQUIRED FILE MISSING FROM ARTIFACT: {rel}" for rel in missing]


def gpt_base_promotion_failures(base_dir: Path, base: str) -> list[str]:
    """A packaged live GPT base must be a CURRENT, COMPLETE, promoted output set.

    File presence alone is not enough: an incomplete rerun used to leave the previous run's
    detail files and analyses in place beside a new partial cache, and both would ship. The
    runner now promotes a complete attempt atomically and records `run_state.json` last, so
    verification requires that marker plus agreement between the promoted cache stamps, the
    stamps embedded in the detail files, and the stamps on the packaged per-rep caches."""
    failures = []
    state_path = base_dir / RUN_STATE_FILE
    if not state_path.is_file():
        return [f"missing {state_path.relative_to(ROOT)}: the packaged GPT outputs for base "
                f"{base!r} are not a verifiably complete promoted set"]
    try:
        state = json.loads(state_path.read_text())
    except json.JSONDecodeError as exc:
        return [f"unreadable {state_path.relative_to(ROOT)}: {exc}"]
    if state.get("state") != "complete" or state.get("complete") is not True:
        failures.append(
            f"{state_path.relative_to(ROOT)} reports state={state.get('state')!r} "
            f"complete={state.get('complete')!r}: base {base!r} was packaged with outputs a "
            "later incomplete scoring attempt invalidated")
        return failures
    # The whole promoted set must be present -- not just the caches and details.
    missing = [name for name in REQUIRED_BASE_OUTPUTS if not (base_dir / name).is_file()]
    if missing:
        failures.append(
            f"base {base!r} is missing promoted output(s) {missing}: "
            f"{state_path.relative_to(ROOT)} claims a complete set, so the archive was "
            "assembled from an incomplete result layer")
    # ...and the runner's own record of what it promoted must agree with what is required here,
    # so the two lists cannot drift apart silently.
    promoted = state.get("promoted_outputs")
    if promoted is None:
        failures.append(f"{state_path.relative_to(ROOT)} records no promoted_outputs list")
    elif set(promoted) != set(REQUIRED_BASE_OUTPUTS):
        failures.append(
            f"{state_path.relative_to(ROOT)} promoted_outputs "
            f"{sorted(set(promoted) ^ set(REQUIRED_BASE_OUTPUTS))} disagrees with the output set "
            "artifact verification requires; the runner and the verifier disagree about what a "
            "complete base is")
    stamps = state.get("cache_stamps") or {}
    for instrument in GPT_INSTRUMENTS:
        promoted = stamps.get(instrument)
        if promoted is None:
            failures.append(f"{state_path.relative_to(ROOT)} records no cache stamp for "
                            f"{instrument}")
            continue
        # The packaged layer must be PAID scores. Nothing here used to check the backend, so a
        # complete three-base MOCK rehearsal plus a (backend-blind) manifest verified as a live
        # second-judge layer -- with details literally reading "MOCK synthetic -- DO NOT
        # REPORT". Only "live" certifies: an offline-cache-only reconstruction promotes the
        # VALIDATED live cache stamps (the runner refuses any other source), so it still says
        # "live" here; a mock stamp, a missing backend, or a malformed stamp all fail.
        recorded = promoted.get("backend") if isinstance(promoted, dict) else None
        # strip()+lower(), matching _backends_in -- the wire check and this one must apply the
        # SAME normalization or a padded value passes one and fails the other.
        if str(recorded or "").strip().lower() != "live":
            failures.append(
                f"{state_path.relative_to(ROOT)} promoted stamp for {instrument} records "
                f"backend={recorded!r}, not 'live': base {base!r} is packaged as the "
                "second-judge layer but its scores were not produced by the paid live run")
            continue
        detail = base_dir / f"{instrument}_detail.json"
        if detail.is_file():
            try:
                if json.loads(detail.read_text()).get("stamp") != promoted:
                    failures.append(
                        f"{detail.relative_to(ROOT)} stamp differs from the promoted "
                        f"{RUN_STATE_FILE} stamp (outputs and run state disagree about which "
                        "scoring run produced them)")
            except json.JSONDecodeError as exc:
                failures.append(f"unreadable {detail.relative_to(ROOT)}: {exc}")
        cache = base_dir / "cache" / f"{instrument}_cache.json"
        if cache.is_file():
            try:
                if json.loads(cache.read_text()).get("stamp") != promoted:
                    failures.append(
                        f"{cache.relative_to(ROOT)} stamp differs from the promoted "
                        f"{RUN_STATE_FILE} stamp (the cache was re-scored after these outputs "
                        "were published)")
            except json.JSONDecodeError as exc:
                failures.append(f"unreadable {cache.relative_to(ROOT)}: {exc}")
    # completeness.json is REQUIRED (it is in REQUIRED_BASE_OUTPUTS) and must affirm completeness
    # -- it used to be inspected only when it happened to be present.
    completeness = base_dir / "completeness.json"
    if completeness.is_file():
        try:
            if json.loads(completeness.read_text()).get("complete") is not True:
                failures.append(f"{completeness.relative_to(ROOT)} reports complete=false")
        except json.JSONDecodeError as exc:
            failures.append(f"unreadable {completeness.relative_to(ROOT)}: {exc}")
    return failures


# Kept deliberately in step with tools/build_submission_artifact.py:live_gpt_artifacts -- the
# builder and the verifier must classify the same tree identically, or a build that succeeds
# produces an artifact that fails verification. Duplicated rather than imported by design: the
# verifier is the trust anchor inside an extracted artifact and must not import the analysis
# code it exists to check. tools/test_cross_judge_audit.py pins the two to the same verdicts.
PRE_LIVE_NAMES = frozenset({"plan.json", "input_manifest.jsonl", "protected-primary.sha256"})


def _transient(path: Path, root: Path) -> bool:
    return any(part.startswith("tmp.") for part in path.relative_to(root).parts)


def _backends_in(obj) -> list[str]:
    """Every value recorded under a "backend" key, at any depth -- the runner stamps it into
    many shapes (cache `stamp.backend`, detail top-level, `cache_stamps.<rubric>.backend`,
    `resolved.backend`, per wire record)."""
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
    """Backends recorded in one file, or None if it cannot be read as provenance (UNKNOWN --
    never treated as "mock"). A `wire/` file recording NO backend at all is also UNKNOWN: the
    live preflight's wire records carry none and are written before its abort gate, so stale
    mock siblings must not vouch a directory that holds paid records (see the builder)."""
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
    except Exception:  # noqa: BLE001
        return None
    return []


def _output_dir_of(path: Path, jr: Path) -> Path:
    d = path.parent
    while d != jr and d.name in ("cache", "wire"):
        d = d.parent
    return d


def live_gpt_artifacts(jr: Path) -> list[Path]:
    """Files that must be pinned by the wire/score manifest before they may ship: a directory's
    files are evidence UNLESS the directory proves it is MOCK. Only "mock" is positively
    unpaid; live, `offline-cache-only` (reconstructed FROM paid caches), `cache`, unknown,
    missing and unreadable all fail CLOSED. See the builder for the full rationale."""
    if not jr.is_dir():
        return []
    # Same exclusions as the packaging scope: a file that would never be packaged (.DS_Store,
    # __pycache__) can never be evidence that requires a manifest. See the builder.
    files = [p for p in jr.rglob("*")
             if p.is_file() and not p.is_symlink() and not _transient(p, jr)
             and p.name != ".DS_Store"
             and not (set(p.relative_to(jr).parts) & {"__pycache__", ".pytest_cache"})]
    by_dir: dict[Path, list[Path]] = {}
    for p in files:
        by_dir.setdefault(_output_dir_of(p, jr), []).append(p)

    evidence = []
    for out_dir, members in by_dir.items():
        payload = [p for p in members if p.name not in PRE_LIVE_NAMES]
        if not payload:
            continue
        backends: list[str] = []
        unknown = False
        for p in members:
            got = _file_backends(p)
            if got is None:
                unknown = True
            else:
                backends.extend(got)
        if not (backends and not unknown and all(b == "mock" for b in backends)):
            evidence.extend(payload)
    return sorted(evidence)


def gpt_wire_live_failures(base_dir: Path, base: str) -> list[str]:
    """Every packaged wire log must RECORD the paid run it is being certified as.

    Presence was already required, but never content: a wire log whose every record says
    backend="mock" (or that is empty, or unreadable) satisfied the layer. One parsed record
    with backend "live" is the requirement -- an offline-cache-only reconstruction appends
    nothing to the wire (100% cache hits), so the live run's records are still what the file
    contains."""
    failures = []
    for inst in GPT_INSTRUMENTS:
        wire = base_dir / "wire" / f"{inst}.jsonl"
        if not wire.is_file():
            continue                      # presence is reported separately by the caller
        try:
            live = 0
            with wire.open(encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    live += sum(1 for b in _backends_in(json.loads(line)) if b == "live")
        except Exception as exc:  # noqa: BLE001 - a pinned wire log must be readable
            failures.append(f"unreadable GPT wire log {wire.relative_to(ROOT)} for base "
                            f"{base!r}: {type(exc).__name__}: {exc}")
            continue
        if not live:
            failures.append(
                f"{wire.relative_to(ROOT)} records no live provider request: base {base!r} "
                "is packaged as the paid second-judge layer but its wire log holds no "
                "backend='live' record")
    return failures


def gpt_manifest_coverage_failures(manifest: Path, jr: Path) -> list[str]:
    """The wire/score manifest must pin EVERY packaged second-judge file, both directions.

    verify_manifest() only checks the files a manifest LISTS, so a manifest built before later
    scoring (or hand-pruned) verified while live files sat beside it unpinned. The scope rule
    mirrors tools/build_gpt_judge_manifest.py:_acceptable and the artifact builder's
    acceptable(): regular non-transient files, no __pycache__/.pytest_cache/.DS_Store. Entries
    must also LIE IN that scope: an entry pinning a transient file passes in-repo hash checks
    but fails only after extraction (the archive never contains it), a '..' segment would
    defeat the prefix rule, and duplicate lines are last-wins for a dict while the documented
    `shasum -a 256 -c` fails the same manifest."""
    failures = []
    seen: set[str] = set()
    try:
        for line in manifest.read_text().splitlines():
            if not line.strip():
                continue
            _, relative = line.split(None, 1)
            relative = relative.strip()
            if relative in seen:
                failures.append(f"duplicate manifest entry for {relative}")
            seen.add(relative)
    except Exception as exc:  # noqa: BLE001
        return [f"unreadable {manifest.name}: {type(exc).__name__}: {exc}"]
    entries = {Path(rel) for rel in seen}
    scope = {p.relative_to(ROOT) for p in jr.rglob("*")
             if p.is_file() and not p.is_symlink()
             and not (set(p.relative_to(ROOT).parts) & {"__pycache__", ".pytest_cache"})
             and p.name != ".DS_Store"
             and not _transient(p, jr)} if jr.is_dir() else set()
    failures += [f"unmanifested second-judge file {rel} (present but not pinned by "
                 f"{manifest.name})" for rel in sorted(scope - entries)]
    for rel in sorted(entries - scope):
        if ".." in rel.parts:
            failures.append(f"manifest entry {rel} contains a '..' path segment")
        elif not str(rel).startswith("results/judge_robustness/"):
            failures.append(f"manifest entry {rel} lies outside results/judge_robustness")
        else:
            failures.append(f"manifest entry {rel} pins a transient/excluded or absent file "
                            "the archive will not contain")
    return failures


def gpt_mock_contamination_failures(jr: Path) -> list[str]:
    """POST-live only: no file anywhere under the packaged layer may record backend="mock".

    The per-base promotion checks iterate the three known bases; a mock file OUTSIDE them (a
    leftover rehearsal directory, a stray fixture) was provenance-checked by nothing once a
    manifest existed. A legitimate post-live tree records only "live" (scoring, preflight) or
    "offline-cache-only"/"cache" (a reconstruction) -- never "mock"."""
    failures = []
    if not jr.is_dir():
        return failures
    for p in sorted(jr.rglob("*")):
        if not (p.is_file() and not p.is_symlink() and not _transient(p, jr)):
            continue
        recorded = _file_backends(p)
        if recorded and "mock" in recorded:
            try:                          # scan-root-safe: jr may lie outside this repo
                shown = p.relative_to(ROOT)
            except ValueError:
                shown = p.relative_to(jr)
            failures.append(f"{shown} records backend='mock': synthetic "
                            "rehearsal output is packaged inside the live second-judge layer")
    return failures


def gpt_judge_layer() -> tuple[list[str], str]:
    """Verify the second-judge (GPT-5.6 Sol) layer. Two states are legitimate:
      * PRE-live: only input manifests / protected hashes -- no live scores, no wire manifest.
      * POST-live: the wire/score manifest verifies AND all three bases carry both instruments'
        per-rep caches, detail files, and wire logs.
    Any other state fails: live artifacts without a manifest are unverifiable, and a manifest
    without a complete three-base layer would let a partial audit pass as whole."""
    manifest = ROOT / GPT_WIRE_MANIFEST
    jr = ROOT / "results" / "judge_robustness"
    # Inventory counts for the summary line only. Transient files are excluded so a leftover
    # `cache/tmp.lock.<instrument>_cache.json` is never reported as a packaged score cache.
    def _inv(pattern):
        return sorted(p for p in jr.glob(pattern)
                      if p.is_file() and not p.is_symlink() and not _transient(p, jr)
                      ) if jr.is_dir() else []
    caches = _inv("**/cache/*_cache.json")
    wires = _inv("**/wire/*.jsonl")
    details = _inv("**/*_detail.json")

    if not manifest.is_file():
        live = live_gpt_artifacts(jr)
        if live:
            return ([f"live GPT judge artifacts are packaged ({len(live)}: "
                     + ", ".join(str(p.relative_to(ROOT)) for p in sorted(live)[:6])
                     + (", ..." if len(live) > 6 else "")
                     + f") but {GPT_WIRE_MANIFEST} is MISSING -- the second-judge scores are "
                     "unmanifested and cannot be verified"],
                    "GPT layer unmanifested")
        return [], ("GPT-5.6 Sol judge layer: input manifests only, no live scores yet; "
                    "wire/score manifest not built (live run pending)")

    failures = verify_manifest(manifest)
    failures.extend(gpt_manifest_coverage_failures(manifest, jr))
    failures.extend(gpt_mock_contamination_failures(jr))
    root = jr / "gpt-5.6-sol"
    for base in GPT_BASES:
        for inst in GPT_INSTRUMENTS:
            cache = root / base / "cache" / f"{inst}_cache.json"
            if not cache.is_file():
                failures.append(f"missing GPT per-rep score cache {cache.relative_to(ROOT)} "
                                "(offline cache-only reconstruction impossible)")
            # the detail files are covered by REQUIRED_BASE_OUTPUTS in the promotion check below
        # Named per instrument, not `glob("*.jsonl")`: the docstring's POST-live contract is
        # that every base carries BOTH instruments' wire logs, and a wildcard let any single
        # stray .jsonl (a `tmp.` leftover included) stand in for the whole set.
        for inst in GPT_INSTRUMENTS:
            wire = root / base / "wire" / f"{inst}.jsonl"
            if not wire.is_file():
                failures.append(f"missing GPT wire log {wire.relative_to(ROOT)} for base "
                                f"{base!r}")
        failures.extend(gpt_wire_live_failures(root / base, base))
        failures.extend(gpt_base_promotion_failures(root / base, base))
    failures.extend(comparison_failures(root))
    return failures, (f"GPT-5.6 Sol judge layer: wire/score manifest verified; "
                      f"{len(caches)} caches, {len(wires)} wire logs, {len(details)} details "
                      f"across all {len(GPT_BASES)} bases; every base is a current complete "
                      "promoted output set with matching cache stamps")


def comparison_failures(root: Path) -> list[str]:
    """A packaged cross-judge comparison must be CURRENT with the data it was computed from.

    This check used to fail OPEN in three ways: a missing `comparison.json` returned success even
    beside a complete run_state; `comparison_sha256` and `inputs` were both optional; and only
    whatever bases and files happened to be listed were checked. Deleting the report, or
    stripping its bindings, and rebuilding the inventory manifests therefore produced an archive
    that verified while its integrity evidence was gone. Everything below is now mandatory."""
    comparison_dir = root / "comparison"
    report = comparison_dir / "comparison.json"
    state_path = comparison_dir / RUN_STATE_FILE
    if not report.is_file() and not state_path.is_file():
        return []          # genuinely pre-comparison: legitimate
    failures = []
    if not report.is_file():
        return [f"missing {report.relative_to(ROOT)} although "
                f"{state_path.relative_to(ROOT)} is packaged: the comparison's report is gone "
                "but its promotion record remains"]
    if not state_path.is_file():
        return [f"missing {state_path.relative_to(ROOT)}: the packaged comparison is not a "
                "verifiably complete promoted report"]
    try:
        state = json.loads(state_path.read_text())
    except json.JSONDecodeError as exc:
        return [f"unreadable {state_path.relative_to(ROOT)}: {exc}"]
    if state.get("state") != "complete" or state.get("complete") is not True:
        return [f"{state_path.relative_to(ROOT)} reports state={state.get('state')!r} "
                f"complete={state.get('complete')!r}: the packaged comparison.json is from a "
                "superseded or failed comparison run"]

    recorded = state.get("comparison_sha256")
    if not recorded:
        failures.append(f"{state_path.relative_to(ROOT)} records no comparison_sha256; the "
                        "packaged report cannot be tied to what was promoted")
    elif sha256(report) != recorded:
        failures.append(f"{report.relative_to(ROOT)} does not match the sha256 recorded when it "
                        "was promoted")

    inputs = state.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        return failures + [f"{state_path.relative_to(ROOT)} records no input bindings; the "
                           "comparison cannot be shown to correspond to any base outputs"]
    if set(inputs) != set(COMPARISON_BASES):
        failures.append(
            f"{state_path.relative_to(ROOT)} binds bases {sorted(inputs)} but the comparison is "
            f"declared over exactly {list(COMPARISON_BASES)}")
    for base, entry in sorted(inputs.items()):
        files = (entry or {}).get("files") or {}
        missing_labels = [lbl for lbl in REQUIRED_COMPARISON_INPUTS if lbl not in files]
        if missing_labels:
            failures.append(f"comparison bindings for base {base!r} omit {missing_labels}: an "
                            "incomplete binding cannot establish the report's freshness")
        for label, expected in sorted(files.items()):
            side, _, name = label.partition("/")
            side_dir = entry.get("opus_dir") if side == "opus" else entry.get("gpt_dir")
            if not side_dir:
                failures.append(f"comparison bindings for base {base!r} record no {side}_dir for "
                                f"{label}")
                continue
            target = ROOT / side_dir / name
            if not target.is_file():
                failures.append(f"comparison input {label} for base {base!r} "
                                f"({target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}) "
                                "is missing but was hashed when the comparison was published")
            elif sha256(target) != expected:
                failures.append(
                    f"comparison input {label} for base {base!r} changed after the comparison "
                    "was published: the packaged report no longer corresponds to this data")
    return failures


def sensitive_findings() -> list[str]:
    findings = []
    for path in sorted(p for p in ROOT.rglob("*") if p.is_file()):
        text = path.read_bytes().decode("utf-8", errors="ignore")
        for label, pattern in SENSITIVE_PATTERNS.items():
            match = pattern.search(text)
            if match:
                if label == "assigned API key" and "..." in match.group(0):
                    continue  # documented placeholder, not a credential
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(ROOT)}:{line}: {label}")
    return findings


def main() -> None:
    failures = []
    # FIRST: presence. Every check below is manifest-derived and therefore blind to a
    # build-time omission -- see REQUIRED_ARTIFACT_PATHS. Run it before the rest so a
    # hollowed-out archive fails on what is missing rather than passing on what remains.
    failures.extend(missing_required_failures())
    failures.extend(verify_manifest(ROOT / "ARTIFACT-MANIFEST.sha256", exhaustive=True))
    for family, manifest in LOG_MANIFESTS.items():
        failures.extend(verify_manifest(ROOT / manifest))
    failures.extend(inventory_failures())
    gpt_failures, gpt_note = gpt_judge_layer()
    failures.extend(gpt_failures)
    failures.extend(sensitive_findings())
    n_dirs = 30 * len(RAW_FAMILIES)
    if failures:
        print(f"FAIL artifact verification ({len(failures)} finding(s))")
        for failure in failures:
            print(f"  {failure}")
        raise SystemExit(1)
    n_required = len(REQUIRED_ARTIFACT_PATHS) + (
        len(REQUIRED_AFTER_LIVE_JUDGE_PASS) if live_judge_pass_present() else 0)
    print(f"PASS required-file inventory: all {n_required} documents, instruments, and result "
          "surfaces a recipient must receive are present"
          + ("" if live_judge_pass_present() else " (pre-live: post-live surfaces not yet due)"))
    print("PASS artifact payload manifest: every extracted file is covered and matches")
    print("PASS embedded raw-log manifests: Sonnet, GPT, and Gemini hashes match")
    print(f"PASS raw-log inventory: {n_dirs} run directories, {n_dirs * 3} files, "
          "three files per run")
    print("PASS score-cache inventory: helpfulness and pedagogy caches for all three Opus bases")
    print(f"PASS {gpt_note}")
    print("PASS sensitive-data scan: no home path, email, credential, or account-id match")


if __name__ == "__main__":
    main()
