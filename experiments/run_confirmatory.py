"""Confirmatory 10x3 runner -- the FROZEN-STATE experiment driver.

Runs 10 replicates x {cold, conv, ped} through the frozen continuous protocol
(protocol.full_session.run_full_session), one session per cell into its own
logs/<run_id>/, tagging EVERY model call with `condition` and `replicate_id` so the
metrics pipeline pairs by replicate id (paper-plan.md §10). This is the inferential
run; unlike experiments/run_pilot.py (non-inferential, no call tags) it:

  - tags condition + replicate_id on every call (the "logging fix #2" the Step-5
    entry left to this runner; analysis/metrics.py already READS those tags);
  - REFUSES to run unless the tree is clean and at the freeze commit (so the
    pre-registration is frozen before any confirmatory datum exists);
  - resumes at (condition, replicate) granularity after a rate-limit abort.

Integrity / condition-neutrality:
  - The call path is IDENTICAL for conv and ped: same TaggingClient, same seed,
    same turn budget, same tagging. The ONLY per-condition difference is the
    unavoidable one -- cold has no tutor (tutor=None), conv uses ConvTutor, ped
    uses PedTutor. No throttling/backoff is added here (the client's existing
    _with_backoff is reused unchanged), so sampling is not silently altered and a
    quota abort is not masked -- it propagates loudly and the cell is resumed.
  - replicate r uses seed = base_seed + r for ALL three conditions (paired), and
    is tagged replicate_id = r (the pairing key, independent of base_seed).
  - canonical_answer never reaches a live prompt: this runner only drives the
    frozen protocol/agents, which already keep the answer out of every live prompt
    (it lives in mock_meta, ignored by the live backend).
  - Reads the frozen problems/configs; never writes them.

The LIVE 10x3 (Anthropic Sonnet tutor, OpenRouter->Groq student, Opus judge) is run
separately; this file is built and mock-validated offline. See experiments/RUN.md for
the live command/gate order.

Usage:
  # offline plumbing rehearsal (synthetic, NOT a result; freeze guard not enforced):
  python experiments/run_confirmatory.py --backend mock --replicates 2

  # live confirmatory run (lead): commit the freeze first, then:
  ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... \
      python experiments/run_confirmatory.py --replicates 10 \
      --freeze-commit <freeze-hash>

  # resume after an abort (skips completed cells; re-does only missing ones):
  python experiments/run_confirmatory.py --replicates 10 --freeze-commit <freeze-hash>

  # cross-model base run (pre-registered extension): ONLY the tutor model changes
  # (a per-base configs/models.<base>.yaml); --base namespaces the logs so the base
  # can never overwrite or be pooled with the primary (Sonnet) cells:
  ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... OPENAI_API_KEY=... \
      python experiments/run_confirmatory.py --replicates 10 \
      --models configs/models.gpt.yaml --base gpt --freeze-commit <crossmodel-freeze-hash>

  # just show which cells are done / missing, run nothing:
  python experiments/run_confirmatory.py --replicates 10 --status

  # ablation extension (#5; pre-registered, DESCRIPTIVE; decisions-log 2026-06-30): runs ONLY
  # the ablation conditions on the PRIMARY Sonnet config (NOT --base), namespaced `abl-...`,
  # paired with the existing primary baselines; needs its OWN ablation freeze:
  ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... \
      python experiments/run_confirmatory.py --replicates 10 \
      --conditions conv_socratic,conv_no_final_answer,ped_no_gate,ped_no_tracker,ped_no_cascade \
      --freeze-commit ABLATION_FREEZE_HASH   # the ablation freeze (falls back to the `ablation-freeze` tag)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.config import load_models_config  # noqa: E402
from agents.logging_utils import RunLogger  # noqa: E402
from agents.model_client import ModelClient  # noqa: E402
from protocol.full_session import run_full_session  # noqa: E402
from protocol.session import load_problems  # noqa: E402

CONDITIONS = ("cold", "conv", "ped")

# ----- #5 ablation conditions (pre-registered, ADDITIVE; decisions-log 2026-06-30) -----
# DESCRIPTIVE extensions on the PRIMARY Sonnet config (NOT a cross-model --base). Each maps
# to (agent_kind, config). conv_* reuse the minimal ConvTutor agent with a NEW prompt config
# (single call, unchanged path); ped_* use the PedTutorVariant subclass with a NEW thin
# variant config (one node dropped). The minimal ConvTutor + frozen PedTutor + their configs
# stay byte-stable. Run ids are namespaced `abl-...` (distinct from the primary `conf-...`)
# and reuse the SAME base-seed / replicate structure so each ablation replicate r pairs with
# the existing primary conv/ped/cold replicate r (seed = base_seed + r). Ablations are NEVER
# fed to the frozen §10 run_inference (J1/J2); they go through compute_metrics + the separate
# descriptive analysis/ablation_analysis.py.
ABLATION_SPECS = {
    "conv_socratic":        ("conv",    "configs/conv_socratic.yaml"),
    "conv_no_final_answer": ("conv",    "configs/conv_no_final_answer.yaml"),
    "ped_no_gate":          ("ped_var", "configs/ped_no_gate.yaml"),
    "ped_no_tracker":       ("ped_var", "configs/ped_no_tracker.yaml"),
    "ped_no_cascade":       ("ped_var", "configs/ped_no_cascade.yaml"),
}
ABLATION_CONDITIONS = tuple(ABLATION_SPECS)
ABLATION_FREEZE_TAG = "ablation-freeze"   # ablations have their OWN freeze (NOT confirmatory-freeze)

LOGS_DIR = REPO_ROOT / "logs"


# --------------------------------------------------------------- tagging client
class TaggingClient(ModelClient):
    """A ModelClient that stamps `condition` and `replicate_id` onto EVERY model
    call. complete() is the one code path taken by every role and every condition,
    so the stamp is uniform by construction -- it cannot advantage one tutor. The
    base tags are AUTHORITATIVE (merged last) so they can never be clobbered by a
    per-call tag; the per-call tags written by the agents (component / problem_id /
    turn_index / node / branch) use disjoint keys, so nothing is overwritten."""

    def __init__(self, models_cfg, backend, logger, base_tags):
        super().__init__(models_cfg=models_cfg, backend=backend, logger=logger)
        self._base_tags = dict(base_tags)

    def complete(self, role, system, messages, seed, tags=None, mock_meta=None):
        merged = {**(tags or {}), **self._base_tags}
        return super().complete(role, system, messages, seed,
                                tags=merged, mock_meta=mock_meta)


# --------------------------------------------------------------- freeze guard
def git_state(repo_root: Path) -> dict:
    """Current git HEAD + working-tree cleanliness. `dirty` is True if there is ANY
    modified, staged, or UNTRACKED file (a confirmatory run must be fully committed;
    gitignored paths like logs/ and results/ do not count -- git omits them)."""
    def _git(*a):
        return subprocess.run(["git", "-C", str(repo_root), *a],
                              capture_output=True, text=True)

    head = _git("rev-parse", "HEAD")
    if head.returncode != 0:
        return {"head": None, "dirty": True, "porcelain": "(not a git repository)"}
    porc = _git("status", "--porcelain")
    out = porc.stdout
    return {"head": head.stdout.strip(), "dirty": bool(out.strip()), "porcelain": out}


def resolve_freeze_commit(arg_commit, repo_root: Path, default_tag: str = "confirmatory-freeze"):
    """The expected freeze commit, in priority: --freeze-commit > $FREEZE_COMMIT >
    the `default_tag` git tag. None if none is set. An empty/whitespace value is
    treated as not-set (it must NEVER be able to match HEAD and bypass the guard).
    `default_tag` is `confirmatory-freeze` for the primary; an ablation run passes
    `ablation-freeze` so it can NEVER fall back to the (wrong) confirmatory freeze."""
    if arg_commit and arg_commit.strip():
        return arg_commit.strip()
    env = (os.environ.get("FREEZE_COMMIT") or "").strip()
    if env:
        return env
    tag = subprocess.run(["git", "-C", str(repo_root), "rev-parse", default_tag],
                         capture_output=True, text=True)
    if tag.returncode == 0 and tag.stdout.strip():
        return tag.stdout.strip()
    return None


def check_freeze(state: dict, expected_commit, enforce: bool) -> dict:
    """Decide whether the run may proceed and return a metadata record. When
    `enforce` is True (the live run), raise SystemExit unless the tree is clean AND
    at the freeze commit. The freeze hash + cleanliness are recorded either way."""
    head, dirty = state["head"], state["dirty"]
    # Match only a full hash or a >=7-char prefix of HEAD (git's short-hash floor).
    # No reverse-prefix and no <7-char match -- both would let a too-short or garbage
    # value spuriously "match" and silently bypass the guard on a live run.
    matches = (expected_commit is not None and head is not None
               and len(expected_commit) >= 7
               and (head == expected_commit or head.startswith(expected_commit)))
    at_freeze = bool(matches) and not dirty
    meta = {"head": head, "dirty": dirty, "expected_commit": expected_commit,
            "at_freeze_commit": at_freeze, "enforced": enforce,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if not enforce:
        return meta
    if dirty:
        raise SystemExit(
            "FREEZE GUARD: working tree is DIRTY (uncommitted or untracked changes). "
            "Commit the confirmatory freeze first (and gitignore scratch dirs) so the "
            "run is reproducible from one hash. `git status` shows what is uncommitted:\n"
            + state["porcelain"])
    if expected_commit is None:
        raise SystemExit(
            "FREEZE GUARD: no freeze commit specified. Pass --freeze-commit <hash> "
            "(the commit you froze the pre-registration at), or set $FREEZE_COMMIT, or "
            "tag it `confirmatory-freeze`. The runner will not start a confirmatory run "
            "without confirming HEAD is the freeze commit.")
    if not matches:
        raise SystemExit(
            f"FREEZE GUARD: HEAD ({head}) is not the freeze commit ({expected_commit}). "
            "Check out the freeze commit before running the confirmatory experiment.")
    return meta


# --------------------------------------------------------------- provider keys
def missing_provider_keys(models_cfg: dict, roles) -> list:
    """For each role, the (role, provider, api_key_env) whose key env is NOT set in the
    environment. Mirrors the provider/key resolution in agents/model_client.py, so a live
    run can fail fast with a clear message naming the env var instead of dying mid-run
    with a RuntimeError on the first call."""
    out = []
    providers = models_cfg.get("providers") or {}
    for role in roles:
        spec = models_cfg["roles"][role]
        provider = spec.get("provider") or models_cfg.get("provider") or "anthropic"
        env = (providers.get(provider, {}).get("api_key_env")
               or ("ANTHROPIC_API_KEY" if provider == "anthropic" else ""))
        if env and not os.environ.get(env):
            out.append((role, provider, env))
    return out


# --------------------------------------------------------------- cross-model guards
PRIMARY_MODELS = "configs/models.yaml"   # the frozen primary config a base is checked against


def tutor_only_drift(base_cfg: dict, primary_cfg: dict) -> list:
    """For a cross-model base run the ONLY allowed change vs the frozen primary config is
    the tutor's model (and the provider it routes through). Returns the list of FORBIDDEN
    differences -- student/judge role specs, the providers those roles use, the tutor's
    sampling budget, or the global backend -- so 'only the tutor changes' (paper-plan §12)
    is ENFORCED before a base run, not just logged after the fact."""
    drift = []
    broles, proles = base_cfg.get("roles", {}), primary_cfg.get("roles", {})
    for role in ("student", "judge"):
        if broles.get(role) != proles.get(role):
            drift.append(f"roles.{role} differs from the primary")
    bprov, pprov = base_cfg.get("providers") or {}, primary_cfg.get("providers") or {}
    for role in ("student", "judge"):
        name = (broles.get(role, {}).get("provider")
                or base_cfg.get("provider") or "anthropic")
        if bprov.get(name) != pprov.get(name):
            drift.append(f"providers.{name} (used by {role}) differs from the primary")
    bt, pt = broles.get("tutor", {}), proles.get("tutor", {})
    for k in ("temperature", "max_tokens"):
        if bt.get(k) != pt.get(k):
            drift.append(f"roles.tutor.{k} differs from the primary (only the model may change)")
    if base_cfg.get("backend") != primary_cfg.get("backend"):
        drift.append("global backend differs from the primary")
    return drift


# The registered confirmatory protocol -- a LIVE cross-model base run must match it
# exactly (only the tutor model changes; paper-plan §12). These are runtime knobs the
# freeze guard does NOT see (it only pins the committed files), so they are checked here.
REGISTERED_PROTOCOL = {
    "domain": "domain/algebra/problems.yaml",
    "conditions": ["cold", "conv", "ped"],
    "replicates": 10,
    "base_seed": 0,
    "max_train_turns": 4,
}


def protocol_knob_drift(args, conds: list) -> list:
    """Runtime invocation knobs that differ from the registered protocol. Used to refuse a
    LIVE `--base` run that quietly changes the domain, conditions, replicate count, seed
    schedule, or turn budget -- any of which would break 'only the tutor changes' while
    still producing base-tagged logs that look legitimate."""
    drift = []
    if args.domain != REGISTERED_PROTOCOL["domain"]:
        drift.append(f"--domain {args.domain!r} != {REGISTERED_PROTOCOL['domain']!r}")
    if conds != REGISTERED_PROTOCOL["conditions"]:
        drift.append(f"--conditions {conds} != {REGISTERED_PROTOCOL['conditions']}")
    if args.replicates != REGISTERED_PROTOCOL["replicates"]:
        drift.append(f"--replicates {args.replicates} != {REGISTERED_PROTOCOL['replicates']}")
    if args.base_seed != REGISTERED_PROTOCOL["base_seed"]:
        drift.append(f"--base-seed {args.base_seed} != {REGISTERED_PROTOCOL['base_seed']}")
    if args.max_train_turns != REGISTERED_PROTOCOL["max_train_turns"]:
        drift.append(f"--max-train-turns {args.max_train_turns} != "
                     f"{REGISTERED_PROTOCOL['max_train_turns']}")
    return drift


def ablation_protocol_drift(args, conds: list) -> list:
    """Runtime knobs that differ from the pre-registered ablation protocol. A LIVE ablation
    run must use ONLY the pre-registered ablation conditions on the PRIMARY Sonnet config and
    the SAME domain / replicate count / seed schedule / turn budget as the primary (so each
    ablation replicate pairs with its frozen primary baseline). The freeze guard pins the
    committed files; these are the runtime knobs it does not see."""
    drift = []
    bad = [c for c in conds if c not in ABLATION_CONDITIONS]
    if bad:
        drift.append(f"conditions {bad} are not pre-registered ablation conditions "
                     f"({list(ABLATION_CONDITIONS)})")
    if args.models != PRIMARY_MODELS:
        drift.append(f"--models {args.models!r} != {PRIMARY_MODELS!r} "
                     "(ablations run on the primary Sonnet config, not a --base config)")
    if args.domain != REGISTERED_PROTOCOL["domain"]:
        drift.append(f"--domain {args.domain!r} != {REGISTERED_PROTOCOL['domain']!r}")
    if args.replicates != REGISTERED_PROTOCOL["replicates"]:
        drift.append(f"--replicates {args.replicates} != {REGISTERED_PROTOCOL['replicates']}")
    if args.base_seed != REGISTERED_PROTOCOL["base_seed"]:
        drift.append(f"--base-seed {args.base_seed} != {REGISTERED_PROTOCOL['base_seed']}")
    if args.max_train_turns != REGISTERED_PROTOCOL["max_train_turns"]:
        drift.append(f"--max-train-turns {args.max_train_turns} != "
                     f"{REGISTERED_PROTOCOL['max_train_turns']}")
    return drift


def cell_meta_mismatch(d: Path, expected: dict, require_present=()) -> str | None:
    """For a file-complete cell, compare its recorded confirmatory_meta.json against the
    CURRENT invocation. Returns a human-readable mismatch reason, or None if it matches.
    Keys in `require_present` MUST appear in the recorded meta (a base invocation requires
    base + tutor_model); their ABSENCE is a mismatch -- it flags a pre-hardening or
    hand-assembled cell that would otherwise be silently skipped. Other keys absent from a
    (legacy/primary) meta are tolerated. This stops a stale or contaminated cell -- same
    conf-<base>-s.. namespace, different tutor id / config / freeze -- from being skipped."""
    try:
        m = json.loads((d / "confirmatory_meta.json").read_text())
    except (ValueError, OSError):
        return "unreadable confirmatory_meta.json"
    for k in ("condition", "replicate_id", "seed", "backend", "max_train_turns",
              "models_config", "base", "tutor_model"):
        if k in expected and k not in m and k in require_present:
            return f"{k}: missing from recorded meta (expected {expected.get(k)!r})"
        if k in m and k in expected and m.get(k) != expected.get(k):
            return f"{k}: recorded {m.get(k)!r} != current {expected.get(k)!r}"
    rec_head = (m.get("freeze") or {}).get("head")
    want = expected.get("freeze_head")
    if want and rec_head and not (rec_head == want or rec_head.startswith(want)
                                  or want.startswith(rec_head)):
        return f"freeze head: recorded {rec_head!r} != current {want!r}"
    return None


# --------------------------------------------------------------- cells / resume
def cell_run_id(base_seed: int, cond: str, r: int, base: str = "",
                ablation: bool = False) -> str:
    """Deterministic per-cell run id so a cell maps to ONE logs/<run_id>/ dir and a
    resume is idempotent (re-running a completed cell is a no-op; the base seed is in
    the id so two batches at different seeds never collide). A cross-model `base` tag
    (e.g. "gpt", "gemini") namespaces the id -- `conf-gpt-s0-conv-r0` -- so a
    cross-model base run can NEVER overwrite or be pooled with the primary (Sonnet)
    cells `conf-s0-conv-r0`. Empty base reproduces the primary ids byte-for-byte.
    `ablation` (#5; mutually exclusive with a cross-model base) namespaces the id
    `abl-s0-conv_socratic-r0`, disjoint from the primary `conf-...` cells so an ablation run
    can never overwrite a primary cell and a primary glob (`logs/conf-s0-*`) never picks up
    an ablation cell."""
    if ablation:
        prefix = "abl-"   # ablation namespace (primary Sonnet base; no cross-model base)
    else:
        prefix = f"conf-{base}-" if base else "conf-"
    return f"{prefix}s{base_seed}-{cond}-r{r}"


def cell_dir(base_seed: int, cond: str, r: int, base: str = "",
             ablation: bool = False) -> Path:
    return LOGS_DIR / cell_run_id(base_seed, cond, r, base, ablation)


def cell_complete(d: Path) -> bool:
    """A cell is complete iff calls were logged, the session result was written, AND the
    run's `confirmatory_meta.json` (the LAST file run_cell writes -- the freeze-provenance
    record) is present and valid. Gating on the last-written file means a crash between
    the result json and the meta leaves the cell INCOMPLETE (re-run on resume), so resume
    never skips a cell whose freeze hash + run metadata were not recorded."""
    calls = d / "calls.jsonl"
    if not (calls.exists() and calls.stat().st_size > 0):
        return False
    if not (d / "full_session_result.json").exists():
        return False
    meta = d / "confirmatory_meta.json"
    if not meta.exists():
        return False
    try:
        m = json.loads(meta.read_text())
    except (ValueError, OSError):
        return False
    return bool(m.get("condition")) and m.get("replicate_id") is not None


def plan_cells(conds, replicates: int, base_seed: int, base: str = "",
               ablation: bool = False) -> list[dict]:
    """The full (condition, replicate) grid. Replicate r: seed = base_seed + r for
    every condition (paired), tagged replicate_id = r. `base` namespaces the run ids
    (cross-model extension); empty = the primary namespace. `ablation` namespaces the run
    ids `abl-...` (#5) and uses the SAME seed schedule as the primary so each ablation
    replicate pairs with its frozen primary baseline replicate."""
    cells = []
    for r in range(replicates):
        for cond in conds:
            cells.append({"condition": cond, "replicate": r,
                          "seed": base_seed + r,
                          "run_id": cell_run_id(base_seed, cond, r, base, ablation)})
    return cells


# --------------------------------------------------------------- run one cell
def build_tutor(cond: str, client):
    """The tutor instance for a condition (None for cold). Lazy imports so a cold run where
    langgraph is unavailable does not import the tutors. The cold/conv/ped PRIMARY path is
    byte-identical to before (default configs, no config argument); ablation conditions
    thread their NEW per-condition config -- conv_* reuse the minimal ConvTutor agent with a
    new prompt config (single call), ped_* use the PedTutorVariant subclass with a new thin
    variant config (one node dropped). The frozen agents/configs are never edited."""
    if cond == "cold":
        return None
    if cond == "conv":
        from agents.conv_tutor import ConvTutor
        return ConvTutor(client)
    if cond == "ped":
        from agents.ped_tutor import PedTutor
        return PedTutor(client)
    spec = ABLATION_SPECS.get(cond)
    if spec is None:
        raise SystemExit(f"unknown condition {cond!r} "
                         f"(expected {'|'.join(CONDITIONS)} or an ablation: "
                         f"{'|'.join(ABLATION_CONDITIONS)})")
    kind, cfg = spec
    if kind == "conv":
        from agents.conv_tutor import ConvTutor
        return ConvTutor(client, config_path=cfg)
    if kind == "ped_var":
        from agents.ped_ablations import PedTutorVariant
        return PedTutorVariant(client, config_path=cfg)
    raise SystemExit(f"unknown ablation agent kind {kind!r} for condition {cond!r}")


def run_cell(cell: dict, problems, models_cfg, backend: str, max_train_turns: int,
             freeze_meta: dict, models_path: str, base: str = "") -> dict:
    """Run one (condition, replicate) cell into its own deterministic logs dir.
    Clears any partial dir first so a re-run never appends to / mixes a prior abort."""
    cond, r, seed, run_id = (cell["condition"], cell["replicate"],
                             cell["seed"], cell["run_id"])
    d = LOGS_DIR / run_id
    if d.exists():
        shutil.rmtree(d)   # partial/incomplete cell: start clean (no append-mixing)

    logger = RunLogger(run_id)
    # `base` (the cross-model tutor-base tag) is stamped on EVERY call alongside
    # condition/replicate_id, so analysis can group by base and never pool two bases.
    # Only added when set, so the primary's call records stay byte-identical.
    base_tags = {"condition": cond, "replicate_id": r}
    if base:
        base_tags["base"] = base
    client = TaggingClient(models_cfg=models_cfg, backend=backend, logger=logger,
                           base_tags=base_tags)
    tutor = build_tutor(cond, client)

    res = run_full_session(problems, client, tutor=tutor, seed=seed,
                           condition=cond, max_train_turns=max_train_turns)
    logger.write_json("full_session_result.json", asdict(res))
    # Write the meta LAST -- cell_complete() uses it as the completion sentinel, so a
    # crash before this point leaves the cell incomplete (re-run on resume) rather than
    # skipped without its freeze provenance.
    meta = {
        "run_id": run_id, "condition": cond, "replicate_id": r, "seed": seed,
        "backend": backend, "max_train_turns": max_train_turns,
        "models_config": models_path, "freeze": freeze_meta,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if base:
        # Cross-model provenance: the base + its resolved tutor model (the only role
        # that changes). OMITTED for the primary so the primary's meta key set stays
        # byte-identical to the frozen runner's output -- mirrors the per-call base tag.
        meta["base"] = base
        meta["tutor_model"] = (models_cfg.get("roles", {}).get("tutor", {}) or {}).get("model")
    logger.write_json("confirmatory_meta.json", meta)
    print(f"  {cond:5s} r{r:<2d} seed={seed} -> logs/{run_id}/  "
          f"items={len(res.items)} calls={logger._call_seq} "
          f"total_tokens={res.total_tokens} tutor_calls={res.n_model_calls}")
    return {"run_id": run_id, "calls": logger._call_seq, "total_tokens": res.total_tokens}


# --------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replicates", type=int, default=10,
                    help="confirmatory replicates per condition (paper-plan §10 = 10).")
    ap.add_argument("--base-seed", type=int, default=0,
                    help="replicate r uses seed = base-seed + r for all conditions.")
    ap.add_argument("--base", default="",
                    help="cross-model tutor-base tag (e.g. 'gpt', 'gemini'). Namespaces "
                         "run ids/dirs (conf-<base>-s0-...) and is stamped on every call "
                         "and the run meta, so a cross-model base can NEVER overwrite or "
                         "be pooled with the primary (Sonnet) cells. Empty = the primary "
                         "namespace (ids/tags byte-identical to the primary).")
    ap.add_argument("--conditions", default="cold,conv,ped")
    ap.add_argument("--domain", default="domain/algebra/problems.yaml")
    ap.add_argument("--models", default="configs/models.yaml")
    ap.add_argument("--backend", default="live", choices=("live", "mock"),
                    help="'live' (real models; freeze guard ENFORCED) or 'mock' "
                         "(offline plumbing rehearsal -- synthetic, freeze guard recorded "
                         "but NOT enforced; NOT a result).")
    ap.add_argument("--max-train-turns", type=int, default=4,
                    help="visible tutor-turn budget per training problem. IDENTICAL "
                         "across conditions; keep at the pilot/protocol value (4).")
    ap.add_argument("--freeze-commit", default=None,
                    help="the freeze commit hash; HEAD must equal it (live). Falls back to "
                         "$FREEZE_COMMIT, then a git tag: `confirmatory-freeze` for a primary "
                         "run, `ablation-freeze` for an ablation (#5) run.")
    ap.add_argument("--status", action="store_true",
                    help="print which cells are complete/missing and exit (runs nothing).")
    ap.add_argument("--force", action="store_true",
                    help="re-run ALL cells even if complete (clears their dirs). Off by "
                         "default so a resume only fills missing cells. REFUSED on "
                         "--backend live -- it would overwrite already-collected cells.")
    args = ap.parse_args()

    conds = [c.strip() for c in args.conditions.split(",") if c.strip()]
    # A run is EITHER all-primary (cold/conv/ped) OR all-ablation (#5). Mixing is refused so
    # the freeze namespace, the freeze-tag fallback, and the analysis path stay unambiguous
    # (primary -> conf-/confirmatory-freeze/run_inference; ablation -> abl-/ablation-freeze/
    # the descriptive analysis). The existing cold/conv/ped path is unchanged when no
    # ablation condition is requested.
    is_ablation = any(c in ABLATION_CONDITIONS for c in conds)
    known = set(CONDITIONS) | set(ABLATION_CONDITIONS)
    for c in conds:
        if c not in known:
            raise SystemExit(f"unknown condition {c!r} (expected {'|'.join(CONDITIONS)} "
                             f"or an ablation: {'|'.join(ABLATION_CONDITIONS)})")
    if is_ablation:
        non_abl = [c for c in conds if c not in ABLATION_CONDITIONS]
        if non_abl:
            raise SystemExit(
                f"cannot mix ablation and primary conditions in one run: {non_abl} are not "
                f"ablation conditions. Ablation runs use ONLY {list(ABLATION_CONDITIONS)} and "
                "reuse the EXISTING primary cold/conv/ped cells as baselines (do not re-run "
                "them). Run the primary grid and the ablation grid separately.")
        if args.base:
            raise SystemExit(
                "--base (cross-model) and ablation conditions are mutually exclusive: "
                "ablations run on the PRIMARY Sonnet config, not a --base config. Drop --base.")
    # A base tag becomes part of run-id dir names: keep it a safe lowercase slug
    # (alphanumeric ends, internal dashes only) so it can't collide with the primary
    # namespace or produce odd paths like `conf-gpt--s0-...`.
    if args.base and not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", args.base):
        raise SystemExit(
            f"--base {args.base!r} must be a lowercase slug [a-z0-9-] starting and "
            "ending alphanumeric (e.g. 'gpt', 'gemini', 'gpt-4o').")
    cells = plan_cells(conds, args.replicates, args.base_seed, args.base, is_ablation)

    # ----- resume bookkeeping (disk is the source of truth) -----
    done = [c for c in cells if cell_complete(LOGS_DIR / c["run_id"])]
    todo = cells if args.force else [c for c in cells if c not in done]

    if args.status:
        kind = "ablation (#5)" if is_ablation else "confirmatory"
        print(f"{kind} grid: {len(conds)} conditions x {args.replicates} replicates "
              f"= {len(cells)} cells (base_seed={args.base_seed})")
        print(f"  complete: {len(done)}   missing: {len(cells) - len(done)}")
        for c in cells:
            mark = "done" if cell_complete(LOGS_DIR / c["run_id"]) else "MISSING"
            print(f"    [{mark:7s}] {c['run_id']}")
        return

    if args.force and args.backend == "live":
        raise SystemExit(
            "--force is REFUSED on a live confirmatory run: it deletes and resamples "
            "already-collected cells under the same run ids, making the dataset "
            "non-auditable and irreproducible. To redo cells, manually quarantine the "
            "old logs/conf-* dirs (or use a fresh --base-seed namespace) and re-run "
            "WITHOUT --force -- resume then fills only the missing cells.")

    # ----- freeze guard (enforced live; recorded-only on the mock rehearsal) -----
    # Ablations have their OWN freeze (the ablation code is NEW -- not the confirmatory
    # freeze); their tag fallback is `ablation-freeze` so a tag-resolved live ablation run
    # can never bind to the wrong (confirmatory) freeze.
    state = git_state(REPO_ROOT)
    default_tag = ABLATION_FREEZE_TAG if is_ablation else "confirmatory-freeze"
    expected = resolve_freeze_commit(args.freeze_commit, REPO_ROOT, default_tag)
    enforce = (args.backend == "live")
    freeze_meta = check_freeze(state, expected, enforce=enforce)
    if not enforce:
        print("*** backend=mock: synthetic plumbing data, NOT a result. "
              "Freeze guard recorded but NOT enforced. ***")
        print(f"    git: head={freeze_meta['head']} dirty={freeze_meta['dirty']} "
              f"at_freeze_commit={freeze_meta['at_freeze_commit']}")
    else:
        print(f"freeze OK: HEAD={freeze_meta['head']} (clean, at freeze commit)")

    models_cfg = load_models_config(args.models)
    if args.backend == "live":
        # The tutor key is needed whenever ANY non-cold condition is present -- the primary
        # conv/ped AND every ablation condition (conv_* / ped_*) drive a live tutor, so the
        # ablations cannot escape this preflight and fail late mid-run.
        needs_tutor = any(c != "cold" for c in conds)
        roles = ["student"] + (["tutor"] if needs_tutor else [])
        miss = missing_provider_keys(models_cfg, roles)
        if miss:
            raise SystemExit(
                "missing API keys for a live run: "
                + "; ".join(f"{r} ({p}) needs ${e}" for r, p, e in miss)
                + ".\nSet them, e.g.:  ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... "
                  "python experiments/run_confirmatory.py ...  (see experiments/RUN.md). "
                  "Or rehearse offline with --backend mock.")

    tutor_model_now = (models_cfg.get("roles", {}).get("tutor", {}) or {}).get("model")
    # ----- 'only the tutor changes' guard (cross-model base; paper-plan §12) -----
    # Enforce that a per-base config differs from the frozen primary ONLY in the tutor
    # model -- not the student, judge, their providers, the tutor budget, or the backend.
    if args.base:
        drift = tutor_only_drift(models_cfg, load_models_config(PRIMARY_MODELS))
        if drift:
            raise SystemExit(
                f"--base {args.base!r}: the per-base config {args.models} changes more than "
                "the tutor model -- ONLY the tutor may change (paper-plan §12). Forbidden:\n  - "
                + "\n  - ".join(drift)
                + f"\nMake student / judge / providers / tutor budget / backend match "
                  f"{PRIMARY_MODELS}, so the base swap is the only difference.")
        # Live base runs must also match the registered runtime protocol (knobs the freeze
        # guard does not see). Mock rehearsals are exempt so small offline runs stay flexible.
        if enforce:
            kdrift = protocol_knob_drift(args, conds)
            if kdrift:
                raise SystemExit(
                    f"--base {args.base!r} (LIVE): the invocation differs from the registered "
                    "protocol -- only the tutor model may change (paper-plan §12). Off-protocol:"
                    "\n  - " + "\n  - ".join(kdrift)
                    + "\nMatch the registered domain / conditions / replicates / base-seed / "
                      "turn budget (the freeze guard already pins the frozen files).")

    # ----- ablation registered-protocol guard (#5; LIVE only) -----
    # A live ablation run must use ONLY the pre-registered ablation conditions on the primary
    # Sonnet config with the SAME domain / replicates / seed schedule / turn budget as the
    # primary, so each ablation replicate pairs with its frozen primary baseline. Mock
    # rehearsals are exempt (stay flexible for small offline runs).
    if is_ablation and enforce:
        adrift = ablation_protocol_drift(args, conds)
        if adrift:
            raise SystemExit(
                "ablation run (LIVE): the invocation differs from the pre-registered ablation "
                "protocol (decisions-log 2026-06-30). Off-protocol:\n  - " + "\n  - ".join(adrift)
                + "\nUse only the pre-registered ablation conditions on configs/models.yaml "
                  "with the registered domain / replicates / base-seed / turn budget.")

    # ----- invocation-aware resume guard (stale/contaminated cells; #4) -----
    # A file-complete cell is only safe to SKIP if its recorded provenance matches this
    # invocation. Refuse loudly otherwise (same run-id namespace reused with a different
    # config / tutor id / freeze) instead of silently skipping or overwriting it.
    expected_base = args.base or None
    # A base invocation REQUIRES base + tutor_model in the recorded meta: a complete base
    # cell missing them is pre-hardening / hand-assembled and must not be silently skipped.
    require_present = ("base", "tutor_model") if args.base else ()
    stale = []
    for c in done:
        exp = {"condition": c["condition"], "replicate_id": c["replicate"], "seed": c["seed"],
               "backend": args.backend, "max_train_turns": args.max_train_turns,
               "models_config": args.models, "base": expected_base,
               "tutor_model": tutor_model_now}
        if enforce:   # the recorded HEAD must equal the current freeze on a live resume
            exp["freeze_head"] = freeze_meta.get("head")
        reason = cell_meta_mismatch(LOGS_DIR / c["run_id"], exp, require_present=require_present)
        if reason:
            stale.append((c["run_id"], reason))
    if stale:
        raise SystemExit(
            "RESUME GUARD: existing complete cell(s) disagree with this invocation (stale "
            "or contaminated -- same run-id namespace, different config / tutor id / freeze). "
            "Quarantine these dirs (or use a fresh --base / --base-seed) and re-run:\n"
            + "\n".join(f"  {rid}: {why}" for rid, why in stale))

    problems = load_problems(args.domain)

    label = "ablation (#5)" if is_ablation else "confirmatory"
    print(f"{label}: {args.replicates} replicate(s) x {conds} "
          f"(models={args.models}, backend={args.backend}, "
          f"base={args.base or ('ablation' if is_ablation else '(primary)')}, "
          f"max_train_turns={args.max_train_turns})")
    if done and not args.force:
        print(f"resume: {len(done)} cell(s) already complete -> skipping; "
              f"{len(todo)} to run.")

    for cell in todo:
        run_cell(cell, problems, models_cfg, args.backend, args.max_train_turns,
                 freeze_meta, args.models, args.base)

    n_done = sum(1 for c in cells if cell_complete(LOGS_DIR / c["run_id"]))
    print(f"\ndone: {n_done}/{len(cells)} cells complete.")
    if n_done == len(cells) and is_ablation:
        # Ablation analysis is SEPARATE + DESCRIPTIVE. Metricize the ablation cells together
        # with the EXISTING primary conv/ped/cold baseline cells (reused, NOT re-run) into
        # results/ablation, then run the descriptive ablation analysis. NEVER feed this dir
        # to analysis/run_inference.py: the frozen §10 J1/J2 is variant-unsafe (it pools
        # every per-turn row and pairs only conv-vs-ped), so an ablation dir would contaminate
        # the frozen verdict.
        abl_globs = " ".join(f"logs/abl-s{args.base_seed}-{c}-r*" for c in conds)
        base_globs = " ".join(f"logs/conf-s{args.base_seed}-{c}-r*" for c in ("conv", "ped", "cold"))
        print("Next (DESCRIPTIVE ablation analysis -- ablation cells + reused primary baselines):")
        print(f"  python analysis/compute_metrics.py {abl_globs} {base_globs} "
              f"--out results/ablation --judge-helpfulness --judge-pedagogy")
        print(f"  python analysis/ablation_analysis.py results/ablation")
        print("  (do NOT run analysis/run_inference.py on results/ablation -- the frozen "
              "§10 J1/J2 is variant-unsafe and would pool ablation turns.)")
    elif n_done == len(cells):
        prefix = f"conf-{args.base}-" if args.base else "conf-"
        globs = " ".join(f"logs/{prefix}s{args.base_seed}-{c}-r*" for c in conds)
        out = f"results/confirmatory_{args.base}" if args.base else "results/confirmatory"
        print("Next (judge + metrics over the paired confirmatory cells):")
        print(f"  python analysis/compute_metrics.py {globs} "
              f"--out {out} --judge-helpfulness")


if __name__ == "__main__":
    main()
