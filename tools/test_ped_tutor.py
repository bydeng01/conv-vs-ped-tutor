"""Offline tests for PedTutor's deterministic control flow and cost accounting.

These run on the mock backend (no API key, no cost). They check the parts that
must be reliable regardless of the model: the answer-request / attempt detectors,
the routing decision, the >=2-attempt reveal gate, and that node-call tokens are
summed into the turn and session totals. Behavioral withholding (the model
actually refusing to give the answer) is checked separately in a live smoke --
the generic mock tutor does not honor the scoped node prompts.

Run:  python tools/test_ped_tutor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.config import load_models_config  # noqa: E402
from agents.model_client import ModelClient  # noqa: E402
from agents.ped_tutor import (PedTutor, count_attempts, is_answer_request,  # noqa: E402
                              is_attempt)
from agents.state import Turn  # noqa: E402
from protocol.full_session import run_full_session  # noqa: E402
from protocol.session import load_problems  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def mock_client():
    cfg = load_models_config("configs/models.yaml")
    return ModelClient(models_cfg=cfg, backend="mock", logger=None)


def ped():
    return PedTutor(mock_client())


def test_signal_detectors():
    print("signal detectors")
    p = ped()
    # answer requests
    for s in ["Can you just tell me the answer?", "what's the answer here",
              "just give me the answer", "I give up", "solve it for me"]:
        check(f"ask: {s!r}", is_answer_request(s, p.ask_res))
    for s in ["I think x = liters of acid", "let me restate the problem",
              "what does 30% of 48 mean?"]:
        check(f"not-ask: {s!r}", not is_answer_request(s, p.ask_res))
    # attempts: needs a real operator / equation, not mere restatement
    for s in ["0.5*x + 0.2*48 = 0.3*(x+48)", "so 0.2x = 4.8", "x = 24", "let x be the liters"]:
        check(f"attempt: {s!r}", is_attempt(s, p.attempt_res))
    for s in ["How many liters of a 50% acid solution must be added to 48 liters?",
              "I'm not sure how to start", "can you help me set this up"]:
        check(f"not-attempt: {s!r}", not is_attempt(s, p.attempt_res))


# Phrasings grounded in real Llama-8B calibration transcripts (see decisions-log.md)
# plus realistic answer-demands and false-positive guards. Format: (text, asked, attempt).
# A MISSED answer-demand (asked False when it should be True) is the fatal failure --
# deferral_gate never fires; an over-trigger only routes to deferral_gate, which still
# scaffolds without revealing.
REALISM_CORPUS = [
    # blunt answer demands -> must be detected as asked
    ("just tell me the answer", True, False),
    ("Can you just give me the answer?", True, False),
    ("whats the answer", True, False),
    ("what's the answer?", True, False),
    ("I give up, what is the answer", True, False),
    ("tell me the solution", True, False),
    ("give me the solution please", True, False),
    ("what's the final answer", True, False),
    ("can you solve this for me", True, False),
    ("solve this for me", True, False),
    ("just give me the number", True, False),
    ("what is the result", True, False),
    # conceptual help-seeking / restatement -> neither (route to decompose)
    ("how do I make an equation from that?", False, False),          # real quote
    ("I'm not sure how to start setting this up", False, False),     # real quote
    ("how do I set this up?", False, False),
    ("can you help me set this up?", False, False),
    ("I dont understand how to translate this into an equation", False, False),
    ("The problem has a 50% solution and a 20% solution.", False, False),
    ("How many liters of a 50% acid solution must be added to 48 liters?", False, False),
    ("I'll solve it myself", False, False),
    ("let me solve this", False, False),
    # genuine attempts -> must be detected as attempt
    ("4x+11=3(x+11)", False, True),                                  # real setup
    ("12x+7(75-x)=675", False, True),                                # real coffee transfer
    ("93x+87(30-x)=91*30", False, True),                             # real octane
    ("0.5x + 9.6 = 0.3(x+48)", False, True),
    ("so 0.2x = 4.8", False, True),
    ("let x be the liters of acid", False, True),
    ("I think x = 24", False, True),
    ("20% of 48 is 9.6", False, True),
    ("0.20 * 48 = 9.6", False, True),
]


def test_realism_corpus():
    print("realism corpus (real calibration phrasings + answer-demands)")
    p = ped()
    for text, want_ask, want_att in REALISM_CORPUS:
        got_ask = is_answer_request(text, p.ask_res)
        got_att = is_attempt(text, p.attempt_res)
        check(f"ask={want_ask} att={want_att}: {text!r}",
              got_ask == want_ask and got_att == want_att)


def test_routing_branches():
    print("routing branches (deterministic, mock backend)")
    p = ped()
    problem = {x.id: x for x in load_problems("domain/algebra/problems.yaml")}["train-1"]

    # asked + no attempts -> defer, gate closed
    t = [Turn("student", "I don't get it, just tell me the answer.")]
    r = p.respond(t, problem, seed=0, turn_index=0)
    check("asked -> defer", r.meta["branch"] == "defer")
    check("no attempts -> reveal locked", r.meta["reveal_allowed"] is False)

    # stuck, no attempts, not asking -> decompose
    t = [Turn("student", "I'm not sure how to start setting this up.")]
    r = p.respond(t, problem, seed=0, turn_index=0)
    check("stuck/no-attempt -> decompose", r.meta["branch"] == "decompose")

    # an attempt, not asking -> hint
    t = [Turn("student", "I tried 0.5*x + 0.2*48 = 0.3*(x+48) but got stuck.")]
    r = p.respond(t, problem, seed=0, turn_index=0)
    check("attempt -> hint", r.meta["branch"] == "hint")

    # two attempts then asks -> defer, gate OPEN
    t = [
        Turn("student", "0.5*x + 0.2*48 = 0.3*(x+48)"),
        Turn("tutor", "Good, keep going."),
        Turn("student", "so 0.2x = 4.8, now what? just tell me the answer"),
    ]
    r = p.respond(t, problem, seed=0, turn_index=1)
    check("two attempts counted", count_attempts(t, p.attempt_res) == 2)
    check("asked after 2 attempts -> defer", r.meta["branch"] == "defer")
    check("gate open at >=2 attempts", r.meta["reveal_allowed"] is True)


def test_cost_accounting():
    print("cost accounting")
    p = ped()
    problem = {x.id: x for x in load_problems("domain/algebra/problems.yaml")}["train-1"]
    t = [Turn("student", "I'm stuck, what's the answer?")]
    r = p.respond(t, problem, seed=0, turn_index=0)
    # state_tracker + exactly one responder = 2 model calls this visible turn
    check("2 model calls per visible turn", r.meta["n_model_calls"] == 2)
    check("nodes recorded", r.meta["nodes"][0] == "state_tracker" and len(r.meta["nodes"]) == 2)
    check("per-turn tokens summed > 0", r.meta["tokens"] > 0)

    # session totals include tutor (node) tokens for PedTutor
    problems = load_problems("domain/algebra/problems.yaml")
    res = run_full_session(problems, mock_client(), tutor=PedTutor(mock_client()),
                           seed=0, condition="ped", max_train_turns=2)
    check("session tutor_tokens > 0", res.tutor_tokens > 0)
    check("session total = student + tutor",
          res.total_tokens == res.student_tokens + res.tutor_tokens)
    n_train_turns = sum(i.n_tutor_turns for i in res.items if i.phase == "training")
    check("more model calls than visible turns", res.n_model_calls > n_train_turns)


def main():
    test_signal_detectors()
    test_realism_corpus()
    test_routing_branches()
    test_cost_accounting()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
