"""Post-hoc metrics pipeline (paper-plan.md §9).

Pure functions over a parsed calls.jsonl (the canonical per-call record written by
agents/logging_utils.py) plus the problem set. NOTHING here changes a run; metrics
are computed after the fact from the logs (build brief, Engineering conventions).

Frozen primitives are REUSED, never reimplemented:
  - agents.extraction.extract_final_answer   (metric 1, §9.1)
  - domain.algebra.checker.is_correct        (metric 1, §9.1)
  - protocol.leakage.turn_leaks              (metric 2, §9.2)

The independence attempt-detection regex (metric 3, §9.3) is THIS pipeline's own
frozen artifact, released verbatim in supplement/independence_rubric.md. It is
defined fresh here and deliberately NOT imported from agents/ped_tutor.py: that
detector is an agent-internal routing signal, and coupling the reported metric to
one agent's internals would be illegitimate (the two may look similar; the metric's
regex is its own thing and is frozen here).

Condition-neutrality: every metric is computed identically for ConvTutor and
PedTutor. The ONLY condition-specific code is identifying the student-visible tutor
turn (ConvTutor = its single call; PedTutor = the responder call, with the internal
state_tracker excluded), which is a faithful read of "what the student saw," not an
advantage to either side.

The post-hoc scorer may read canonical_answer (allowed, per the rigor rule); the
independence LLM-verification prompt is given ONLY the student turn + rubric, never
canonical_answer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from agents.extraction import extract_final_answer  # frozen §9.1
from domain.algebra.checker import is_correct       # frozen §9.1
from protocol.leakage import turn_leaks             # frozen §9.2
from protocol.session import load_problems          # problem-set loader (reused)

# ---------------------------------------------------------------- vocabulary
# Mirror protocol/full_session.py so phase membership matches the harness exactly.
SCORED_PHASES = ("immediate", "delayed", "transfer")
TRAINING_PHASE = "training"

# Visible-turn identification.
RESPONDER_NODES = ("deferral_gate", "decomposer", "hint_cascade")  # PedTutor responders
CONV_COMPONENT = "conv_tutor"
PED_COMPONENT = "ped_tutor"
TUTOR_COMPONENTS = (CONV_COMPONENT, PED_COMPONENT)

# Student-turn components (continuous protocol, protocol/full_session.py).
STUDENT_TRAIN = "student_train"
STUDENT_PROBE = "student_probe"
STUDENT_COMMIT = "student_commit"

# =====================================================================
# FROZEN independence attempt-detection regex (paper-plan.md §9.3).
# Released verbatim in supplement/independence_rubric.md. Frozen before any
# confirmatory run; never tuned afterward.
#
# A student turn "attempts a reasoning step" iff its text contains at least one of:
#   (E)  an explicit equation                  -> something '=' something
#   (C)  an arithmetic computation             -> number <op> number
#   (A1) a coefficient-variable algebra term   -> e.g. 12x, 0.5x
#   (A2) a variable in an operator relation    -> e.g. x - 3, x/2, a + b
# A bare number or a bare answer guess (no operator, no '=', no variable relation)
# does NOT count -- that is a guess, not a reasoning step. This is the conservative
# choice: it does not inflate the independence ratio.
# =====================================================================
INDEPENDENCE_ATTEMPT_PATTERNS = (
    r"[0-9a-z\)]\s*=\s*[-+(]?\s*[0-9a-z]",          # (E) equation
    r"\d+(?:\.\d+)?\s*[-+*/×·]\s*\d+(?:\.\d+)?",      # (C) number <op> number
    r"\d+(?:\.\d+)?[a-z]\b",                           # (A1) coefficient·variable
    r"\b[a-z]\s*[-+*/]\s*[0-9a-z(]",                  # (A2) variable <op> term
)
_ATTEMPT_RE = [re.compile(p, re.IGNORECASE) for p in INDEPENDENCE_ATTEMPT_PATTERNS]


def attempts_reasoning(text: str) -> bool:
    """Frozen regex-primary independence detector (§9.3). True iff the student
    turn contains an algebraic expression or a numerical computation."""
    text = text or ""
    return any(r.search(text) for r in _ATTEMPT_RE)


# The rubric the LLM-verification pass applies. The judge sees ONLY a student turn
# and this rubric -- never the canonical answer. Released in the supplement.
INDEPENDENCE_RUBRIC_TEXT = (
    "A student turn ATTEMPTED a reasoning step if it contains the student's own "
    "mathematical work toward solving the problem: writing or manipulating an "
    "equation, performing an arithmetic computation, defining and combining "
    "variables, or carrying out an algebraic step. It did NOT attempt a reasoning "
    "step if it only asks for help, restates or paraphrases the problem, expresses "
    "confusion, or states a bare numeric guess with no supporting work. Judge only "
    "what THIS turn contains, not whether any value is correct."
)

INDEPENDENCE_JUDGE_SYSTEM = (
    "You are a careful annotator labeling whether a student's chat turn contains "
    "the student's own mathematical reasoning. Apply the rubric exactly. Do not try "
    "to solve the problem; do not consider correctness. Respond with a single JSON "
    "object and nothing else.\n\nRUBRIC:\n" + INDEPENDENCE_RUBRIC_TEXT
)
INDEPENDENCE_JUDGE_USER = (
    'Student turn:\n"""\n{turn}\n"""\n\n'
    'Did this turn attempt a reasoning step per the rubric? '
    'Reply as JSON: {{"attempted": true|false, "reason": "<short>"}}'
)


# ---------------------------------------------------------------- call helpers
def _tags(c: dict) -> dict:
    return c.get("tags") or {}


def _text(c: dict) -> str:
    return ((c.get("response") or {}).get("text") or "")


def _tokens(c: dict) -> int:
    u = c.get("usage") or {}
    return int(u.get("input_tokens", 0) or 0) + int(u.get("output_tokens", 0) or 0)


def load_calls(run_dir: str | Path) -> list[dict]:
    """Read one run's calls.jsonl into a list of records (seq-ordered)."""
    path = Path(run_dir) / "calls.jsonl"
    calls = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    calls.sort(key=lambda c: c.get("seq", 0))
    return calls


def resolve_problem_ids(calls: list[dict]) -> None:
    """Annotate each call with c['_pid'].

    Primary: the tags.problem_id written by the harness (student calls always carry
    it; tutor calls carry it after the Step-5 tag fix). Fallback for logs written
    BEFORE that fix: a tutor call inherits the problem_id of the most recent
    preceding call -- the student turn that opened the same problem (the interleave
    reconstruction the brief allows). Mutates the calls in place. Condition-neutral.
    """
    current: Optional[str] = None
    for c in calls:  # already seq-sorted by load_calls
        pid = _tags(c).get("problem_id")
        if pid:
            current = pid
        c["_pid"] = pid or current


def is_full_protocol(calls: list[dict]) -> bool:
    """True iff this run is a continuous-protocol session (protocol/full_session.py):
    it has student turns tagged student_train and/or student_probe. Legacy
    single-problem runs (experiments/run.py, ped_smoke dynamic) use the bare
    `student` component and have no phase structure, so they are NOT sessions for
    the metrics and should be excluded from the tables."""
    comps = {_tags(c).get("component") for c in calls if c.get("role") == "student"}
    return bool(comps & {STUDENT_TRAIN, STUDENT_PROBE})


def infer_condition(calls: list[dict]) -> str:
    """condition from (1) an explicit tags.condition if R1's runner set it, else
    (2) the tutor component actually exercised, else (3) cold (no tutor calls)."""
    tagged = {_tags(c).get("condition") for c in calls if _tags(c).get("condition")}
    if len(tagged) == 1:
        return next(iter(tagged))
    comps = {_tags(c).get("component") for c in calls if c.get("role") == "tutor"}
    if PED_COMPONENT in comps:
        return "ped"
    if CONV_COMPONENT in comps:
        return "conv"
    return "cold"


def infer_replicate_id(calls: list[dict]) -> str:
    """replicate_id from tags.replicate_id if present (R1's runner, Week 2), else
    the seed (the only stable per-run id today). Read as a string for tidy keys."""
    rids = {str(_tags(c).get("replicate_id")) for c in calls
            if _tags(c).get("replicate_id") is not None}
    if len(rids) == 1:
        return next(iter(rids))
    seeds = {str(c.get("seed")) for c in calls if c.get("seed") is not None}
    return next(iter(seeds)) if len(seeds) == 1 else (sorted(seeds)[0] if seeds else "NA")


# ---------------------------------------------------------------- visible turns
@dataclass
class VisibleTurn:
    """One student-visible tutor turn = what the student actually saw that turn.
    ConvTutor: its single call. PedTutor: the responder call (state_tracker is
    internal and excluded). Token/call counts cover ALL node calls of the turn."""
    problem_id: Optional[str]
    turn_index: Optional[int]
    text: str
    tutor_tokens: int       # sum over every node call this visible turn (§9.5)
    n_model_calls: int      # node calls this visible turn (PedTutor: >1)
    branch: Optional[str]
    first_seq: int
    last_seq: int


def visible_tutor_turns(calls: list[dict]) -> list[VisibleTurn]:
    groups: dict[tuple, list[dict]] = {}
    for c in calls:
        if c.get("role") != "tutor":
            continue
        if _tags(c).get("component") not in TUTOR_COMPONENTS:
            continue
        key = (c.get("_pid"), _tags(c).get("turn_index"))
        groups.setdefault(key, []).append(c)

    out: list[VisibleTurn] = []
    for (pid, ti), g in groups.items():
        g.sort(key=lambda c: c.get("seq", 0))
        # The responder is what the student saw: a PedTutor responder node, or the
        # single ConvTutor call. state_tracker (internal) is never the visible turn.
        responders = [c for c in g
                      if _tags(c).get("node") in RESPONDER_NODES
                      or _tags(c).get("component") == CONV_COMPONENT]
        resp = responders[-1] if responders else g[-1]
        out.append(VisibleTurn(
            problem_id=pid, turn_index=ti, text=_text(resp),
            tutor_tokens=sum(_tokens(c) for c in g),
            n_model_calls=len(g), branch=_tags(resp).get("branch"),
            first_seq=g[0].get("seq", 0), last_seq=g[-1].get("seq", 0),
        ))
    out.sort(key=lambda v: v.first_seq)
    return out


# ---------------------------------------------------------------- student turns
def student_turns(calls: list[dict], components: Iterable[str]) -> list[dict]:
    comps = set(components)
    rows = [c for c in calls
            if c.get("role") == "student" and _tags(c).get("component") in comps]
    rows.sort(key=lambda c: c.get("seq", 0))
    return rows


# ---------------------------------------------------------------- answer-phase window
# FROZEN 2026-06-19 (metric-amendment-2026-06-19.md, post-pilot / pre-confirmatory). Every
# turn-level metric (leakage, independence, helpfulness) is computed only over the answer
# phase of each TRAINING problem: the tutoring up to the student's first committed answer.
# Post-resolution turns (e.g. ConvTutor's motivational filler) are not tutoring and are
# excluded. Applied identically to ConvTutor and PedTutor.
def commit_seqs(calls: list[dict]) -> dict:
    """Per training problem, the seq of the FIRST student_train turn that commits an answer
    under the frozen `FINAL ANSWER:` extractor (§9.1). A turn with no marker is not a commit
    (conservative). Problems with no in-training commit are absent -> full window for them."""
    out: dict = {}
    for c in student_turns(calls, (STUDENT_TRAIN,)):
        pid, seq = c.get("_pid"), c.get("seq")
        if pid is None or seq is None:
            continue
        if extract_final_answer(_text(c)) is None:
            continue
        if pid not in out or seq < out[pid]:
            out[pid] = seq
    return out


def tutor_in_window(commit_seq: Optional[dict], problem_id, first_seq: int) -> bool:
    """A visible tutor turn is in the answer phase iff it occurred BEFORE the student's
    commit (first_seq < commit). No commit for the problem -> full window (True)."""
    c = (commit_seq or {}).get(problem_id)
    return c is None or first_seq < c


def student_in_window(commit_seq: Optional[dict], problem_id, seq: int) -> bool:
    """A student training turn is in the answer phase iff seq <= commit (up to and including
    the commit turn). No commit -> full window (True)."""
    c = (commit_seq or {}).get(problem_id)
    return c is None or seq <= c


# ---------------------------------------------------------------- metric 1: accuracy
def accuracy_items(calls: list[dict], problems_by_id: dict) -> list[dict]:
    """Per scored-probe item: the committed final answer and its correctness.

    The committed value is taken from the LAST probe/commit turn for the problem,
    which reproduces protocol/full_session.py's returned `final` exactly: a probe
    that parsed has only its probe turn; an unparsed probe is followed by the forced
    commit (+ one retry), whose last turn is what the protocol commits."""
    turns_by_pid: dict[Optional[str], list[dict]] = {}
    for c in student_turns(calls, (STUDENT_PROBE, STUDENT_COMMIT)):
        turns_by_pid.setdefault(c.get("_pid"), []).append(c)

    rows = []
    for pid, turns in turns_by_pid.items():
        prob = problems_by_id.get(pid)
        if prob is None or prob.role not in SCORED_PHASES:
            continue
        final = extract_final_answer(_text(turns[-1]))
        rows.append({
            "problem_id": pid, "role": prob.role,
            "final_answer": final,
            "correct": bool(is_correct(final, prob.canonical_answer)),
        })
    return rows


def accuracy_by_role(acc_items: list[dict]) -> dict[str, Optional[float]]:
    out: dict[str, Optional[float]] = {}
    for role in SCORED_PHASES:
        xs = [a["correct"] for a in acc_items if a["role"] == role]
        out[role] = (sum(xs) / len(xs)) if xs else None
    return out


# ---------------------------------------------------------------- metric 2: leakage
def leakage_items(visible_turns: list[VisibleTurn], problems_by_id: dict,
                  commit_seq: Optional[dict] = None) -> list[dict]:
    """Per visible TRAINING tutor turn: does the student-visible text leak the
    answer (frozen matcher)? Probes are untutored, so they have no tutor turns.
    `commit_seq` (the answer-phase window) restricts to turns before the student's
    commit; None = full window."""
    rows = []
    for v in visible_turns:
        prob = problems_by_id.get(v.problem_id)
        if prob is None or prob.role != TRAINING_PHASE:
            continue
        if not tutor_in_window(commit_seq, v.problem_id, v.first_seq):
            continue
        lk = prob.leakage or {}
        leaks = turn_leaks(v.text, lk.get("numeric_form", []), lk.get("solution_form", []))
        rows.append({
            "problem_id": v.problem_id, "turn_index": v.turn_index,
            "leaks": bool(leaks), "tutor_tokens": v.tutor_tokens,
            "n_model_calls": v.n_model_calls, "branch": v.branch,
            "first_seq": v.first_seq, "last_seq": v.last_seq,
        })
    return rows


def _rate(flags: list[bool]) -> Optional[float]:
    return (sum(1 for f in flags if f) / len(flags)) if flags else None


# ---------------------------------------------------------------- metric 3: independence
def independence_items(calls: list[dict], commit_seq: Optional[dict] = None) -> list[dict]:
    """Per student TRAINING turn: did it attempt a reasoning step (frozen regex)?
    `commit_seq` (the answer-phase window) restricts to turns up to and including the
    student's commit; None = full window."""
    rows = []
    for c in student_turns(calls, (STUDENT_TRAIN,)):
        if not student_in_window(commit_seq, c.get("_pid"), c.get("seq")):
            continue
        txt = _text(c)
        rows.append({
            "problem_id": c.get("_pid"), "seq": c.get("seq"),
            "text": txt, "attempt": attempts_reasoning(txt),
        })
    return rows


def next_turn_independence(visible_turns: list[VisibleTurn],
                           indep_items: list[dict]) -> dict[tuple, Optional[bool]]:
    """For each visible tutor turn, did the FOLLOWING student training turn attempt
    a step (J2 input)? Pairs by problem and seq: the student turn with the smallest
    seq greater than the tutor turn's last call."""
    by_problem: dict[Optional[str], list[dict]] = {}
    for t in indep_items:
        by_problem.setdefault(t["problem_id"], []).append(t)
    for v in by_problem.values():
        v.sort(key=lambda r: (r["seq"] is None, r["seq"]))

    res: dict[tuple, Optional[bool]] = {}
    for vt in visible_turns:
        cand = [t for t in by_problem.get(vt.problem_id, [])
                if t["seq"] is not None and t["seq"] > vt.last_seq]
        res[(vt.problem_id, vt.turn_index)] = cand[0]["attempt"] if cand else None
    return res


# ---------------------------------------------------------------- metric 5: cost
def cost_accounting(calls: list[dict], n_visible_turns: int) -> dict:
    """Per-session cost/effort (§9.5). Counts the EXPERIMENT's calls (tutor +
    student) only; any post-hoc judge calls are measurement, not experiment cost,
    and are excluded. For PedTutor n_model_calls exceeds visible turns because each
    visible turn is state_tracker + one responder."""
    tutor = [c for c in calls if c.get("role") == "tutor"]
    student = [c for c in calls if c.get("role") == "student"]
    in_tok = sum(int((c.get("usage") or {}).get("input_tokens", 0) or 0) for c in tutor + student)
    out_tok = sum(int((c.get("usage") or {}).get("output_tokens", 0) or 0) for c in tutor + student)
    return {
        "visible_tutor_turns": n_visible_turns,
        "student_turns": len(student),
        "n_model_calls": len(tutor) + len(student),
        "tutor_tokens": sum(_tokens(c) for c in tutor),
        "student_tokens": sum(_tokens(c) for c in student),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "total_tokens": in_tok + out_tok,
    }


# ---------------------------------------------------------------- session object
@dataclass
class SessionMetrics:
    run_id: str
    run_dir: str
    condition: str
    replicate_id: str
    seed: Optional[int]
    backend: str
    visible_turns: list[VisibleTurn]
    acc_items: list[dict]
    leak_items: list[dict]
    indep_items: list[dict]
    next_indep: dict[tuple, Optional[bool]]
    cost: dict
    commit_seq: dict = field(default_factory=dict)   # answer-phase window (per training pid)

    @property
    def leakage_rate(self) -> Optional[float]:
        return _rate([r["leaks"] for r in self.leak_items])

    @property
    def independence_ratio(self) -> Optional[float]:
        return _rate([r["attempt"] for r in self.indep_items])

    @property
    def accuracy(self) -> dict[str, Optional[float]]:
        return accuracy_by_role(self.acc_items)


def analyze_session(run_dir: str | Path, problems_by_id: dict,
                    condition_override: Optional[str] = None,
                    answer_phase: bool = True) -> SessionMetrics:
    """`answer_phase=True` (the frozen default, metric-amendment-2026-06-19.md) computes
    leakage / independence / helpfulness only over the answer-phase window; False reverts to
    the full-window behavior (full transcript) for the sensitivity / disclosure view. Cost and
    accuracy are never windowed (cost is total compute spent; accuracy is over probes)."""
    calls = load_calls(run_dir)
    resolve_problem_ids(calls)
    condition = condition_override or infer_condition(calls)
    replicate_id = infer_replicate_id(calls)
    seeds = {c.get("seed") for c in calls if c.get("seed") is not None}
    seed = next(iter(seeds)) if len(seeds) == 1 else None
    backends = {c.get("backend") for c in calls if c.get("backend")}
    backend = next(iter(backends)) if len(backends) == 1 else ("mixed" if backends else "unknown")

    cseq = commit_seqs(calls) if answer_phase else {}
    vts = visible_tutor_turns(calls)
    acc = accuracy_items(calls, problems_by_id)
    leak = leakage_items(vts, problems_by_id, cseq)
    indep = independence_items(calls, cseq)
    nxt = next_turn_independence(vts, indep)
    cost = cost_accounting(calls, n_visible_turns=len(vts))

    run_id = calls[0].get("run_id", Path(run_dir).name) if calls else Path(run_dir).name
    return SessionMetrics(
        run_id=run_id, run_dir=str(run_dir), condition=condition,
        replicate_id=replicate_id, seed=seed, backend=backend, visible_turns=vts,
        acc_items=acc, leak_items=leak, indep_items=indep, next_indep=nxt, cost=cost,
        commit_seq=cseq,
    )


# ---------------------------------------------------------------- tidy tables (J2 scaffolding)
def per_turn_rows(sm: SessionMetrics,
                  helpfulness: Optional[dict] = None,
                  pedagogy: Optional[dict] = None) -> list[dict]:
    """One row per TRAINING tutor turn. `helpfulness` is the Step-6 judge fill: a
    map {(problem_id, turn_index): per-turn helpfulness mean}; None (the default)
    leaves the reserved column empty, exactly as before Step 6. `pedagogy` is the
    analogous fill for the pedagogical-quality judge EXTENSION (decisions-log
    2026-06-27), same map shape; None leaves its reserved column empty too."""
    hmap = helpfulness or {}
    pmap = pedagogy or {}
    by_key = {(r["problem_id"], r["turn_index"]): r for r in sm.leak_items}
    rows = []
    for v in sm.visible_turns:
        key = (v.problem_id, v.turn_index)
        if key not in by_key:   # leak_items already restricts to training turns
            continue
        rows.append({
            "condition": sm.condition,
            "replicate_id": sm.replicate_id,
            "problem_id": v.problem_id,
            "turn_index": v.turn_index,
            "leaks": by_key[key]["leaks"],
            "helpfulness": hmap.get(key),              # filled in Step 6 (judge)
            "pedagogy": pmap.get(key),                 # filled by the pedagogy judge (extension)
            "next_turn_independence": sm.next_indep.get(key),
            "n_model_calls": v.n_model_calls,
            "tutor_tokens": v.tutor_tokens,
            "branch": v.branch,
        })
    return rows


def _per_1k(n: Optional[float], tutor_tokens: int) -> Optional[float]:
    if n is None or not tutor_tokens:
        return None
    return n / (tutor_tokens / 1000.0)


def per_session_row(sm: SessionMetrics,
                    helpfulness_mean: Optional[float] = None,
                    pedagogy_mean: Optional[float] = None) -> dict:
    acc = sm.accuracy
    tutor_tokens = sm.cost["tutor_tokens"]
    n_leaky = sum(1 for r in sm.leak_items if r["leaks"])
    n_indep = sum(1 for r in sm.indep_items if r["attempt"])
    n_correct = sum(1 for a in sm.acc_items if a["correct"])
    return {
        "condition": sm.condition,
        "replicate_id": sm.replicate_id,
        "seed": sm.seed,
        "run_id": sm.run_id,
        "backend": sm.backend,
        "leakage_rate": sm.leakage_rate,
        "independence_ratio": sm.independence_ratio,
        "helpfulness_mean": helpfulness_mean,          # filled in Step 6 (judge)
        "pedagogy_mean": pedagogy_mean,                # filled by the pedagogy judge (extension)
        "acc_immediate": acc["immediate"],
        "acc_delayed": acc["delayed"],
        "acc_transfer": acc["transfer"],
        "n_train_tutor_turns": len(sm.leak_items),
        "n_train_student_turns": len(sm.indep_items),
        "visible_tutor_turns": sm.cost["visible_tutor_turns"],
        "student_turns": sm.cost["student_turns"],
        "n_model_calls": sm.cost["n_model_calls"],
        "tutor_tokens": tutor_tokens,
        "student_tokens": sm.cost["student_tokens"],
        "input_tokens": sm.cost["input_tokens"],
        "output_tokens": sm.cost["output_tokens"],
        "total_tokens": sm.cost["total_tokens"],
        # cost-normalized view (§10 sensitivity): outcomes per 1k tutor tokens
        "leaky_turns_per_1k_tutor_tok": _per_1k(n_leaky, tutor_tokens),
        "independent_turns_per_1k_tutor_tok": _per_1k(n_indep, tutor_tokens),
        "correct_probes_per_1k_tutor_tok": _per_1k(n_correct, tutor_tokens),
    }


def _mean(xs: list[Optional[float]]) -> Optional[float]:
    vals = [x for x in xs if x is not None]
    return (sum(vals) / len(vals)) if vals else None


def per_replicate_rows(sessions: list[SessionMetrics],
                       helpfulness_by_run: Optional[dict] = None,
                       pedagogy_by_run: Optional[dict] = None) -> list[dict]:
    """One row per (condition, replicate_id) -- the unit of the primary tests
    (§10). With one session per (condition, replicate_id) this is the session row;
    if several sessions share a key they are averaged. `helpfulness_by_run` is the
    Step-6 fill: {run_id: per-session helpfulness_mean}; None leaves it empty so the
    averaged helpfulness_mean column stays None, as before Step 6. `pedagogy_by_run`
    is the analogous fill for the pedagogical-quality judge EXTENSION."""
    hmap = helpfulness_by_run or {}
    pmap = pedagogy_by_run or {}
    groups: dict[tuple, list[SessionMetrics]] = {}
    for sm in sessions:
        groups.setdefault((sm.condition, sm.replicate_id), []).append(sm)

    rows = []
    for (cond, rid), sms in sorted(groups.items()):
        srows = [per_session_row(sm, hmap.get(sm.run_id), pmap.get(sm.run_id)) for sm in sms]
        backends = sorted({sm.backend for sm in sms})
        agg = {"condition": cond, "replicate_id": rid, "n_sessions": len(sms),
               "backend": backends[0] if len(backends) == 1 else ",".join(backends)}
        for k in ("leakage_rate", "independence_ratio", "helpfulness_mean", "pedagogy_mean",
                  "acc_immediate", "acc_delayed", "acc_transfer",
                  "tutor_tokens", "total_tokens", "n_model_calls",
                  "visible_tutor_turns"):
            agg[k] = _mean([r[k] for r in srows])
        rows.append(agg)
    return rows


# ---------------------------------------------------------------- independence LLM-verify (§9.3)
@dataclass
class IndependenceVerify:
    rows: list[dict]                 # {problem_id, seq, regex, llm, agree, final}
    n_total: int
    n_judged: int
    n_disagree: int
    agreement_rate: Optional[float]
    disagreements: list[dict]


def reconcile(regex_result: bool, llm_result: Optional[bool]) -> dict:
    """Combine the frozen-regex result with the LLM verdict. The regex is
    AUTHORITATIVE (§9.3): `final` is always the regex result. The LLM pass is a
    documented robustness check; disagreements are recorded, never an override."""
    agree = None if llm_result is None else (llm_result == regex_result)
    return {"regex": regex_result, "llm": llm_result, "agree": agree,
            "final": regex_result}


def verify_independence(indep_items: list[dict],
                        judge_fn: Callable[[str], Optional[bool]]) -> IndependenceVerify:
    """Run the LLM-verification pass over student training turns. `judge_fn(text)`
    returns the model's attempted/not verdict (True/False) or None if unparseable.
    Disagreements default to the regex result and are logged (§9.3)."""
    rows, disagreements = [], []
    n_judged = n_disagree = 0
    for t in indep_items:
        r = bool(t["attempt"])
        verdict = judge_fn(t["text"])
        rec = reconcile(r, verdict)
        rec.update({"problem_id": t["problem_id"], "seq": t["seq"]})
        rows.append(rec)
        if verdict is not None:
            n_judged += 1
            if rec["agree"] is False:
                n_disagree += 1
                disagreements.append({"problem_id": t["problem_id"], "seq": t["seq"],
                                      "regex": r, "llm": verdict,
                                      "text": (t["text"] or "")[:300]})
    agreement = ((n_judged - n_disagree) / n_judged) if n_judged else None
    return IndependenceVerify(rows, len(indep_items), n_judged, n_disagree,
                              agreement, disagreements)


def parse_attempted(text: str) -> Optional[bool]:
    """Parse the judge's reply into True/False/None. Accepts the JSON `attempted`
    field or a bare yes/no/true/false."""
    if not text:
        return None
    m = re.search(r'attempted"?\s*[:=]\s*"?(true|false|yes|no)', text, re.IGNORECASE)
    if m:
        return m.group(1).lower() in ("true", "yes")
    m = re.search(r'\b(true|false|yes|no)\b', text, re.IGNORECASE)
    if m:
        return m.group(1).lower() in ("true", "yes")
    return None


def make_judge_fn(client, seed: int = 0) -> Callable[[str], Optional[bool]]:
    """An Opus (role='judge') judge_fn for verify_independence. The prompt contains
    ONLY the student turn and the frozen rubric -- never canonical_answer."""
    def judge_fn(turn_text: str) -> Optional[bool]:
        comp = client.complete(
            role="judge",
            system=INDEPENDENCE_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": INDEPENDENCE_JUDGE_USER.format(turn=turn_text)}],
            seed=seed,
            tags={"component": "independence_verify"},
        )
        return parse_attempted(comp.text)
    return judge_fn


# ---------------------------------------------------------------- problem index
def problem_index(domain_path: str = "domain/algebra/problems.yaml") -> dict:
    """id -> Problem (role, canonical_answer, leakage, ...), via the reused loader."""
    return {p.id: p for p in load_problems(domain_path)}
