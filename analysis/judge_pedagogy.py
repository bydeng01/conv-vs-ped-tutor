"""Pedagogical-quality judge (extension; supplement/judge_pedagogy_rubric.md).

A THIRD post-hoc LLM-judge pass over the stored sessions, added as a pre-registered
EXTENSION on the frozen primary (decisions-log 2026-06-27). It mirrors the
perceived-helpfulness judge (analysis/judge.py) plumbing exactly -- same role="judge"
Opus call shape, a separate log dir, per-rep cache, 3 reps + sample variance -- and
rates the SAME visible training tutor turns over the SAME frozen answer-phase window,
so the three evaluators (helpfulness, pedagogy, independence) line up 1:1 per turn.
Nothing here changes a run or any frozen metric; it is computed after the fact from
logs/<run_id>/calls.jsonl.

What it adds, and why it is fair: helpfulness rates how a turn *feels*, blind to
strategy; this judge rates the *pedagogical quality* of the tutor's move on four cited
principles -- contingent scaffolding (Wood/Bruner/Ross 1976), non-disclosure / the
generation effect (Slamecka/Graf 1978), the assistance dilemma (Koedinger/Aleven 2007),
and eliciting student work / uptake (Aleven et al. 2006). The rubric is SYMMETRIC by
construction: it can credit a ConvTutor turn that genuinely scaffolds and penalize a
PedTutor turn that is vague or unresponsive. It does NOT reward withholding for its own
sake or penalize disclosure for its own sake -- doing so would make the result true by
construction and rig the divergence story. See supplement/judge_pedagogy_rubric.md for
the verbatim, frozen instrument and the fairness argument.

Non-negotiable, asserted in tools/test_judge_pedagogy.py:
  - The judge prompt contains ONLY the student-visible dialogue text + the frozen
    rubric -- never canonical_answer, the leakage strings, the node names, or the
    condition label. The judge cannot tell which tutor it is rating.
  - Same dialogue, same visible-training-turn set, same answer-phase window as the
    helpfulness judge: the dialogue is built by the SAME analysis/judge.py:dialogue_for_turn
    (reused, not re-implemented), so the two judges see byte-identical context per turn.
  - Condition-neutral: identical rubric, context, and rep count for both tutors.
"""
from __future__ import annotations

import json
import re
import statistics
from typing import Callable, Optional

from analysis import judge as J     # reuse dialogue_for_turn / cache_key / _coerce_score
from analysis import metrics as M

# The five-field score schema (matches the rubric: four principle sub-scores + overall).
FIELDS = ("scaffolding", "productive_struggle", "assistance_calibration",
          "elicitation", "overall")


# =====================================================================
# FROZEN pedagogy rubric / system prompt. Released verbatim in
# supplement/judge_pedagogy_rubric.md. Frozen 2026-06-27, before this judge is applied
# to any data; never tuned afterward.
#
# It rates the PEDAGOGICAL QUALITY of the tutor's move on cited learning-science
# principles, blind to which tutor produced the turn. It is written to be a fair,
# symmetric instrument: disclosure is judged by whether it served the student's learning
# at that moment, not by a blanket rule -- it rewards neither withholding nor
# answer-giving per se. (Contrast analysis/judge.py, which rates felt helpfulness and
# is deliberately strategy-blind.)
# =====================================================================
PED_RUBRIC_TEXT = (
    "You are an impartial expert in tutoring and the learning sciences, rating the "
    "pedagogical quality of a single tutor turn in a tutoring chat. Rate ONLY the final "
    "tutor turn, read in the context of the dialogue shown.\n\n"
    "Score each dimension on an integer scale from 1 (poor) to 5 (excellent):\n"
    "- scaffolding (contingent support): Does the turn meet the student where they are "
    "and offer help calibrated to their current difficulty -- diagnosing the specific "
    "sticking point and supplying the next bit of support? 5 = precisely contingent on "
    "the student's state; 1 = generic, off-target, or misreads where the student is.\n"
    "- productive_struggle (preserving the student's thinking): Does the turn preserve "
    "the reasoning step(s) the student can still generate themselves, instead of doing "
    "the student's thinking for them? 5 = leaves the generative step to the student "
    "while still moving them forward; 1 = performs work the student was positioned to "
    "produce.\n"
    "- assistance_calibration (right amount of help): Does the turn give the right "
    "amount of assistance -- enough to prevent floundering, not so much that it removes "
    "the learning? 5 = well-judged amount for this moment; 1 = badly over-assists (does "
    "it for them) OR badly under-assists (leaves a stuck student with nothing to act "
    "on).\n"
    "- elicitation (eliciting and building on student work): Does the turn invite the "
    "student to do the next piece of reasoning, and does it build on what the student "
    "actually said or attempted? 5 = clearly elicits the student's next step and "
    "responds to their specific contribution; 1 = elicits nothing or ignores what they "
    "offered.\n"
    "- overall: Your holistic 1-5 rating of the pedagogical quality of this tutor turn, "
    "taking the four dimensions together."
)

PED_NEUTRALITY_TEXT = (
    "Constraints on your rating:\n"
    "- Judge the pedagogical quality of THIS turn on the four principles, blind to who "
    "produced it. Do not assume any tutoring style is good or bad in the abstract.\n"
    "- Disclosure is not automatically wrong, and withholding is not automatically "
    "right. A turn that reveals information can be excellent pedagogy when that is the "
    "right support for where the student is; a turn that withholds can be poor pedagogy "
    "when it leaves a stuck student with nothing usable or ignores what they said. Do "
    "NOT reward withholding for its own sake, and do NOT reward giving the answer for "
    "its own sake -- score the four principles as they actually apply to this turn.\n"
    "- A clear, well-targeted hint that builds on the student's last attempt is good "
    "pedagogy even if it reveals part of the answer; a generic \"keep trying, what do "
    "you think?\" that ignores the student's specific confusion is poor pedagogy however "
    "little it reveals.\n"
    "- Do NOT solve the problem yourself, and do NOT judge whether anything the tutor "
    "says is mathematically correct. Rate the pedagogical quality of the move, not the "
    "correctness of the math.\n"
    "- Base your rating only on the dialogue shown."
)

PED_SYSTEM = (
    PED_RUBRIC_TEXT + "\n\n" + PED_NEUTRALITY_TEXT +
    "\n\nRespond with a single JSON object and nothing else, in exactly this form:\n"
    '{"scaffolding": <1-5>, "productive_struggle": <1-5>, '
    '"assistance_calibration": <1-5>, "elicitation": <1-5>, "overall": <1-5>}'
)

PED_USER = (
    "Here is a tutoring dialogue between a student and a tutor. Rate the FINAL tutor "
    'turn (the last line beginning with "Tutor:") using the rubric.\n\n'
    'DIALOGUE:\n"""\n{dialogue}\n"""\n\n'
    "Reply with ONLY the JSON object: "
    '{{"scaffolding": <1-5>, "productive_struggle": <1-5>, '
    '"assistance_calibration": <1-5>, "elicitation": <1-5>, "overall": <1-5>}}'
)


# ---------------------------------------------------------------- parsing
def parse_pedagogy_scores(text: str) -> Optional[dict]:
    """Parse the judge's reply into the five-field pedagogy score dict.

    Mirrors analysis/judge.py:parse_judge_scores exactly (first JSON object, then a
    per-field regex fallback for single quotes / '=' / trailing commas). A field that
    cannot be read as an integer 1..5 is None. The reply is usable only if `overall`
    parsed (it is the per-turn pedagogy metric); otherwise returns None and the rep does
    not count toward the turn's mean/variance.
    """
    if not text:
        return None
    scores: dict[str, Optional[int]] = {}

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
        except Exception:  # noqa: BLE001 - garbled JSON falls through to regex
            obj = None
        if isinstance(obj, dict):
            for k in FIELDS:
                scores[k] = J._coerce_score(obj.get(k))

    for k in FIELDS:
        if scores.get(k) is None:
            mm = re.search(rf"['\"]?{k}['\"]?\s*[:=]\s*['\"]?([1-5])", text, re.IGNORECASE)
            if mm:
                scores[k] = J._coerce_score(mm.group(1))

    if scores.get("overall") is None:
        return None
    return {k: scores.get(k) for k in FIELDS}


# ---------------------------------------------------------------- aggregation
def aggregate_reps(rep_scores: list[Optional[dict]]) -> dict:
    """Aggregate the per-rep score dicts for ONE turn.

    Per-turn pedagogy = mean of the reps' `overall`. Variance is the sample variance
    (ddof=1) of the reps' `overall`, or None with fewer than two valid reps. The four
    principle sub-score means are kept for the supplement. Unparseable reps (None) are
    dropped from the means/variance and counted in n_valid. Same shape as
    analysis/judge.py:aggregate_reps, with pedagogy field names.
    """
    valid = [s for s in rep_scores if s is not None and s.get("overall") is not None]

    def field_mean(k: str) -> Optional[float]:
        xs = [s[k] for s in valid if s.get(k) is not None]
        return (sum(xs) / len(xs)) if xs else None

    overall_vals = [s["overall"] for s in valid]
    overall_var = statistics.variance(overall_vals) if len(overall_vals) >= 2 else None
    return {
        "overall_mean": field_mean("overall"),       # the per-turn pedagogy metric
        "overall_var": overall_var,
        "overall_values": overall_vals,
        "scaffolding_mean": field_mean("scaffolding"),
        "productive_struggle_mean": field_mean("productive_struggle"),
        "assistance_calibration_mean": field_mean("assistance_calibration"),
        "elicitation_mean": field_mean("elicitation"),
        "n_reps": len(rep_scores),
        "n_valid": len(valid),
    }


# ---------------------------------------------------------------- judge fn + cache
def make_pedagogy_judge_fn(client, seed: int = 0) -> Callable[..., Optional[dict]]:
    """An Opus (role='judge') judge_fn. The prompt contains ONLY the dialogue and the
    frozen rubric -- never canonical_answer, the leakage strings, or the condition.

    Each rep bumps the seed (seed + rep) so the three reps are three distinct calls (the
    Anthropic path ignores the seed, so its reps stay genuine samples; the mock and
    OpenAI-compatible paths use it). Same shape as
    analysis/judge.py:make_helpfulness_judge_fn.
    """
    def judge_fn(dialogue: str, rep: int = 0, tags: Optional[dict] = None) -> Optional[dict]:
        comp = client.complete(
            role="judge",
            system=PED_SYSTEM,
            messages=[{"role": "user", "content": PED_USER.format(dialogue=dialogue)}],
            seed=seed + rep,
            tags=tags or {"component": "pedagogy_judge"},
        )
        return parse_pedagogy_scores(comp.text)
    return judge_fn


# ---------------------------------------------------------------- per-session pass
def judge_pedagogy_session(sm: "M.SessionMetrics", problems_by_id: dict,
                           judge_fn: Callable[..., Optional[dict]], reps: int = 3,
                           cache: Optional[dict] = None) -> list[dict]:
    """Rate every visible TRAINING tutor turn in the answer-phase window; one row per turn.

    Identical turn selection to analysis/judge.py:judge_session -- training problems,
    `tutor_in_window` answer-phase restriction, the same dialogue from
    J.dialogue_for_turn -- so per-turn pedagogy lines up 1:1 with per-turn helpfulness,
    leakage, and next-turn independence. The cache (if given) is keyed by
    (run_id, problem_id, turn_index, rep) via J.cache_key; unparseable reps are not
    cached (so they are retried).
    """
    rows = []
    for vt in sm.visible_turns:
        prob = problems_by_id.get(vt.problem_id)
        if prob is None or prob.role != M.TRAINING_PHASE:
            continue
        if not M.tutor_in_window(sm.commit_seq, vt.problem_id, vt.first_seq):
            continue
        dialogue = J.dialogue_for_turn(sm, vt)
        rep_scores: list[Optional[dict]] = []
        for rep in range(reps):
            ck = J.cache_key(sm.run_id, vt.problem_id, vt.turn_index, rep)
            if cache is not None and ck in cache:
                rep_scores.append(cache[ck].get("scores"))
                continue
            scores = judge_fn(dialogue, rep, {
                "component": "pedagogy_judge",
                "problem_id": vt.problem_id, "turn_index": vt.turn_index, "rep": rep,
            })
            rep_scores.append(scores)
            if cache is not None and scores is not None:
                cache[ck] = {"scores": scores}
        agg = aggregate_reps(rep_scores)
        rows.append({
            "run_id": sm.run_id, "condition": sm.condition,
            "replicate_id": sm.replicate_id,
            "problem_id": vt.problem_id, "turn_index": vt.turn_index,
            **agg,
            "reps": rep_scores,
        })
    return rows


# ---------------------------------------------------------------- merge helpers
def pedagogy_by_turn(turn_rows: list[dict]) -> dict[tuple, float]:
    """{(problem_id, turn_index): per-turn pedagogy} for filling the per-turn table."""
    return {(r["problem_id"], r["turn_index"]): r["overall_mean"]
            for r in turn_rows if r["overall_mean"] is not None}


def session_pedagogy_mean(turn_rows: list[dict]) -> Optional[float]:
    """Per-session pedagogy_mean = mean of the per-turn means."""
    xs = [r["overall_mean"] for r in turn_rows if r["overall_mean"] is not None]
    return (sum(xs) / len(xs)) if xs else None
