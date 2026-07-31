"""PedTutor: a multi-node LangGraph over the SAME base model as ConvTutor.

ConvTutor is one node and one model call per turn. PedTutor keeps the same model
(read from configs/models.yaml) and the same respond() interface, and changes only
the control flow and the scoped prompts. Per visible turn:

    state_tracker (always; internal, never shown to the student)
        -> route on deterministic signals ->
    exactly one of { deferral_gate | decomposer | hint_cascade } writes the reply.

Each node is a separate, scoped call to role="tutor", so every call is logged by
ModelClient. The tokens of every node call this turn are summed into the returned
Turn's meta (cost accounting, paper-plan.md §9.5).

Node -> principle:
    state_tracker  contingent tutoring     (Wood, Bruner & Ross 1976)
    decomposer     assistance dilemma      (Koedinger & Aleven 2007)
    deferral_gate  generation effect       (Slamecka & Graf 1978)
                   retrieval practice      (Karpicke & Roediger 2008)
    hint_cascade   help-seeking            (Aleven et al. 2006)

The deferral_gate is the highest-leverage node: it fires when the student asks for
the answer and refuses to give it, requiring the student's own attempts first. The
"at least 2 attempts" threshold is counted deterministically from the transcript
(not judged by the model) so it is auditable and cannot be talked around. PedTutor
never puts canonical_answer in any prompt, and never states the final answer at
all (generation effect) -- the low leakage / high independence this produces is a
consequence of the principles, not of tuning against the metrics.
"""
from __future__ import annotations

import json
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .base import mock_meta_for, tutor_message_view
from .config import load_yaml
from .model_client import ModelClient
from .state import Problem, Turn


# ------------------------------------------------------------------ signals
# Pure, deterministic reads of the dialogue. Kept module-level so they can be
# unit-tested without a model. They take pre-compiled regex lists.

def last_student_text(transcript: list[Turn]) -> str:
    for t in reversed(transcript):
        if t.speaker == "student":
            return t.text or ""
    return ""


def is_attempt(text: str, attempt_res: list[re.Pattern]) -> bool:
    return any(r.search(text or "") for r in attempt_res)


def is_answer_request(text: str, ask_res: list[re.Pattern]) -> bool:
    return any(r.search(text or "") for r in ask_res)


def count_attempts(transcript: list[Turn], attempt_res: list[re.Pattern]) -> int:
    return sum(1 for t in transcript
               if t.speaker == "student" and is_attempt(t.text, attempt_res))


def count_prior_tutor_turns(transcript: list[Turn]) -> int:
    return sum(1 for t in transcript if t.speaker == "tutor")


def _parse_assessment(text: str) -> dict:
    """Best-effort parse of the state_tracker's JSON line. The deterministic
    signals do not depend on this; it only enriches the responder prompts, so a
    parse failure (e.g. the offline mock, which is not a real planner) degrades
    gracefully to an empty estimate."""
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


# Only these planner fields are forwarded into a responder prompt. Forwarding the
# parsed fields (rather than the planner's raw text) bounds what can flow
# downstream to the state_tracker's intended estimate -- it cannot carry along an
# unrelated worked solution. (canonical_answer never reaches any prompt regardless;
# it is only ever in mock_meta, which the live backend ignores.)
_ASSESSMENT_FIELDS = ("demonstrated", "missing", "stuck", "progressed")


def format_assessment(raw: str) -> str:
    obj = _parse_assessment(raw)
    if not obj:
        return "(planner produced no structured estimate)"
    parts = [f"{k}: {obj[k]}" for k in _ASSESSMENT_FIELDS if k in obj]
    return "; ".join(parts) if parts else "(planner produced no structured estimate)"


# -------------------------------------------------------------------- state
class PedState(TypedDict):
    messages: list[dict[str, str]]
    problem: Any           # the Problem being tutored (not serialized; mock-only fields aside)
    problem_prompt: str
    seed: int
    turn_index: int
    mock_meta: dict[str, Any]
    # deterministic signals (precomputed in respond())
    attempts: int
    asked: bool
    reveal_allowed: bool
    hint_level: int
    # node outputs / accounting
    assessment: str
    reply_text: str
    branch: str
    total_tokens: int
    n_calls: int
    nodes_run: list[str]


class PedTutor:
    name = "ped"

    def __init__(self, client: ModelClient, config_path: str = "configs/ped_full.yaml"):
        self.client = client
        cfg = load_yaml(config_path)
        self.max_turns_per_problem = cfg.get("max_turns_per_problem", 8)

        nodes = cfg["nodes"]
        self.p_state = nodes["state_tracker"]["system_prompt"].strip()
        self.p_defer = nodes["deferral_gate"]["system_prompt"].strip()
        self.p_decompose = nodes["decomposer"]["system_prompt"].strip()
        self.p_hint = nodes["hint_cascade"]["system_prompt"].strip()

        r = cfg["routing"]
        self.min_attempts = int(r["min_attempts_before_reveal"])
        self.level_names = list(r["hint_level_names"])
        self.directives = r["directives"]
        flags = re.IGNORECASE
        self.attempt_res = [re.compile(p, flags) for p in r["attempt_patterns"]]
        self.ask_res = [re.compile(p, flags) for p in r["answer_request_patterns"]]

        self._graph = self._build_graph()

    # --------------------------------------------------------------- prompts
    def _with_problem(self, node_system: str, problem: Problem) -> str:
        # Same condition-neutral "tutor sees the problem" injection ConvTutor uses.
        return (node_system
                + "\n\nThe student is working on this problem:\n"
                + problem.prompt.strip())

    def _responder_system(self, node_system: str, problem: Problem,
                          state: PedState, directive: str) -> str:
        assessment = format_assessment(state["assessment"])
        progressed = bool(_parse_assessment(state["assessment"]).get("progressed", False))
        progress_note = self.directives["progress_note"].format(progressed=progressed)
        return (
            self._with_problem(node_system, problem)
            + "\n\nINTERNAL ASSESSMENT (private planning notes; do NOT reveal or "
              "quote any of this to the student):\n" + assessment.strip()
            + "\n\n" + progress_note.strip()
            + "\n" + directive.strip()
        )

    # ----------------------------------------------------------------- calls
    def _call(self, system: str, state: PedState, node: str) -> str:
        comp = self.client.complete(
            role="tutor",
            system=system,
            messages=state["messages"],
            seed=state["seed"],
            tags={"component": "ped_tutor", "node": node,
                  "turn_index": state["turn_index"], "branch": state.get("branch", ""),
                  "problem_id": state["problem"].id},
            mock_meta=state["mock_meta"],
        )
        state["total_tokens"] += comp.input_tokens + comp.output_tokens
        state["n_calls"] += 1
        state["nodes_run"].append(node)
        return comp.text

    # ----------------------------------------------------------------- nodes
    def _state_tracker(self, state: PedState) -> PedState:
        problem = state["problem"]
        text = self._call(self._with_problem(self.p_state, problem), state, "state_tracker")
        state["assessment"] = text
        return state

    def _route(self, state: PedState) -> str:
        # Deterministic routing on the precomputed signals.
        if state["asked"]:
            return "defer"          # student demanded the answer -> deferral_gate
        if state["attempts"] == 0:
            return "decompose"      # stuck, no engagement yet -> break off a sub-step
        return "hint"               # engaging -> escalating hint cascade

    def _deferral_gate(self, state: PedState) -> PedState:
        directive = (self.directives["defer_at_threshold"] if state["reveal_allowed"]
                     else self.directives["defer_below_threshold"])
        system = self._responder_system(self.p_defer, state["problem"], state, directive)
        state["reply_text"] = self._call(system, state, "deferral_gate")
        return state

    def _decomposer(self, state: PedState) -> PedState:
        system = self._responder_system(self.p_decompose, state["problem"], state, "")
        state["reply_text"] = self._call(system, state, "decomposer")
        return state

    def _hint_cascade(self, state: PedState) -> PedState:
        # Specificity rises with documented failure (prior tutor turns), but the
        # concrete level stays locked until the attempt threshold is met -- that is
        # the deferral_gate's "earn it first" rule biting on the hint cascade too.
        level = min(state["hint_level"], len(self.level_names) - 1)
        if not state["reveal_allowed"]:
            level = min(level, 1)
        name = self.level_names[level]
        directive = self.directives["hint_level"].format(level=level, name=name)
        system = self._responder_system(self.p_hint, state["problem"], state, directive)
        state["reply_text"] = self._call(system, state, "hint_cascade")
        return state

    # ----------------------------------------------------------------- graph
    def _build_graph(self):
        g = StateGraph(PedState)
        g.add_node("state_tracker", self._state_tracker)
        g.add_node("deferral_gate", self._deferral_gate)
        g.add_node("decomposer", self._decomposer)
        g.add_node("hint_cascade", self._hint_cascade)
        g.add_edge(START, "state_tracker")
        g.add_conditional_edges("state_tracker", self._route, {
            "defer": "deferral_gate",
            "decompose": "decomposer",
            "hint": "hint_cascade",
        })
        g.add_edge("deferral_gate", END)
        g.add_edge("decomposer", END)
        g.add_edge("hint_cascade", END)
        return g.compile()

    # --------------------------------------------------------------- respond
    def respond(self, transcript: list[Turn], problem: Problem, seed: int, turn_index: int) -> Turn:
        # Deterministic signals from the dialogue so far.
        last = last_student_text(transcript)
        attempts = count_attempts(transcript, self.attempt_res)
        asked = is_answer_request(last, self.ask_res)
        hint_level = count_prior_tutor_turns(transcript)
        reveal_allowed = attempts >= self.min_attempts

        state: PedState = {
            "messages": tutor_message_view(transcript),
            "problem": problem,
            "problem_prompt": problem.prompt.strip(),
            "seed": seed,
            "turn_index": turn_index,
            "mock_meta": mock_meta_for(problem, turn_index, tutored=True),
            "attempts": attempts,
            "asked": asked,
            "reveal_allowed": reveal_allowed,
            "hint_level": hint_level,
            "assessment": "",
            "reply_text": "",
            "branch": "defer" if asked else ("decompose" if attempts == 0 else "hint"),
            "total_tokens": 0,
            "n_calls": 0,
            "nodes_run": [],
        }
        out = self._graph.invoke(state)
        return Turn(
            speaker="tutor",
            text=out["reply_text"],
            meta={
                # cost accounting: sum of ALL node calls this visible turn
                "tokens": out["total_tokens"],
                "n_model_calls": out["n_calls"],
                "nodes": out["nodes_run"],
                "branch": out["branch"],
                "attempts": out["attempts"],
                "reveal_allowed": out["reveal_allowed"],
                "hint_level": out["hint_level"],
                # internal planning estimate, logged for inspection; never shown
                # to the student (the student only receives `text`).
                "assessment": out["assessment"],
            },
        )
