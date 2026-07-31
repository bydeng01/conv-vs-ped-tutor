"""Preflight gates for the confirmatory 10x3 run -- run LIVE before committing API
budget. Re-verifies, on the pinned student serving and the
frozen problem set, the things that must hold for the confirmatory run to be
interpretable (paper-plan.md §6, §8, §11; decisions-log 2026-06-18/19):

  1. ISOLATED cold is LOW on the frozen 19 (cold gate). Each probe attempted from a
     FRESH context (run_problem_session, not the carried-memory protocol), so this is
     the genuine-difficulty floor the amendment fixed on (§3/§6/§11; calibration
     ≈ 11%). High *continuous*-protocol cold is expected and is NOT this gate.
  2. Sonnet ConvTutor leakage is PRESENT on the training items (failure-mode #3).
  3. The student's served provider is Groq (the calibration-validated weak serving;
     OpenRouter routing drift produced cold-100% before -- decisions-log 2026-06-18).
  4. A token/cost estimate for the 10x3 run, extrapolated from a stored pilot.

It mirrors experiments/calibrate.py's failure-mode reads (FM #1 cold, FM #3 leakage)
but on the FROZEN 19 and adds the confirmatory-specific provenance + cost checks. It
REUSES the frozen scoring primitives (turn_leaks, is_correct, has_final_marker) and
changes no runtime behavior. The lead runs it live; it is mock-validatable here
(`--backend mock`) for plumbing only -- mock scores are synthetic, NOT a gate result.

Usage:
  # live, on the pinned student serving (the real preflight):
  ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... python experiments/preflight.py
  # offline plumbing rehearsal (synthetic):
  python experiments/preflight.py --backend mock --pilot-results results/pilot_groq
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.config import load_models_config, resolve_backend  # noqa: E402
from agents.conv_tutor import ConvTutor  # noqa: E402
from agents.extraction import has_final_marker  # noqa: E402
from agents.logging_utils import RunLogger, new_run_id  # noqa: E402
from agents.model_client import ModelClient  # noqa: E402
from analysis.metrics import load_calls  # noqa: E402
from domain.algebra.checker import is_correct  # noqa: E402
from experiments.run_confirmatory import missing_provider_keys  # noqa: E402
from protocol.leakage import turn_leaks  # noqa: E402
from protocol.session import load_problems, run_problem_session  # noqa: E402
from student.simulator import StudentSimulator  # noqa: E402

PROBE_ROLES = ("immediate", "delayed", "transfer")
# "Low" sanity ceiling for the ISOLATED-cold gate (§6/§11: cold must be low; ≈11% at
# calibration). A reporting threshold, not a frozen metric and not tuned to a result;
# above it, the student is too strong on a FRESH problem -> uninterpretable run.
COLD_LOW_CEILING = 0.30


def preflight_exit_code(backend: str, gates: dict, advisory_gates: tuple = ()) -> int:
    """Live preflight FAILS (exit 1) if any computed BLOCKING gate is False, so an
    automated workflow / operator relying on the exit code cannot proceed past a CHECK
    into the expensive confirmatory run. The mock backend is a plumbing rehearsal and
    always returns 0. None gates (not applicable, e.g. served-provider on mock) are ignored.

    `advisory_gates` names gates that are RECORDED but NON-blocking -- they are excluded
    from the blocking check, so their failure does not change the exit code. The cross-model
    base run passes `("convtutor_leaky",)`: ConvTutor-leakage ABSENCE on a base is a reported
    finding about that base, not a stop (paper-plan §12). EVERY OTHER gate (cold, FINAL-marker,
    served-provider) stays blocking, and API/key/config errors raise independently of this
    function. Default `()` -> the preregistered primary hard-gate semantics are unchanged."""
    if backend != "live":
        return 0
    blocking = {k: v for k, v in gates.items() if k not in advisory_gates}
    return 1 if any(v is False for v in blocking.values()) else 0


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _git_head() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                           capture_output=True, text=True, check=True)
        return r.stdout.strip() or None
    except Exception:  # noqa: BLE001 - no git / not a repo -> just unrecorded
        return None


def leakage_diagnostic(*, base_slug, backend, tutor_model, models_config, problems_path,
                       problems_sha256, repo_commit, timestamp, leak_turns, tutor_turns,
                       leak_rate, raw_log_dir, pin_record_ref) -> dict:
    """The ConvTutor-leakage ADVISORY diagnostic for a cross-model base (paper-plan §12):
    the FULL read (numerator/denominator/rate) plus provenance, as a SEPARATE artifact that
    REFERENCES the immutable per-vendor pin record -- it never edits the pin. Leakage here is
    advisory: a base whose ConvTutor does not leak is a reported finding about the base, NOT a
    reason to tune the prompt, reselect the model, or change the config ('report, don't tune').

    `backend` is recorded so a `mock` plumbing rehearsal (SYNTHETIC leak counts) can never be
    mistaken for a real `live` gate read in this durable artifact."""
    return {
        "kind": "convtutor_leakage_diagnostic",
        "advisory": True, "blocking": False,
        "backend": backend,                      # 'live' = a real read; 'mock' = SYNTHETIC, not a gate result
        "base_slug": base_slug,
        "pin_record_ref": pin_record_ref,        # the immutable pin record; NOT edited by this read
        "tutor_model": tutor_model,
        "models_config": models_config,
        "problems_path": problems_path,
        "problems_sha256": problems_sha256,
        "repo_commit": repo_commit,
        "timestamp": timestamp,
        "leak_turns": leak_turns,                # numerator
        "tutor_turns": tutor_turns,              # denominator
        "leak_rate": leak_rate,                  # numerator / denominator (None if no tutor turns)
        "raw_log_dir": raw_log_dir,
        "note": ("ConvTutor leakage is ADVISORY for a cross-model base (paper-plan §12): "
                 "recorded, NON-blocking. A base whose ConvTutor does not leak is a reported "
                 "finding about the base -- NOT a reason to tune the prompt, reselect the model, "
                 "or change the config. The model is pinned BEFORE this read (see pin_record_ref) "
                 "and is never reselected after it."),
    }


def _cost_estimate(pilot_results: Path, replicates: int, conds) -> None:
    """Extrapolate per-condition token totals from a stored pilot's per_session.csv
    to the planned `replicates` x conditions run. Tokens only -- multiply by the
    provider's per-token rates for dollars (rates are not in the repo)."""
    csv_path = pilot_results / "per_session.csv"
    if not csv_path.exists():
        print(f"  (no {csv_path}; run a pilot + metrics first for a cost estimate)")
        return
    rows = list(csv.DictReader(csv_path.open()))
    by_cond: dict[str, list[int]] = {}
    for row in rows:
        by_cond.setdefault(row.get("condition", "?"), []).append(
            int(float(row.get("total_tokens") or 0)))
    grand = 0
    for cond in conds:
        vals = by_cond.get(cond, [])
        if not vals:
            print(f"  {cond:5s}: (not in pilot)")
            continue
        mean = sum(vals) / len(vals)
        est = mean * replicates
        grand += est
        print(f"  {cond:5s}: ~{int(mean):>7d} tok/session x {replicates} = ~{int(est):>9d} tok")
    print(f"  TOTAL estimate for {replicates}x{len(conds)}: ~{int(grand):,} experiment tokens "
          f"(judge calls are extra; see PILOT.md cost note).")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="configs/models.yaml")
    ap.add_argument("--backend", choices=["mock", "live"], default=None)
    ap.add_argument("--domain", default="domain/algebra/problems.yaml")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-turns", type=int, default=4,
                    help="ConvTutor rounds per training problem for the leakage read "
                         "(match the confirmatory --max-train-turns).")
    ap.add_argument("--replicates", type=int, default=10,
                    help="planned confirmatory replicates, for the cost estimate.")
    ap.add_argument("--pilot-results", default="results/pilot_groq",
                    help="a stored pilot results dir (per_session.csv) for the cost estimate.")
    ap.add_argument("--leakage-advisory", action="store_true",
                    help="CROSS-MODEL BASE mode (paper-plan §12): treat the ConvTutor-leakage "
                         "gate as an ADVISORY diagnostic (recorded, NON-blocking) instead of a "
                         "hard gate. EVERY other gate (cold, FINAL-marker, served-provider) and "
                         "all key/config/API errors stay blocking. Writes a separate "
                         "leakage_diagnostic.json with the full numerator/denominator/rate + "
                         "provenance. Default OFF -> the preregistered primary hard-gate "
                         "semantics are preserved.")
    ap.add_argument("--diagnostic-out", default=None,
                    help="dir for the cross-base leakage_diagnostic.json (with "
                         "--leakage-advisory); default logs/<run_id>/.")
    ap.add_argument("--pin-record-ref", default=None,
                    help="reference to the immutable per-vendor pin record this base was pinned "
                         "in (e.g. the dated decisions-log entry title). Recorded in the "
                         "diagnostic; the pin record itself is never edited by this read.")
    args = ap.parse_args()

    models_cfg = load_models_config(args.models)
    backend = resolve_backend(models_cfg, args.backend)
    if backend == "live":
        miss = missing_provider_keys(models_cfg, ("tutor", "student"))
        if miss:
            raise SystemExit(
                "preflight (live) is missing API keys: "
                + "; ".join(f"{r} ({p}) needs ${e}" for r, p, e in miss)
                + ".\nSet them, e.g.:  ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... "
                  "python experiments/preflight.py  (see experiments/RUN.md). "
                  "Or rehearse offline with --backend mock.")
    run_id = new_run_id(prefix="preflight")
    logger = RunLogger(run_id)
    client = ModelClient(models_cfg=models_cfg, backend=backend, logger=logger)
    problems = load_problems(args.domain)
    student = StudentSimulator(client)
    conv = ConvTutor(client)

    print(f"preflight run_id={run_id} backend={backend} "
          f"tutor={models_cfg['roles']['tutor']['model']} "
          f"student={models_cfg['roles']['student']['model']} n_problems={len(problems)}")
    if backend == "mock":
        print("*** backend=mock: SYNTHETIC scores, plumbing only -- NOT a gate result ***")

    # ---- Gate 1: ISOLATED cold on the frozen 19 (each probe from a fresh context) ----
    cold_by_role: dict[str, list[int]] = {}
    markers = 0
    for p in problems:
        res = run_problem_session(p, student, tutor=None, seed=args.seed, condition="cold")
        rr = cold_by_role.setdefault(p.role, [0, 0])
        rr[0] += int(bool(res.correct)); rr[1] += 1
        if any(t.speaker == "student" and has_final_marker(t.text) for t in res.transcript):
            markers += 1
    probe_c = sum(cold_by_role.get(r, [0, 0])[0] for r in PROBE_ROLES)
    probe_t = sum(cold_by_role.get(r, [0, 0])[1] for r in PROBE_ROLES)
    probe_cold = (probe_c / probe_t) if probe_t else None
    marker_rate = markers / len(problems) if problems else 0.0

    # ---- Gate 2: ConvTutor leakage present on the training items ----
    leak_turns = tutor_turns = 0
    for p in [p for p in problems if p.role == "training"]:
        res = run_problem_session(p, student, tutor=conv, seed=args.seed, condition="conv",
                                  max_turns=args.max_turns, stop_on_commit=False)
        nf = p.leakage.get("numeric_form", [])
        sf = p.leakage.get("solution_form", [])
        for t in res.transcript:
            if t.speaker == "tutor":
                tutor_turns += 1
                leak_turns += int(bool(turn_leaks(t.text, nf, sf)))
    leak_rate = (leak_turns / tutor_turns) if tutor_turns else None

    # ---- Gate 3: served provider for the student is Groq ----
    calls = load_calls(logger.dir)
    served = {c.get("served_provider") for c in calls
              if c.get("role") == "student" and c.get("served_provider")}

    # ---- report ----
    def gate(ok):
        return "PASS" if ok else "CHECK"

    cold_ok = probe_cold is not None and probe_cold <= COLD_LOW_CEILING
    marker_ok = marker_rate >= 0.95
    leak_ok = leak_rate is not None and leak_rate > 0.0
    groq_ok = (served == {"Groq"}) if backend == "live" else None

    print("\n================ PREFLIGHT ================")
    print(f"1. ISOLATED probe cold : {('%.1f%%' % (probe_cold*100)) if probe_cold is not None else '-':>7s}"
          f"   [want LOW <= {COLD_LOW_CEILING:.0%}; ~11% at calibration]  {gate(cold_ok)}")
    print("     by role: " + "  ".join(
        f"{r}={ (cold_by_role.get(r,[0,1])[0]/cold_by_role.get(r,[0,1])[1]) :.0%}"
        for r in ("training",) + PROBE_ROLES if r in cold_by_role))
    print(f"   FINAL-marker rate    : {marker_rate:6.1%}   [want >= 95%]                  {gate(marker_ok)}")
    leak_label = "ADVISORY (recorded, non-blocking)" if args.leakage_advisory else gate(leak_ok)
    print(f"2. ConvTutor leakage    : {('%.1f%%' % (leak_rate*100)) if leak_rate is not None else '-':>7s}"
          f"   [want PRESENT > 0; ~52% at calibration]   {leak_label}")
    if backend == "live":
        print(f"3. Student served by    : {sorted(served) or '(none logged)'}   "
              f"[want exactly Groq]            {gate(groq_ok)}")
    else:
        print("3. Student served by    : (mock -- no served provider; check live)")
    print("4. Cost estimate (from pilot tokens):")
    _cost_estimate(REPO_ROOT / args.pilot_results, args.replicates,
                   ["cold", "conv", "ped"])
    print("===========================================")
    gates = {"isolated_cold_low": cold_ok, "marker_rate": marker_ok,
             "convtutor_leaky": leak_ok}
    if backend == "live":
        gates["student_served_by_groq"] = groq_ok
    logger.write_json("preflight_report.json", {
        "run_id": run_id, "backend": backend,
        "probe_cold": probe_cold, "cold_by_role": cold_by_role,
        "marker_rate": marker_rate, "convtutor_leak_rate": leak_rate,
        "served_providers": sorted(served), "gates": gates,
    })

    # Cross-model base: the ConvTutor-leakage gate is advisory (recorded, non-blocking;
    # paper-plan §12). Write the SEPARATE diagnostic with the full read + provenance,
    # referencing the immutable pin record -- the pin is never edited by this read.
    advisory_gates = ("convtutor_leaky",) if args.leakage_advisory else ()
    if args.leakage_advisory:
        _stem = Path(args.models).stem                       # "models.gpt" -> "gpt"; primary "models" -> None
        diag = leakage_diagnostic(
            base_slug=(_stem[len("models."):] if _stem.startswith("models.") else None),
            backend=backend,
            tutor_model=models_cfg["roles"]["tutor"]["model"],
            models_config=args.models, problems_path=args.domain,
            problems_sha256=_sha256_file(REPO_ROOT / args.domain),
            repo_commit=_git_head(), timestamp=datetime.now(timezone.utc).isoformat(),
            leak_turns=leak_turns, tutor_turns=tutor_turns, leak_rate=leak_rate,
            raw_log_dir=f"logs/{run_id}/", pin_record_ref=args.pin_record_ref,
        )
        if args.diagnostic_out:
            dout = Path(args.diagnostic_out)
            out_dir = dout if dout.is_absolute() else REPO_ROOT / dout
        else:
            out_dir = Path(logger.dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        diag_path = out_dir / "leakage_diagnostic.json"
        diag_path.write_text(json.dumps(diag, indent=2, default=str))
        print(f"\nConvTutor leakage is ADVISORY for this cross-model base (paper-plan §12): "
              f"{leak_turns}/{tutor_turns} tutor turns leak"
              + (f" = {leak_rate:.1%}" if leak_rate is not None else "")
              + " -- recorded, NON-blocking.")
        if not leak_ok:
            print("  -> ConvTutor leakage ABSENT/zero on this base: a REPORTED FINDING about the "
                  "base, NOT a stop. Do not tune the prompt, reselect the model, or change the "
                  "config (report, don't tune).")
        print(f"  diagnostic: {diag_path}  (pin record: {args.pin_record_ref or '<unset --pin-record-ref>'})")

    print(f"Report + transcripts: logs/{run_id}/")
    code = preflight_exit_code(backend, gates, advisory_gates)
    if code:
        print("\nAt least one gate is CHECK -- resolve before the confirmatory run "
              "(do NOT tune toward a result; see paper-plan §11 + RUN.md). "
              "Exiting non-zero so an automated workflow stops here.")
        raise SystemExit(code)


if __name__ == "__main__":
    main()
