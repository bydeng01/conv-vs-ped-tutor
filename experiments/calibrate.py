"""Live diagnostic / Step-2 calibration runner.

Reads the two thesis-decisive failure modes on a live model BEFORE authoring the
frozen problem set:
  - FAILURE MODE #1: cold-baseline accuracy LOW (target 20-40%, paper-plan §6).
  - FAILURE MODE #3: ConvTutor actually leaky (leakage rate clearly > 0, §8).
Also reports the §6 student acceptance bands: behavior frequencies and the
FINAL ANSWER marker-emission rate.

Usage:
  # offline plumbing dry-run
  python experiments/calibrate.py --backend mock

  # live (free provider): set the provider's key first, e.g. GROQ_API_KEY
  python experiments/calibrate.py --models configs/models.free.yaml

Behavior classification here is an APPROXIMATE regex read for calibration only;
the frozen independence metric (regex + LLM verification, §9.3) is built in Step 5.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.config import load_models_config, resolve_backend  # noqa: E402
from agents.conv_tutor import ConvTutor  # noqa: E402
from agents.extraction import has_final_marker  # noqa: E402
from agents.logging_utils import RunLogger, new_run_id  # noqa: E402
from agents.model_client import ModelClient  # noqa: E402
from protocol.leakage import turn_leaks  # noqa: E402
from protocol.session import load_problems, run_problem_session  # noqa: E402
from student.simulator import StudentSimulator  # noqa: E402

# --- approximate student-turn behavior classification (calibration only) -------
_EXPR_RE = re.compile(r"(x\s*=|=\s*\d|\d+\s*[-+*/]\s*\d+|\b\d+\s*/\s*\d+\b)")
# Blunt requests to be handed the answer/solution (the deferral-relevant behavior).
_ASK_RE = re.compile(
    r"(what'?s the (answer|solution)|what is the (answer|solution)|"
    r"just tell me|tell me the (answer|solution)|give me the (answer|solution)|"
    r"can you (just )?(tell|give) me|what'?s the final)",
    re.IGNORECASE)


def classify_student_turn(text: str) -> str:
    # Blunt answer-requests count as asking even if a number is present.
    if _ASK_RE.search(text):
        return "ask_for_answer"
    if _EXPR_RE.search(text):
        return "attempt"
    return "restate"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="configs/models.free.yaml")
    ap.add_argument("--backend", choices=["mock", "live"], default=None)
    ap.add_argument("--domain", default="domain/algebra/calibration.yaml")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-turns", type=int, default=4,
                    help="max tutor/student rounds per ConvTutor problem (kept "
                         "small for calibration token frugality)")
    ap.add_argument("--cold-only", action="store_true",
                    help="measure only the cold baseline (no ConvTutor calls). Use "
                         "for a cheap difficulty check on the final student (the weak "
                         "Llama-3.1-8B).")
    args = ap.parse_args()

    models_cfg = load_models_config(args.models)
    backend = resolve_backend(models_cfg, args.backend)
    run_id = new_run_id(prefix="calib")
    logger = RunLogger(run_id)
    client = ModelClient(models_cfg=models_cfg, backend=backend, logger=logger)

    problems = load_problems(args.domain)
    student = StudentSimulator(client)
    conv = ConvTutor(client)

    def _role_str(role):
        r = models_cfg["roles"][role]
        prov = r.get("provider") or models_cfg.get("provider") or "anthropic"
        return f"{prov}:{r['model']}"

    tutor_model = models_cfg["roles"]["tutor"]["model"]
    student_model = models_cfg["roles"]["student"]["model"]
    mode = "COLD-ONLY" if args.cold_only else "full"
    print(f"run_id={run_id} backend={backend} mode={mode} "
          f"tutor={_role_str('tutor')} student={_role_str('student')} "
          f"n_problems={len(problems)} seed={args.seed} max_turns={args.max_turns}")
    if backend == "mock":
        print("\n*** WARNING: backend=mock — these results are SYNTHETIC (offline "
              "stub), NOT a real model. Use --backend live (or backend: live in the "
              "config) for real calibration. ***\n")

    cold_correct = 0
    cold_marker = 0
    leak_turns = 0
    tutor_turns = 0
    behavior = {"attempt": 0, "ask_for_answer": 0, "restate": 0}
    cold_by_role = {}   # role -> [n_correct, n_total]
    per_problem = []

    for p in problems:
        # --- cold baseline (failure mode #1) ---
        cold = run_problem_session(p, student, tutor=None, seed=args.seed, condition="cold")
        cold_ok = bool(cold.correct)
        cold_correct += int(cold_ok)
        rr = cold_by_role.setdefault(p.role, [0, 0])
        rr[0] += int(cold_ok); rr[1] += 1
        cold_has_marker = any(t.speaker == "student" and has_final_marker(t.text)
                              for t in cold.transcript)
        cold_marker += int(cold_has_marker)
        logger.write_transcript(f"cold_{p.id}", {"problem": p.id, "phase": "cold",
                                "final": cold.final_answer, "canonical": p.canonical_answer,
                                "correct": cold_ok}, cold.transcript)

        rec = {"id": p.id, "cold_correct": cold_ok, "cold_marker": cold_has_marker}

        if not args.cold_only:
            # --- ConvTutor (failure mode #3 leakage + behavior bands) ---
            # stop_on_commit=False so the tutor engages every round (training-style
            # dialogue), making leakage and behavior measurable even for a student
            # that would otherwise blurt an answer on turn 0.
            conv_res = run_problem_session(p, student, tutor=conv, seed=args.seed,
                                           condition="conv", max_turns=args.max_turns,
                                           stop_on_commit=False)
            nf = p.leakage.get("numeric_form", [])
            sf = p.leakage.get("solution_form", [])
            p_tutor_turns = [t.text for t in conv_res.transcript if t.speaker == "tutor"]
            p_leaks = sum(1 for t in p_tutor_turns if turn_leaks(t, nf, sf))
            leak_turns += p_leaks
            tutor_turns += len(p_tutor_turns)
            for t in conv_res.transcript:
                if t.speaker == "student":
                    behavior[classify_student_turn(t.text)] += 1
            logger.write_transcript(f"conv_{p.id}", {"problem": p.id, "phase": "conv",
                                    "final": conv_res.final_answer, "canonical": p.canonical_answer,
                                    "correct": conv_res.correct,
                                    "leak_turns": f"{p_leaks}/{len(p_tutor_turns)}"},
                                    conv_res.transcript)
            rec.update({"conv_correct": bool(conv_res.correct),
                        "conv_leak_turns": p_leaks, "conv_tutor_turns": len(p_tutor_turns)})

        per_problem.append(rec)

    n = len(problems)
    cold_acc = cold_correct / n if n else 0.0
    marker_rate = cold_marker / n if n else 0.0

    # Probe cold = accuracy over the TEST probes only (the calibration target);
    # training and interference are excluded.
    probe_roles = ("immediate", "delayed", "transfer")
    probe_c = sum(cold_by_role.get(r, [0, 0])[0] for r in probe_roles)
    probe_t = sum(cold_by_role.get(r, [0, 0])[1] for r in probe_roles)
    probe_cold = probe_c / probe_t if probe_t else 0.0
    cold_role_acc = {r: (c / t if t else 0.0) for r, (c, t) in cold_by_role.items()}
    leak_rate = leak_turns / tutor_turns if tutor_turns else 0.0
    beh_total = sum(behavior.values()) or 1
    beh_freq = {k: v / beh_total for k, v in behavior.items()}

    def gate(ok: bool) -> str:
        return "PASS" if ok else "CHECK"

    # Gate on PROBE cold (the meaningful target) when probes are present;
    # otherwise fall back to the all-problem cold accuracy.
    gate_cold = probe_cold if probe_t else cold_acc
    gates = {
        "cold_in_20_40": 0.20 <= gate_cold <= 0.40,
        "marker_rate_ge_0.95": marker_rate >= 0.95,
    }
    if not args.cold_only:
        gates.update({
            "leaky_convtutor": leak_rate >= 0.20,
            "ask_band_0.35_0.65": 0.35 <= beh_freq["ask_for_answer"] <= 0.65,
            "restate_band_0.10_0.30": 0.10 <= beh_freq["restate"] <= 0.30,
        })

    report = {
        "run_id": run_id, "backend": backend, "cold_only": args.cold_only,
        "tutor_model": tutor_model, "student_model": student_model,
        "n_problems": n, "seed": args.seed,
        "cold_baseline_accuracy": cold_acc,
        "probe_cold_accuracy": probe_cold,
        "cold_accuracy_by_role": cold_role_acc,
        "convtutor_leakage_rate": (None if args.cold_only else leak_rate),
        "student_behavior_freq": (None if args.cold_only else beh_freq),
        "final_marker_rate": marker_rate,
        "gates": gates,
        "per_problem": per_problem,
    }
    logger.write_json("calibration_report.json", report)

    print("\n================ CALIBRATION REPORT ================")
    if probe_t:
        print(f"PROBE cold (imm/del/transfer): {probe_cold:5.1%}   [target 20-40%]  {gate(gates['cold_in_20_40'])}")
        print(f"  by role: " + "  ".join(f"{r}={cold_role_acc.get(r,0):.0%}"
                                         for r in ("training","immediate","interference","delayed","transfer")
                                         if r in cold_role_acc))
        print(f"  (all-problem cold {cold_acc:.1%}, not the gate)")
    else:
        print(f"Cold-baseline accuracy : {cold_acc:5.1%}   [target 20-40%]  {gate(gates['cold_in_20_40'])}")
    print(f"FINAL-marker rate      : {marker_rate:5.1%}   [want >=95%]     {gate(gates['marker_rate_ge_0.95'])}")
    if not args.cold_only:
        print(f"ConvTutor leakage rate : {leak_rate:5.1%}   [want >=20%]     {gate(gates['leaky_convtutor'])}")
        print(f"Student behavior       : ask={beh_freq['ask_for_answer']:.2f} "
              f"restate={beh_freq['restate']:.2f} attempt={beh_freq['attempt']:.2f}")
        print(f"  ask band 0.35-0.65   : {gate(gates['ask_band_0.35_0.65'])}")
        print(f"  restate band 0.10-0.30: {gate(gates['restate_band_0.10_0.30'])}")
    else:
        print("(cold-only: leakage/behavior skipped — difficulty check on final student)")
    print("===================================================")
    print(f"Full report + transcripts: logs/{run_id}/")


if __name__ == "__main__":
    main()
