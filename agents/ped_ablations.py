"""PedTutor structural-ablation variants (#5 ablations; decisions-log.md 2026-06-30).

ADDITIVE, DESCRIPTIVE node-drop variants of the frozen PedTutor. The frozen agent
(`agents/ped_tutor.py`) and its prompts/routing (`configs/ped_full.yaml`) are NOT
edited and stay byte-stable: `PedTutorVariant` SUBCLASSES `PedTutor` and overrides
ONLY graph construction (`_build_graph`). Everything else — the deterministic signals,
the per-node scoped prompts, the `branch` stamping, the per-turn cost accounting, and
the `respond()` entry point — is inherited UNCHANGED. So a variant differs from the
full agent in exactly one way: which node(s) the compiled graph contains and how the
deterministic router's orphaned route lands.

Each variant is declared in a thin `configs/ped_{variant}.yaml` that sources all prompts
and routing from the frozen `base_config` (ped_full.yaml) and declares only the structural
manipulation. The three pre-registered variants (the spec is frozen in decisions-log.md
2026-06-30, BEFORE any live run):

  variant      drop          graph change                                  per-turn calls
  -----------  ------------  --------------------------------------------  --------------
  no_gate      deferral_gate route "defer"  -> decomposer (retained)        2  (unchanged)
  no_cascade   hint_cascade  route "hint"   -> decomposer (retained)        2  (unchanged)
  no_tracker   state_tracker START routes directly to the responder;        1  (one fewer:
                             responders get the empty assessment fallback     state_tracker
                             "(planner produced no structured estimate)")      dropped)

Faithfulness rules (enforced by `_validate` + tools/test_ped_ablations.py):
  - The dropped node's model call NEVER happens and the graph never enters it (it is
    genuinely absent, not stubbed or re-implemented elsewhere).
  - Each orphaned route value lands on a RETAINED responder that metrics.py recognizes
    (deferral_gate / decomposer / hint_cascade = metrics.RESPONDER_NODES) — no new
    visible-responder tag is introduced.
  - `branch` keeps its ORIGINAL deterministic route value (inherited, unchanged): a
    rerouted "defer" turn handled by the decomposer still carries branch="defer". The
    realized responder is recoverable from the call's `node` tag.

Nothing here is tuned toward an outcome. "No node collapses the leakage/independence
separation" is an explicitly allowed, fully-reportable result.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .config import load_yaml
from .model_client import ModelClient
from .ped_tutor import PedState, PedTutor

# The full graph's route-value -> handling-node map (mirrors PedTutor._route +
# PedTutor._build_graph). The three responders are exactly metrics.RESPONDER_NODES.
_BASE_ROUTE = {"defer": "deferral_gate", "decompose": "decomposer", "hint": "hint_cascade"}
_RESPONDERS = ("deferral_gate", "decomposer", "hint_cascade")
_ALL_NODES = ("state_tracker",) + _RESPONDERS
_VARIANTS = {  # variant name -> the node it drops (the single source of truth)
    "no_gate": "deferral_gate",
    "no_cascade": "hint_cascade",
    "no_tracker": "state_tracker",
}


class PedTutorVariant(PedTutor):
    """A PedTutor with one node removed. `config_path` points at a thin variant config
    (configs/ped_{variant}.yaml) that names the frozen base config + the manipulation."""

    def __init__(self, client: ModelClient, config_path: str):
        vcfg = load_yaml(config_path)
        self.variant = vcfg.get("variant")
        self.drop_node = vcfg.get("drop_node")
        self.reroute = dict(vcfg.get("reroute") or {})
        self.new_entry = vcfg.get("new_entry")
        self.assessment_fallback = vcfg.get("assessment_fallback", "")
        base_config = vcfg.get("base_config")
        if not base_config:
            raise ValueError(f"{config_path}: ablation config must name a frozen `base_config`")
        self._validate(config_path)
        # Load the frozen base (prompts + routing) UNCHANGED; super().__init__ ends by
        # calling self._build_graph() (overridden below), which reads the fields set above.
        super().__init__(client, config_path=base_config)
        self.name = f"ped_{self.variant}"

    # ------------------------------------------------------------- validation
    def _validate(self, config_path: str) -> None:
        """Fail loudly on any malformed / placeholder variant spec (a surviving angle-bracket
        placeholder would not match these membership checks). Enforces the pre-registered remap
        rules so the code can never silently diverge from the frozen spec."""
        if self.variant not in _VARIANTS:
            raise ValueError(
                f"{config_path}: variant={self.variant!r} must be one of {sorted(_VARIANTS)}")
        if self.drop_node != _VARIANTS[self.variant]:
            raise ValueError(
                f"{config_path}: variant {self.variant!r} must drop "
                f"{_VARIANTS[self.variant]!r}, not {self.drop_node!r}")
        if self.drop_node == "state_tracker":
            # Entry/planner drop: no responder reroute; the pinned fallback is the empty
            # assessment (rendered by format_assessment as the no-estimate string).
            if self.reroute:
                raise ValueError(
                    f"{config_path}: no_tracker drops the entry node, not a responder; it "
                    f"must not declare a `reroute` (got {self.reroute!r})")
            if self.assessment_fallback != "":
                raise ValueError(
                    f"{config_path}: no_tracker assessment_fallback is pinned to \"\" "
                    f"(the empty assessment); got {self.assessment_fallback!r}")
            if self.new_entry != "route":
                raise ValueError(
                    f"{config_path}: no_tracker new_entry is pinned to 'route' "
                    f"(START routes directly to the responder); got {self.new_entry!r}")
        else:
            # Responder drop: exactly the route value(s) that pointed at the dropped node
            # must be rerouted, each onto a RETAINED responder (a recognized visible tag).
            orphan_keys = {k for k, v in _BASE_ROUTE.items() if v == self.drop_node}
            if set(self.reroute) != orphan_keys:
                raise ValueError(
                    f"{config_path}: reroute keys {sorted(self.reroute)} must be exactly the "
                    f"orphaned route value(s) {sorted(orphan_keys)} of the dropped "
                    f"{self.drop_node!r}")
            for k, tgt in self.reroute.items():
                if tgt not in _RESPONDERS or tgt == self.drop_node:
                    raise ValueError(
                        f"{config_path}: reroute {k!r}->{tgt!r} must land on a RETAINED "
                        f"responder in {_RESPONDERS} (not the dropped node, not a new tag)")

    # ----------------------------------------------------------------- graph
    def _build_graph(self):
        """Build the variant graph. The default (full) graph is NEVER built here; the
        frozen PedTutor._build_graph is untouched and produces it for the primary `ped`."""
        node_fns = {
            "state_tracker": self._state_tracker,
            "deferral_gate": self._deferral_gate,
            "decomposer": self._decomposer,
            "hint_cascade": self._hint_cascade,
        }
        g = StateGraph(PedState)

        if self.drop_node == "state_tracker":
            # Drop the entry/planner: responders are the entry. assessment stays the
            # respond()-initialized "" (the pinned empty fallback) since no node sets it.
            for n in _RESPONDERS:
                g.add_node(n, node_fns[n])
            g.set_conditional_entry_point(self._route, dict(_BASE_ROUTE))
            for n in _RESPONDERS:
                g.add_edge(n, END)
        else:
            # Drop a responder: keep state_tracker; reroute the orphaned route value(s)
            # onto the retained responder; the dropped node is absent from the graph.
            route_map = dict(_BASE_ROUTE)
            route_map.update(self.reroute)
            retained = [n for n in _RESPONDERS if n != self.drop_node]
            g.add_node("state_tracker", node_fns["state_tracker"])
            for n in retained:
                g.add_node(n, node_fns[n])
            g.add_edge(START, "state_tracker")
            g.add_conditional_edges("state_tracker", self._route, route_map)
            for n in retained:
                g.add_edge(n, END)
        return g.compile()
