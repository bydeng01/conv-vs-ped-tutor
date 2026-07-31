"""ConvTutor: a single-node LangGraph. One model call per turn.

The system prompt is read from configs/conv_tutor.yaml and is deliberately
minimal and realistic. It is NOT engineered to be weak or to refuse answering;
any tendency to give away answers is the phenomenon under study (build brief).
The verbatim prompt is mirrored in supplement/prompts.md.
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .base import mock_meta_for, tutor_message_view
from .config import load_yaml
from .model_client import ModelClient
from .state import Problem, Turn


class ConvState(TypedDict):
    messages: list[dict[str, str]]
    system: str
    seed: int
    turn_index: int
    problem_id: str
    mock_meta: dict[str, Any]
    reply_text: str
    reply_tokens: int


class ConvTutor:
    name = "conv"

    def __init__(self, client: ModelClient, config_path: str = "configs/conv_tutor.yaml"):
        self.client = client
        cfg = load_yaml(config_path)
        self.system_prompt = cfg["system_prompt"].strip()
        self.max_turns_per_problem = cfg.get("max_turns_per_problem", 8)
        self._graph = self._build_graph()

    # Single node: call the base model once and emit the reply.
    def _respond_node(self, state: ConvState) -> ConvState:
        comp = self.client.complete(
            role="tutor",
            system=state["system"],
            messages=state["messages"],
            seed=state["seed"],
            tags={"component": "conv_tutor", "turn_index": state["turn_index"],
                  "problem_id": state["problem_id"]},
            mock_meta=state["mock_meta"],
        )
        state["reply_text"] = comp.text
        state["reply_tokens"] = comp.input_tokens + comp.output_tokens
        return state

    def _build_graph(self):
        g = StateGraph(ConvState)
        g.add_node("respond", self._respond_node)
        g.add_edge(START, "respond")
        g.add_edge("respond", END)
        return g.compile()

    def respond(self, transcript: list[Turn], problem: Problem, seed: int, turn_index: int) -> Turn:
        # The tutor sees the problem it is tutoring (condition-neutral; PedTutor
        # nodes get the same). Without this the tutor only sees the student's
        # messages and may not know the problem at all.
        system = (self.system_prompt
                  + "\n\nThe student is working on this problem:\n"
                  + problem.prompt.strip())
        state: ConvState = {
            "messages": tutor_message_view(transcript),
            "system": system,
            "seed": seed,
            "turn_index": turn_index,
            "problem_id": problem.id,
            "mock_meta": mock_meta_for(problem, turn_index, tutored=True),
            "reply_text": "",
            "reply_tokens": 0,
        }
        out = self._graph.invoke(state)
        # n_model_calls is recorded for parity with PedTutor's per-turn cost
        # accounting (ConvTutor always makes exactly one model call per turn).
        return Turn(speaker="tutor", text=out["reply_text"],
                    meta={"tokens": out["reply_tokens"], "n_model_calls": 1})
