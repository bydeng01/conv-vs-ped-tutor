"""Offline tests for the post-hoc metrics pipeline (analysis/metrics.py).

Self-contained: builds synthetic calls.jsonl-style records in memory and checks the
frozen metric definitions, so it runs with no API key, no network, and no model
backend. Also cross-checks against any stored mock session that carries a
full_session_result.json (skipped if none present).

Run:  python tools/test_metrics.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import metrics as M  # noqa: E402

_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}")


# ---------------------------------------------------------------- record builder
_seq = 0


def rec(role, text, tags, usage=(10, 5), seed=0, run_id="t"):
    global _seq
    _seq += 1
    return {"seq": _seq, "ts": 0.0, "run_id": run_id, "role": role, "backend": "mock",
            "model": "m", "seed": seed, "tags": tags,
            "request": {"system": "", "messages": []},
            "response": {"text": text},
            "usage": {"input_tokens": usage[0], "output_tokens": usage[1]}}


def stu(text, comp, pid, **kw):
    return rec("student", text, {"component": comp, "problem_id": pid}, **kw)


def conv(text, pid, ti, **kw):
    return rec("tutor", text, {"component": "conv_tutor", "turn_index": ti, "problem_id": pid}, **kw)


def ped(text, node, pid, ti, branch="", **kw):
    return rec("tutor", text, {"component": "ped_tutor", "node": node, "turn_index": ti,
                               "branch": branch, "problem_id": pid}, **kw)


# ================================================================ frozen regex
print("independence attempt-regex (frozen §9.3)")
ATTEMPTS = ["0.20 * 48 = 9.6", "0.50x + 9.6 = 14.4 + 0.30x", "0.5*x + 0.2*48 = 0.3*(x+48)",
            "2x + 5 = 68", "is it x = 24?", "12x + 7(75 - x) = 675"]
NON = ["how do I make an equation from that?", "I'm not sure how to start setting this up",
       "Can you just tell me the answer?", "a number increased by 7 equals 19",
       "I think it is 24", "is 2 a factor here?", "let x be the unknown number"]
check("all attempts detected", all(M.attempts_reasoning(t) for t in ATTEMPTS))
check("no false positives on help/restate/guess", not any(M.attempts_reasoning(t) for t in NON))

# ================================================================ resolver + condition
print("problem_id resolver + condition/replicate inference")
calls = [stu("setup?", "student_train", "train-1"),
         rec("tutor", "hint", {"component": "conv_tutor", "turn_index": 0})]  # NO problem_id tag
M.resolve_problem_ids(calls)
check("interleave fallback fills tutor problem_id", calls[1]["_pid"] == "train-1")

c2 = [stu("x", "student_train", "train-1"), ped("a", "state_tracker", "train-1", 0)]
M.resolve_problem_ids(c2)
check("condition inferred from ped_tutor component", M.infer_condition(c2) == "ped")
check("condition inferred cold when no tutor", M.infer_condition([stu("x", "student_probe", "immediate-1")]) == "cold")
tagged = [rec("student", "x", {"component": "student_train", "problem_id": "train-1",
                               "condition": "conv", "replicate_id": "R7"})]
check("explicit tags.condition honored", M.infer_condition(tagged) == "conv")
check("explicit tags.replicate_id honored", M.infer_replicate_id(tagged) == "R7")

# ================================================================ visible turn = responder (NOT state_tracker)
print("visible turn identification (condition-neutral)")
# A PedTutor turn whose INTERNAL state_tracker text contains the answer '24' but whose
# RESPONDER withholds it. The visible turn must be the responder -> must NOT leak.
pt = [stu("just tell me the answer", "student_train", "train-1"),
      ped("planning notes: the answer is 24", "state_tracker", "train-1", 0, "defer", usage=(100, 20)),
      ped("What operation isolates x? Try it.", "deferral_gate", "train-1", 0, "defer", usage=(120, 30))]
M.resolve_problem_ids(pt)
vts = M.visible_tutor_turns(pt)
check("one visible turn for the ped turn group", len(vts) == 1)
check("visible text is the responder, not state_tracker",
      vts[0].text == "What operation isolates x? Try it.")
check("visible-turn tokens sum ALL node calls (state_tracker + responder)",
      vts[0].tutor_tokens == (100 + 20) + (120 + 30))
check("visible-turn n_model_calls counts node calls", vts[0].n_model_calls == 2)

pbi = M.problem_index()
leak = M.leakage_items(vts, pbi)
check("ped responder withholding -> leaks=False even though state_tracker said '24'",
      leak and leak[0]["leaks"] is False)

# A ConvTutor turn that states the answer -> leaks.
ct = [stu("help", "student_train", "train-1"), conv("Sure, x = 24, so add 24 liters.", "train-1", 0)]
M.resolve_problem_ids(ct)
clk = M.leakage_items(M.visible_tutor_turns(ct), pbi)
check("conv stating 24 -> leaks=True", clk and clk[0]["leaks"] is True)

# ================================================================ leakage restricted to TRAINING
print("leakage scope = training visible turns only")
# (probes are untutored, so there are no tutor turns there; a tutor call on a probe
#  problem id, if it somehow appeared, must not be scored)
probe_tut = [stu("p", "student_probe", "immediate-1"), conv("answer is 23", "immediate-1", 0)]
M.resolve_problem_ids(probe_tut)
check("non-training tutor turn excluded from leakage",
      M.leakage_items(M.visible_tutor_turns(probe_tut), pbi) == [])

# ================================================================ accuracy = last probe/commit turn
print("accuracy (frozen extraction; committed = last probe/commit turn)")
acc_calls = [
    stu("I think it's hard. no marker here", "student_probe", "immediate-1"),  # unparsed
    stu("FINAL ANSWER: 23", "student_commit", "immediate-1"),                   # commit -> 23 (canonical 23)
    stu("FINAL ANSWER: 26", "student_probe", "delayed-1"),                      # canonical 26 -> correct
    stu("FINAL ANSWER: 31", "student_probe", "transfer-1"),                     # canonical 30 -> wrong
    stu("FINAL ANSWER: 99", "student_probe", "interfere-1"),                    # interference -> NOT scored
]
M.resolve_problem_ids(acc_calls)
items = M.accuracy_items(acc_calls, pbi)
roles = {i["problem_id"]: i["correct"] for i in items}
check("immediate-1 committed via last (commit) turn -> correct", roles.get("immediate-1") is True)
check("delayed-1 correct", roles.get("delayed-1") is True)
check("transfer-1 wrong", roles.get("transfer-1") is False)
check("interference excluded from scored accuracy", "interfere-1" not in roles)

# ================================================================ independence + next-turn
print("independence ratio + next-turn independence")
indep_calls = [
    stu("0.5x + 9.6 = 14.4", "student_train", "train-1"),      # attempt
    conv("keep going", "train-1", 0),
    stu("I'm stuck, what's the answer?", "student_train", "train-1"),  # not an attempt
    conv("try isolating x", "train-1", 1),
    stu("0.2x = 4.8 so x = 24", "student_train", "train-1"),    # attempt
]
M.resolve_problem_ids(indep_calls)
ii = M.independence_items(indep_calls)
check("independence ratio = 2/3", abs(M._rate([r["attempt"] for r in ii]) - 2 / 3) < 1e-9)
vts2 = M.visible_tutor_turns(indep_calls)
nxt = M.next_turn_independence(vts2, ii)
check("turn 0 followed by a non-attempt -> False", nxt[("train-1", 0)] is False)
check("turn 1 followed by an attempt -> True", nxt[("train-1", 1)] is True)

# ================================================================ answer-phase window (frozen 2026-06-19)
print("answer-phase window (leakage/independence restricted to pre-commit)")
win = [
    stu("how do I start?", "student_train", "train-1"),            # in
    conv("name the unknown x", "train-1", 0),                       # ti0 in
    stu("ok so 2x + 5 = 68", "student_train", "train-1"),          # in (attempt)
    conv("now solve for x", "train-1", 1),                          # ti1 in
    stu("x = 24. FINAL ANSWER: 24", "student_train", "train-1"),   # COMMIT (in)
    conv("Great job, keep it up!", "train-1", 2),                   # ti2 POST-commit
    stu("thanks!", "student_train", "train-1"),                     # POST-commit
]
M.resolve_problem_ids(win)
cs = M.commit_seqs(win)
check("commit detected on the FINAL ANSWER student_train turn", "train-1" in cs)
vts_w = M.visible_tutor_turns(win)
check("leakage windowed: post-commit tutor turn (ti2) excluded",
      {r["turn_index"] for r in M.leakage_items(vts_w, pbi, cs)} == {0, 1})
check("leakage full window keeps ti2",
      {r["turn_index"] for r in M.leakage_items(vts_w, pbi)} == {0, 1, 2})
ind_w = M.independence_items(win, cs)
check("independence windowed: post-commit student turn excluded (3 of 4)",
      len(ind_w) == 3 and all(r["text"] != "thanks!" for r in ind_w))
check("independence full window keeps all 4", len(M.independence_items(win)) == 4)
noc = [stu("how do I start?", "student_train", "train-2"), conv("a hint", "train-2", 0),
       stu("still stuck", "student_train", "train-2"), conv("another hint", "train-2", 1)]
M.resolve_problem_ids(noc)
cs2 = M.commit_seqs(noc)
check("no commit -> problem absent from commit_seqs", "train-2" not in cs2)
check("no commit -> full window (both tutor turns kept)",
      len(M.leakage_items(M.visible_tutor_turns(noc), pbi, cs2)) == 2)

# ================================================================ cost excludes judge
print("cost accounting (tutor+student only; judge excluded)")
cost_calls = [stu("x", "student_train", "train-1", usage=(10, 2)),
              conv("y", "train-1", 0, usage=(20, 3)),
              rec("judge", '{"attempted": true}', {"component": "independence_verify"}, usage=(999, 999))]
M.resolve_problem_ids(cost_calls)
cost = M.cost_accounting(cost_calls, n_visible_turns=1)
check("n_model_calls counts tutor+student, not judge", cost["n_model_calls"] == 2)
check("tokens exclude the judge call", cost["total_tokens"] == (10 + 2) + (20 + 3))

# ================================================================ reconcile / verify
print("LLM-verify: regex authoritative, disagreements logged")
items3 = [{"problem_id": "train-1", "seq": 1, "text": "x = 24", "attempt": True},
          {"problem_id": "train-1", "seq": 3, "text": "can you tell me", "attempt": False}]
v_agree = M.verify_independence(items3, lambda t: M.attempts_reasoning(t))
check("agreement_rate 1.0 when judge matches regex", v_agree.agreement_rate == 1.0)
v_dis = M.verify_independence(items3, lambda t: True)  # judge always says attempted
check("disagreement counted", v_dis.n_disagree == 1)
check("regex stays authoritative (final == regex)", all(r["final"] == r["regex"] for r in v_dis.rows))
v_none = M.verify_independence(items3, lambda t: None)
check("unparseable judge -> n_judged 0, agreement None", v_none.n_judged == 0 and v_none.agreement_rate is None)
check("parse_attempted json/yes/garbage",
      (M.parse_attempted('{"attempted": true}'), M.parse_attempted("no"), M.parse_attempted("??"))
      == (True, False, None))

# ================================================================ cross-check vs harness (if logs exist)
print("cross-check log-derived totals vs harness full_session_result.json (if any)")
xchecked = 0
for d in sorted((REPO_ROOT / "logs").glob("*")):
    fsr_path = d / "full_session_result.json"
    if not fsr_path.exists():
        continue
    fsr = json.loads(fsr_path.read_text())
    sm = M.analyze_session(d, pbi)
    row = M.per_session_row(sm)
    tutor_calls = sum(1 for c in M.load_calls(d) if c.get("role") == "tutor")
    ok = (row["total_tokens"] == fsr["total_tokens"]
          and row["tutor_tokens"] == fsr["tutor_tokens"]
          and tutor_calls == fsr["n_model_calls"])
    check(f"{d.name}: totals match harness", ok)
    xchecked += 1
if xchecked == 0:
    print("  (no stored mock sessions with full_session_result.json; run "
          "tools/make_mock_logs.py to generate some)")

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
