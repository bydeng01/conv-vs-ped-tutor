"""Second-judge (GPT-5.6 Sol) robustness audit over the frozen confirmatory transcripts.

EPISTEMIC STATUS: prospectively specified post hoc cross-judge robustness analysis over
frozen transcripts (cross-judge-amendment-2026-07-19.md). Claude Opus 4.8 remains the
frozen PRIMARY judge. GPT-5.6 Sol is an additive ROBUSTNESS judge applied to the
already-collected transcripts. This runner never re-runs the student, the tutors, the
training protocol, or the Opus judge; it makes ZERO tutor / student / Anthropic / Gemini
calls. It scores the SAME visible-training tutor turns, over the SAME frozen answer-phase
window, using the EXACT frozen helpfulness (analysis/judge.py) and pedagogy
(analysis/judge_pedagogy.py) prompts and parsers -- imported, never re-implemented.

The prompt sent to GPT contains ONLY the student-visible dialogue + the frozen rubric,
exactly like the Opus pass (analysis.judge.dialogue_for_turn excludes PedTutor's internal
state_tracker; condition, policy name, base identity, canonical answer, leakage strings,
node names, and reference solutions are never in the prompt).

Modes (see the module CLI):
  --preflight         one SYNTHETIC (non-study) dialogue through both rubrics to resolve
                      the transport contract (model access, endpoint, reasoning field,
                      output-token field, seed support, returned model, parser, finish
                      reason, usage). Writes preflight/ and preflight/resolved_config.json.
  --manifest-only     OFFLINE: write input_manifest.jsonl + protected-primary.sha256 +
                      plan.json (expected unit/call counts). No provider calls.
  (default scoring)   the paid pass: score every unit x rubric x rep with cache + retry.
                      Requires a completed preflight. Writes final detail/CSV/analysis
                      files only after completeness (n_valid == 3 everywhere) passes.
  --offline-cache-only  reconstruct from the released per-rep cache with a hard tripwire:
                      any cache miss aborts (no provider call, no synthetic score).
  --judge-backend mock  OFFLINE plumbing with synthetic scores (do NOT report); exercises
                      the whole pipeline with no key.

Output namespace (enforced): results/judge_robustness/gpt-5.6-sol/<base>/ (never a
canonical results dir).
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import csv
import datetime as _dt
import hashlib
import inspect
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import judge as J          # noqa: E402  frozen helpfulness prompts/parser
from analysis import judge_pedagogy as JP  # noqa: E402  frozen pedagogy prompts/parser
from analysis import metrics as M        # noqa: E402  frozen dialogue/window/tables

# -------------------------------------------------------------------- constants
SCHEMA_VERSION = "cross-judge-1"
REQUESTED_MODEL = "openai/gpt-5.6-sol"   # the OpenRouter slug for the pinned Sol model; see
                                         # FROZEN_TRANSPORT below and the OpenRouter amendment
ALLOWED_NAMESPACE = ("results", "judge_robustness")
PLAN_FREEZE_TAG = "judge-robustness-openrouter-freeze"

# ---- transport freeze (cross-judge-amendment-openrouter-2026-07-19.md) --------------------
# The second judge is served through OpenRouter rather than OpenAI direct. This is a FREEZE
# AMENDMENT, forced by two empirically established faults on the OpenAI-direct route: an
# intermittent provider-side 401 "insufficient permissions" on 10-30% of byte-identical
# requests (rejected at the edge -- openai-processing-ms 177-306 on every failure vs 546-2083
# on every success, no overlap), which the fail-fast taxonomy correctly treats as FATAL and
# which therefore killed every batch; and a 1,350,000 token/day account cap against a
# ~7.4M-token batch, which no single base fits under.
#
# PROVENANCE RULE: the provider recorded in a cache stamp, a wire record, or provenance.json is
# always DERIVED from the configuration actually used (`_judge_provider`), never a literal. A
# rating stamped `openai` while the request went to openrouter.ai would be false provenance in
# a research artifact. `load_judge_cfg` allow-lists exactly the frozen provider below and
# refuses every other provider/endpoint pair, including a provider name that does not match its
# own endpoint.
FROZEN_TRANSPORT = {"openrouter": "https://openrouter.ai/api/v1"}

# OpenRouter routing pin, sent as `extra_body` on EVERY request (scoring, retry, preflight).
# Without it OpenRouter's documented default is "automatic failover to alternative providers
# when errors occur", and default routing was empirically observed serving Azure, not OpenAI.
#
# `order` takes the endpoint's `tag` (openai, openai/flex, openai/priority, azure, azure/eu) --
# NOT `provider_name`. Plain `openai` is frozen: flex/priority are service tiers with different
# latency and capacity behaviour. Verified: order=["openai"] served provider 'OpenAI' on 6/6
# consecutive calls, and a bogus tag is refused with 404 (negative control -- the pin is
# genuinely enforced, not advisory).
#
# `require_parameters` is deliberately ABSENT. It filters endpoints by OpenRouter's NORMALIZED
# parameter names, and `max_completion_tokens` is not among them (the endpoint advertises
# `max_tokens`), so including it 404s the whole route with "No endpoints found" on every call.
PROVIDER_PIN = {"provider": {"order": ["openai"], "allow_fallbacks": False}}

# The FIXED design a paid batch is allowed to run. A live run may not choose its own output
# path, source dir, rubric subset, or repetition count: those are the prospectively frozen
# design (amendment §2 / §5), and letting the CLI vary them is how a post-freeze `--manifest-only`
# could quietly re-baseline the batch onto a different corpus.
CANONICAL_OUT = {
    "sonnet": "results/judge_robustness/gpt-5.6-sol/sonnet",
    "gpt": "results/judge_robustness/gpt-5.6-sol/gpt",
    "gemini": "results/judge_robustness/gpt-5.6-sol/gemini",
}
CANONICAL_SOURCE = {
    "sonnet": "results/confirmatory",
    "gpt": "results/confirmatory_gpt",
    "gemini": "results/confirmatory_gemini",
}
REQUIRED_RUBRICS = ("helpfulness", "pedagogy")
REQUIRED_REPS = 3
# The plan artifacts that must be byte-identical to their versions inside PLAN_FREEZE_TAG.
FROZEN_PLAN_FILES = ("plan.json", "input_manifest.jsonl", "protected-primary.sha256")

# base tag (source metrics_summary "base") -> (human base name, extension freeze tag)
BASE_MAP = {
    "primary": ("sonnet", "confirmatory-freeze"),
    "gpt": ("gpt", "crossmodel-gpt-freeze"),
    "gemini": ("gemini", "crossmodel-gemini-freeze"),
}
# base name -> the source raw-log manifest that pins that base's transcripts
BASE_LOG_MANIFEST = {
    "sonnet": "confirmatory-log-manifest.sha256",
    "gpt": "crossmodel-gpt-log-manifest.sha256",
    "gemini": "crossmodel-gemini-log-manifest.sha256",
}

RUBRICS = {
    "helpfulness": {
        "system": J.JUDGE_SYSTEM, "user": J.JUDGE_USER,
        "parse": J.parse_judge_scores, "aggregate": J.aggregate_reps,
        "mean_key": "helpfulness_mean", "component": "helpfulness_judge",
        "rubric_file": "supplement/judge_rubric.md",
    },
    "pedagogy": {
        "system": JP.PED_SYSTEM, "user": JP.PED_USER,
        "parse": JP.parse_pedagogy_scores, "aggregate": JP.aggregate_reps,
        "mean_key": "pedagogy_mean", "component": "pedagogy_judge",
        "rubric_file": "supplement/judge_pedagogy_rubric.md",
    },
}

# A SYNTHETIC dialogue for the transport preflight -- deliberately NOT confirmatory or
# ablation text (a made-up arithmetic exchange), so no study unit is ever sent at preflight.
PREFLIGHT_DIALOGUE = (
    "Student: I need to work out 6 times 7 but I keep second-guessing myself.\n\n"
    "Tutor: Let's anchor it. You already know 6 times 7 is the same as six sevens added "
    "up, or you can lean on a fact you're sure of -- what is 6 times 5?\n\n"
    "Student: 6 times 5 is 30.\n\n"
    "Tutor: Good. Now you just need two more sixes on top of that 30. What do you get?"
)


# -------------------------------------------------------------------- small utilities
def _now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _scrub(s: str) -> str:
    """Redact the user segment of any absolute home path so released artifacts never leak a
    local username (mirrors analysis/run_inference.py:_scrub_paths)."""
    return re.sub(r'(/Users/|/home/)[^/\s"]+', r'\1<user>', s)


def _git(*args: str) -> Optional[str]:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def _git_bytes(*args: str) -> Optional[bytes]:
    """Raw (unstripped, undecoded) git stdout -- required for byte-for-byte `git show` blob
    comparison, where _git()'s text decoding and .strip() would hide trailing-newline and
    encoding differences."""
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                              check=True).stdout
    except Exception:  # noqa: BLE001
        return None


def _commit_of(ref: str) -> Optional[str]:
    """Resolve a ref to its COMMIT sha, peeling annotated tags (`<ref>^{commit}`).

    Bare `git rev-parse <annotated-tag>` yields the TAG OBJECT's sha, not the commit's. This
    repo already uses annotated tags (e.g. `crossmodel-freeze`), so an annotated
    `judge-robustness-gpt56-freeze` would make a `HEAD == tag` comparison always false and
    refuse every paid run, and would record a tag-object sha as the run's freeze commit.
    Peeling is fail-safe in both directions: an unresolvable ref still returns None."""
    return _git("rev-parse", f"{ref}^{{commit}}")


def _repo_rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(p)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_scrub(json.dumps(obj, indent=2, default=str)))


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _pkg_versions() -> dict:
    import numpy
    import scipy
    out = {"python": platform.python_version(), "numpy": numpy.__version__,
           "scipy": scipy.__version__}
    for name in ("pandas", "statsmodels", "openai"):
        try:
            out[name] = __import__(name).__version__
        except Exception:  # noqa: BLE001
            out[name] = None
    return out


def _enforce_namespace(out_dir: Path) -> None:
    """Refuse to write anywhere but results/judge_robustness/... -- never a canonical dir."""
    try:
        rel = out_dir.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        raise SystemExit(f"--out must be inside the repo (results/judge_robustness/...): {out_dir}")
    if rel.parts[:2] != ALLOWED_NAMESPACE:
        raise SystemExit(
            f"REFUSING to write to {rel}: the cross-judge audit may only write under "
            f"results/judge_robustness/ (it never touches results/confirmatory*, "
            f"results/ablation, or results/condition_adjusted_sensitivity).")


# -------------------------------------------------------------------- config loading
def _judge_provider(cfg: dict) -> Optional[str]:
    """The CONFIGURED provider name for the judge role, role-level first then top-level.

    Single source of truth for provider identity. Every stamp, hash, endpoint lookup and
    provenance record derives the provider from here rather than assuming a literal, so a
    rating can never be recorded as served by a provider other than the one actually called.
    """
    j = (cfg.get("roles") or {}).get("judge") or {}
    return j.get("provider") or cfg.get("provider")


def _provider_cfg(cfg: dict) -> dict:
    """The providers.<configured-provider> block (base_url / api_key_env)."""
    return (cfg.get("providers") or {}).get(_judge_provider(cfg)) or {}


def load_judge_cfg(models_path: str) -> dict:
    """Load a JUDGE-ONLY models config for the cross-judge runner.

    Requires ONLY roles.judge (so agents/config.py:load_models_config -- which requires
    tutor/student -- rejects it, and it can never drive the confirmatory runner). Validates
    the frozen transport contract: an ALLOW-LISTED provider paired with ITS OWN frozen
    endpoint, the requested model, explicit medium reasoning, temperature omitted, and an
    output-token limit.
    """
    import yaml
    p = Path(models_path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    cfg = yaml.safe_load(p.read_text()) or {}
    roles = cfg.get("roles") or {}
    if "judge" not in roles:
        raise SystemExit(f"{models_path}: cross-judge config must define roles.judge")
    j = roles["judge"]
    prov = _judge_provider(cfg)
    # ALLOW-LIST, not a free choice: exactly the provider frozen by the OpenRouter amendment.
    # Anything else -- including the superseded OpenAI-direct route and any other intermediary
    # -- is refused, so the transport can only ever change by amending this constant, which is
    # a tracked, dated, reviewable act.
    if prov not in FROZEN_TRANSPORT:
        raise SystemExit(
            f"{models_path}: judge.provider must be one of {sorted(FROZEN_TRANSPORT)!r} (the "
            f"transport frozen by cross-judge-amendment-openrouter-2026-07-19.md); got "
            f"{prov!r}. Changing the transport requires a new amendment, not a config edit.")
    pc = (cfg.get("providers") or {}).get(prov) or {}
    base_url = pc.get("base_url")
    want_url = FROZEN_TRANSPORT[prov]
    # The provider NAME and the endpoint must agree. This is the falsification trap the
    # amendment exists to close: naming the provider `openrouter` while pointing base_url at
    # api.openai.com (or vice versa) would stamp every rating with a provenance that does not
    # describe where the request actually went.
    if base_url != want_url:
        raise SystemExit(
            f"{models_path}: providers.{prov}.base_url must be {want_url!r} (the frozen "
            f"endpoint for provider {prov!r}); got {base_url!r}. The recorded provider name "
            "and the endpoint actually called must always describe the same route.")
    if not pc.get("api_key_env"):
        raise SystemExit(f"{models_path}: providers.{prov}.api_key_env is required")
    if not j.get("model"):
        raise SystemExit(f"{models_path}: judge.model is required")
    if j.get("model") != REQUESTED_MODEL:
        raise SystemExit(f"{models_path}: judge.model must be {REQUESTED_MODEL!r} (the pinned "
                         f"slug, not the movable alias); got {j.get('model')!r}")
    if "temperature" not in j or j["temperature"] is not None:
        raise SystemExit(f"{models_path}: judge.temperature must be explicitly null "
                         f"(the parameter is omitted from the request)")
    if j.get("reasoning_effort") != "medium":
        raise SystemExit(f"{models_path}: judge.reasoning_effort must be 'medium' (explicit)")
    if not j.get("max_tokens"):
        raise SystemExit(f"{models_path}: judge.max_tokens (output-token limit) is required")
    return cfg


# -------------------------------------------------------------------- stamps / hashes
def _instrument_stamp(instrument: str, backend: str, cfg: dict, seed_policy: str,
                      reps: int, returned_model: Optional[str]) -> dict:
    """The cache identity for one instrument. Binds everything that would change a score:
    schema, backend, provider/endpoint, requested+returned model, reasoning effort,
    temperature behavior, output-token limit, seed policy, rep count, the rubric text /
    system prompt / user template hashes, the parser code hash, and the second-judge-plan
    freeze. The dialogue hash lives per-entry (in the key), not here."""
    spec = RUBRICS[instrument]
    j = cfg["roles"]["judge"]
    pc = _provider_cfg(cfg)
    parse_src = inspect.getsource(spec["parse"])
    # Records the freeze the scores bind to. The REQUIREMENT that a live batch actually be
    # frozen is enforced by assert_live_freeze_state() in main() -- not here, because this
    # function also runs during offline reconstruction inside an extracted artifact, which has
    # no .git at all and must still be able to validate a released cache.
    plan_freeze = _commit_of(PLAN_FREEZE_TAG) or "unfrozen-dev"
    return {
        "schema_version": SCHEMA_VERSION,
        "instrument": instrument,
        "backend": backend,
        # DERIVED from the config, never a literal: a stamp that names a provider the request
        # did not go to is false provenance. `load_judge_cfg` has already proved this name and
        # `endpoint` below describe the same allow-listed route.
        "provider": _judge_provider(cfg),
        "endpoint": pc.get("base_url"),
        # The routing pin is part of the scoring identity: through a router, WHICH upstream
        # served the request can change the scores, so a routing change must invalidate the
        # cache exactly as a model or rubric change does.
        "provider_routing": PROVIDER_PIN,
        "requested_model": j.get("model"),
        "returned_model": returned_model,
        "reasoning_effort": j.get("reasoning_effort"),
        "temperature_behavior": "omitted",
        "max_completion_tokens": j.get("max_tokens"),
        "seed_policy": seed_policy,
        "reps": reps,
        "rubric_text_sha256": _sha256_file(REPO_ROOT / spec["rubric_file"]),
        "system_prompt_sha256": _sha256_text(spec["system"]),
        "user_template_sha256": _sha256_text(spec["user"]),
        "parser_code_sha256": _sha256_text(parse_src),
        "plan_freeze": plan_freeze,
    }


def _request_contract_sha256(cfg: dict) -> str:
    """Hash of everything that defines WHAT a scoring request is and how its reply is read.

    The preflight resolves and freezes a transport contract that the paid batch then relies on.
    Binding that contract to a hash lets scoring prove the preflight was run by *this* code
    against *this* configuration, rather than by some other checkout that happened to leave a
    resolved_config.json behind."""
    j = cfg["roles"]["judge"]
    pc = _provider_cfg(cfg)
    parts = [
        # Provider name DERIVED, and the routing pin folded in whole (including `order`), so a
        # routing change between the sonnet run and the gemini run cannot happen silently: it
        # changes this hash, which makes `_load_resolved` reject the preflight as STALE.
        SCHEMA_VERSION, str(_judge_provider(cfg)), str(pc.get("base_url")), str(j.get("model")),
        str(j.get("reasoning_effort")), "temperature=omitted", str(j.get("max_tokens")),
        "extra_body=" + json.dumps(PROVIDER_PIN, sort_keys=True, separators=(",", ":")),
    ]
    for instrument in sorted(RUBRICS):
        spec = RUBRICS[instrument]
        parts += [instrument, _sha256_text(spec["system"]), _sha256_text(spec["user"]),
                  _sha256_text(inspect.getsource(spec["parse"])),
                  _sha256_file(REPO_ROOT / spec["rubric_file"])]
    return _sha256_text("|".join(parts))


def cache_key(base: str, run_id: str, condition: str, replicate_id, problem_id,
              turn_index, rep: int, dialogue_sha: str) -> str:
    """Full unit identity + dialogue hash. Two units with coincidentally identical text
    still differ here (distinct run/problem/turn); a changed dialogue misses (invalidates)."""
    return f"{base}|{run_id}|{condition}|{replicate_id}|{problem_id}|{turn_index}|{rep}|{dialogue_sha}"


# -------------------------------------------------------------------- atomic cache
def _load_cache(cache_path: Path, stamp: dict) -> dict:
    try:
        blob = json.loads(cache_path.read_text())
    except Exception:  # noqa: BLE001 - absent or corrupt cache is just empty
        return {}
    if not isinstance(blob, dict) or blob.get("stamp") != stamp:
        return {}
    entries = blob.get("entries")
    return entries if isinstance(entries, dict) else {}


# The frozen-content fields of a stamp -- everything that fixes what a score means EXCEPT the
# run-specific returned_model / seed policy / plan freeze. Offline reconstruction validates
# these against the released cache without re-deriving the run-specific fields.
_STAMP_CONTENT_FIELDS = (
    # `provider` only became a real discriminator once it was DERIVED from config: while it was
    # the hardcoded literal "openai", this comparison was literal-against-literal and could
    # never fail, so the one control meant to catch a provider change was inert. `endpoint` has
    # always been derived, and `provider_routing` is included for the same reason -- through a
    # router, WHICH upstream served a rating is part of what produced the scores, so a released
    # cache must not be reusable under different routing.
    "schema_version", "instrument", "provider", "endpoint", "provider_routing",
    "requested_model",
    "reasoning_effort", "temperature_behavior", "max_completion_tokens", "reps",
    "rubric_text_sha256", "system_prompt_sha256", "user_template_sha256", "parser_code_sha256",
)


def _load_cache_reconstruction(cache_path: Path, instrument: str, cfg: dict, reps: int):
    """Offline reconstruction loader: read the released cache, take its stamp as-is (it
    carries the run-specific returned_model / seed policy / plan freeze), but VALIDATE that
    the frozen-content fields match what this checkout would produce -- so a released cache
    can only be reused with the byte-identical prompts, parser, model, and parameters."""
    try:
        blob = json.loads(cache_path.read_text())
    except Exception:  # noqa: BLE001
        raise SystemExit(f"--offline-cache-only: no readable cache at {cache_path}. Copy the "
                         "released cache into --out/cache/ first.")
    stamp = blob.get("stamp") if isinstance(blob, dict) else None
    entries = blob.get("entries") if isinstance(blob, dict) else None
    if not isinstance(stamp, dict) or not isinstance(entries, dict):
        raise SystemExit(f"--offline-cache-only: malformed cache at {cache_path}")
    # Only a real LIVE released cache may be reconstructed. A mock/synthetic cache (or any
    # non-live backend) must never be reconstructed as "released" scores (§ cache/resumability
    # and the do-not-report discipline).
    if stamp.get("backend") != "live":
        raise SystemExit(
            f"--offline-cache-only: cache at {cache_path} has backend={stamp.get('backend')!r}, "
            "not 'live'. Synthetic / mock scores are never reconstructed as released results.")
    # Per-ENTRY synthetic provenance, so flipping the stamp's `backend` cannot promote a mock
    # cache into reportable results. Also require the run-specific fields a real live cache
    # always carries; a hand-edited stamp that merely says "live" will not satisfy these.
    synthetic = [k for k, v in entries.items() if isinstance(v, dict) and v.get("synthetic")]
    if synthetic:
        raise SystemExit(
            f"--offline-cache-only: {len(synthetic)} entr(y/ies) in {cache_path} are marked "
            "synthetic (mock-generated). Refusing to reconstruct synthetic scores as released "
            f"results (e.g. {synthetic[:2]}).")
    if not stamp.get("returned_model"):
        raise SystemExit(
            f"--offline-cache-only: cache at {cache_path} records no returned_model; a released "
            "live cache always binds the served model identity. Refusing to reconstruct.")
    # seed_policy / returned_model are RUN-specific: they are not re-derivable offline and are
    # deliberately excluded from _STAMP_CONTENT_FIELDS. They are echoed back from the cache here
    # purely so `want` is faithful; agreement ACROSS the rubrics' caches is enforced separately
    # by _validate_reconstruction_stamps().
    want = _instrument_stamp(instrument, "live", cfg, stamp.get("seed_policy"), reps, None)
    mismatch = [k for k in _STAMP_CONTENT_FIELDS if stamp.get(k) != want.get(k)]
    if mismatch:
        raise SystemExit(
            f"--offline-cache-only: released cache stamp does not match this checkout for "
            f"{instrument} (differing: {mismatch}). The prompts, parser, model, or parameters "
            "changed since the cache was produced; refusing to reuse it.")
    return entries, stamp


# The RUN-level fields of a stamp. Every rubric's cache in one reconstruction must agree on all
# of them: they identify WHICH run produced the scores. Mixing them would let a reconstruction
# combine caches from two served models, two seed policies, or two plan freezes and report only
# whichever rubric happened to be loaded last.
_STAMP_RUN_FIELDS = ("returned_model", "seed_policy", "plan_freeze", "backend", "reps")


def _validate_reconstruction_stamps(stamps: dict) -> dict:
    """Cross-validate the per-rubric cache stamps of an offline reconstruction and return the
    single agreed run-level provenance.

    Offline mode used to initialize the run-level seed policy as the hardcoded literal
    "unseeded" and then let each rubric's returned_model overwrite a shared variable, so the
    LAST rubric silently won. A seeded live cache was therefore reconstructed with false
    top-level `unseeded` provenance, and caches from two different served models could be
    combined while the output named only one of them. All rubric stamps must now agree, and the
    agreed values are what the reconstructed outputs report.
    """
    if not stamps:
        raise SystemExit("offline reconstruction loaded no cache stamps; nothing to validate.")
    items = sorted(stamps.items())
    ref_name, ref = items[0]
    disagreements = []
    for name, st in items[1:]:
        for field in _STAMP_RUN_FIELDS:
            if st.get(field) != ref.get(field):
                disagreements.append(
                    f"{field}: {ref_name}={ref.get(field)!r} vs {name}={st.get(field)!r}")
    if disagreements:
        raise SystemExit(
            "--offline-cache-only: the rubric caches do not come from one run -- their stamps "
            "disagree on run-level provenance:\n  - " + "\n  - ".join(disagreements)
            + "\nRefusing to reconstruct: scores from different served models, seed policies, "
              "plan freezes, backends, or repetition counts must never be combined into one "
              "reported result.")
    validated = {field: ref.get(field) for field in _STAMP_RUN_FIELDS}
    if not validated.get("seed_policy"):
        raise SystemExit(
            "--offline-cache-only: the released cache stamps record no seed_policy; a live "
            "cache always binds one. Refusing to invent run-level provenance.")
    return validated


def _flush_cache(cache_path: Path, stamp: dict, cache: dict) -> None:
    """Atomic, crash-resumable flush under an exclusive flock. Merges any same-stamp entries
    already on disk (so a concurrent/earlier writer's paid entries are never dropped), then
    os.replace. A foreign stamp on disk means the config changed -> the loader already
    ignored it -> overwrite. Transient files keep the *_cache.json suffix so the namespace
    gitignore covers them."""
    import fcntl
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = cache_path.with_name("tmp.lock." + cache_path.name)
    with open(lock_path, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        merged = dict(cache)
        try:
            existing = json.loads(cache_path.read_text())
            if isinstance(existing, dict) and existing.get("stamp") == stamp:
                for k, v in (existing.get("entries") or {}).items():
                    merged.setdefault(k, v)
        except Exception:  # noqa: BLE001
            pass
        tmp = cache_path.with_name(f"tmp.{os.getpid()}.{cache_path.name}")
        tmp.write_text(json.dumps({"stamp": stamp, "entries": merged}, indent=2, default=str))
        os.replace(tmp, cache_path)


# -------------------------------------------------------------------- session loading
def _load_sessions(source_results: str):
    """Load (base, human_base, freeze_tag, freeze_head, sessions, runs_meta) from a frozen
    compute_metrics output dir. Sessions are analyzed over the frozen answer-phase window
    (M.analyze_session default). Cold sessions produce no training turns and are kept out."""
    d = Path(source_results)
    if not d.is_absolute():
        d = REPO_ROOT / d
    summ_path = d / "metrics_summary.json"
    if not summ_path.exists():
        raise SystemExit(f"no metrics_summary.json in {source_results}; point --source-results "
                         "at a frozen compute_metrics output dir (results/confirmatory*).")
    summ = json.loads(summ_path.read_text())
    base = summ.get("base", "primary")
    if base not in BASE_MAP:
        raise SystemExit(f"unrecognized base {base!r} in {summ_path}")
    human_base, freeze_tag = BASE_MAP[base]
    freeze_heads = [h for h in summ.get("freeze_heads", []) if h]
    freeze_head = freeze_heads[0] if freeze_heads else None

    pbi = M.problem_index("domain/algebra/problems.yaml")
    sessions, runs_meta = [], []
    for r in summ.get("runs", []):
        run_id = r["run_id"]
        rd = REPO_ROOT / "logs" / run_id
        if not (rd / "calls.jsonl").exists():
            raise SystemExit(f"missing raw log for {run_id}: {rd}/calls.jsonl (needed to "
                             "reconstruct the frozen dialogue).")
        sm = M.analyze_session(rd, pbi)
        sessions.append(sm)
        runs_meta.append({"run_id": run_id, "condition": sm.condition,
                          "replicate_id": sm.replicate_id, "seed": r.get("seed"),
                          "log_dir": _repo_rel(rd)})
    return {"base": base, "human_base": human_base, "freeze_tag": freeze_tag,
            "freeze_head": freeze_head, "source_results": _repo_rel(d),
            "sessions": sessions, "runs_meta": runs_meta, "pbi": pbi}


def _planned_units(loaded) -> list[dict]:
    """Every planned (turn) unit across the base: one dict per visible training tutor turn,
    carrying the full key tuple + the reconstructed dialogue and its sha256. This is the
    single source of truth for what gets judged; it is byte-identical to the turn selection
    the Opus pass used (same analysis.judge.judge_session loop, no-op judge)."""
    base = loaded["base"]
    pbi = loaded["pbi"]
    units = []
    for sm in loaded["sessions"]:
        rows = J.judge_session(sm, pbi, judge_fn=lambda *a, **k: None, reps=0)
        for row in rows:
            dialogue = J.dialogue_for_turn(sm, _vt_for(sm, row["problem_id"], row["turn_index"]))
            units.append({
                "base": base, "run_id": sm.run_id, "condition": row["condition"],
                "replicate_id": row["replicate_id"], "problem_id": row["problem_id"],
                "turn_index": row["turn_index"], "dialogue": dialogue,
                "dialogue_sha256": _sha256_text(dialogue),
                "log_dir": _repo_rel(REPO_ROOT / "logs" / sm.run_id),
            })
    return units


def _vt_for(sm, problem_id, turn_index):
    for vt in sm.visible_turns:
        if vt.problem_id == problem_id and vt.turn_index == turn_index:
            return vt
    raise KeyError((sm.run_id, problem_id, turn_index))


# -------------------------------------------------------------------- transport error taxonomy
#
# Re-checked against OPENROUTER's error shapes, which differ from OpenAI direct. Two of them
# would be misclassified by the original lists, in both dangerous directions:
#
#   * 404 "No endpoints found" -- an UNROUTABLE pin (e.g. a bogus provider tag, or
#     `require_parameters` filtering on normalized names `max_completion_tokens` is not among).
#     It contains "not found", so it is FATAL, which is correct and must stay correct: it fails
#     on EVERY call, so retrying it would burn the spend ceiling on a route that can never work.
#     Kept fatal deliberately, and listed here so a future edit cannot make it "transient".
#
#   * 401 "Missing Authentication header" -- observed on a burst of UNPACED requests and NOT a
#     real auth failure (the same key authenticates before and after). The original taxonomy
#     classified every 401 as fatal via `openai.AuthenticationError` and the "authenticat"
#     substring, which would kill a whole batch on an edge-side throttle. This one specific
#     message is treated as TRANSIENT, checked BEFORE the fatal auth rules. Every OTHER 401 --
#     a genuinely bad or unauthorized key -- stays fatal, because retrying it is pointless.
_TRANSIENT = ("rate", "429", "timeout", "overloaded", "503", "502", "temporarily",
              "connection", "per minute", "tpm", "rpm")
_FATAL = ("authenticat", "permission", "invalid api key", "no access", "does not exist",
          "not found", "model_not_found", "insufficient_quota", "exceeded your current quota")
# Edge-side throttling that presents AS an auth error. Narrow on purpose: a substring this
# specific cannot swallow a real credential failure. Retried under the same bounded, logged
# backoff as any other transient, so it can never retry unboundedly.
_TRANSIENT_AUTH = ("missing authentication header",)
# Unroutable-pin messages, kept FATAL explicitly (they already match "not found", but the
# routing pin is new and this must not silently become retryable).
_UNROUTABLE = ("no endpoints found", "no allowed providers", "no endpoints match")
# Per-DAY / quota caps do not reset within a backoff window -> fail fast (brief: quota fails
# fast). Per-MINUTE limits are transient. Checked before the generic 'rate' token.
_DAILY = ("per day", "rpd", "tpd", "tokens per day", "daily",
          "insufficient_quota", "exceeded your current quota")
_PER_MINUTE = ("per minute", "tpm", "rpm")


def _categorize_error(e) -> str:
    """Classify a transport error as 'fatal' (fail fast), 'transient' (retry with backoff),
    or 'other' (raise). Prefer the OpenAI SDK exception TYPE (robust to message wording);
    fall back to substring matching for non-SDK exceptions. Auth / permission / not-found /
    exhausted-quota and per-DAY rate caps fail fast; per-minute rate limits, timeouts,
    connection drops, and 5xx retry.

    Message-shape checks run BEFORE the SDK-type checks for the two OpenRouter cases where the
    HTTP status alone is misleading (see the taxonomy notes above): an unroutable pin is fatal
    even though it is a 404 that could be read as a missing model, and the edge-side
    "Missing Authentication header" 401 is transient even though its type is AuthenticationError.
    """
    m0 = str(e).lower()
    if any(s in m0 for s in _UNROUTABLE):
        return "fatal"
    if any(s in m0 for s in _TRANSIENT_AUTH):
        return "transient"
    try:
        import openai
        if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError,
                          openai.NotFoundError)):
            return "fatal"
        if isinstance(e, openai.RateLimitError):
            m = str(e).lower()
            if any(s in m for s in _DAILY) and not any(s in m for s in _PER_MINUTE):
                return "fatal"      # per-day cap / exhausted quota -> won't reset in backoff
            return "transient"      # per-minute (TPM/RPM) limit
        if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError,
                          openai.InternalServerError)):
            return "transient"
        if isinstance(e, openai.APIStatusError):
            code = getattr(e, "status_code", None)
            if code in (500, 502, 503, 504):
                return "transient"
            if code in (401, 403, 404):
                return "fatal"
    except Exception:  # noqa: BLE001 - SDK import/shape issues fall back to substrings
        pass
    m = str(e).lower()
    per_minute = any(s in m for s in _PER_MINUTE)
    if (not per_minute) and any(s in m for s in _DAILY):
        return "fatal"
    if any(s in m for s in _FATAL):
        return "fatal"
    if any(s in m for s in _TRANSIENT):
        return "transient"
    return "other"


# Spend containment. The amendment authorizes 7,074 RATINGS; the retry policy allows up to three
# attempts per rating, so a systematic production failure (a parser that never matches, a served
# model that always truncates) could quietly issue 3x that in completed, billable responses
# across the whole corpus before completeness is ever evaluated. The authorized number was only
# ever an expectation in a document -- nothing in the runner enforced it.
DEFAULT_RETRY_ALLOWANCE = 0.10   # fraction of planned calls reserved for legitimate retries
BREAKER_WARMUP_CALLS = 60        # don't judge the accept rate on a handful of RESPONSES
BREAKER_MIN_ACCEPT_RATE = 0.5    # >half the calls unusable => stop, something is systemically wrong


SPEND_LEDGER_FILE = "spend_ledger.json"


class _SpendLedger:
    """CUMULATIVE, persisted HTTP-attempt accounting for one base, across invocations.

    A per-invocation ceiling is not an authorization. `score_base` built a fresh budget with the
    full allowance every time it ran, so attempts spent by an earlier canary, by parse failures,
    or by terminal transport retries were forgotten on the next run -- and the canary-then-resume
    workflow this project *recommends* is exactly the sequence that resets it. N resumes could
    spend N x the authorized amount while every individual process stayed under its cap.

    The ledger is the durable side of the ceiling: `--max-provider-calls` is a LIFETIME
    authorization for the base, not a per-process one. Raising it is an explicit, recorded act.
    It is written on every charge (a few hundred microseconds against a multi-second network
    call) so a crash cannot silently forget spend, and it is only ever touched while the caller
    holds the per-base run lock.
    """

    def __init__(self, path: Path, authorized_total: int, live: bool = False,
                 provider: Optional[str] = None):
        self.path = path
        self.authorized_total = int(authorized_total)
        # The ledger is keyed by BASE DIRECTORY, not by provider, so spend made against a
        # DIFFERENT provider persists in this file across a transport amendment. `backend`
        # already carves out mock-vs-live for exactly this class of bug (a mock rehearsal was
        # consuming the paid allowance); provider is the same problem one level down, and rows
        # are labeled with it from here on. See `_adopt` for how prior rows are treated.
        self.provider = provider
        # Only a LIVE paid run can lose real spend to a lost ledger. Mock and reconstruction
        # runs issue no billable request, so the missing-ledger refusal below would be pure
        # false positive there.
        self.live = bool(live)
        self.prior_attempts = 0    # the CURRENT regime's prior spend (what the ceiling charges)
        self.file_total = 0        # sum over ALL rows regardless of regime (file invariant)
        self.prior_authorized = None
        self.invocations = []
        self._load()

    # How to recover a lost or damaged ledger, stated accurately. The wire log is NOT a
    # per-HTTP-request journal: `_write_wire` runs once per rating ATTEMPT, transport retries
    # are a COUNT inside that record, and a call whose transport retries are all exhausted
    # raises before any record is written. Telling an operator to "reconstruct the attempt
    # count from the wire log" therefore under-counts real spend by exactly the retries the
    # per-request charge exists to capture -- the fail-OPEN direction, in the one message
    # printed when the fail-closed gates fire.
    _RECOVERY = (
        "To recover: prefer a previously promoted provenance.json for this base, whose "
        "spend_containment.spend_ledger.http_attempts_total is the exact lifetime figure. "
        "Failing that, the wire log gives only a LOWER BOUND -- it holds one record per "
        "rating ATTEMPT (transport retries are the `transport_retries` count inside each "
        "record, and an attempt whose retries were all exhausted wrote no record at all), so "
        "requests >= (records) + (sum of transport_retries). Re-authorize "
        "--max-provider-calls from a deliberately CONSERVATIVE estimate above that bound; the "
        "ledger is cumulative and never rewinds, so over-stating prior spend is the safe "
        "direction and under-stating it silently replenishes the allowance.")

    def _corrupt(self, why: str) -> None:
        raise SystemExit(
            f"SPEND LEDGER CORRUPT: {_repo_rel(self.path)} {why}. A ledger that cannot be "
            "trusted must NOT be read as zero prior spend -- that silently replenishes the "
            "lifetime authorization, which is the one thing this file exists to prevent. "
            f"Refusing to run. {self._RECOVERY}")

    def _live_spend_evidence(self) -> list[str]:
        """Traces that billable requests were already issued for this base.

        Distinguishes a genuinely fresh base from one whose ledger was deleted or never
        restored. Deliberately conservative: only LIVE-stamped caches and wire records
        actually marked `backend == "live"` count, so a mock run can never trip it.

        The file selection is EXACT, never a glob. `_flush_cache` leaves a zero-byte
        `cache/tmp.lock.<instrument>_cache.json` behind, which `glob("*_cache.json")` matched
        and `json.loads` rejected -- so the mock rehearsal the handoff prescribes before paying
        made the FIRST live run on every base abort claiming spend that never happened, and
        told the operator to reconstruct a ledger from nothing. An unparseable file is only
        evidence when it is a file this runner would actually have written ratings into."""
        base_dir, found = self.path.parent, []
        wire_dir = base_dir / "wire"
        for name in sorted(RUBRICS):
            p = wire_dir / f"{name}.jsonl"
            if not p.is_file():
                continue
            live_records = 0
            try:
                for line in p.read_text().splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001 - a truncated tail is still a request
                        live_records += 1
                        continue
                    if str((rec or {}).get("backend", "")).lower() == "live":
                        live_records += 1
            except Exception:  # noqa: BLE001 - a wire log we cannot read may hold paid records
                found.append(f"an unreadable provider wire log ({_repo_rel(p)})")
                continue
            if live_records:
                found.append(f"{live_records} logged LIVE provider request(s) in "
                             f"{_repo_rel(p)}")
        for name in sorted(RUBRICS):
            p = base_dir / "cache" / f"{name}_cache.json"
            if not p.is_file():
                continue
            try:
                blob = json.loads(p.read_text())
            except Exception:  # noqa: BLE001 - unreadable paid cache is itself evidence
                found.append(f"an unreadable per-rep cache ({_repo_rel(p)})")
                continue
            if str(((blob or {}).get("stamp") or {}).get("backend", "")).lower() == "live":
                found.append(f"a LIVE-stamped per-rep cache ({_repo_rel(p)})")
        return found

    def _load(self) -> None:
        if not self.path.exists():
            # A missing ledger is legitimate only on a base that has never spent. The file is
            # gitignored (it must be, or a resumed paid run would dirty the tree and its own
            # freeze gate would refuse it), so neither the clean-tree gate nor
            # protected-primary.sha256 covers it: deleting it is invisible to every other
            # control. If the base carries evidence of paid requests, refuse.
            evidence = self._live_spend_evidence() if self.live else []
            if evidence:
                raise SystemExit(
                    "SPEND LEDGER MISSING BESIDE EVIDENCE OF PAID SPEND: "
                    f"{_repo_rel(self.path)} does not exist, but this base already carries "
                    f"{'; '.join(evidence)}. The ledger is the only durable record of HTTP "
                    "requests that were billed -- including requests that never produced a "
                    "usable rating -- and it is gitignored, so its absence is caught by no "
                    "other gate. Refusing to run: continuing would hand this invocation a "
                    f"full fresh lifetime allowance. {self._RECOVERY}")
            return
        try:
            blob = json.loads(self.path.read_text())
        except Exception as e:  # noqa: BLE001 - an unreadable ledger FAILS CLOSED
            raise SystemExit(
                f"SPEND LEDGER UNREADABLE: {_repo_rel(self.path)} exists but could not be "
                f"parsed ({type(e).__name__}: {e}). Reading it as a fresh ledger would forget "
                "spend that was actually made and re-authorize the full lifetime allowance. "
                "Refusing to run. Delete it ONLY after confirming no paid request was ever "
                f"issued for this base. {self._RECOVERY}") from e
        self._adopt(blob)
        if self.authorized_total < self.prior_attempts:
            raise SystemExit(
                f"SPEND AUTHORIZATION BELOW SPEND ALREADY MADE: {_repo_rel(self.path)} records "
                f"{self.prior_attempts} HTTP request(s) already issued for this base, but this "
                f"run authorizes only {self.authorized_total}. Refusing to run: the ledger is "
                "cumulative and never rewinds. Raise --max-provider-calls deliberately, or "
                "investigate why prior spend was higher than expected.")

    def _adopt(self, blob) -> None:
        """Validate the persisted shape before trusting it.

        Every rejected case below used to fall through to `prior_attempts = 0`: a truncated
        write, a partially-restored operational state, or a hand-edited file all read as a
        fresh ledger and admitted another full allowance. The internal-consistency check is
        the load-bearing one -- `persist` always writes `http_attempts_total` equal to the sum
        of its invocation records, so a disagreement means the file was damaged or edited."""
        def is_count(v) -> bool:
            return isinstance(v, int) and not isinstance(v, bool) and v >= 0

        if not isinstance(blob, dict):
            self._corrupt(f"holds a {type(blob).__name__}, not a JSON object")
        total = blob.get("http_attempts_total")
        if not is_count(total):
            self._corrupt(f"records http_attempts_total={total!r}, which is not a "
                          "non-negative integer")
        invocations = blob.get("invocations")
        if not isinstance(invocations, list):
            self._corrupt(f"records invocations={invocations!r}, which is not a list")
        counted = 0
        for i, inv in enumerate(invocations):
            if not isinstance(inv, dict):
                self._corrupt(f"invocation #{i} is a {type(inv).__name__}, not an object")
            n = inv.get("http_attempts")
            if not is_count(n):
                self._corrupt(f"invocation #{i} records http_attempts={n!r}, which is not a "
                              "non-negative integer")
            counted += n
        if counted != total:
            self._corrupt(f"is internally inconsistent: http_attempts_total={total} but its "
                          f"{len(invocations)} invocation record(s) sum to {counted}")
        prior_authorized = blob.get("authorized_total")
        if prior_authorized is not None and not is_count(prior_authorized):
            self._corrupt(f"records authorized_total={prior_authorized!r}, which is neither "
                          "absent nor a non-negative integer")
        # The ceiling charges against the CURRENT REGIME's prior spend, not the file total. A
        # mock rehearsal on the canonical base dirs used to persist thousands of simulated
        # "HTTP attempts" into this same file, so the first paid batch started with most of its
        # lifetime allowance already consumed by spend that was never billed -- and its
        # exhaustion message pressured the operator into a false re-authorization. Only rows
        # EXPLICITLY labeled with the other regime are excluded; unlabeled (legacy) rows count
        # for both regimes, because over-stating prior spend is the safe direction.
        other = "mock" if self.live else "live"
        excluded = sum(inv["http_attempts"] for inv in invocations
                       if inv.get("backend") == other)
        if excluded and self.live:
            print(f"spend ledger: excluding {excluded:,} MOCK-rehearsal request(s) from the "
                  "paid allowance (simulated, never billed)")
        # PROVIDER dimension, same rule and the same conservative default as `backend`: only
        # rows EXPLICITLY labeled with a DIFFERENT provider are excluded. Rows with no provider
        # label -- every row written before the OpenRouter amendment, including the 6 attempts
        # (3 paid ratings + 3 spurious 401s) from the abandoned OpenAI-direct runs on the
        # `sonnet` base -- still COUNT against this allowance. That is deliberate: over-stating
        # prior spend is the safe direction, it costs a handful of attempts out of thousands,
        # and it means no one has to hand-edit a record of real paid spend to proceed. The
        # rows stay in the file as evidence, which is what `_live_spend_evidence` needs them
        # for. See cross-judge-amendment-openrouter-2026-07-19.md.
        prov_excluded = 0
        if self.provider:
            prov_excluded = sum(inv["http_attempts"] for inv in invocations
                                if inv.get("provider")
                                and inv.get("provider") != self.provider
                                and inv.get("backend") != other)
            if prov_excluded and self.live:
                print(f"spend ledger: excluding {prov_excluded:,} request(s) made against a "
                      f"DIFFERENT provider from the {self.provider!r} allowance")
        unlabeled = sum(inv["http_attempts"] for inv in invocations
                        if not inv.get("provider") and inv.get("backend") != other)
        if unlabeled and self.live and self.provider:
            print(f"spend ledger: counting {unlabeled:,} request(s) with NO provider label "
                  f"against the {self.provider!r} allowance (conservative: an unlabeled row "
                  "predates provider labeling and may or may not be this provider's spend)")
        self.file_total = total
        self.prior_attempts = total - excluded - prov_excluded
        self.prior_authorized = prior_authorized
        self.invocations = invocations

    def note_authorization_change(self) -> Optional[str]:
        if self.prior_authorized is None or self.prior_authorized == self.authorized_total:
            return None
        return (f"lifetime authorization changed {self.prior_authorized} -> "
                f"{self.authorized_total}")

    def persist(self, this_run_attempts: int) -> None:
        # `http_attempts_total` stays the sum over ALL invocation rows regardless of regime --
        # that equality is the file-integrity invariant `_adopt` checks. The REGIME-relevant
        # prior (what the ceiling charges against) is computed at load from the per-row
        # `backend` labels; `remaining` reports the current regime's remaining allowance.
        payload = {
            "base_dir": _repo_rel(self.path.parent),
            "authorized_total": self.authorized_total,
            "http_attempts_total": self.file_total + this_run_attempts,
            "remaining": max(0, self.authorized_total - self.prior_attempts - this_run_attempts),
            "note": "CUMULATIVE across invocations. --max-provider-calls is a lifetime "
                    "authorization for this base, not a per-run one; resuming does not "
                    "replenish it. Rows are labeled by backend AND provider; a run counts "
                    "rows from its own regime plus UNLABELED rows, and excludes rows "
                    "explicitly labeled with the other backend or a different provider -- so "
                    "a mock rehearsal never consumes the paid allowance, and spend made "
                    "against a superseded transport never consumes the current one, while an "
                    "unlabeled legacy row is still counted (over-stating prior spend is the "
                    "safe direction).",
            "invocations": [*self.invocations,
                            {"pid": os.getpid(), "utc": _now_utc(),
                             "backend": "live" if self.live else "mock",
                             "provider": self.provider,
                             "http_attempts": this_run_attempts}],
        }
        tmp = self.path.with_name(f"tmp.{os.getpid()}.{self.path.name}")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, indent=2))
        os.replace(tmp, self.path)

    def summary(self, this_run_attempts: int) -> dict:
        return {"ledger": _repo_rel(self.path),
                "provider": self.provider,
                "authorized_total_lifetime": self.authorized_total,
                "http_attempts_before_this_run": self.prior_attempts,
                "http_attempts_this_run": this_run_attempts,
                "http_attempts_total": self.prior_attempts + this_run_attempts,
                "remaining": max(0, self.authorized_total - self.prior_attempts
                                 - this_run_attempts),
                "prior_invocations": len(self.invocations)}


class _Budget:
    """A hard ceiling on HTTP requests, plus an early circuit breaker on unusable responses.

    The ceiling counts **every HTTP request**, including transport retries. Charging once per
    logical rating attempt was not enough: `_Caller.call` retries transient failures up to five
    times internally, so one charge could cover five real requests -- a measured 5x bypass of a
    limit documented as "charged before every request, retries included". Only a per-request
    charge makes the authorization enforceable rather than aspirational.

    Two counters, two jobs, deliberately not conflated:
      * `http_attempts` bounds SPEND -- it is what leaves the process and can be billed.
      * `responses` / `accepted` drive the BREAKER, which is about response QUALITY. A
        rate-limit storm inflates http_attempts without saying anything about whether the
        served model still produces usable ratings, so the breaker must not read it.

    Setting the cap small is also the canary: the run stops at it with its cache intact, the
    operator inspects the wire log, then re-runs with the full authorization and pays only for
    what is still missing.
    """

    def __init__(self, max_http_attempts: int, warmup: int = BREAKER_WARMUP_CALLS,
                 min_accept_rate: float = BREAKER_MIN_ACCEPT_RATE,
                 ledger: Optional["_SpendLedger"] = None):
        self.max_http_attempts = int(max_http_attempts)
        self.warmup = int(warmup)
        self.min_accept_rate = float(min_accept_rate)
        self.http_attempts = 0
        self.responses = 0
        self.accepted = 0
        # Spend already made for this base in EARLIER invocations. The ceiling applies to the
        # lifetime total, so a resume continues the count instead of restarting it.
        self.ledger = ledger
        self.prior_attempts = ledger.prior_attempts if ledger is not None else 0

    @property
    def total_attempts(self) -> int:
        return self.prior_attempts + self.http_attempts

    def charge(self, where: str, attempt: Optional[int] = None) -> None:
        """Reserve ONE HTTP request. Raises BEFORE that request is issued."""
        if self.total_attempts >= self.max_http_attempts:
            retry_note = "" if attempt in (None, 1) else f" (transport retry #{attempt}) "
            prior = (f"{self.prior_attempts} in earlier invocation(s) + {self.http_attempts} in "
                     f"this one" if self.prior_attempts else f"{self.http_attempts}")
            raise SystemExit(
                f"PROVIDER-CALL BUDGET EXHAUSTED at {self.total_attempts} HTTP request(s) "
                f"({prior}; LIFETIME cap {self.max_http_attempts}) {where}{retry_note}. Stopping "
                "before issuing another request. The cache holds every rating already scored, so "
                "re-running pays only for what is still missing -- but the ceiling is cumulative, "
                "so resuming does NOT replenish it. Raising --max-provider-calls is an explicit "
                "re-authorization and is recorded in the spend ledger. If the cap was not "
                f"expected to bind, inspect the wire log first: {self.total_attempts} attempts "
                f"for {self.responses} responses means requests are being retried, not that the "
                "corpus grew.")
        self.http_attempts += 1
        if self.ledger is not None:
            # Persisted per charge: a crash must never forget spend that was actually made.
            self.ledger.persist(self.http_attempts)

    def record(self, accepted: bool, where: str) -> None:
        """One response was received and evaluated. Drives the quality circuit breaker."""
        self.responses += 1
        if accepted:
            self.accepted += 1
        if self.responses >= self.warmup:
            rate = self.accepted / self.responses
            if rate < self.min_accept_rate:
                raise SystemExit(
                    f"CIRCUIT BREAKER: only {self.accepted}/{self.responses} provider responses "
                    f"({rate:.0%}) produced a usable rating, below the {self.min_accept_rate:.0%} "
                    f"floor {where}. Stopping early rather than spending the rest of the budget "
                    "on a systematic failure. Inspect the wire log: a near-zero rate usually "
                    "means the served model, the response shape, or the parser contract changed.")

    def summary(self) -> dict:
        out = {"max_provider_calls": self.max_http_attempts,
               "http_attempts_used": self.http_attempts,
               "http_attempts_lifetime": self.total_attempts,
               "responses_evaluated": self.responses,
               "accepted_ratings": self.accepted,
               "attempts_per_response": (self.http_attempts / self.responses)
                                        if self.responses else None,
               "accept_rate": (self.accepted / self.responses) if self.responses else None,
               "ceiling_counts": "every HTTP request, including transport retries; CUMULATIVE "
                                 "across invocations (resuming does not replenish it)",
               "breaker_warmup_responses": self.warmup,
               "breaker_min_accept_rate": self.min_accept_rate}
        if self.ledger is not None:
            out["spend_ledger"] = self.ledger.summary(self.http_attempts)
        return out


def default_max_provider_calls(n_units: int, n_rubrics: int, reps: int,
                               allowance: float = DEFAULT_RETRY_ALLOWANCE) -> int:
    """The authorized call count plus a bounded allowance for BOTH retry kinds.

    The ceiling bounds HTTP requests, so the allowance has to absorb parse retries and
    transport retries together. If it binds, that is informative rather than merely
    inconvenient: the run stops safely and resumably, and the operator raises it knowing why."""
    import math
    planned = n_units * n_rubrics * reps
    return planned + math.ceil(planned * allowance)


class _Caller:
    """Issues one frozen GPT-5.6 Sol Chat Completions call and returns the raw SDK response.
    The endpoint and the API-key environment variable come from the ALLOW-LISTED provider block
    in the config (never a literal), and every request carries the frozen OpenRouter routing pin
    so the upstream cannot silently fail over. No fallback of provider or model. Temperature is
    OMITTED; reasoning_effort=medium and max_completion_tokens are sent; seed only when the
    resolved policy allows. Transport retries (bounded exponential backoff on transient
    429/timeout/conn/5xx; fast-fail on auth/permission/model/quota) are counted per call.

    `openai.OpenAI` here is the CLIENT LIBRARY for an OpenAI-COMPATIBLE endpoint -- it is not a
    claim about which provider is being called. The provider is `_judge_provider(cfg)`.
    """

    # CLASS-level default, so the routing pin is present on any instance -- including one
    # built via `__new__` in a test harness, or any future construction path that bypasses
    # `__init__`. The failure direction matters: an absent `extra_body` would send UNPINNED
    # requests, and OpenRouter's default is automatic failover, so the batch would silently
    # route to whatever upstream it liked. Defaulting to the pin fails SAFE; `__init__` still
    # installs a per-instance deep copy, and `_request` copies again per request.
    extra_body = PROVIDER_PIN

    def __init__(self, cfg: dict, seed_supported: bool, max_backoff_attempts: int = 5):
        from openai import OpenAI
        j = cfg["roles"]["judge"]
        pc = _provider_cfg(cfg)
        env_name = pc.get("api_key_env")
        key = os.environ.get(env_name) if env_name else None
        if not key:
            raise SystemExit(f"{env_name} is not set; the live GPT judge pass needs it "
                             f"(provider {_judge_provider(cfg)!r}). See the amendment for the "
                             "exact commands.")
        # max_retries=0: the SDK retries internally by DEFAULT (openai>=1 ships
        # DEFAULT_MAX_RETRIES=2), which would silently multiply the frozen bound -- 5 outer
        # attempts x 3 SDK attempts x 3 parse attempts = up to 45 HTTP requests for ONE rated
        # rep, none of the internal ones visible in transient_retries, the wire log, or
        # provider_calls. The amendment declares a bounded, LOGGED retry policy, so all retrying
        # must happen in the outer loop where it is counted and written to the wire log.
        self.client = OpenAI(base_url=pc["base_url"], api_key=key, max_retries=0)
        self.sdk_max_retries = 0
        self.provider = _judge_provider(cfg)
        self.base_url = pc["base_url"]
        self.model = j["model"]
        self.max_completion_tokens = j["max_tokens"]
        self.reasoning_effort = j["reasoning_effort"]
        self.seed_supported = seed_supported
        self.max_backoff_attempts = max_backoff_attempts
        self.sdk_version = __import__("openai").__version__
        # Deep-copied so no caller can mutate the frozen module-level pin through this
        # attribute; `_request` copies again per request for the same reason.
        self.extra_body = copy.deepcopy(PROVIDER_PIN)

    def _request(self, system: str, user: str, seed: Optional[int]) -> dict:
        req = dict(model=self.model,
                   messages=[{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                   max_completion_tokens=self.max_completion_tokens,
                   reasoning_effort=self.reasoning_effort)
        # temperature: never added (omitted, model default sampling)
        if self.seed_supported and seed is not None:
            req["seed"] = seed
        # The routing pin rides on EVERY request built here -- and `call` builds the request
        # once and reuses it across all transport retries, so retries are pinned too. Built
        # here rather than in `call` so the preflight, which goes through the same path, is
        # certified under exactly the routing production uses.
        if self.extra_body:
            req["extra_body"] = copy.deepcopy(self.extra_body)
        return req

    def call(self, system: str, user: str, seed: Optional[int], budget=None,
             where: str = "") -> dict:
        req = self._request(system, user, seed)
        transient_retries = 0
        last = None
        for i in range(self.max_backoff_attempts):
            # The spend ceiling is charged HERE, per HTTP request, not once per logical rating
            # attempt: this loop can issue up to max_backoff_attempts real requests, so charging
            # outside it under-counts actual requests by up to that factor.
            if budget is not None:
                budget.charge(where, attempt=i + 1)
            try:
                resp = self.client.chat.completions.create(**req)
                return {"resp": resp, "transient_retries": transient_retries,
                        "seed_sent": "seed" in req}
            except Exception as e:  # noqa: BLE001
                last = e
                cat = _categorize_error(e)
                if cat == "fatal":
                    raise SystemExit(f"GPT judge fatal error (fail fast, no retry): {e}")
                if cat != "transient" or i == self.max_backoff_attempts - 1:
                    raise
                transient_retries += 1
                time.sleep(2.0 ** i)
        raise last  # pragma: no cover


def _served_provider(resp) -> Optional[str]:
    """The upstream that actually served this call, from the response body's top-level
    `provider` field (e.g. 'OpenAI').

    This is a PER-CALL served-backend attestation and the strongest identity signal available
    on this route. It matters because `returned_model` through a router attests only to the
    ROUTER's label for the model, not to which upstream deployment produced the tokens -- and
    `system_fingerprint` was already `None` on OpenAI direct, so it was never a working control.

    `provider` is not part of the OpenAI Chat Completions schema, so it does not become a
    declared attribute on the SDK's pydantic model. It survives in `model_extra` (and in
    `model_dump()`); a plain `getattr` returns nothing. Try each shape and fall back to None
    rather than raising -- an absent attestation is reported honestly and gated elsewhere, not
    papered over here.
    """
    for get in (lambda: (resp.model_extra or {}).get("provider"),
                lambda: resp.model_dump().get("provider"),
                lambda: getattr(resp, "provider", None)):
        try:
            v = get()
        except Exception:  # noqa: BLE001 - probe the next shape
            continue
        if v:
            return str(v)
    return None


def _extract_meta(resp) -> dict:
    """Pull the required per-call metadata off an OpenAI SDK response (defensive)."""
    def g(o, name, default=None):
        return getattr(o, name, default) if o is not None else default
    usage = g(resp, "usage")
    details = g(usage, "completion_tokens_details")
    choices = g(resp, "choices") or []
    finish = g(choices[0], "finish_reason") if choices else None
    text = ""
    if choices:
        text = (g(g(choices[0], "message"), "content") or "")
    return {
        "returned_model": g(resp, "model"),
        "response_id": g(resp, "id"),
        "system_fingerprint": g(resp, "system_fingerprint"),
        "served_provider": _served_provider(resp),
        "finish_reason": finish,
        "usage": {"prompt_tokens": g(usage, "prompt_tokens"),
                  "completion_tokens": g(usage, "completion_tokens"),
                  "reasoning_tokens": g(details, "reasoning_tokens")},
        "text": text,
    }


# -------------------------------------------------------------------- mock scorer (offline)
def _mock_meta(instrument: str, system: str, user: str, seed: Optional[int]) -> dict:
    """Deterministic synthetic scorer for the OFFLINE plumbing path (--judge-backend mock).
    Produces a valid rubric JSON so the whole pipeline runs with no key. DO NOT REPORT."""
    fields = J.FIELDS if instrument == "helpfulness" else JP.FIELDS
    h = int(hashlib.sha256(f"{instrument}|{user}|{seed}".encode()).hexdigest()[:8], 16)
    overall = 3 + (h % 3)  # 3..5
    obj = {k: (overall if k == "overall" else 3 + ((h >> (i + 1)) % 3))
           for i, k in enumerate(fields)}
    text = json.dumps(obj)
    return {"returned_model": "mock-gpt-5.6-sol", "response_id": f"mock-{h:08x}",
            "system_fingerprint": None, "served_provider": "mock", "finish_reason": "stop",
            "usage": {"prompt_tokens": len(user.split()), "completion_tokens": len(text.split()),
                      "reasoning_tokens": 0},
            "text": text, "transient_retries": 0, "seed_sent": seed is not None}


# -------------------------------------------------------------------- preflight
def run_preflight(cfg: dict, out_dir: Path, backend: str) -> dict:
    _enforce_namespace(out_dir)
    wire_dir = out_dir / "wire"
    wire_dir.mkdir(parents=True, exist_ok=True)
    records = []
    resolved = {"epistemic_status": "prospectively specified post hoc cross-judge robustness "
                                    "analysis over frozen transcripts",
                "timestamp_utc": _now_utc(), "requested_model": cfg["roles"]["judge"]["model"],
                "provider": _judge_provider(cfg),
                "endpoint": _provider_cfg(cfg).get("base_url"),
                "provider_routing": PROVIDER_PIN,
                "reasoning_effort": cfg["roles"]["judge"]["reasoning_effort"],
                "temperature": "omitted from request",
                "max_completion_tokens": cfg["roles"]["judge"]["max_tokens"],
                "backend": backend}

    if backend == "mock":
        resolved.update({"seed_supported": True, "token_field": "max_completion_tokens",
                         "returned_model": "mock-gpt-5.6-sol", "served_provider": "mock",
                         "openai_sdk_version": None,
                         "note": "MOCK preflight (no key); production requires a live preflight"})
        for instrument in ("helpfulness", "pedagogy"):
            spec = RUBRICS[instrument]
            user = spec["user"].format(dialogue=PREFLIGHT_DIALOGUE)
            meta = _mock_meta(instrument, spec["system"], user, seed=0)
            parsed = spec["parse"](meta["text"])
            records.append({"instrument": instrument, "parsed_ok": parsed is not None,
                            "finish_reason": meta["finish_reason"], **meta})
        resolved["parser_ok"] = all(r["parsed_ok"] for r in records)
        _write_json(out_dir / "preflight.json", {"resolved": resolved, "calls": records})
        _write_json(out_dir / "resolved_config.json", resolved)
        return resolved

    # live preflight: probe seed support on the FIRST call, then reuse the resolved policy.
    seed_supported = True
    caller = _Caller(cfg, seed_supported=True)
    resolved["openai_sdk_version"] = caller.sdk_version
    # Recorded so the audited attempt bound is the REAL one: all retrying is the outer,
    # logged loop; the SDK's own retry layer is disabled.
    resolved["sdk_max_retries"] = caller.sdk_max_retries
    resolved["max_transport_attempts_per_call"] = caller.max_backoff_attempts
    for idx, instrument in enumerate(("helpfulness", "pedagogy")):
        spec = RUBRICS[instrument]
        user = spec["user"].format(dialogue=PREFLIGHT_DIALOGUE)
        try:
            res = caller.call(spec["system"], user, seed=0)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if "seed" in msg and "rate" not in msg and seed_supported:
                seed_supported = False
                caller.seed_supported = False
                res = caller.call(spec["system"], user, seed=None)
            else:
                raise SystemExit(f"preflight failed on {instrument}: {e}")
        meta = _extract_meta(res["resp"])
        parsed = spec["parse"](meta["text"])
        rec = {"instrument": instrument, "parsed_ok": parsed is not None,
               "parsed_overall": (parsed or {}).get("overall"),
               "seed_sent": res["seed_sent"], "transient_retries": res["transient_retries"],
               "requested_model": caller.model, **meta}
        records.append(rec)
        (wire_dir / f"preflight_{instrument}.jsonl").write_text(
            _scrub(json.dumps(rec, default=str)) + "\n")

    returned_models = {r["returned_model"] for r in records}
    # The preflight must apply the EXACT predicate production applies, or it can certify a
    # contract every production response then fails. Two divergences existed: `finish_reasons`
    # dropped falsy values, so finish_reason=None was never seen as non-'stop'; and
    # `usage_logged` checked only completion_tokens while scoring also requires prompt_tokens.
    degraded = {r["instrument"]: _degraded_reason(r) for r in records}
    degraded = {k: v for k, v in degraded.items() if v}
    resolved.update({
        "seed_supported": seed_supported,
        "temperature_omitted": True,
        "token_field": "max_completion_tokens",
        "returned_model": sorted(m for m in returned_models if m),
        "response_model_consistent": len(returned_models) == 1,
        # None is RETAINED here: a missing finish reason is itself a contract violation.
        "finish_reasons": sorted((str(r["finish_reason"]) for r in records), key=str),
        "parser_ok": all(r["parsed_ok"] for r in records),
        "usage_logged": all(r["usage"].get(k) is not None
                            for r in records for k in ("prompt_tokens", "completion_tokens")),
        "degraded_responses": degraded,
        # The served BACKEND identity. `gpt-5.6-sol` is explicitly not an immutable dated
        # snapshot, so the model string alone cannot detect an in-place backend update;
        # system_fingerprint is the only signal the API offers, and it was previously logged
        # and never compared. Frozen here when the provider supplies one.
        "system_fingerprint": (sorted({r.get("system_fingerprint") for r in records})[0]
                               if len({r.get("system_fingerprint") for r in records}) == 1
                               else None),
        "system_fingerprints_seen": sorted(
            {str(r.get("system_fingerprint")) for r in records}),
        "fingerprint_drift_detectable": all(r.get("system_fingerprint") for r in records)
                                        and len({r.get("system_fingerprint")
                                                 for r in records}) == 1,
        # The served UPSTREAM, frozen here and re-checked on every scored call. On this route
        # this is the load-bearing identity control: `system_fingerprint` is None on this
        # provider (as it already was on OpenAI direct, where the drift control was therefore
        # inert), and `returned_model` through a router attests only to the router's label.
        # Frozen only when every preflight call agrees; a split is a violation below.
        "served_provider": (sorted({r.get("served_provider") for r in records})[0]
                            if len({r.get("served_provider") for r in records}) == 1
                            else None),
        "served_providers_seen": sorted({str(r.get("served_provider")) for r in records}),
    })
    # The preflight is a GATE, not a logbook: any contract violation STOPS here rather than
    # being recorded and scored through.
    violations = []
    if not resolved["parser_ok"]:
        violations.append("the frozen parser did not parse GPT-5.6 Sol output "
                          "(do NOT migrate transport/parser)")
    if not resolved["response_model_consistent"]:
        violations.append(f"inconsistent returned models across calls: {resolved['returned_model']}")
    if not resolved["returned_model"]:
        violations.append("no returned model identity reported")
    if any(not r.get("returned_model") for r in records):
        violations.append("a preflight response carried no model identity at all")
    # Refusing to freeze a contract with no served-upstream attestation is what keeps the
    # per-call check from being vacuous: `score_base` requires `served_provider` to be present
    # before it will spend, so a preflight that recorded None would otherwise simply disable
    # the strongest identity control on this route rather than fail loudly here.
    if any(not r.get("served_provider") for r in records):
        violations.append(
            "a preflight response carried no served-provider attestation (no top-level "
            "`provider` in the response body); through a router that attestation is the only "
            "evidence of WHICH upstream served a rating, so the contract must not be frozen "
            "without it")
    elif not resolved["served_provider"]:
        violations.append(
            f"preflight calls were served by DIFFERENT upstreams "
            f"({resolved['served_providers_seen']}) despite the routing pin "
            f"{PROVIDER_PIN!r}; the pin is not holding, so the contract must not be frozen")
    for instrument, why in sorted(degraded.items()):
        violations.append(f"{instrument}: {why} -- production scoring refuses this response "
                          "shape, so the contract must not be frozen with it")
    if violations:
        raise SystemExit("preflight FAILED -- refusing to freeze this transport contract:\n  - "
                         + "\n  - ".join(violations) + f"\nSee {_repo_rel(out_dir)}/preflight.json.")
    # Bind the resolved contract to the code, freeze, and dependency that produced it, so a
    # later scoring run can prove it is scoring under the conditions the preflight actually
    # tested rather than merely finding *a* resolved_config.json on disk.
    resolved.update({
        "request_contract_sha256": _request_contract_sha256(cfg),
        "preflight_freeze_commit": _commit_of(PLAN_FREEZE_TAG),
        "implementation_commit": _git("rev-parse", "HEAD"),
        "openai_sdk_version": caller.sdk_version,
        "sdk_max_retries": caller.sdk_max_retries,
    })
    _write_json(out_dir / "preflight.json", {"resolved": resolved, "calls": records})
    _write_json(out_dir / "resolved_config.json", resolved)
    return resolved


def _load_resolved(out_dir: Path, cfg: dict, backend: str) -> dict:
    """Production scoring requires a completed preflight sibling AND that the preflight actually
    describes THIS frozen configuration (a stale preflight must not authorize a paid batch)."""
    pf = out_dir.parent / "preflight" / "resolved_config.json"
    if not pf.exists():
        raise SystemExit(
            f"no preflight resolved_config at {pf}. Run --preflight first:\n"
            f"  {_provider_cfg(cfg).get('api_key_env')}=... .venv/bin/python "
            f"analysis/run_cross_judge_audit.py "
            f"--preflight --models configs/models.judge-gpt56.yaml --out {out_dir.parent}/preflight")
    resolved = json.loads(pf.read_text())
    if backend == "live" and resolved.get("backend") == "mock":
        raise SystemExit(f"{pf} is a MOCK preflight; a live scoring run needs a live preflight.")
    j = cfg["roles"]["judge"]
    expected = {
        "requested_model": j["model"],
        # Provider name AND endpoint both checked: a preflight resolved against a different
        # route must never authorize this batch, and the pair must agree.
        "provider": _judge_provider(cfg),
        "endpoint": _provider_cfg(cfg).get("base_url"),
        "reasoning_effort": j["reasoning_effort"],
        "max_completion_tokens": j["max_tokens"],
    }
    drift = {k: (resolved.get(k), v) for k, v in expected.items() if resolved.get(k) != v}
    if drift:
        raise SystemExit(
            f"STALE PREFLIGHT: {pf} does not describe the current frozen config "
            f"(preflight vs config: {drift}). Re-run --preflight before scoring.")
    if resolved.get("temperature") != "omitted from request":
        raise SystemExit(f"STALE PREFLIGHT: {pf} did not record temperature omission.")
    if backend == "live" and not resolved.get("parser_ok"):
        raise SystemExit(f"{pf} records parser_ok=false; refusing to score.")
    if backend == "live" and resolved.get("response_model_consistent") is False:
        raise SystemExit(f"{pf} records inconsistent returned models; refusing to score.")
    if backend == "live":
        # The preflight must have been run by THIS code, at THIS freeze, on THIS SDK. Otherwise
        # a contract resolved under a different checkout or dependency could authorize the paid
        # batch -- the requests actually sent would not be the requests that were tested.
        want_contract = _request_contract_sha256(cfg)
        if resolved.get("request_contract_sha256") != want_contract:
            raise SystemExit(
                f"STALE PREFLIGHT: {pf} was resolved for a different request contract "
                f"(recorded {str(resolved.get('request_contract_sha256'))[:12]}, this checkout "
                f"produces {want_contract[:12]}). The prompts, parser, rubric, model, or request "
                "parameters changed since the preflight; re-run --preflight before scoring.")
        want_freeze = _commit_of(PLAN_FREEZE_TAG)
        if resolved.get("preflight_freeze_commit") != want_freeze:
            raise SystemExit(
                f"STALE PREFLIGHT: {pf} was run at plan freeze "
                f"{str(resolved.get('preflight_freeze_commit'))[:12]} but this run is at "
                f"{str(want_freeze)[:12]}. The transport contract must be resolved at the same "
                "freeze the batch is paid for; re-run --preflight.")
        sdk_now = None
        try:
            sdk_now = __import__("openai").__version__
        except Exception:  # noqa: BLE001
            pass
        if sdk_now and resolved.get("openai_sdk_version") != sdk_now:
            raise SystemExit(
                f"STALE PREFLIGHT: {pf} was resolved with openai "
                f"{resolved.get('openai_sdk_version')!r} but this environment has {sdk_now!r}. "
                "Retry semantics and request serialization are SDK-dependent; re-run --preflight.")
    return resolved


# -------------------------------------------------------------------- scoring
def score_base(loaded, cfg, out_dir: Path, rubrics: list[str], reps: int, backend: str,
               offline_cache_only: bool, resolved: dict, units=None,
               max_provider_calls: Optional[int] = None,
               allow_fingerprint_drift: bool = False) -> dict:
    base = loaded["base"]
    human_base = loaded["human_base"]
    units = units if units is not None else _planned_units(loaded)
    seed_supported = bool(resolved.get("seed_supported", False))
    seed_policy = "seeded(base=0,+rep)" if seed_supported else "unseeded"
    token_limit = cfg["roles"]["judge"]["max_tokens"]

    # One budget for the WHOLE base (both rubrics): the authorization is per run, not per
    # instrument, so a retry storm in helpfulness must eat into what pedagogy may spend.
    if max_provider_calls is None:
        max_provider_calls = default_max_provider_calls(len(units), len(rubrics), reps)
    # The ceiling is a LIFETIME authorization for this base, carried across invocations by the
    # persisted ledger -- otherwise the canary-then-resume workflow silently re-authorizes
    # itself every time it runs.
    ledger = _SpendLedger(out_dir / SPEND_LEDGER_FILE, max_provider_calls,
                          live=(backend == "live" and not offline_cache_only),
                          provider=_judge_provider(cfg))
    changed = ledger.note_authorization_change()
    if changed:
        print(f"spend ledger: {changed} (explicit re-authorization, recorded)")
    if ledger.prior_attempts:
        print(f"spend ledger: {ledger.prior_attempts:,} HTTP request(s) already made for this "
              f"base in {len(ledger.invocations)} earlier invocation(s); "
              f"{max(0, max_provider_calls - ledger.prior_attempts):,} remain authorized")
    budget = _Budget(max_http_attempts=max_provider_calls, ledger=ledger)
    # The upstream frozen at preflight. Every scored call is checked against it, and -- unlike
    # system_fingerprint, which this provider has never populated -- it is REQUIRED for a paid
    # batch: without it the per-call served-provider check would silently pass on every call,
    # which is precisely the "guard that is correct in isolation but not wired into the gate"
    # failure this suite has hit before.
    expected_provider = resolved.get("served_provider")
    if backend == "live" and not offline_cache_only and not expected_provider:
        raise SystemExit(
            "the resolved preflight records no served_provider, so the per-call served-upstream "
            "attestation could not be enforced for a single scored call. Through a router, that "
            "attestation is the only evidence of WHICH upstream produced a rating. Re-run "
            "--preflight before scoring; refusing to spend the batch unverified.")

    expected_fingerprint = resolved.get("system_fingerprint")
    if backend == "live" and not offline_cache_only and not expected_fingerprint:
        print("NOTE: the preflight recorded no stable system_fingerprint, so an in-place "
              "BACKEND change under the same model ID cannot be detected. Every fingerprint "
              "observed is still recorded in completeness.json for disclosure.")

    caller = None
    if backend == "live" and not offline_cache_only:
        caller = _Caller(cfg, seed_supported=seed_supported)

    # returned model bound into the stamp: from the resolved preflight (live) or mock.
    rm = resolved.get("returned_model")
    returned_model = (rm[0] if isinstance(rm, list) and rm else
                      (rm if isinstance(rm, str) else None))
    # The per-call identity check is only a guarantee if there is something to check against.
    # Without a frozen served model, every scored call would skip it silently.
    if backend == "live" and not offline_cache_only and not returned_model:
        raise SystemExit(
            "the resolved preflight records no returned_model, so per-call served-model "
            "identity could not be enforced for a single scored call. Re-run --preflight "
            "before scoring; refusing to spend the batch unverified.")

    wire_dir = out_dir / "wire"
    stats = _new_stats(rubrics)
    detail = {}
    resolved_returned = returned_model
    reconstruction_stamps: dict = {}
    for instrument in rubrics:
        spec = RUBRICS[instrument]
        cache_path = out_dir / "cache" / f"{instrument}_cache.json"
        if offline_cache_only:
            # Reconstruction reads the stamp FROM the released cache (returned_model, seed
            # policy, and plan freeze are run-specific and not re-derivable offline); it
            # validates the frozen-content fields (prompts, parser, model, params) match.
            # The RUN-level fields are collected here and cross-validated across ALL rubrics
            # below -- never taken from whichever rubric loaded last.
            cache, stamp = _load_cache_reconstruction(cache_path, instrument, cfg, reps)
            reconstruction_stamps[instrument] = stamp
        else:
            stamp = _instrument_stamp(instrument, backend, cfg, seed_policy, reps, returned_model)
            cache = _load_cache(cache_path, stamp)
        wire_path = wire_dir / f"{instrument}.jsonl"
        if not offline_cache_only:
            wire_dir.mkdir(parents=True, exist_ok=True)
        runs = _score_instrument(instrument, spec, units, loaded, cache, cache_path, stamp,
                                 wire_path, caller, backend, reps, seed_supported,
                                 offline_cache_only, stats, token_limit,
                                 expected_model=returned_model, budget=budget,
                                 expected_fingerprint=expected_fingerprint,
                                 allow_fingerprint_drift=allow_fingerprint_drift,
                                 expected_provider=expected_provider)
        detail[instrument] = {"stamp": stamp, "reps": reps, "runs": runs}

    plan_freeze = None
    if offline_cache_only:
        # Every rubric's cache must agree on the run-level provenance; the AGREED values (not
        # the CLI defaults and not the last rubric's) are what the reconstruction reports.
        validated = _validate_reconstruction_stamps(reconstruction_stamps)
        seed_policy = validated["seed_policy"]
        resolved_returned = validated["returned_model"]
        plan_freeze = validated["plan_freeze"]
    fps = fingerprint_summary(stats, expected_fingerprint)
    sps = served_provider_summary(stats, expected_provider)
    return {"units": units, "detail": detail, "stats": stats, "seed_policy": seed_policy,
            "human_base": human_base, "returned_model": resolved_returned,
            "plan_freeze": plan_freeze, "budget": budget.summary(),
            "system_fingerprint_frozen": expected_fingerprint,
            "system_fingerprints_observed": fps["observed"],
            "spans_multiple_backends": fps["spans_multiple_backends"],
            "observed_disagrees_with_frozen": fps["observed_disagrees_with_frozen"],
            "fingerprint_drift_allowed": allow_fingerprint_drift,
            "provider_frozen": expected_provider,
            "provider_routing": PROVIDER_PIN,
            "served_providers_observed": sps["observed"],
            "served_provider_missing": sps["missing"],
            "spans_multiple_providers": sps["spans_multiple_providers"],
            "served_provider_disagrees_with_frozen": sps["observed_disagrees_with_frozen"]}


def _new_stats(rubrics: list[str]) -> dict:
    return {r: {"planned_ratings": 0, "valid_ratings": 0, "parse_retries": 0,
                "transport_retries": 0, "parse_failures": 0, "cache_hits": 0,
                "provider_calls": 0, "degraded_responses": 0,
                "system_fingerprints": {},
                "served_providers": {},
                "by_condition": {}} for r in rubrics}


def fingerprint_summary(stats, expected_fingerprint=None) -> dict:
    """Run-level backend provenance over EVERY rating in the promoted set.

    Extracted from `score_base` so the run-level claim is testable without a paid batch: the
    defect it now covers was invisible at this level precisely because the cache-hit path never
    reached the counters this reads.

    Two DIFFERENT questions, deliberately not conflated:
      * `spans_multiple_backends` -- did this run MIX regimes? A multiplicity test.
      * `observed_disagrees_with_frozen` -- did any rating come from a backend other than the
        one the preflight froze? A DIVERGENCE test. Multiplicity alone cannot answer it: a run
        that is 100% cache hits on a rotated backend observes exactly one fingerprint, so it
        reported `spans_multiple_backends: false` while not one rating came from the frozen
        backend -- and the provenance note tells readers to key on that flag. The per-call
        abort in `_score_one_rep` only ever sees FRESH responses, so it cannot cover this
        either. Recorded, never fatal: these ratings were validated against the preflight in
        force when they were paid for, so the honest statement is that they came from a
        different regime than this run's provenance otherwise implies."""
    observed = {}
    for st in stats.values():
        for fp, n in st["system_fingerprints"].items():
            observed[fp] = observed.get(fp, 0) + n
    real = [f for f in observed if f != "None"]
    return {"observed": observed,
            "spans_multiple_backends": len(real) > 1,
            "observed_disagrees_with_frozen": bool(expected_fingerprint) and any(
                f != expected_fingerprint for f in real)}


def served_provider_summary(stats, expected_provider=None) -> dict:
    """Run-level SERVED-UPSTREAM provenance over EVERY rating in the promoted set.

    The router-era counterpart of `fingerprint_summary`, and the completeness assertion the
    OpenRouter amendment turns on: a promoted base must be able to state which upstream served
    it, for every single rating, not merely for the ones this invocation happened to pay for.

    Same two deliberately separate questions as the fingerprint summary:
      * `spans_multiple_providers` -- did this run MIX upstreams? A multiplicity test.
      * `observed_disagrees_with_frozen` -- did any rating come from an upstream other than the
        one the preflight froze? A DIVERGENCE test, which multiplicity alone cannot answer: a
        fully-cached resume against a rotated upstream observes exactly one provider.
    `missing` counts ratings carrying NO attestation at all; a promoted live base must have
    none, since an unattested rating is exactly what this control exists to make impossible.
    """
    observed = {}
    for st in stats.values():
        for prov, n in st["served_providers"].items():
            observed[prov] = observed.get(prov, 0) + n
    real = [p for p in observed if p != "None"]
    return {"observed": observed,
            "missing": observed.get("None", 0),
            "spans_multiple_providers": len(real) > 1,
            "observed_disagrees_with_frozen": bool(expected_provider) and any(
                p != expected_provider for p in real)}


def _note_served_provider(stats, instrument, prov) -> None:
    """Record one observed served upstream for run-level provenance.

    Called from BOTH the fresh-response path and the cache-hit path, for the same reason
    `_note_fingerprint` is: the run-level claim is about every rating in the PROMOTED set, not
    only the ones this invocation paid for. Counting fresh responses only would let a resume
    report a single upstream while the promoted set actually mixes two."""
    counts = stats[instrument]["served_providers"]
    counts[str(prov)] = counts.get(str(prov), 0) + 1


def _note_fingerprint(stats, instrument, fp) -> None:
    """Record one observed backend fingerprint for run-level provenance.

    Called from BOTH the fresh-response path and the cache-hit path: run-level
    `system_fingerprints_observed` / `spans_multiple_backends` are a claim about every rating
    in the promoted set, not only the ones this invocation paid for."""
    counts = stats[instrument]["system_fingerprints"]
    counts[str(fp)] = counts.get(str(fp), 0) + 1


def _bump(stats, instrument, condition, key, n=1):
    s = stats[instrument]
    s[key] += n
    bc = s["by_condition"].setdefault(condition, {"planned": 0, "valid": 0})
    if key == "planned_ratings":
        bc["planned"] += n
    elif key == "valid_ratings":
        bc["valid"] += n


def _score_instrument(instrument, spec, units, loaded, cache, cache_path, stamp, wire_path,
                      caller, backend, reps, seed_supported, offline_cache_only, stats,
                      token_limit, expected_model=None, budget=None,
                      expected_fingerprint=None, allow_fingerprint_drift=False,
                      expected_provider=None):
    """Score every unit's `reps` reps for one instrument, with cache + parse-retry, and
    aggregate per turn (reusing the frozen aggregate). Groups turn rows into runs (mirroring
    the Opus *_detail.json shape) with GPT metadata appended."""
    base = loaded["base"]
    by_run: dict[str, list[dict]] = {}
    for u in units:
        by_run.setdefault(u["run_id"], []).append(u)

    runs_meta = {r["run_id"]: r for r in loaded["runs_meta"]}
    runs_out = []
    try:
        return _score_runs(instrument, spec, by_run, runs_meta, cache, cache_path, stamp,
                           wire_path, caller, backend, reps, seed_supported, offline_cache_only,
                           stats, token_limit, expected_model, budget, runs_out, base,
                           expected_fingerprint, allow_fingerprint_drift, expected_provider)
    except BaseException:
        # A budget/breaker/drift abort must not throw away ratings already PAID for: flush what
        # is in memory so a resumed run pays only for what is still missing. Same condition as
        # the normal end-of-instrument flush -- only a reconstruction, which writes no cache at
        # all, is excluded.
        #
        # BaseException, not SystemExit: paid ratings are equally lost to an unexpected
        # TypeError, a KeyboardInterrupt, or a provider-SDK exception that escapes the retry
        # loop. Catching only the ORDERLY aborts meant the disorderly ones -- the ones an
        # operator is most likely to hit mid-batch -- silently discarded this conversation's
        # unflushed reps AND left the base with no live-stamped cache for the ledger's
        # missing-evidence scan to find. The exception is always re-raised.
        if not offline_cache_only:
            try:
                _flush_cache(cache_path, stamp, cache)
            except Exception:  # noqa: BLE001 - never mask the original abort
                pass
        raise


def _score_runs(instrument, spec, by_run, runs_meta, cache, cache_path, stamp, wire_path,
                caller, backend, reps, seed_supported, offline_cache_only, stats, token_limit,
                expected_model, budget, runs_out, base, expected_fingerprint,
                allow_fingerprint_drift, expected_provider=None):
    for run_id, run_units in by_run.items():
        rmeta = runs_meta[run_id]
        turn_rows = []
        for u in run_units:
            rep_scores, rep_meta = [], []
            for rep in range(reps):
                _bump(stats, instrument, u["condition"], "planned_ratings")
                ck = cache_key(base, run_id, u["condition"], u["replicate_id"],
                               u["problem_id"], u["turn_index"], rep, u["dialogue_sha256"])
                cached = cache.get(ck)
                if cached is not None:
                    stats[instrument]["cache_hits"] += 1
                    rep_scores.append(cached.get("scores"))
                    rep_meta.append(cached.get("meta"))
                    # A REUSED rating was still produced by some backend, and the amendment
                    # deliberately keeps system_fingerprint OUT of the cache stamp so a backend
                    # rotation does not force a full re-spend. That trade is only sound if the
                    # cached fingerprint is still aggregated here: counting fresh responses
                    # only made the recommended canary-then-resume workflow report a single
                    # backend while actually mixing two, suppressing the very disclosure
                    # `--allow-fingerprint-drift` exists to force.
                    # isinstance, not `or {}`: a truthy NON-dict meta (a stray string in a
                    # hand-edited or partially-corrupted cache) raised AttributeError here,
                    # which is not a rating problem but did abort the instrument.
                    _cm = cached.get("meta")
                    _note_fingerprint(stats, instrument,
                                      _cm.get("system_fingerprint")
                                      if isinstance(_cm, dict) else None)
                    # Same reasoning for the served upstream: the promoted set's attestation
                    # must cover reused ratings too, or a fully-cached resume would report a
                    # single upstream while the promoted set actually mixes two. A cache
                    # written before this field existed notes None, which surfaces as
                    # `missing` in served_provider_summary rather than as a silent pass.
                    _note_served_provider(stats, instrument,
                                          _cm.get("served_provider")
                                          if isinstance(_cm, dict) else None)
                    if cached.get("scores") is not None:
                        _bump(stats, instrument, u["condition"], "valid_ratings")
                    continue
                if offline_cache_only:
                    raise SystemExit(
                        "OFFLINE-CACHE-ONLY tripwire: cache miss for "
                        f"{instrument} {ck}. Refusing provider access / synthetic score. "
                        "Copy the released cache into --out/cache/ first.")
                scores, meta = _score_one_rep(instrument, spec, u, rep, caller, backend,
                                              seed_supported, stats, wire_path, token_limit,
                                              expected_model, budget=budget,
                                              expected_fingerprint=expected_fingerprint,
                                              allow_fingerprint_drift=allow_fingerprint_drift,
                                              expected_provider=expected_provider)
                rep_scores.append(scores)
                rep_meta.append(meta)
                if scores is not None:
                    entry = {"scores": scores, "dialogue_sha256": u["dialogue_sha256"],
                             "meta": meta, "base": base, "run_id": run_id,
                             "condition": u["condition"], "replicate_id": u["replicate_id"],
                             "problem_id": u["problem_id"], "turn_index": u["turn_index"],
                             "rep": rep}
                    if backend == "mock":
                        # Per-ENTRY synthetic provenance: relabelling the stamp's backend can
                        # never promote synthetic scores into a reportable reconstruction.
                        entry["synthetic"] = True
                    cache[ck] = entry
                    _bump(stats, instrument, u["condition"], "valid_ratings")
            agg = spec["aggregate"](rep_scores)
            turn_rows.append({
                "run_id": run_id, "condition": u["condition"],
                "replicate_id": u["replicate_id"], "problem_id": u["problem_id"],
                "turn_index": u["turn_index"], "dialogue_sha256": u["dialogue_sha256"],
                **agg, "reps": rep_scores, "rep_meta": rep_meta,
            })
        # Flush once per CONVERSATION (run) -- the crash-safety granularity compute_metrics.py
        # uses. The in-memory cache holds every rep already scored; a mid-session crash forfeits
        # at most this conversation's not-yet-flushed reps, re-scored free on resume. Per-rep
        # flushing would be O(n^2) file rewrites and is unnecessary (the live path is
        # network-bound; a conversation is a handful of turns).
        if not offline_cache_only and backend != "mock":
            _flush_cache(cache_path, stamp, cache)
        mean_vals = [r["overall_mean"] for r in turn_rows if r["overall_mean"] is not None]
        runs_out.append({
            "run_id": run_id, "condition": rmeta["condition"],
            "replicate_id": rmeta["replicate_id"],
            spec["mean_key"]: (sum(mean_vals) / len(mean_vals)) if mean_vals else None,
            "n_turns": len(turn_rows), "turns": turn_rows,
        })
    if not offline_cache_only:
        _flush_cache(cache_path, stamp, cache)
    return runs_out


def _degraded_reason(meta: dict) -> Optional[str]:
    """Why this response is not a usable rating even if the frozen parser accepts its text.

    Mirrors the preflight contract gate (run_preflight): a non-'stop' finish reason means the
    reply was cut off rather than completed, and absent token accounting means the call cannot
    be cost-audited or reconciled against the expected spend. Returns None when the response is
    a clean, complete, auditable one."""
    finish = meta.get("finish_reason")
    if finish != "stop":
        return (f"finish_reason={finish!r} is not 'stop' (the reply did not complete -- e.g. "
                "truncation at the output-token limit)")
    usage = meta.get("usage") or {}
    missing = [k for k in ("prompt_tokens", "completion_tokens") if usage.get(k) is None]
    if missing:
        return f"usage is missing {missing}; the call cannot be token/cost audited"
    return None


def _score_one_rep(instrument, spec, u, rep, caller, backend, seed_supported, stats,
                   wire_path, token_limit, expected_model=None, budget=None,
                   expected_fingerprint=None, allow_fingerprint_drift=False,
                   expected_provider=None):
    """One rep: up to 3 identical attempts (record raw text, retry an UNPARSEABLE reply at
    most twice more; no repair prompt, no parameter change). Returns (scores_or_None, meta)."""
    system = spec["system"]
    user = spec["user"].format(dialogue=u["dialogue"])
    seed = (0 + rep) if seed_supported else None
    scores = None
    attempts = []
    rep_transport = 0
    meta = None
    for attempt in range(3):
        where = (f"[{instrument} {u['run_id']} {u['problem_id']} "
                 f"t{u['turn_index']} rep{rep} attempt{attempt + 1}]")
        if backend == "mock":
            if budget is not None:
                budget.charge(where)      # one simulated request
            meta = _mock_meta(instrument, system, user, seed)
        else:
            # The budget goes DOWN into the caller so every transport retry is charged too.
            res = caller.call(system, user, seed, budget=budget, where=where)
            m = _extract_meta(res["resp"])
            m["transient_retries"] = res["transient_retries"]
            m["seed_sent"] = res["seed_sent"]
            meta = m
        stats[instrument]["provider_calls"] += 1
        stats[instrument]["transport_retries"] += meta.get("transient_retries", 0)
        rep_transport += meta.get("transient_retries", 0)
        # Served-model identity is FATAL, and an ABSENT identity is just as fatal as a changed
        # one: `got and got != expected` used to skip the check entirely when the response
        # carried no model, so a reply with no identity at all satisfied a guarantee that
        # claims every call is checked against the model frozen at preflight.
        got = meta.get("returned_model")
        if expected_model:
            if not got:
                raise SystemExit(
                    f"NO RETURNED-MODEL IDENTITY on a scored call {where}: the response carries "
                    f"no model field, so it cannot be checked against the model frozen at "
                    f"preflight ({expected_model!r}). Stopping: an unauditable rating must never "
                    "enter the results.")
            if got != expected_model:
                raise SystemExit(
                    f"RETURNED-MODEL DRIFT mid-batch: expected {expected_model!r} (frozen at "
                    f"preflight) but this call returned {got!r} {where}. "
                    "Stopping: results from two different served models must never be mixed.")
        # BACKEND drift under an unchanged model string. `gpt-5.6-sol` is not an immutable dated
        # snapshot, so the model name alone cannot detect an in-place backend update -- the two
        # regimes would be mixed while provenance reported a single model. system_fingerprint is
        # the only signal the API offers; it used to be recorded and never compared.
        # SERVED-UPSTREAM identity. Through a router, `returned_model` attests only to the
        # router's label for the model; the response body's `provider` field is what says which
        # upstream actually produced the tokens. The routing pin (PROVIDER_PIN, fallbacks
        # disabled) is supposed to make this constant -- this is the check that the pin was
        # honoured on THIS call rather than trusted because it was configured. Fatal, and an
        # ABSENT attestation is as fatal as a changed one: a rating nobody can attribute to an
        # upstream must never enter the results.
        sp = meta.get("served_provider")
        _note_served_provider(stats, instrument, sp)
        if expected_provider:
            if not sp:
                raise SystemExit(
                    f"NO SERVED-PROVIDER ATTESTATION on a scored call {where}: the response "
                    f"carries no `provider` field, so the upstream that produced this rating "
                    f"cannot be identified or checked against the one frozen at preflight "
                    f"({expected_provider!r}). Stopping: the routing pin is only a guarantee if "
                    "every call is verified to have been served under it.")
            if sp != expected_provider:
                raise SystemExit(
                    f"SERVED-PROVIDER DRIFT mid-batch: expected {expected_provider!r} (frozen at "
                    f"preflight, pinned via {PROVIDER_PIN!r}) but this call was served by "
                    f"{sp!r} {where}. The routing pin did not hold. Stopping: ratings from two "
                    "different upstreams must never be mixed.\n"
                    "  * The cache is intact -- nothing already paid for is lost.")
        fp = meta.get("system_fingerprint")
        _note_fingerprint(stats, instrument, fp)
        if expected_fingerprint and fp and fp != expected_fingerprint:
            if not allow_fingerprint_drift:
                raise SystemExit(
                    f"SYSTEM-FINGERPRINT DRIFT mid-batch: preflight froze "
                    f"{expected_fingerprint!r} but this call returned {fp!r} {where}. The served "
                    "model ID is unchanged, so this is an in-place BACKEND change: ratings before "
                    "and after it come from different scoring regimes. Stopping.\n"
                    "  * The cache is intact -- nothing already paid for is lost.\n"
                    "  * To continue deliberately, re-run with --allow-fingerprint-drift. Every "
                    "fingerprint observed is then recorded in completeness.json and "
                    "provenance.json, and the run is marked as spanning multiple backends, which "
                    "MUST be disclosed alongside the results.")
        # A DEGRADED response is not a valid rating even when it happens to parse. A
        # `finish_reason` other than 'stop' means the reply was cut off (e.g. truncated at the
        # output-token limit) and missing usage means the call cannot be cost-audited. The
        # preflight already refuses both; scoring must too, otherwise the gate only ever applied
        # to the one synthetic call. These take the frozen retry policy -- the identical request,
        # at most three attempts -- and if they never clear, the rep stays invalid and
        # completeness blocks publication.
        degraded = _degraded_reason(meta)
        parsed = spec["parse"](meta["text"])
        accepted = parsed is not None and degraded is None
        attempts.append({"attempt": attempt + 1, "parsed_ok": parsed is not None,
                         "finish_reason": meta.get("finish_reason"),
                         "returned_model": meta.get("returned_model"),
                         "served_provider": meta.get("served_provider"),
                         "degraded_reason": degraded, "accepted": accepted})
        _write_wire(wire_path, instrument, u, rep, attempt + 1, meta, parsed, backend,
                    token_limit, degraded=degraded)
        if budget is not None:
            budget.record(accepted, where)
        if accepted:
            scores = parsed
            break
        if degraded is not None:
            stats[instrument]["degraded_responses"] += 1
        if attempt < 2:
            stats[instrument]["parse_retries"] += 1
    if scores is None:
        stats[instrument]["parse_failures"] += 1
    # `served_provider` is carried into the CACHED entry, not only the wire log: a rating
    # reused from cache must still be able to state which upstream produced it, or the
    # promoted-set attestation would silently degrade to "whatever this invocation refreshed".
    meta_summary = {"returned_model": meta.get("returned_model"),
                    "response_id": meta.get("response_id"),
                    "system_fingerprint": meta.get("system_fingerprint"),
                    "served_provider": meta.get("served_provider"),
                    "finish_reason": meta.get("finish_reason"),
                    "seed_sent": meta.get("seed_sent"),
                    "usage": meta.get("usage"),
                    "attempts": attempts,
                    "transport_retries": rep_transport}
    return scores, meta_summary


def _write_wire(wire_path: Path, instrument, u, rep, attempt, meta, parsed, backend,
                token_limit, degraded=None) -> None:
    rec = {
        "ts": _now_utc(), "instrument": instrument, "base": u["base"],
        "run_id": u["run_id"], "condition": u["condition"],
        "replicate_id": u["replicate_id"], "problem_id": u["problem_id"],
        "turn_index": u["turn_index"], "rep": rep, "attempt": attempt,
        "requested_model": REQUESTED_MODEL, "returned_model": meta.get("returned_model"),
        "response_id": meta.get("response_id"),
        "system_fingerprint": meta.get("system_fingerprint"),
        # Per-rating served-upstream attestation, alongside the routing that was pinned to
        # obtain it. Both are recorded on every wire record so the log alone can prove which
        # upstream served each rating and under what routing it was asked for.
        "served_provider": meta.get("served_provider"),
        "provider_routing": PROVIDER_PIN,
        "seed_sent": meta.get("seed_sent"),
        "reasoning_effort": "medium", "temperature_omitted": True,
        "max_completion_tokens": token_limit,
        "finish_reason": meta.get("finish_reason"),
        "usage": meta.get("usage"), "dialogue_sha256": u["dialogue_sha256"],
        "raw_text": meta.get("text"), "parsed": parsed is not None,
        "parsed_overall": (parsed or {}).get("overall"),
        "transport_retries": meta.get("transient_retries", 0), "backend": backend,
        "degraded_reason": degraded,
        "accepted": parsed is not None and degraded is None,
    }
    wire_path.parent.mkdir(parents=True, exist_ok=True)
    with open(wire_path, "a") as f:
        f.write(_scrub(json.dumps(rec, default=str)) + "\n")


# -------------------------------------------------------------------- completeness
def check_completeness(scored, reps: int) -> dict:
    """n_valid == reps for every planned turn and rubric, plus retry/missingness stats."""
    detail = scored["detail"]
    stats = scored["stats"]
    per_rubric = {}
    complete = True
    for instrument, block in detail.items():
        n_turns = sum(len(r["turns"]) for r in block["runs"])
        bad = [(r["run_id"], t["problem_id"], t["turn_index"], t["n_valid"])
               for r in block["runs"] for t in r["turns"] if t["n_valid"] != reps]
        st = stats[instrument]
        per_rubric[instrument] = {
            "n_turns": n_turns, "planned_ratings": st["planned_ratings"],
            "valid_ratings": st["valid_ratings"], "expected_valid": n_turns * reps,
            "all_turns_have_full_valid_reps": not bad,
            "turns_missing_valid_reps": bad[:50],
            "n_turns_incomplete": len(bad),
            "parse_retries": st["parse_retries"], "parse_failures": st["parse_failures"],
            "degraded_responses": st["degraded_responses"],
            "system_fingerprints": st["system_fingerprints"],
            "served_providers": st["served_providers"],
            "transport_retries": st["transport_retries"],
            "cache_hits": st["cache_hits"], "provider_calls": st["provider_calls"],
            "valid_rep_rate": (st["valid_ratings"] / st["planned_ratings"])
                              if st["planned_ratings"] else None,
            "by_condition": st["by_condition"],
        }
        if bad or st["valid_ratings"] != n_turns * reps:
            complete = False

    # SERVED-UPSTREAM completeness over the PROMOTED set. The per-call gate in `_score_one_rep`
    # only ever sees FRESH responses, so on its own it cannot make this claim about a run that
    # is partly or wholly cache hits -- exactly the gap `fingerprint_summary` was extracted to
    # close for fingerprints. Stated as a hard completeness condition, not a note: through a
    # router, "every rating in this base was served by one identified upstream" IS the identity
    # guarantee the amendment claims, and an unattested or mixed set must not be publishable.
    provider_attestation = {
        "frozen_at_preflight": scored.get("provider_frozen"),
        "routing_pin": scored.get("provider_routing"),
        "observed": scored.get("served_providers_observed") or {},
        "ratings_without_attestation": scored.get("served_provider_missing") or 0,
        "spans_multiple_providers": bool(scored.get("spans_multiple_providers")),
        "disagrees_with_frozen": bool(scored.get("served_provider_disagrees_with_frozen")),
    }
    provider_problems = []
    if provider_attestation["ratings_without_attestation"]:
        provider_problems.append(
            f"{provider_attestation['ratings_without_attestation']} rating(s) carry no "
            "served-provider attestation")
    if provider_attestation["spans_multiple_providers"]:
        provider_problems.append(
            f"the promoted set spans multiple upstreams: {sorted(provider_attestation['observed'])}")
    if provider_attestation["disagrees_with_frozen"]:
        provider_problems.append(
            f"at least one rating was served by an upstream other than the one frozen at "
            f"preflight ({provider_attestation['frozen_at_preflight']!r})")
    provider_attestation["problems"] = provider_problems
    provider_attestation["all_ratings_same_provider"] = not provider_problems
    if provider_problems:
        complete = False

    return {"reps": reps, "complete": complete, "per_rubric": per_rubric,
            "served_provider_attestation": provider_attestation,
            "budget": scored.get("budget")}


# -------------------------------------------------------------------- transactional outputs
RUN_STATE_FILE = "run_state.json"
# The rubric-independent final outputs, plus every rubric's detail file. A published result is
# this WHOLE set, promoted together; consumers must never see a mix of two runs' files.
_FINAL_OUTPUT_BASENAMES = (
    "per_turn.csv", "per_session.csv", "per_replicate.csv",
    "metrics_summary.json", "judge_inference.json", "policy_adjusted.json",
    "completeness.json", "provenance.json",
)


def final_output_names(rubrics: list[str]) -> tuple[str, ...]:
    """The exact file set one complete scoring attempt must produce."""
    return tuple([*_FINAL_OUTPUT_BASENAMES, *(f"{i}_detail.json" for i in rubrics)])


def _all_promotable_names() -> tuple[str, ...]:
    """Every file the runner may ever have promoted, regardless of the rubric subset that
    produced it -- so a helpfulness-only rerun still clears a stale pedagogy detail."""
    return final_output_names(list(RUBRICS))


def mark_run_state(out_dir: Path, state: str, payload: dict) -> None:
    """Write the single authoritative publishability marker.

    `run_state.json` is the atomic switch: it is promoted LAST on success and rewritten FIRST
    on any other transition, so `state == "complete"` is true only for a fully promoted set.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / RUN_STATE_FILE, {"state": state, "timestamp_utc": _now_utc(),
                                           **payload})


STAGING_PREFIX = "tmp.staging."
RUN_LOCK_NAME = "tmp.lock.run"


@contextlib.contextmanager
def run_lock(out_dir: Path):
    """Serialize every scoring attempt for one base behind a non-blocking exclusive lock.

    Two concurrent invocations for the same base would otherwise issue DUPLICATE PAID CALLS,
    overwrite each other's run state, interleave their individually-atomic promotions into a
    mixed output set, and -- since clear_staging() sweeps staging directories from any pid --
    delete each other's staged results mid-run. The per-cache flock only protects cache writes;
    it does not serialize scoring or promotion.

    Non-blocking on purpose: a second run should fail immediately with an explanation, not queue
    up behind a multi-hour paid batch and then start its own.
    """
    import fcntl
    out_dir.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir / RUN_LOCK_NAME
    handle = open(lock_path, "w")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit(
                f"another cross-judge scoring run already holds the lock on "
                f"{_repo_rel(out_dir)} ({lock_path.name}). Concurrent runs for one base would "
                "duplicate paid calls and corrupt output promotion. Wait for it to finish, or "
                "confirm it died before removing the lock file.")
        handle.write(f"{os.getpid()} {_now_utc()}\n")
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        except Exception:  # noqa: BLE001
            pass
        handle.close()


def clear_staging(out_dir: Path) -> list[str]:
    """Remove EVERY staging directory, not just this process's.

    Callers MUST hold the per-base run_lock(): this sweeps directories belonging to any pid,
    so running it while another process is mid-attempt would delete that run's staged results.

    A staging directory holds an attempt that was never promoted. If a run is interrupted
    between building outputs and promoting them (Ctrl-C, OOM, a statsmodels raise inside
    build_outputs, SIGKILL), its `tmp.staging.<pid>/` survives. Sweeping only the current pid
    would let such a directory persist indefinitely, where a later manifest build could pin
    unpromoted results that the artifact builder deliberately excludes -- producing a released
    manifest referencing files the artifact does not contain.
    """
    import shutil
    removed = []
    if not out_dir.is_dir():
        return removed
    for p in sorted(out_dir.glob(f"{STAGING_PREFIX}*")):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            removed.append(p.name)
    return removed


def invalidate_outputs(out_dir: Path, reason: str, payload: dict) -> list[str]:
    """Mark any previously promoted outputs INVALID before a scoring attempt begins.

    Previously an incomplete rerun wrote a fresh `completeness.json` but left the prior run's
    detail files, CSVs, judge_inference, policy_adjusted, and provenance in place, so stale
    results stayed comparable and packageable next to a new partial cache. Now every attempt
    first flips `run_state.json` away from "complete"; consumers (`compare_judges`,
    `verify_artifact`) refuse anything that is not a current complete promoted set.

    The stale FILES are deleted on the failure path (`discard_outputs`) and replaced atomically
    on the success path (`promote_outputs`) rather than here: an aborted `--offline-cache-only`
    reconstruction inside an extracted artifact must not destroy the shipped outputs it was only
    trying to re-derive. The marker already makes them unpublishable in the meantime.
    """
    present = [n for n in _all_promotable_names() if (out_dir / n).is_file()]
    stale_staging = clear_staging(out_dir)   # never inherit an earlier attempt's staged files
    mark_run_state(out_dir, "scoring", {
        "complete": False,
        "reason": reason,
        "previously_promoted_outputs_now_invalid": present,
        "stale_staging_dirs_removed": stale_staging,
        "note": "A scoring attempt is in progress. Any files listed above are from an EARLIER "
                "run and must not be reported, compared, or packaged; they are replaced "
                "atomically on success and deleted on failure.",
        **payload})
    return present


def discard_outputs(out_dir: Path) -> list[str]:
    """Delete every previously promoted output. Called when an attempt ends incomplete, so the
    prior run's results cannot survive as publishable files."""
    removed = []
    for name in _all_promotable_names():
        p = out_dir / name
        if p.is_file():
            p.unlink()
            removed.append(name)
    return removed


def promote_outputs(staging: Path, out_dir: Path, names, state_payload: dict) -> None:
    """Atomically publish one complete attempt.

    The whole set is verified present in staging first; then each file is os.replace'd into
    place (same filesystem, so each replacement is atomic); then `run_state.json` is written
    LAST. A reader that requires state == "complete" therefore never observes a partial set.
    """
    import shutil
    missing = [n for n in names if not (staging / n).is_file()]
    if missing:
        raise SystemExit(
            f"refusing to promote an incomplete output set from {_repo_rel(staging)}: missing "
            f"{missing}. Nothing was published; the previous outputs stay marked invalid.")
    stale = [n for n in _all_promotable_names() if n not in set(names)]
    for name in stale:                      # e.g. a pedagogy detail from a two-rubric run
        p = out_dir / name                  # being superseded by a helpfulness-only run
        if p.is_file():
            p.unlink()
    for name in names:
        os.replace(staging / name, out_dir / name)
    mark_run_state(out_dir, "complete", state_payload)
    shutil.rmtree(staging, ignore_errors=True)


# -------------------------------------------------------------------- derived outputs
def build_outputs(loaded, scored, completeness, out_dir, cfg, backend, resolved, reps,
                  rubrics) -> None:
    """Write the final GPT-judge derived files ONLY after completeness passes (else the run
    stays resumable with just cache + wire on disk)."""
    from analysis import inferential as I

    human_base = loaded["human_base"]
    sessions = loaded["sessions"]
    detail = scored["detail"]

    epi = {
        "epistemic_status": "post hoc judge robustness",
        "analysis": "prospectively specified post hoc cross-judge robustness analysis over "
                    "frozen transcripts",
        "primary_judge": "Claude Opus 4.8",
        "robustness_judge": "GPT-5.6 Sol (gpt-5.6-sol)",
        "base": human_base,
        "original_transcript_freeze": {loaded["freeze_tag"]: loaded["freeze_head"]},
        # For a reconstruction the plan freeze comes from the VALIDATED cache stamps (an
        # extracted artifact has no .git to re-derive it from); for a live/mock run it is
        # resolved here.
        "second_judge_plan_freeze": {
            PLAN_FREEZE_TAG: scored.get("plan_freeze") or _commit_of(PLAN_FREEZE_TAG)},
        "requested_model": REQUESTED_MODEL,
        "returned_model": scored.get("returned_model") or resolved.get("returned_model"),
        "request_parameters": {"reasoning_effort": "medium", "temperature": "omitted",
                               "max_completion_tokens": cfg["roles"]["judge"]["max_tokens"],
                               "seed_policy": scored["seed_policy"], "reps": reps,
                               "provider": _judge_provider(cfg),
                               "endpoint": _provider_cfg(cfg).get("base_url"),
                               "provider_routing": PROVIDER_PIN},
        "backend": backend,
        "score_source": ("released per-rep cache" if backend == "offline-cache-only"
                         else ("MOCK synthetic -- DO NOT REPORT" if backend == "mock"
                               else "GPT-5.6 Sol judge calls")),
    }

    # per-turn / per-run maps for the frozen table builders
    h_by_turn = h_by_run = p_by_turn = p_by_run = None
    if "helpfulness" in detail:
        h_by_turn = {r["run_id"]: {(t["problem_id"], t["turn_index"]): t["overall_mean"]
                                   for t in r["turns"] if t["overall_mean"] is not None}
                     for r in detail["helpfulness"]["runs"]}
        h_by_run = {r["run_id"]: r["helpfulness_mean"] for r in detail["helpfulness"]["runs"]}
        _write_json(out_dir / "helpfulness_detail.json",
                    {**epi, "instrument": "helpfulness", **detail["helpfulness"]})
    if "pedagogy" in detail:
        p_by_turn = {r["run_id"]: {(t["problem_id"], t["turn_index"]): t["overall_mean"]
                                   for t in r["turns"] if t["overall_mean"] is not None}
                     for r in detail["pedagogy"]["runs"]}
        p_by_run = {r["run_id"]: r["pedagogy_mean"] for r in detail["pedagogy"]["runs"]}
        _write_json(out_dir / "pedagogy_detail.json",
                    {**epi, "instrument": "pedagogy", **detail["pedagogy"]})

    per_turn, per_session = [], []
    for sm in sessions:
        per_turn.extend(M.per_turn_rows(sm, helpfulness=(h_by_turn or {}).get(sm.run_id),
                                        pedagogy=(p_by_turn or {}).get(sm.run_id)))
        per_session.append(M.per_session_row(sm, helpfulness_mean=(h_by_run or {}).get(sm.run_id),
                                             pedagogy_mean=(p_by_run or {}).get(sm.run_id)))
    per_replicate = M.per_replicate_rows(sessions, helpfulness_by_run=h_by_run,
                                         pedagogy_by_run=p_by_run)
    _write_csv(out_dir / "per_turn.csv", per_turn)
    _write_csv(out_dir / "per_session.csv", per_session)
    _write_csv(out_dir / "per_replicate.csv", per_replicate)

    # metrics_summary.json
    summary = {**epi, "n_sessions": len(sessions),
               "runs": loaded["runs_meta"],
               "per_session": per_session, "per_replicate": per_replicate}
    _write_json(out_dir / "metrics_summary.json", summary)

    # judge_inference.json (NOT inference.json) -- the frozen §10 tests over the GPT tables.
    judge_inf = _judge_inference(per_replicate, per_turn, epi, human_base, rubrics)
    _write_json(out_dir / "judge_inference.json", judge_inf)

    # policy_adjusted.json -- condition-adjusted leakage sensitivity on the GPT scores.
    _write_json(out_dir / "policy_adjusted.json",
                _policy_adjusted(per_turn, epi, human_base))

    # completeness.json
    _write_json(out_dir / "completeness.json", {**epi, **completeness})

    # provenance.json
    _write_json(out_dir / "provenance.json",
                _provenance(loaded, scored, cfg, backend, resolved, reps, rubrics))


def _judge_inference(per_replicate, per_turn, epi, human_base, rubrics) -> dict:
    from analysis import inferential as I
    j1 = I.j1(per_replicate)          # includes P2 helpfulness session contrast + legs
    j2 = I.j2(per_turn) if per_turn else {"note": "no per_turn rows"}
    out = {**epi,
           "note": "Frozen §10 tests re-run over the GPT-5.6 Sol-filled tables. The leakage "
                   "and next-turn-independence legs are DETERMINISTIC (judge-invariant) and "
                   "should equal the Opus values; only the helpfulness and pedagogy contrasts "
                   "are GPT-specific. This is a manipulation check, NOT independent validation.",
           "session_helpfulness_contrast": j1.get("P2_helpfulness"),
           "session_pedagogy_contrast_manipulation_check": _pedagogy_contrast(per_replicate),
           "turn_leak_to_helpfulness": (j2.get("leak_to_helpfulness") or {}).get("mixed_effects"),
           "j1_full": j1, "j2_full": j2}
    return out


def _pedagogy_contrast(per_replicate) -> dict:
    """Session-level ConvTutor vs PedTutor pedagogy contrast (manipulation check), same
    descriptive summaries as the other paired marginals. Predicted direction ped>conv."""
    from analysis import inferential as I
    conv, ped, rids = I._paired(per_replicate, "pedagogy_mean")
    if not conv:
        return {"note": "no paired pedagogy_mean rows"}
    res = I.paired_test(conv, ped, predicted_sign=-1)  # ped>conv (manipulation check)
    res["n_replicates"] = len(rids)
    res["framing"] = "manipulation check (PedTutor designed around the pedagogy rubric); NOT " \
                     "independent validation"
    return res


def _policy_adjusted(per_turn, epi, human_base) -> dict:
    import pandas as pd
    from analysis import condition_adjusted_sensitivity as S
    df = pd.DataFrame(per_turn)
    prepared, audit = S.prepare_data(df, source=f"gpt-judge/{human_base}/per_turn.csv")
    models = {}
    for label, spec in S.OUTCOMES.items():
        models[label] = S.fit_policy_adjusted(prepared, spec["column"])
    return {**epi,
            "analysis": "condition-adjusted leakage sensitivity on GPT-5.6 Sol scores",
            "formula": S.FORMULA_TEMPLATE, "eligible_conditions": list(S.ELIGIBLE_CONDITIONS),
            "note": "leak->helpfulness is GPT-specific; leak->next_turn_independence is the "
                    "DETERMINISTIC (judge-invariant) leg, included for completeness.",
            "sample": audit, "models": models}


def _provenance(loaded, scored, cfg, backend, resolved, reps, rubrics) -> dict:
    human_base = loaded["human_base"]
    units = scored["units"]
    n_units = len(units)
    manifest = BASE_LOG_MANIFEST[human_base]
    stamps = {i: scored["detail"][i]["stamp"] for i in rubrics if i in scored["detail"]}
    return {
        "epistemic_status": "post hoc judge robustness",
        "analysis": "prospectively specified post hoc cross-judge robustness analysis over "
                    "frozen transcripts",
        "primary_judge": "Claude Opus 4.8",
        "robustness_judge": "GPT-5.6 Sol",
        "base": human_base,
        "original_data_freezes": {
            "confirmatory-freeze": _commit_of("confirmatory-freeze"),
            "crossmodel-gpt-freeze": _commit_of("crossmodel-gpt-freeze"),
            "crossmodel-gemini-freeze": _commit_of("crossmodel-gemini-freeze"),
        },
        "this_base_freeze": {loaded["freeze_tag"]: loaded["freeze_head"]},
        "implementation_commit": _git("rev-parse", "HEAD"),
        "implementation_commit_dirty": bool(_git("status", "--porcelain")),
        "second_judge_plan_freeze": {
            PLAN_FREEZE_TAG: scored.get("plan_freeze") or _commit_of(PLAN_FREEZE_TAG)},
        "requested_model": REQUESTED_MODEL,
        "returned_model": scored.get("returned_model") or resolved.get("returned_model"),
        "request_parameters": {"reasoning_effort": "medium", "temperature": "omitted",
                               "max_completion_tokens": cfg["roles"]["judge"]["max_tokens"],
                               "seed_policy": scored["seed_policy"], "reps": reps,
                               "provider": _judge_provider(cfg),
                               "endpoint": _provider_cfg(cfg).get("base_url"),
                               "provider_routing": PROVIDER_PIN,
                               "backend": backend},
        "spend_containment": scored.get("budget"),
        # The per-rating served-upstream attestation, reported for EVERY promoted rating. On
        # this route it replaces system_fingerprint as the identity control below the model
        # label -- and it is a strictly stronger one than the original freeze ever had, since
        # system_fingerprint was already None on OpenAI direct (fingerprint_drift_detectable
        # was false there), so nothing that worked was given up.
        "served_provider_identity": {
            "provider_configured": _judge_provider(cfg),
            "endpoint": _provider_cfg(cfg).get("base_url"),
            "routing_pin": scored.get("provider_routing"),
            "provider_frozen_at_preflight": scored.get("provider_frozen"),
            "served_providers_observed": scored.get("served_providers_observed"),
            "ratings_without_attestation": scored.get("served_provider_missing"),
            "spans_multiple_providers": scored.get("spans_multiple_providers"),
            "observed_disagrees_with_frozen": scored.get(
                "served_provider_disagrees_with_frozen"),
            "note": "Ratings were served through an intermediary (OpenRouter), pinned to the "
                    "`openai` upstream with fallbacks DISABLED. Each rating records the "
                    "upstream that actually served it, taken from the response body's "
                    "top-level `provider` field; a promoted base is asserted to have one "
                    "identified upstream for every rating. `requested_model` is the ROUTER's "
                    "slug and attests to the router's label, not to an upstream deployment -- "
                    "which is why the per-rating attestation above, and the dated snapshot the "
                    "route resolves to, are the identity evidence. The residual caveat is the "
                    "intermediary itself: one additional hop that could in principle misroute, "
                    "mitigated by the enforced pin (a bogus provider tag is refused) and by "
                    "this per-rating attestation. See "
                    "cross-judge-amendment-openrouter-2026-07-19.md.",
        },
        "served_backend_identity": {
            "system_fingerprint_frozen_at_preflight": scored.get("system_fingerprint_frozen"),
            "system_fingerprints_observed": scored.get("system_fingerprints_observed"),
            "spans_multiple_backends": scored.get("spans_multiple_backends"),
            "observed_disagrees_with_frozen": scored.get("observed_disagrees_with_frozen"),
            "fingerprint_drift_allowed": scored.get("fingerprint_drift_allowed"),
            "note": "`gpt-5.6-sol` is not an immutable dated snapshot. A change of "
                    "system_fingerprint under an unchanged model ID is an in-place BACKEND "
                    "update. Read BOTH flags: spans_multiple_backends true means this run "
                    "MIXED regimes; observed_disagrees_with_frozen true means at least one "
                    "rating came from a backend other than the one frozen at preflight -- "
                    "which a fully-cached resume shows WITHOUT spanning, since it observes a "
                    "single (rotated) fingerprint. Either flag MUST be disclosed."},
        "versions": _pkg_versions(),
        "rubric_and_module_hashes": {
            "analysis/judge.py": _sha256_file(REPO_ROOT / "analysis/judge.py"),
            "analysis/judge_pedagogy.py": _sha256_file(REPO_ROOT / "analysis/judge_pedagogy.py"),
            "supplement/judge_rubric.md": _sha256_file(REPO_ROOT / "supplement/judge_rubric.md"),
            "supplement/judge_pedagogy_rubric.md":
                _sha256_file(REPO_ROOT / "supplement/judge_pedagogy_rubric.md"),
        },
        "source_manifest": {manifest: _sha256_file(REPO_ROOT / manifest)},
        "expected_counts": {"units": n_units, "rubrics": len(rubrics), "reps": reps,
                            "calls_per_rubric": n_units * reps,
                            "calls_total": n_units * len(rubrics) * reps},
        "cache_stamps": stamps,
    }


# -------------------------------------------------------------------- manifests
def write_input_manifest(loaded, out_dir: Path, reps: int, rubrics: list[str]) -> int:
    """input_manifest.jsonl: one line per planned unit + a protected-primary hash file."""
    _enforce_namespace(out_dir)
    units = _planned_units(loaded)
    human_base = loaded["human_base"]
    src_results = loaded["source_results"]
    # source raw-log sha (per run dir's calls.jsonl)
    log_sha_cache = {}
    def _log_sha(run_id):
        if run_id not in log_sha_cache:
            log_sha_cache[run_id] = _sha256_file(REPO_ROOT / "logs" / run_id / "calls.jsonl")
        return log_sha_cache[run_id]

    manifest_path = out_dir / "input_manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w") as f:
        for u in units:
            rec = {
                "base": human_base, "source_results_dir": src_results,
                "source_raw_log_dir": u["log_dir"],
                "run_id": u["run_id"], "condition": u["condition"],
                "replicate_id": u["replicate_id"], "problem_id": u["problem_id"],
                "turn_index": u["turn_index"],
                "dialogue_sha256": u["dialogue_sha256"],
                "source_log_sha256": _log_sha(u["run_id"]),
                "inclusion_reason": "training problem, in answer-phase window",
                "freeze_tag": loaded["freeze_tag"], "freeze_head": loaded["freeze_head"],
            }
            f.write(json.dumps(rec, default=str) + "\n")
    write_protected_hashes(out_dir / "protected-primary.sha256")
    return len(units)


PROTECTED_SOURCE_FILES = (
    "configs/models.yaml", "configs/models.gpt.yaml", "configs/models.gemini.yaml",
    "analysis/judge.py", "analysis/judge_pedagogy.py", "analysis/metrics.py",
    "analysis/compute_metrics.py",
    "supplement/judge_rubric.md", "supplement/judge_pedagogy_rubric.md",
)
PROTECTED_RESULT_DIRS = (
    "results/confirmatory", "results/confirmatory_gpt", "results/confirmatory_gemini",
    "results/ablation", "results/condition_adjusted_sensitivity",
)


def write_protected_hashes(path: Path) -> None:
    """SHA-256 of every protected primary file (source/config/rubric + all files under the
    five protected result dirs), for before/after verification around the paid run."""
    lines = []
    for f in PROTECTED_SOURCE_FILES:
        p = REPO_ROOT / f
        if p.is_file():
            lines.append(f"{_sha256_file(p)}  {f}")
    for d in PROTECTED_RESULT_DIRS:
        for p in sorted((REPO_ROOT / d).rglob("*")):
            if p.is_file() and not p.name.startswith("tmp."):
                lines.append(f"{_sha256_file(p)}  {_repo_rel(p)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def verify_protected_hashes(path: Path) -> list[str]:
    failures = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        digest, rel = line.split(None, 1)
        p = REPO_ROOT / rel.strip()
        if not p.is_file():
            failures.append(f"missing {rel.strip()}")
        elif _sha256_file(p) != digest:
            failures.append(f"CHANGED {rel.strip()}")
    return failures


# -------------------------------------------------------------------- live freeze guards
def assert_live_freeze_state() -> str:
    """A paid batch must run from the FROZEN tree: the plan freeze tag must resolve, HEAD must
    BE that commit, and no tracked file may be modified/staged (untracked scratch is ignored).
    Returns the freeze commit."""
    freeze = _commit_of(PLAN_FREEZE_TAG)
    if freeze is None:
        raise SystemExit(
            f"live scoring requires the freeze tag {PLAN_FREEZE_TAG!r}. Commit the plan, config, "
            f"implementation, and passing tests, then: git tag {PLAN_FREEZE_TAG}")
    head = _git("rev-parse", "HEAD")
    if head != freeze:
        raise SystemExit(
            f"live scoring must run AT the freeze commit: HEAD={str(head)[:12]} but "
            f"{PLAN_FREEZE_TAG}={str(freeze)[:12]}. Check out the freeze commit before paying.")
    porcelain = _git("status", "--porcelain") or ""
    dirty = [ln for ln in porcelain.splitlines() if ln.strip() and not ln.startswith("??")]
    if dirty:
        raise SystemExit(
            "live scoring requires a clean tracked tree (untracked scratch is fine); modified or "
            "staged tracked files found:\n  " + "\n  ".join(dirty[:20]))
    return freeze


def assert_plan_matches(loaded, out_dir: Path, units: list[dict], rubrics: list[str],
                        reps: int, require: bool) -> None:
    """Re-validate the saved plan against what this run would actually score. The paid batch
    must score exactly the planned units, with the same dialogue hashes, rubrics, and reps --
    otherwise a post-planning change silently re-baselines the frozen inputs."""
    manifest_path = out_dir / "input_manifest.jsonl"
    plan_path = out_dir / "plan.json"
    if not manifest_path.exists() or not plan_path.exists():
        if require:
            raise SystemExit(
                f"live scoring requires the saved plan in {_repo_rel(out_dir)} "
                "(input_manifest.jsonl + plan.json). Run --manifest-only first, review it, then "
                "score. The paid batch must be validated against a pre-committed plan.")
        return
    planned = {}
    for line in manifest_path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        planned[(r["run_id"], r["problem_id"], r["turn_index"])] = r
    actual = {(u["run_id"], u["problem_id"], u["turn_index"]): u for u in units}
    if set(planned) != set(actual):
        only_p = sorted(set(planned) - set(actual))[:5]
        only_a = sorted(set(actual) - set(planned))[:5]
        raise SystemExit(
            f"planned units no longer match the reconstruction for {loaded['human_base']}: "
            f"plan-only {only_p}, run-only {only_a}. The frozen inputs changed since planning; "
            "refusing the paid batch.")
    manifest_bases = {r.get("base") for r in planned.values()}
    if manifest_bases != {loaded["human_base"]}:
        raise SystemExit(
            f"the saved manifest in {_repo_rel(out_dir)} declares base(s) {sorted(manifest_bases)} "
            f"but this run scores {loaded['human_base']!r}; refusing the paid batch.")
    drifted = [k for k, u in actual.items()
               if planned[k].get("dialogue_sha256") != u["dialogue_sha256"]]
    if drifted:
        raise SystemExit(
            f"dialogue hash drift on {len(drifted)} unit(s) for {loaded['human_base']} "
            f"(e.g. {drifted[:3]}). The frozen transcripts or the dialogue reconstruction "
            "changed since planning; refusing the paid batch.")
    # FULL unit identity, not just the join key. `condition` and `replicate_id` are what every
    # per-policy analysis is cut by, and they live in the raw logs under logs/ -- which is
    # gitignored, so neither the clean-tree gate nor protected-primary.sha256 covers it. Keying
    # identity on (run_id, problem_id, turn_index) + dialogue hash alone meant a run could be
    # relabelled from conv to ped without changing a byte of dialogue, and the paid batch would
    # score it and publish misclassified per-policy results.
    id_drift = [(k, (planned[k].get("condition"), planned[k].get("replicate_id")),
                 (u["condition"], u["replicate_id"]))
                for k, u in actual.items()
                if str(planned[k].get("condition")) != str(u["condition"])
                or str(planned[k].get("replicate_id")) != str(u["replicate_id"])]
    if id_drift:
        raise SystemExit(
            f"unit IDENTITY drift on {len(id_drift)} unit(s) for {loaded['human_base']}: the "
            f"condition/replicate_id recorded in the frozen manifest no longer matches the "
            f"reconstruction (e.g. {id_drift[:3]} as (key, planned, now)). The raw logs were "
            "relabelled after planning; refusing the paid batch -- every per-policy result "
            "would be misclassified.")
    # The manifest pins each source transcript by hash. Verifying it here is the only check that
    # the gitignored raw logs are still byte-identical to what was planned.
    log_sha: dict[str, Optional[str]] = {}
    log_drift = []
    for k, u in actual.items():
        want = planned[k].get("source_log_sha256")
        if not want:
            raise SystemExit(
                f"the saved manifest in {_repo_rel(out_dir)} records no source_log_sha256 for "
                f"{k}; the frozen transcripts cannot be verified. Regenerate the plan.")
        run_id = u["run_id"]
        if run_id not in log_sha:
            lp = REPO_ROOT / "logs" / run_id / "calls.jsonl"
            log_sha[run_id] = _sha256_file(lp) if lp.is_file() else None
        if log_sha[run_id] != want:
            log_drift.append((run_id, want[:12],
                              (log_sha[run_id] or "MISSING")[:12]))
    if log_drift:
        uniq = sorted(set(log_drift))
        raise SystemExit(
            f"source raw-log drift on {len(uniq)} run(s) for {loaded['human_base']} "
            f"(e.g. {uniq[:3]} as (run_id, planned, now)). logs/ is gitignored, so this is the "
            "only guard on the frozen transcripts; refusing the paid batch.")
    plan = json.loads(plan_path.read_text())
    if list(plan.get("rubrics", [])) != list(rubrics) or plan.get("reps") != reps:
        raise SystemExit(
            f"plan mismatch: planned rubrics={plan.get('rubrics')} reps={plan.get('reps')} but "
            f"this run requests rubrics={rubrics} reps={reps}.")


def assert_plan_frozen(loaded, out_dir: Path, rubrics: list[str], reps: int,
                       freeze_ref: str = PLAN_FREEZE_TAG) -> dict:
    """Bind the paid batch to the FROZEN plan, not merely to *a* self-consistent plan.

    `assert_plan_matches` only proves the plan on disk agrees with the current reconstruction.
    That is satisfiable *after* the freeze: the output namespace accepts arbitrary
    subdirectories and the clean-tree check ignores untracked files, so a post-tag
    `--manifest-only` could mint a fresh untracked plan -- possibly over different inputs,
    rubrics, or repetition counts -- and a paid run would accept it while HEAD stayed clean.

    This gate closes that path:
      1. the --out directory and --source-results dir must be the CANONICAL ones for this base;
      2. the design must be exactly both frozen rubrics and exactly three repetitions;
      3. plan.json, input_manifest.jsonl, and protected-primary.sha256 must be byte-for-byte
         identical to their versions inside `freeze_ref`;
      4. the plan's own recorded base/source/rubrics/reps must match the canonical design.

    `freeze_ref` is a parameter (not the hardcoded tag) so the binding can be exercised against
    a stand-in ref offline, before the real freeze tag exists. It is only ever called from the
    live-scoring gate: offline reconstruction must keep working inside an extracted artifact
    that has no .git at all.
    """
    human_base = loaded["human_base"]
    if human_base not in CANONICAL_OUT:
        raise SystemExit(f"unknown base {human_base!r}: no canonical frozen plan location")

    want_out = CANONICAL_OUT[human_base]
    got_out = _repo_rel(out_dir)
    if got_out != want_out:
        raise SystemExit(
            f"live scoring must write to the CANONICAL frozen output path for base "
            f"{human_base!r}: expected {want_out}, got {got_out}. A plan under any other "
            "directory is not the frozen plan, however self-consistent it looks.")

    want_src = CANONICAL_SOURCE[human_base]
    got_src = loaded["source_results"]
    if got_src != want_src:
        raise SystemExit(
            f"live scoring for base {human_base!r} must read the CANONICAL frozen source "
            f"{want_src}, got {got_src}.")

    if list(rubrics) != list(REQUIRED_RUBRICS):
        raise SystemExit(
            f"live scoring must run exactly the two frozen rubrics {list(REQUIRED_RUBRICS)} "
            f"(amendment §2); got {list(rubrics)}. A rubric subset is a different design and "
            "must not be paid for under this freeze.")
    if reps != REQUIRED_REPS:
        raise SystemExit(
            f"live scoring must use exactly {REQUIRED_REPS} repetitions (amendment §5); "
            f"got {reps}.")

    frozen_head = _commit_of(freeze_ref)
    if frozen_head is None:
        raise SystemExit(
            f"cannot resolve the plan freeze ref {freeze_ref!r}; the paid batch must be bound to "
            "a committed, tagged plan.")

    for name in FROZEN_PLAN_FILES:
        live_path = out_dir / name
        rel = f"{want_out}/{name}"
        if not live_path.is_file():
            raise SystemExit(
                f"missing frozen plan artifact {rel}. Run --manifest-only, review it, commit it, "
                f"and tag {freeze_ref} before scoring.")
        frozen = _git_bytes("show", f"{frozen_head}:{rel}")
        if frozen is None:
            raise SystemExit(
                f"{rel} does not exist in {freeze_ref} ({str(frozen_head)[:12]}). The plan being "
                "scored was created after the freeze (it is untracked or was added later); "
                "refusing the paid batch -- the whole point of the freeze is that the design was "
                "fixed before any money was spent.")
        live = live_path.read_bytes()
        if live != frozen:
            raise SystemExit(
                f"{rel} differs from its frozen version in {freeze_ref} "
                f"(working tree sha256 {_sha256_text(live.decode('utf-8', 'replace'))[:12]} vs "
                f"frozen {_sha256_text(frozen.decode('utf-8', 'replace'))[:12]}, "
                f"{len(live)} vs {len(frozen)} bytes). The frozen plan was edited after tagging; "
                "refusing the paid batch.")

    plan = json.loads((out_dir / "plan.json").read_text())
    if plan.get("base") != human_base:
        raise SystemExit(f"frozen plan.json declares base {plan.get('base')!r}, scoring "
                         f"{human_base!r}.")
    if plan.get("source_results") != want_src:
        raise SystemExit(f"frozen plan.json declares source_results "
                         f"{plan.get('source_results')!r}, expected {want_src!r}.")
    if list(plan.get("rubrics", [])) != list(REQUIRED_RUBRICS):
        raise SystemExit(f"frozen plan.json declares rubrics {plan.get('rubrics')!r}, expected "
                         f"{list(REQUIRED_RUBRICS)}.")
    if plan.get("reps") != REQUIRED_REPS:
        raise SystemExit(f"frozen plan.json declares reps {plan.get('reps')!r}, expected "
                         f"{REQUIRED_REPS}.")
    return {"freeze_ref": freeze_ref, "freeze_commit": frozen_head,
            "canonical_out": want_out, "canonical_source": want_src,
            "verified_files": list(FROZEN_PLAN_FILES)}


# -------------------------------------------------------------------- CLI
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="configs/models.judge-gpt56.yaml")
    ap.add_argument("--out", required=True, help="results/judge_robustness/gpt-5.6-sol/<base>")
    ap.add_argument("--source-results", help="a frozen compute_metrics output dir "
                    "(results/confirmatory / _gpt / _gemini)")
    ap.add_argument("--rubrics", default="helpfulness,pedagogy")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--preflight", action="store_true",
                    help="synthetic transport preflight (no study text); writes preflight/")
    ap.add_argument("--manifest-only", action="store_true",
                    help="OFFLINE: write input_manifest.jsonl + protected-primary.sha256 + plan.json")
    ap.add_argument("--offline-cache-only", action="store_true",
                    help="reconstruct from the released per-rep cache; a miss aborts")
    ap.add_argument("--judge-backend", default="live", choices=("live", "mock"),
                    help="'live' (real GPT-5.6 Sol; needs the configured provider's API-key "
                         "env var, OPENROUTER_API_KEY) or 'mock' (offline"
                         "plumbing, synthetic scores -- DO NOT REPORT)")
    ap.add_argument("--max-provider-calls", type=int, default=None,
                    help="HARD ceiling on HTTP requests for this base, charged before EVERY "
                         "request including transport retries. Default: planned calls + a "
                         "10%% allowance covering parse and transport retries together. Set "
                         "it small for a canary tranche: the run stops at the cap with its "
                         "cache intact.")
    ap.add_argument("--allow-fingerprint-drift", action="store_true",
                    help="continue when the served system_fingerprint changes mid-batch "
                         "(an in-place backend update under the same model ID). Off by "
                         "default: drift aborts. When on, every fingerprint observed is "
                         "recorded and the run is marked as spanning multiple backends.")
    ap.add_argument("--verify-protected", action="store_true",
                    help="re-verify protected-primary.sha256 in --out and exit")
    args = ap.parse_args()

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    _enforce_namespace(out_dir)
    rubrics = [r.strip() for r in args.rubrics.split(",") if r.strip()]
    for r in rubrics:
        if r not in RUBRICS:
            raise SystemExit(f"unknown rubric {r!r}; choose from {list(RUBRICS)}")

    if args.verify_protected:
        failures = verify_protected_hashes(out_dir / "protected-primary.sha256")
        if failures:
            print("PROTECTED-PRIMARY CHANGED:")
            for f in failures:
                print("  " + f)
            raise SystemExit(1)
        print("PASS protected-primary: every protected file unchanged")
        return

    cfg = load_judge_cfg(args.models)

    if args.preflight:
        if args.judge_backend == "live":
            # A LIVE preflight is a real provider call that FREEZES the transport contract the
            # paid batch depends on. It must therefore run from the frozen tree too -- otherwise
            # a dirty, untagged checkout could resolve a contract that a later frozen scoring run
            # inherits, which is exactly the bypass the two-stage freeze exists to prevent.
            # (The mock preflight is offline plumbing and is deliberately not gated.)
            assert_live_freeze_state()
        resolved = run_preflight(cfg, out_dir, args.judge_backend)
        print(f"preflight ({args.judge_backend}) -> {_repo_rel(out_dir)}/resolved_config.json")
        print(f"  requested_model={resolved['requested_model']} "
              f"returned_model={resolved.get('returned_model')}")
        print(f"  seed_supported={resolved.get('seed_supported')} "
              f"parser_ok={resolved.get('parser_ok')} "
              f"finish_reasons={resolved.get('finish_reasons')}")
        return

    if not args.source_results:
        raise SystemExit("--source-results is required for manifest/scoring runs")
    loaded = _load_sessions(args.source_results)
    # Output isolation: the --out leaf must name the base being scored, so a Sonnet command can
    # never write into the gpt/ (or any other base's) directory.
    if out_dir.name != loaded["human_base"]:
        raise SystemExit(
            f"--out leaf {out_dir.name!r} does not match the base being scored "
            f"({loaded['human_base']!r}, from {loaded['source_results']}). Use "
            f".../gpt-5.6-sol/{loaded['human_base']} so per-base outputs stay isolated.")
    units_now = _planned_units(loaded)      # reconstructed once, reused by plan check + scoring
    n_units = len(units_now)

    if args.manifest_only:
        n = write_input_manifest(loaded, out_dir, args.reps, rubrics)
        plan = {"base": loaded["human_base"], "source_results": loaded["source_results"],
                "units": n, "rubrics": rubrics, "reps": args.reps,
                "expected_valid_ratings_per_rubric": n * args.reps,
                "expected_calls_total": n * len(rubrics) * args.reps,
                "freeze_tag": loaded["freeze_tag"], "freeze_head": loaded["freeze_head"]}
        _write_json(out_dir / "plan.json", plan)
        print(f"manifest-only ({loaded['human_base']}): {n} units -> "
              f"{_repo_rel(out_dir)}/input_manifest.jsonl")
        print(f"  expected calls: {n} units x {len(rubrics)} rubrics x {args.reps} reps = "
              f"{n * len(rubrics) * args.reps}")
        return

    # ---- scoring pass ----
    # The env-var name FOLLOWS the configured provider. A hardcoded "OPENAI_API_KEY" default
    # would let this check pass against a variable the runner never reads (or fail against one
    # it does), i.e. report readiness for the wrong route.
    _key_env = _provider_cfg(cfg).get("api_key_env")
    if args.judge_backend == "live" and not args.offline_cache_only and not (
            _key_env and os.environ.get(_key_env)):
        raise SystemExit(
            f"{_key_env or '<providers.*.api_key_env>'} is not set. The live GPT judge pass is "
            "blocked. Everything else (manifest, offline tests) is complete. See "
            "cross-judge-amendment-openrouter-2026-07-19.md for the exact live commands.")

    if args.offline_cache_only:
        # Reconstruction is self-contained: the stamp (returned_model, seed policy) is read
        # FROM the released cache and its frozen-content fields are validated there; no
        # preflight or provider is involved.
        resolved = {"seed_supported": False, "returned_model": None, "backend": "cache"}
    elif args.judge_backend == "mock":
        # offline plumbing: synthesize the resolved config
        resolved = run_preflight(cfg, out_dir.parent / "preflight", "mock")
    else:
        resolved = _load_resolved(out_dir, cfg, args.judge_backend)

    live_paid = (args.judge_backend == "live" and not args.offline_cache_only)

    # A paid batch must run from the frozen tree and against the pre-committed plan.
    if live_paid:
        assert_live_freeze_state()
        # ...and that plan must provably BE the frozen one (canonical paths, the exact frozen
        # design, and byte-identical plan artifacts inside the freeze tag) -- not merely a
        # self-consistent plan minted after tagging.
        assert_plan_frozen(loaded, out_dir, rubrics, args.reps)
    assert_plan_matches(loaded, out_dir, units_now, rubrics, args.reps, require=live_paid)

    # protected-primary: VERIFY the baseline written at plan time -- never rewrite it here
    # (rewriting then verifying would be tautological and would silently re-baseline any
    # post-planning change to a protected file).
    prot = out_dir / "protected-primary.sha256"
    if prot.exists():
        pre = verify_protected_hashes(prot)
        if pre:
            raise SystemExit(
                "PROTECTED-PRIMARY changed since the plan baseline was written:\n  "
                + "\n  ".join(pre[:20])
                + "\nRefusing to score: the frozen primary artifacts must be byte-identical.")
    elif live_paid:
        raise SystemExit(
            f"no protected-primary.sha256 baseline in {_repo_rel(out_dir)}; run --manifest-only "
            "first so the paid run can verify the frozen artifacts against a pre-committed "
            "baseline.")
    else:
        write_protected_hashes(prot)   # offline/mock: establish a baseline to verify against

    mode = "offline-cache-only" if args.offline_cache_only else args.judge_backend
    names = final_output_names(rubrics)

    # Everything from invalidation through promotion runs under an exclusive per-base lock.
    # Without it two concurrent invocations for the same base would duplicate paid calls,
    # clobber each other's run state, sweep each other's staging directories, and interleave
    # their promotions into a mixed output set.
    with run_lock(out_dir):
        # Transactional output promotion. Every attempt first invalidates whatever was published
        # before, so an attempt that ends incomplete can never leave the PREVIOUS run's detail
        # files, CSVs, inference, policy-adjusted analysis, or provenance reportable next to a new
        # partial cache and wire log.
        invalidated = invalidate_outputs(out_dir, reason=f"{mode} scoring attempt started", payload={
            "base": loaded["human_base"], "rubrics": list(rubrics), "reps": args.reps,
            "backend": mode, "units": n_units})
        if invalidated:
            print(f"invalidated {len(invalidated)} previously promoted output(s) in "
                  f"{_repo_rel(out_dir)} before scoring")
        cap = (args.max_provider_calls if args.max_provider_calls is not None
               else default_max_provider_calls(n_units, len(rubrics), args.reps))
        print(f"spend ceiling: {cap:,} HTTP requests (transport retries included; "
              f"{n_units * len(rubrics) * args.reps:,} planned + retry allowance); "
              f"circuit breaker below {BREAKER_MIN_ACCEPT_RATE:.0%} accepted after "
              f"{BREAKER_WARMUP_CALLS} responses")

        scored = score_base(loaded, cfg, out_dir, rubrics, args.reps, args.judge_backend,
                            args.offline_cache_only, resolved, units=units_now,
                            max_provider_calls=args.max_provider_calls,
                            allow_fingerprint_drift=args.allow_fingerprint_drift)
        completeness = check_completeness(scored, args.reps)

        # protected-primary must be unchanged BY the run (same baseline, re-verified)
        post = verify_protected_hashes(prot)
        if post:
            raise SystemExit("PROTECTED-PRIMARY CHANGED during scoring: " + "; ".join(post))

        if not completeness["complete"]:
            clear_staging(out_dir)
            removed = discard_outputs(out_dir)
            mark_run_state(out_dir, "incomplete", {
                "complete": False, "base": loaded["human_base"], "rubrics": list(rubrics),
                "reps": args.reps, "backend": mode, "units": n_units,
                "discarded_stale_outputs": removed,
                "note": "Scoring did not reach n_valid == reps for every planned turn and rubric. "
                        "No results are published; the cache and wire logs stay resumable. "
                        "Re-run the same command to finish.",
                **completeness})
            print(f"INCOMPLETE ({loaded['human_base']}): not writing final tables; cache + wire are "
                  "resumable. Re-run the same command to finish.")
            if removed:
                print(f"  discarded {len(removed)} stale output(s) from the previous run: "
                      f"{', '.join(removed)}")
            for inst, pr in completeness["per_rubric"].items():
                print(f"  {inst}: valid {pr['valid_ratings']}/{pr['expected_valid']} "
                      f"(incomplete turns: {pr['n_turns_incomplete']}, "
                      f"parse_failures: {pr['parse_failures']})")
            raise SystemExit(2)

        # Build into a staging directory, then promote the verified-complete set atomically.
        # `tmp.` prefix: covered by the namespace .gitignore and skipped by the artifact builder.
        staging = out_dir / f"{STAGING_PREFIX}{os.getpid()}"
        clear_staging(out_dir)
        try:
            build_outputs(loaded, scored, completeness, staging, cfg, mode, resolved,
                          args.reps, rubrics)
            promote_outputs(staging, out_dir, names, {
                "complete": True, "base": loaded["human_base"], "rubrics": list(rubrics),
                "reps": args.reps, "backend": mode, "units": n_units,
                "promoted_outputs": list(names),
                "cache_stamps": {i: scored["detail"][i]["stamp"] for i in rubrics
                                 if i in scored["detail"]},
                "note": "Complete promoted set. Consumers must require state == 'complete' and "
                        "cache stamps matching these before reporting or packaging these outputs."})
        finally:
            # Any exit other than a successful promotion (a raise in build_outputs, promote's own
            # refusal, Ctrl-C) must not leave unpromoted results on disk for a later manifest build
            # to pin. promote_outputs already removed it on success; this is idempotent.
            clear_staging(out_dir)
        print(f"wrote {_repo_rel(out_dir)}/  (base={loaded['human_base']}, "
              f"units={n_units}, mode={mode})")
        for inst, pr in completeness["per_rubric"].items():
            print(f"  {inst}: {pr['n_turns']} turns, {pr['valid_ratings']} valid ratings, "
                  f"parse_retries={pr['parse_retries']}, transport_retries={pr['transport_retries']}")


if __name__ == "__main__":
    main()
