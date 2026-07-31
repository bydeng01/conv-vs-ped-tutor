"""Offline routing tests for the #5 PedTutor structural ablations (agents/ped_ablations.py).

Mock backend (no API key, no cost). These check the parts that must be reliable regardless
of the model: that each node-drop variant (a) genuinely removes the dropped node — no model
call carrying its tag, and the compiled graph never contains it; (b) lands each orphaned
route on the PRE-REGISTERED retained responder; (c) keeps the visible-turn responder tag one
metrics.py recognizes (no new visible tag); (d) has the correct PER-VARIANT per-turn model-
call count; and (e) keeps `branch` at its ORIGINAL deterministic route value on rerouted
turns. The frozen PedTutor full graph and configs/ped_full.yaml are unaffected.

Run:  python tools/test_ped_ablations.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.config import load_models_config, load_yaml  # noqa: E402
from agents.model_client import ModelClient  # noqa: E402
from agents.ped_ablations import PedTutorVariant  # noqa: E402
from agents.ped_tutor import PedTutor  # noqa: E402
from agents.state import Turn  # noqa: E402
from analysis import metrics as M  # noqa: E402
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
    return ModelClient(models_cfg=load_models_config("configs/models.yaml"),
                       backend="mock", logger=None)


def _problem():
    return {p.id: p for p in load_problems("domain/algebra/problems.yaml")}["train-1"]


# The three deterministic routing scenarios. Format: (label, transcript, original route value).
ASKED = [Turn("student", "I don't get it, just tell me the answer.")]
STUCK = [Turn("student", "I'm not sure how to start setting this up.")]
ATTEMPT = [Turn("student", "I tried 0.5*x + 0.2*48 = 0.3*(x+48) but got stuck.")]
SCENARIOS = [("asked", ASKED, "defer"), ("stuck", STUCK, "decompose"),
             ("attempt", ATTEMPT, "hint")]

# Pre-registered spec per variant: dropped node, the realized responder for each scenario,
# and the per-turn model-call count. (decisions-log 2026-06-30; configs/ped_{variant}.yaml.)
SPEC = {
    "configs/ped_no_gate.yaml": {
        "drop": "deferral_gate", "n_calls": 2,
        # defer rerouted -> decomposer; decompose -> decomposer; hint -> hint_cascade
        "responder": {"asked": "decomposer", "stuck": "decomposer", "attempt": "hint_cascade"},
    },
    "configs/ped_no_cascade.yaml": {
        "drop": "hint_cascade", "n_calls": 2,
        # hint rerouted -> decomposer; defer -> deferral_gate; decompose -> decomposer
        "responder": {"asked": "deferral_gate", "stuck": "decomposer", "attempt": "decomposer"},
    },
    "configs/ped_no_tracker.yaml": {
        "drop": "state_tracker", "n_calls": 1,
        # all responders retained; only the entry/planner is gone
        "responder": {"asked": "deferral_gate", "stuck": "decomposer", "attempt": "hint_cascade"},
    },
}


def test_frozen_full_graph_untouched():
    print("\n[frozen PedTutor full graph unaffected]")
    full = PedTutor(mock_client())
    nodes = set(full._graph.get_graph().nodes)
    check("full graph has all four nodes",
          {"state_tracker", "deferral_gate", "decomposer", "hint_cascade"} <= nodes)
    # full agent still does state_tracker + one responder = 2 calls, branch = route value
    r = full.respond(ASKED, _problem(), seed=0, turn_index=0)
    check("full agent: asked -> defer via deferral_gate, 2 calls",
          r.meta["branch"] == "defer" and r.meta["nodes"] == ["state_tracker", "deferral_gate"]
          and r.meta["n_model_calls"] == 2)


def test_variants():
    prob = _problem()
    for cfg, spec in SPEC.items():
        drop = spec["drop"]
        print(f"\n[{cfg}  (drop {drop})]")
        tutor = PedTutorVariant(mock_client(), cfg)

        # (i) the dropped node is structurally absent from the compiled graph
        gnodes = set(tutor._graph.get_graph().nodes)
        check(f"(i) compiled graph never contains {drop}", drop not in gnodes)

        for label, transcript, route_val in SCENARIOS:
            r = tutor.respond(transcript, prob, seed=0, turn_index=0)
            nodes = r.meta["nodes"]
            responder = nodes[-1]
            want_resp = spec["responder"][label]

            # (i) the dropped node's model call never happens this turn
            check(f"(i) {label}: no model call tagged {drop}", drop not in nodes)
            # (ii) the orphaned/realized route lands on the pre-registered retained responder
            check(f"(ii) {label}: handled by {want_resp}", responder == want_resp)
            # (iii) the visible-turn responder tag is one metrics.py recognizes (no new tag)
            check(f"(iii) {label}: responder tag in metrics.RESPONDER_NODES",
                  responder in M.RESPONDER_NODES)
            # (iv) per-turn model-call count matches the pre-registered per-variant expectation
            check(f"(iv) {label}: n_model_calls == {spec['n_calls']}",
                  r.meta["n_model_calls"] == spec["n_calls"])
            # (v) branch keeps the ORIGINAL deterministic route value (not the responder used)
            check(f"(v) {label}: branch == original route {route_val!r}",
                  r.meta["branch"] == route_val)

        # no_tracker is the only variant that drops a call; responder-drops are unchanged at 2
        if drop == "state_tracker":
            check("(iv) no_tracker reduces the per-turn call count to 1 (disclosed confound)",
                  spec["n_calls"] == 1)
        else:
            check("(iv) responder-drop keeps the per-turn call count at 2 (UNCHANGED vs full)",
                  spec["n_calls"] == 2)


def test_no_new_visible_tag():
    print("\n[no new visible-responder tag introduced]")
    # metrics.py recognizes visible responders ONLY as these three; the ablations must not
    # add a fourth. Every variant's realized responders are a subset of this frozen set.
    check("metrics.RESPONDER_NODES unchanged (frozen set of 3)",
          M.RESPONDER_NODES == ("deferral_gate", "decomposer", "hint_cascade"))
    realized = {resp for spec in SPEC.values() for resp in spec["responder"].values()}
    check("every realized responder is in the frozen RESPONDER_NODES",
          realized <= set(M.RESPONDER_NODES))


def test_config_consistency():
    print("\n[variant configs are concrete + consistent with the frozen spec]")
    responders = {"deferral_gate", "decomposer", "hint_cascade"}
    base_route = {"defer": "deferral_gate", "decompose": "decomposer", "hint": "hint_cascade"}
    for cfg, spec in SPEC.items():
        c = load_yaml(cfg)
        check(f"{cfg}: base_config is the frozen ped_full.yaml",
              c.get("base_config") == "configs/ped_full.yaml")
        check(f"{cfg}: drop_node matches the variant spec", c.get("drop_node") == spec["drop"])
        # no surviving angle-bracket placeholder anywhere in the config text
        check(f"{cfg}: contains no angle-bracket placeholder",
              "<" not in Path(REPO_ROOT, cfg).read_text())
        if spec["drop"] == "state_tracker":
            check(f"{cfg}: no_tracker pins assessment_fallback='' + new_entry=route + no reroute",
                  c.get("assessment_fallback") == "" and c.get("new_entry") == "route"
                  and not c.get("reroute"))
        else:
            orphan = {k for k, v in base_route.items() if v == spec["drop"]}
            rr = c.get("reroute") or {}
            check(f"{cfg}: reroute keys are exactly the orphaned route(s) {sorted(orphan)}",
                  set(rr) == orphan)
            check(f"{cfg}: reroute targets are RETAINED responders (recognized tags)",
                  all(t in responders and t != spec["drop"] for t in rr.values()))


def test_rejects_malformed():
    print("\n[malformed / placeholder variant config is refused]")
    import tempfile

    def _raises(text):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, dir="/tmp") as f:
            f.write(text); path = f.name
        try:
            PedTutorVariant(mock_client(), path)
            return False
        except (ValueError, KeyError, AssertionError):
            return True
        finally:
            Path(path).unlink(missing_ok=True)

    check("no base_config -> refused",
          _raises("variant: no_gate\ndrop_node: deferral_gate\nreroute: {defer: decomposer}\n"))
    check("placeholder reroute target (not a retained responder) -> refused",
          _raises("base_config: configs/ped_full.yaml\nvariant: no_gate\n"
                  "drop_node: deferral_gate\nreroute: {defer: SOMENODE}\n"))
    check("rerouting onto the DROPPED node -> refused",
          _raises("base_config: configs/ped_full.yaml\nvariant: no_gate\n"
                  "drop_node: deferral_gate\nreroute: {defer: deferral_gate}\n"))
    check("wrong reroute key (not the orphaned route) -> refused",
          _raises("base_config: configs/ped_full.yaml\nvariant: no_gate\n"
                  "drop_node: deferral_gate\nreroute: {hint: decomposer}\n"))
    check("variant/drop_node mismatch -> refused",
          _raises("base_config: configs/ped_full.yaml\nvariant: no_gate\n"
                  "drop_node: hint_cascade\nreroute: {hint: decomposer}\n"))
    check("no_tracker with a non-empty assessment_fallback -> refused",
          _raises("base_config: configs/ped_full.yaml\nvariant: no_tracker\n"
                  "drop_node: state_tracker\nnew_entry: route\nassessment_fallback: x\n"))


def main():
    test_frozen_full_graph_untouched()
    test_variants()
    test_no_new_visible_tag()
    test_config_consistency()
    test_rejects_malformed()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
