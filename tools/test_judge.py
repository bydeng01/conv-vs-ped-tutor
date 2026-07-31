"""Offline tests for the perceived-helpfulness judge (analysis/judge.py).

Self-contained: builds synthetic calls.jsonl-style records in memory and uses a stub
judge_fn (and the offline mock backend) so it runs with no API key, no network. Mirrors
tools/test_metrics.py. Covers: the score parser on good/garbled JSON, the 3-rep
mean/variance aggregation, the canonical-answer-absent-from-prompt guarantee, the
dialogue reconstruction, the column merge filling helpfulness / helpfulness_mean, the
training-only restriction, the per-rep cache, and an end-to-end mock pass over a
stored mock session (if present).

Run:  python tools/test_judge.py
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import metrics as M  # noqa: E402
from analysis import judge as J    # noqa: E402

_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}")


# ---------------------------------------------------------------- record builders
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


def make_sm(calls, condition="conv", run_id="t", replicate_id="0"):
    """Assemble a SessionMetrics from in-memory calls (no disk), reusing the frozen
    primitives so the judge sees exactly what the real pipeline produces."""
    M.resolve_problem_ids(calls)
    pbi = M.problem_index()
    vts = M.visible_tutor_turns(calls)
    cseq = M.commit_seqs(calls)   # answer-phase window, exactly as analyze_session computes it
    return M.SessionMetrics(
        run_id=run_id, run_dir="", condition=condition, replicate_id=replicate_id,
        seed=0, backend="mock", visible_turns=vts,
        acc_items=[], leak_items=M.leakage_items(vts, pbi, cseq),
        indep_items=M.independence_items(calls, cseq), next_indep={},
        cost=M.cost_accounting(calls, len(vts)), commit_seq=cseq,
    )


pbi = M.problem_index()

# ================================================================ score parser
print("score parser (good / garbled / garbage)")
good = J.parse_judge_scores('{"clarity": 4, "responsiveness": 5, "helpfulness": 4, "overall": 4}')
check("good JSON parses to four ints",
      good == {"clarity": 4, "responsiveness": 5, "helpfulness": 4, "overall": 4})
prose = J.parse_judge_scores('Here are my scores:\n{"clarity":3,"responsiveness":4,'
                             '"helpfulness":4,"overall":4}\nHope that helps!')
check("JSON embedded in prose is recovered", prose and prose["overall"] == 4)
garbled = J.parse_judge_scores("{'clarity': 3, 'responsiveness': 4, 'helpfulness': 4, 'overall': 4,}")
check("single-quoted / trailing-comma recovered via regex", garbled and garbled["overall"] == 4)
check("garbage -> None", J.parse_judge_scores("no idea, sorry") is None)
check("missing overall -> None (rep unusable)",
      J.parse_judge_scores('{"clarity":4,"responsiveness":4,"helpfulness":4}') is None)
check("out-of-range field -> None for that field",
      J.parse_judge_scores('{"clarity":9,"responsiveness":4,"helpfulness":4,"overall":5}')["clarity"] is None)
check("empty -> None", J.parse_judge_scores("") is None)

# ================================================================ rep aggregation
print("rep aggregation (mean + sample variance, drops unparseable reps)")
agg = J.aggregate_reps([{"clarity": 4, "responsiveness": 4, "helpfulness": 4, "overall": 4},
                        {"clarity": 4, "responsiveness": 5, "helpfulness": 4, "overall": 4},
                        {"clarity": 5, "responsiveness": 5, "helpfulness": 5, "overall": 5}])
check("per-turn helpfulness = mean of reps' overall", abs(agg["overall_mean"] - (4 + 4 + 5) / 3) < 1e-9)
check("variance is sample variance (ddof=1)", abs(agg["overall_var"] - statistics.variance([4, 4, 5])) < 1e-9)
check("n_valid counts parsed reps", agg["n_valid"] == 3)
check("sub-score means kept separately", abs(agg["clarity_mean"] - (4 + 4 + 5) / 3) < 1e-9)
one = J.aggregate_reps([{"clarity": 4, "responsiveness": 4, "helpfulness": 4, "overall": 4}])
check("variance undefined (None) with <2 valid reps", one["overall_var"] is None)
dropna = J.aggregate_reps([{"clarity": 4, "responsiveness": 4, "helpfulness": 4, "overall": 4},
                           None,
                           {"clarity": 5, "responsiveness": 5, "helpfulness": 5, "overall": 5}])
check("unparseable rep dropped from mean", abs(dropna["overall_mean"] - 4.5) < 1e-9 and dropna["n_valid"] == 2)
allbad = J.aggregate_reps([None, None, None])
check("all-unparseable -> overall_mean None, n_valid 0",
      allbad["overall_mean"] is None and allbad["n_valid"] == 0)

# ================================================================ dialogue + NO answer leakage
print("dialogue reconstruction + no canonical_answer in the judge prompt")
# Digit-free turns so the (numeric) canonical answer cannot appear by construction.
calls = [
    stu("I'm stuck. Can you help me start?", "student_train", "train-1"),
    conv("Sure. What is the quantity the problem asks you to find? Give it a letter.", "train-1", 0),
    stu("Maybe I should name the unknown amount.", "student_train", "train-1"),
    conv("Good. Now turn the sentence into an equation using that letter.", "train-1", 1),
]
sm = make_sm(calls, condition="conv", run_id="r1", replicate_id="R1")
v_last = sm.visible_turns[-1]
dialogue = J.dialogue_for_turn(sm, v_last)
check("dialogue interleaves both student and tutor turns",
      dialogue.count("Student:") == 2 and dialogue.count("Tutor:") == 2)
check("dialogue ends with the rated tutor turn", dialogue.strip().endswith(v_last.text))
check("dialogue is digit-free (no numeric answer injected)", not any(c.isdigit() for c in dialogue))
ans = pbi["train-1"].canonical_answer
check("problem canonical_answer is absent from the dialogue", str(ans) not in dialogue)

prompt = J.JUDGE_SYSTEM + "\n" + J.JUDGE_USER.format(dialogue=dialogue)
check("canonical_answer absent from the full judge prompt", str(ans) not in dialogue)  # via dialogue
forbidden = ["conv_tutor", "ped_tutor", "state_tracker", "deferral_gate", "decomposer",
             "hint_cascade", "canonical", "condition"]
check("no condition label / node names / 'canonical' in the prompt",
      not any(tok in prompt.lower() for tok in forbidden))

# PedTutor: the visible turn is the responder; state_tracker's internal text (which
# may name the answer) must never enter the dialogue.
ped_calls = [
    stu("just tell me the answer", "student_train", "train-1"),
    ped("internal note: the final answer is 24", "state_tracker", "train-1", 0, "defer", usage=(50, 10)),
    ped("What does each part contribute? Try writing that down.", "deferral_gate", "train-1", 0, "defer"),
]
sm_ped = make_sm(ped_calls, condition="ped", run_id="rp")
d_ped = J.dialogue_for_turn(sm_ped, sm_ped.visible_turns[-1])
check("ped dialogue shows the responder, not state_tracker", "internal note" not in d_ped)
check("ped dialogue has no leaked number from state_tracker", "24" not in d_ped)

# ================================================================ judge_session: training-only + reps
print("judge_session restricts to training turns; reps + variance per turn")
stub_calls = [
    stu("how do I start?", "student_train", "train-1"),
    conv("Begin by naming the unknown with a letter.", "train-1", 0),
    stu("ok, then what?", "student_probe", "immediate-1"),     # probe: untutored normally
    conv("the answer is twenty-three", "immediate-1", 0),       # a stray non-training tutor turn
]
sm_mix = make_sm(stub_calls, run_id="rmix")
scores_seq = iter([{"clarity": 4, "responsiveness": 4, "helpfulness": 4, "overall": 4},
                   {"clarity": 4, "responsiveness": 5, "helpfulness": 4, "overall": 4},
                   {"clarity": 5, "responsiveness": 5, "helpfulness": 5, "overall": 5}])


def stub_fn(dialogue, rep=0, tags=None):
    return next(scores_seq)


rows = J.judge_session(sm_mix, pbi, stub_fn, reps=3)
check("only the training turn is judged (probe turn excluded)",
      len(rows) == 1 and rows[0]["problem_id"] == "train-1")
check("per-turn row carries overall_mean + variance",
      abs(rows[0]["overall_mean"] - (4 + 4 + 5) / 3) < 1e-9 and rows[0]["overall_var"] is not None)
check("per-turn row records all reps", len(rows[0]["reps"]) == 3)

# ================================================================ answer-phase window (frozen 2026-06-19)
print("judge restricts to the answer-phase window (pre-commit turns only)")
win_calls = [
    stu("how do I start?", "student_train", "train-1"),
    conv("name the unknown", "train-1", 0),                     # ti0 pre-commit
    stu("x = 24. FINAL ANSWER: 24", "student_train", "train-1"),  # commit
    conv("Great job, keep it up!", "train-1", 1),                # ti1 POST-commit
]
sm_win = make_sm(win_calls, run_id="rw")
wrows = J.judge_session(sm_win, pbi,
                        lambda d, rep=0, tags=None: {"clarity": 5, "responsiveness": 5,
                                                     "helpfulness": 5, "overall": 5}, reps=1)
check("judge windows out the post-commit (filler) turn",
      len(wrows) == 1 and wrows[0]["turn_index"] == 0)

# ================================================================ cache: no re-pay on re-run
print("per-rep cache prevents re-calling the judge")
calls_made = {"n": 0}


def counting_fn(dialogue, rep=0, tags=None):
    calls_made["n"] += 1
    return {"clarity": 4, "responsiveness": 4, "helpfulness": 4, "overall": 4}


cache = {}
J.judge_session(sm, pbi, counting_fn, reps=3, cache=cache)
after_first = calls_made["n"]
check("first pass calls the judge (3 reps x training turns)", after_first == 3 * len(sm.visible_turns))
J.judge_session(sm, pbi, counting_fn, reps=3, cache=cache)
check("second pass is fully cached (no new calls)", calls_made["n"] == after_first)

# ================================================================ column merge
print("column merge fills the reserved helpfulness / helpfulness_mean columns")
check("per_turn helpfulness defaults to None (pre-Step-6 behavior unchanged)",
      all(r["helpfulness"] is None for r in M.per_turn_rows(sm)))
hmap = {("train-1", 0): 4.5, ("train-1", 1): 4.0}
pt = M.per_turn_rows(sm, helpfulness=hmap)
check("per_turn helpfulness filled from the map",
      {r["turn_index"]: r["helpfulness"] for r in pt} == {0: 4.5, 1: 4.0})
check("per_session helpfulness_mean default None", M.per_session_row(sm)["helpfulness_mean"] is None)
check("per_session helpfulness_mean filled",
      M.per_session_row(sm, helpfulness_mean=4.25)["helpfulness_mean"] == 4.25)
pr = M.per_replicate_rows([sm], helpfulness_by_run={sm.run_id: 4.25})
check("per_replicate helpfulness_mean filled", pr and pr[0]["helpfulness_mean"] == 4.25)
check("per_replicate helpfulness_mean None without the map",
      M.per_replicate_rows([sm])[0]["helpfulness_mean"] is None)

# ================================================================ end-to-end on the mock backend (if logs exist)
print("end-to-end mock judge pass over a stored mock session (if present)")
mock_dir = None
for cand in sorted((REPO_ROOT / "logs").glob("conv-*")):
    calls_c = M.load_calls(cand)
    if M.is_full_protocol(calls_c) and any(c.get("backend") == "mock" for c in calls_c):
        mock_dir = cand
        break
if mock_dir is None:
    print("  (no stored mock conv session; run tools/make_mock_logs.py to generate one)")
else:
    from agents.config import load_models_config
    from agents.model_client import ModelClient
    sm_real = M.analyze_session(mock_dir, pbi)
    client = ModelClient(models_cfg=load_models_config(), backend="mock", logger=None)
    jf = J.make_helpfulness_judge_fn(client, seed=0)
    jrows = J.judge_session(sm_real, pbi, jf, reps=3)
    n_train_turns = len(sm_real.leak_items)
    check(f"{mock_dir.name}: judged every training turn", len(jrows) == n_train_turns)
    check("mock overall_mean in [1,5] for every turn",
          all(r["overall_mean"] is not None and 1 <= r["overall_mean"] <= 5 for r in jrows))
    check("3 reps recorded per turn", all(len(r["reps"]) == 3 for r in jrows))
    smean = J.session_helpfulness_mean(jrows)
    check("session helpfulness_mean in [1,5]", smean is not None and 1 <= smean <= 5)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
