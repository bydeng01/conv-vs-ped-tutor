"""PedTutor smoke + side-by-side comparison with ConvTutor (Step 4 / M1).

Three checks, each independently useful:

  1. SCRIPTED-STUDENT comparison (the headline). Feed ConvTutor and PedTutor the
     EXACT same dialogue and problem, then print both replies. This isolates the
     policy difference: same input, different output. Two scenarios -- the student
     asks for the answer with no attempts (the decisive leakage case), and the
     student asks after two real attempts (PedTutor's gate opens to concrete setup
     help but still withholds the number). Needs only the TUTOR model, so it is the
     cheapest live behavioral check (ANTHROPIC_API_KEY alone).

  2. DYNAMIC dialogue. Run a short training-style dialogue for each tutor on the
     same problem with the simulated student, write transcripts, and report the
     frozen leakage rate over the tutor's turns. Needs the student model too.

  3. FULL mock session. Run the whole continuous protocol with PedTutor on the
     mock backend to confirm it runs end-to-end and to print cost accounting
     (student vs tutor tokens, model calls -- several per visible PedTutor turn).

Usage:
  python experiments/ped_smoke.py --backend mock                 # offline, all three
  python experiments/ped_smoke.py --backend live --scripted-only # tutor-only live check
  python experiments/ped_smoke.py --backend live                 # full live smoke (needs student key)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.config import load_models_config, resolve_backend  # noqa: E402
from agents.conv_tutor import ConvTutor  # noqa: E402
from agents.ped_tutor import (PedTutor, count_attempts, is_answer_request,  # noqa: E402
                              is_attempt)
from agents.logging_utils import RunLogger, new_run_id  # noqa: E402
from agents.model_client import ModelClient  # noqa: E402
from agents.state import Turn  # noqa: E402
from protocol.full_session import run_full_session  # noqa: E402
from protocol.leakage import turn_leaks  # noqa: E402
from protocol.session import load_problems, run_problem_session  # noqa: E402
from student.simulator import StudentSimulator  # noqa: E402


def _leaks(text, problem) -> bool:
    return turn_leaks(text, problem.leakage.get("numeric_form", []),
                      problem.leakage.get("solution_form", []))


def _print_turn(label, text, problem, meta=None):
    flag = "  <-- LEAKS ANSWER" if _leaks(text, problem) else ""
    print(f"\n[{label}]{flag}")
    print(text.strip())
    if meta:
        keep = {k: meta[k] for k in ("branch", "attempts", "reveal_allowed",
                                     "hint_level", "n_model_calls", "nodes") if k in meta}
        print(f"   (meta: {keep})")


def scripted_comparison(client, problem, seed):
    """Same input -> both tutors. Isolates the policy difference."""
    print("\n" + "=" * 72)
    print(f"SCRIPTED-STUDENT COMPARISON on {problem.id}: {problem.prompt.strip()}")
    print("=" * 72)

    conv, ped = ConvTutor(client), PedTutor(client)

    # Scenario A: student asks for the answer, zero reasoning attempts.
    print("\n--- Scenario A: student asks for the answer with NO attempts ---")
    tA = [Turn("student", "I really don't get these mixture problems. "
                          "Can you just tell me the answer?")]
    _print_turn("ConvTutor", conv.respond(tA, problem, seed, 0).text, problem)
    pa = ped.respond(tA, problem, seed, 0)
    _print_turn("PedTutor", pa.text, problem, pa.meta)

    # Scenario B: student asks again, but after two genuine attempts.
    print("\n\n--- Scenario B: student asks after TWO real attempts ---")
    tB = [
        Turn("student", "Let me try. I set x = liters of the strong solution, "
                        "so 0.5*x + 0.2*48 = 0.3*(x+48)?"),
        Turn("tutor", "Good — you've written a balance. Keep going."),
        Turn("student", "So 0.5x + 9.6 = 0.3x + 14.4, then 0.2x = 4.8 ... I'm stuck, "
                        "can you just give me the answer?"),
    ]
    _print_turn("ConvTutor", conv.respond(tB, problem, seed, 1).text, problem)
    pb = ped.respond(tB, problem, seed, 1)
    _print_turn("PedTutor", pb.text, problem, pb.meta)


def dynamic_dialogue(client, problem, seed, max_turns):
    """A short training-style dialogue per tutor with the simulated student."""
    student = StudentSimulator(client)
    print("\n" + "=" * 72)
    print(f"DYNAMIC DIALOGUE on {problem.id} (max_turns={max_turns})")
    print("=" * 72)
    for name, Tutor in (("ConvTutor", ConvTutor), ("PedTutor", PedTutor)):
        res = run_problem_session(problem=problem, student=student, tutor=Tutor(client),
                                  seed=seed, condition=name.lower(), max_turns=max_turns,
                                  stop_on_commit=False)
        tutor_turns = [t.text for t in res.transcript if t.speaker == "tutor"]
        n_leak = sum(1 for t in tutor_turns if _leaks(t, problem))
        rate = (n_leak / len(tutor_turns)) if tutor_turns else 0.0
        print(f"\n----- {name} ----- leakage {n_leak}/{len(tutor_turns)} tutor turns = {rate:.0%}")
        for t in res.transcript:
            _print_turn(t.speaker.upper(), t.text, problem,
                        t.meta if t.speaker == "tutor" else None)


def check_routing(client, problem, seed, max_turns):
    """Run a PedTutor dialogue, then print each student turn next to what the
    deterministic router detected and which branch the next tutor turn took. Use
    this to audit, on a LIVE transcript, that the router fires correctly on the
    real student's phrasing (a missed answer-demand is the failure to watch for)."""
    ped = PedTutor(client)
    student = StudentSimulator(client)
    res = run_problem_session(problem=problem, student=student, tutor=ped, seed=seed,
                              condition="ped", max_turns=max_turns, stop_on_commit=False)
    print("\n" + "=" * 72)
    print(f"ROUTING AUDIT on {problem.id}")
    print("=" * 72)
    print(f"{'role':7s} {'asked':5s} {'attmpt':6s} {'cum':3s} {'branch->reveal/level':22s}  text")
    running: list = []
    for t in res.transcript:
        if t.speaker == "student":
            asked = is_answer_request(t.text, ped.ask_res)
            att = is_attempt(t.text, ped.attempt_res)
            running.append(t)
            cum = count_attempts(running, ped.attempt_res)
            print(f"{'student':7s} {str(asked):5s} {str(att):6s} {cum:<3d} {'':22s}  "
                  f"{t.text.strip()[:70]!r}")
        elif t.speaker == "tutor":
            running.append(t)
            m = t.meta
            tag = f"{m.get('branch','?')}->rev={m.get('reveal_allowed')}/lvl={m.get('hint_level')}"
            leak = " LEAKS" if _leaks(t.text, problem) else ""
            print(f"{'tutor':7s} {'':5s} {'':6s} {'':3s} {tag:22s}  "
                  f"[{','.join(m.get('nodes', []))}]{leak}")
    print("\nWhat to verify by eye: every 'just tell me the answer'-style student "
          "line shows asked=True and the next tutor row shows branch=defer.")


def full_mock_session(client, problems, seed):
    print("\n" + "=" * 72)
    print("FULL PedTutor SESSION (continuous protocol) — cost accounting")
    print("=" * 72)
    res = run_full_session(problems, client, tutor=PedTutor(client), seed=seed,
                           condition="ped", max_train_turns=3)
    print(f"items={len(res.items)}  student_tokens={res.student_tokens}  "
          f"tutor_tokens={res.tutor_tokens}  total_tokens={res.total_tokens}  "
          f"tutor_model_calls={res.n_model_calls}")
    train = [i for i in res.items if i.phase == "training"]
    for i in train:
        per_turn = (i.n_model_calls / i.n_tutor_turns) if i.n_tutor_turns else 0
        print(f"  {i.problem_id}: tutor_turns={i.n_tutor_turns} "
              f"model_calls={i.n_model_calls} ({per_turn:.1f}/turn) tokens={i.tutor_tokens}")
    assert res.n_model_calls > sum(i.n_tutor_turns for i in train), \
        "PedTutor should make more model calls than visible turns (internal nodes)."
    print("OK: PedTutor makes several model calls per visible turn (state_tracker + responder).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["mock", "live"], default="mock")
    ap.add_argument("--models", default="configs/models.yaml")
    ap.add_argument("--problem", default="train-1", help="problem id for the comparisons")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-turns", type=int, default=4)
    ap.add_argument("--scripted-only", action="store_true",
                    help="run only the scripted comparison (tutor-only; cheapest live check)")
    ap.add_argument("--check-routing", action="store_true",
                    help="run a PedTutor dialogue and print a router audit table (needs the "
                         "student model on live); use to confirm routing on real phrasing")
    ap.add_argument("--no-full", action="store_true", help="skip the full mock session")
    args = ap.parse_args()

    models_cfg = load_models_config(args.models)
    backend = resolve_backend(models_cfg, args.backend)
    logger = RunLogger(new_run_id(prefix="pedsmoke"))
    client = ModelClient(models_cfg=models_cfg, backend=backend, logger=logger)
    problems = load_problems("domain/algebra/problems.yaml")
    by_id = {p.id: p for p in problems}
    problem = by_id.get(args.problem) or problems[0]

    if backend == "mock":
        print("*** backend=mock: control-flow / plumbing only. The generic mock tutor "
              "ignores the scoped node prompts, so behavioral withholding is NOT shown "
              "here — run --backend live for that. Routing, cost accounting, and the "
              "full protocol ARE exercised. ***")

    print(f"run_id={logger.run_id} backend={backend} "
          f"tutor={models_cfg['roles']['tutor']['model']}")

    if args.check_routing:
        check_routing(client, problem, args.seed, args.max_turns)
        print(f"\nlogs: logs/{logger.run_id}/")
        return

    scripted_comparison(client, problem, args.seed)
    if not args.scripted_only:
        try:
            dynamic_dialogue(client, problem, args.seed, args.max_turns)
        except Exception as e:  # noqa: BLE001
            print(f"\n[dynamic dialogue skipped: {type(e).__name__}: {e}]")
        if not args.no_full:
            full_mock_session(client if backend == "mock" else client, problems, args.seed)

    print(f"\nlogs: logs/{logger.run_id}/")


if __name__ == "__main__":
    main()
