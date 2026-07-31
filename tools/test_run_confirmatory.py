"""Offline tests for the confirmatory runner (experiments/run_confirmatory.py).

Runs MOCK cells (no API key, no network) and unit-tests the pure pieces, checking:
  - condition + replicate_id are tagged on EVERY model call, for cold/conv/ped, and
    are consistent with what analysis/metrics.py infers (no second source of truth);
  - the freeze guard errors on a dirty tree / off the freeze commit and records the
    hash when clean (and only RECORDS, never blocks, on the mock rehearsal);
  - replicate r uses seed = base_seed + r (paired) and replicate_id = r;
  - resume runs only missing cells, and a partial cell dir is cleared (not appended);
  - frozen inputs (problems + configs + rubrics) are byte-identical before/after a run.

Run:  python tools/test_run_confirmatory.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.config import load_models_config  # noqa: E402
from agents.logging_utils import RunLogger  # noqa: E402
from analysis import metrics as M  # noqa: E402
from experiments import preflight as PF  # noqa: E402
from experiments import run_confirmatory as RC  # noqa: E402

_passed = _failed = 0
# Each cell-creating test gets its own seed namespace so deterministic run ids don't
# collide across tests; all are conf-s99900*-* and cleaned up at the end.
_TEST_SEED = 999000     # tagging + merge tests
SEED_RESUME = 999001    # resume test
SEED_FROZEN = 999002    # frozen-inputs test
SEED_BASE = 999003      # cross-model base-namespacing test
SEED_ABL = 999004       # #5 ablation condition-handling test


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}")


def _raises_systemexit(fn) -> bool:
    try:
        fn()
        return False
    except SystemExit:
        return True


def _read_calls(run_id: str) -> list[dict]:
    path = RC.LOGS_DIR / run_id / "calls.jsonl"
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _cleanup():
    # Matches the primary test namespace (conf-s99900*), base-namespaced test dirs
    # (conf-{base}-s99900*) the cross-model test writes, and the ablation test dirs
    # (abl-s99900*) the #5 test writes.
    for pat in ("conf-*s99900*", "abl-*s99900*"):
        for d in RC.LOGS_DIR.glob(pat):
            shutil.rmtree(d, ignore_errors=True)


# ============================================================= freeze guard
def test_freeze_guard():
    print("\n[freeze guard]")
    clean_at = {"head": "abc123def456", "dirty": False, "porcelain": ""}
    dirty = {"head": "abc123def456", "dirty": True, "porcelain": " M foo.py\n?? bar\n"}

    # enforce + dirty -> refuse
    check("errors on a dirty tree (enforced)",
          _raises_systemexit(lambda: RC.check_freeze(dirty, "abc123def456", enforce=True)))
    # enforce + clean + matching commit -> ok, records the hash + at_freeze_commit
    meta = RC.check_freeze(clean_at, "abc123def456", enforce=True)
    check("clean + matching commit passes and records hash",
          meta["head"] == "abc123def456" and meta["at_freeze_commit"] is True)
    # short-hash prefix also matches
    meta2 = RC.check_freeze(clean_at, "abc123d", enforce=True)
    check("short-hash prefix matches HEAD", meta2["at_freeze_commit"] is True)
    # enforce + clean + WRONG commit -> refuse
    check("errors when HEAD != freeze commit",
          _raises_systemexit(lambda: RC.check_freeze(clean_at, "deadbeef", enforce=True)))
    # enforce + clean + no expected commit -> refuse (must pin)
    check("errors when no freeze commit is specified",
          _raises_systemexit(lambda: RC.check_freeze(clean_at, None, enforce=True)))
    # mock rehearsal (enforce=False): records, never blocks, even on a dirty tree
    meta3 = RC.check_freeze(dirty, None, enforce=False)
    check("mock rehearsal records git state but does not block",
          meta3["dirty"] is True and meta3["enforced"] is False
          and meta3["at_freeze_commit"] is False)

    # adversarial: empty / whitespace / too-short / reverse-prefix must NOT match
    # (each would silently bypass the live guard if the match logic were loose).
    check("empty expected_commit is refused (no silent bypass)",
          _raises_systemexit(lambda: RC.check_freeze(clean_at, "", enforce=True)))
    check("whitespace expected_commit is refused",
          _raises_systemexit(lambda: RC.check_freeze(clean_at, "   ", enforce=True)))
    check("1-char expected_commit does not prefix-match HEAD",
          _raises_systemexit(lambda: RC.check_freeze(clean_at, "a", enforce=True)))
    check("reverse-prefix (expected longer than HEAD) does not match",
          _raises_systemexit(lambda: RC.check_freeze(clean_at, "abc123def456EXTRA", enforce=True)))
    # A whitespace arg must behave exactly like "no arg given" (fall through to env/tag),
    # never short-circuit-return the whitespace. Tag-state-independent assertion.
    check("resolve_freeze_commit treats a whitespace arg as not-set (== no arg)",
          RC.resolve_freeze_commit("   ", REPO_ROOT) == RC.resolve_freeze_commit(None, REPO_ROOT))

    # git_state on the real repo returns a head + dirty flag (this tree is dirty now)
    st = RC.git_state(REPO_ROOT)
    check("git_state returns head + dirty + porcelain",
          set(st) == {"head", "dirty", "porcelain"} and isinstance(st["dirty"], bool))


# ============================================================= seed/replicate pairing
def test_pairing():
    print("\n[seed = base + r pairing]")
    cells = RC.plan_cells(["cold", "conv", "ped"], replicates=3, base_seed=5)
    check("grid size = conds x replicates", len(cells) == 9)
    # replicate r: every condition shares seed = base + r, tagged replicate_id = r
    for r in range(3):
        rcells = [c for c in cells if c["replicate"] == r]
        seeds = {c["seed"] for c in rcells}
        check(f"replicate {r}: all conditions share seed = base+{r} ({5 + r})",
              seeds == {5 + r})
    check("run ids are deterministic + seed-namespaced",
          RC.cell_run_id(5, "conv", 2) == "conf-s5-conv-r2")
    # the primary namespace is byte-stable: no base, or an explicit empty base, both
    # reproduce the original id; a cross-model base prepends a disjoint segment.
    check("empty base reproduces the primary run id exactly",
          RC.cell_run_id(5, "conv", 2, "") == "conf-s5-conv-r2")
    check("a cross-model base namespaces the run id (disjoint from primary)",
          RC.cell_run_id(5, "conv", 2, "gpt") == "conf-gpt-s5-conv-r2"
          and RC.cell_run_id(5, "conv", 2, "gpt") != RC.cell_run_id(5, "conv", 2))
    check("replicate_id is the index r (pairing key), independent of base_seed",
          all(c["replicate"] in (0, 1, 2) for c in cells))
    check("all cell run ids are unique (no cross-replicate dir collision)",
          len({c["run_id"] for c in cells}) == len(cells))


# ============================================================= tagging on every call
def test_tagging_every_call():
    print("\n[condition + replicate_id on EVERY call]")
    models_cfg = load_models_config("configs/models.yaml")
    problems = M.problem_index("domain/algebra/problems.yaml")  # warms the loader
    problems_list = RC.load_problems("domain/algebra/problems.yaml")
    freeze_meta = {"head": "test", "dirty": True, "at_freeze_commit": False}

    for cond in ("cold", "conv", "ped"):
        cell = {"condition": cond, "replicate": 0, "seed": _TEST_SEED,
                "run_id": RC.cell_run_id(_TEST_SEED, cond, 0)}
        RC.run_cell(cell, problems_list, models_cfg, backend="mock",
                    max_train_turns=2, freeze_meta=freeze_meta, models_path="configs/models.yaml")
        calls = _read_calls(cell["run_id"])
        check(f"{cond}: produced calls", len(calls) > 0)
        every_cond = all((c.get("tags") or {}).get("condition") == cond for c in calls)
        every_rid = all((c.get("tags") or {}).get("replicate_id") == 0 for c in calls)
        check(f"{cond}: condition tagged on every call", every_cond)
        check(f"{cond}: replicate_id tagged on every call", every_rid)
        # problem_id present on every student/tutor call (phase derives from component+role)
        pid_ok = all((c.get("tags") or {}).get("problem_id")
                     for c in calls if c.get("role") in ("student", "tutor"))
        check(f"{cond}: problem_id present on every student/tutor call", pid_ok)
        # consistent with metrics.py's readers (no conflicting source of truth)
        check(f"{cond}: metrics.infer_condition reads the tag",
              M.infer_condition(calls) == cond)
        check(f"{cond}: metrics.infer_replicate_id reads the tag",
              M.infer_replicate_id(calls) == "0")
        check(f"{cond}: is a full-protocol session", M.is_full_protocol(calls))

    # tagging holds for a NON-zero replicate id too (not just r=0), end-to-end
    cell2 = {"condition": "conv", "replicate": 2, "seed": _TEST_SEED + 2,
             "run_id": RC.cell_run_id(_TEST_SEED, "conv", 2)}
    RC.run_cell(cell2, problems_list, models_cfg, backend="mock",
                max_train_turns=2, freeze_meta=freeze_meta, models_path="configs/models.yaml")
    calls2 = _read_calls(cell2["run_id"])
    check("non-zero replicate_id tagged on every call",
          all((c.get("tags") or {}).get("replicate_id") == 2 for c in calls2))
    check("metrics reads the non-zero replicate_id", M.infer_replicate_id(calls2) == "2")


# ============================================================= TaggingClient merge
def test_tagging_client_merge():
    print("\n[TaggingClient merge: base tags authoritative, no collision]")
    models_cfg = load_models_config("configs/models.yaml")
    run_id = f"conf-s{_TEST_SEED}-merge-r0"
    logger = RunLogger(run_id)
    client = RC.TaggingClient(models_cfg=models_cfg, backend="mock", logger=logger,
                              base_tags={"condition": "conv", "replicate_id": 3})
    check("TaggingClient is a ModelClient (agents accept it)",
          isinstance(client, M_ModelClient := __import__(
              "agents.model_client", fromlist=["ModelClient"]).ModelClient))
    client.complete(role="tutor", system="", messages=[{"role": "user", "content": "hi"}],
                    seed=0, tags={"component": "conv_tutor", "problem_id": "train-1",
                                  "turn_index": 0},
                    mock_meta={"canonical_answer": 12, "turn_index": 0})
    rec = _read_calls(run_id)[-1]
    tags = rec.get("tags") or {}
    check("base condition reaches the logged call", tags.get("condition") == "conv")
    check("base replicate_id reaches the logged call", tags.get("replicate_id") == 3)
    check("per-call tags preserved (no clobber)",
          tags.get("component") == "conv_tutor" and tags.get("problem_id") == "train-1"
          and tags.get("turn_index") == 0)


# ============================================================= cross-model base tag
def test_base_namespacing():
    print("\n[cross-model base: namespaced ids + base tag on every call + meta]")
    models_cfg = load_models_config("configs/models.yaml")
    problems_list = RC.load_problems("domain/algebra/problems.yaml")
    freeze_meta = {"head": "test", "dirty": True, "at_freeze_commit": False}

    # plan_cells with a base namespaces every run id and cannot collide with the
    # primary (base-less) grid at the same seed.
    primary = RC.plan_cells(["cold", "conv", "ped"], replicates=2, base_seed=SEED_BASE)
    based = RC.plan_cells(["cold", "conv", "ped"], replicates=2, base_seed=SEED_BASE, base="gpt")
    check("base-namespaced run ids are all unique",
          len({c["run_id"] for c in based}) == len(based))
    check("base ids are disjoint from the primary ids at the same seed",
          set(c["run_id"] for c in based).isdisjoint(c["run_id"] for c in primary))
    check("every base id carries the base segment",
          all(c["run_id"].startswith("conf-gpt-s") for c in based))

    # End-to-end mock cell WITH a base: base is stamped on every call and recorded in meta.
    cell = {"condition": "conv", "replicate": 0, "seed": SEED_BASE,
            "run_id": RC.cell_run_id(SEED_BASE, "conv", 0, "gpt")}
    RC.run_cell(cell, problems_list, models_cfg, backend="mock", max_train_turns=2,
                freeze_meta=freeze_meta, models_path="configs/models.yaml", base="gpt")
    calls = _read_calls(cell["run_id"])
    check("base run produced calls", len(calls) > 0)
    check("base tagged on EVERY call",
          all((c.get("tags") or {}).get("base") == "gpt" for c in calls))
    check("condition + replicate_id still tagged alongside base",
          all((c.get("tags") or {}).get("condition") == "conv"
              and (c.get("tags") or {}).get("replicate_id") == 0 for c in calls))
    meta = json.loads((RC.LOGS_DIR / cell["run_id"] / "confirmatory_meta.json").read_text())
    check("run meta records base + the tutor model id",
          meta.get("base") == "gpt"
          and meta.get("tutor_model") == models_cfg["roles"]["tutor"]["model"])

    # A base-less cell stays byte-stable: NO base key in tags, meta base is None.
    cell0 = {"condition": "conv", "replicate": 1, "seed": SEED_BASE + 1,
             "run_id": RC.cell_run_id(SEED_BASE, "conv", 1)}
    RC.run_cell(cell0, problems_list, models_cfg, backend="mock", max_train_turns=2,
                freeze_meta=freeze_meta, models_path="configs/models.yaml")
    calls0 = _read_calls(cell0["run_id"])
    check("base-less call tags contain NO base key (primary byte-stable)",
          all("base" not in (c.get("tags") or {}) for c in calls0))
    # Byte-stability is about key ABSENCE, not a present-but-null base: the base-less
    # meta key set must equal the frozen primary runner's exactly (no base/tutor_model).
    meta0 = json.loads((RC.LOGS_DIR / cell0["run_id"] / "confirmatory_meta.json").read_text())
    PRIMARY_META_KEYS = {"run_id", "condition", "replicate_id", "seed", "backend",
                         "max_train_turns", "models_config", "freeze", "written_at"}
    check("base-less meta omits base + tutor_model entirely (not present-as-null)",
          "base" not in meta0 and "tutor_model" not in meta0)
    check("base-less meta key set is exactly the primary's (byte-stable shape)",
          set(meta0) == PRIMARY_META_KEYS)


# ============================================================= only-tutor-changes guard
def test_tutor_only_drift():
    print("\n[cross-model: only-the-tutor-changes config guard]")
    import copy
    primary = load_models_config("configs/models.yaml")
    check("identical config -> no forbidden drift",
          RC.tutor_only_drift(copy.deepcopy(primary), primary) == [])
    base_ok = copy.deepcopy(primary)
    base_ok["roles"]["tutor"]["model"] = "some-other-tutor-model"
    check("changing ONLY the tutor model is allowed",
          RC.tutor_only_drift(base_ok, primary) == [])
    base_stu = copy.deepcopy(primary)
    base_stu["roles"]["student"]["model"] = "stronger-student"
    check("changing the student is forbidden",
          any("roles.student" in s for s in RC.tutor_only_drift(base_stu, primary)))
    base_judge = copy.deepcopy(primary)
    base_judge["roles"]["judge"]["model"] = "different-judge"
    check("changing the judge is forbidden",
          any("roles.judge" in s for s in RC.tutor_only_drift(base_judge, primary)))
    base_temp = copy.deepcopy(primary)
    base_temp["roles"]["tutor"]["temperature"] = 0.99
    check("changing the tutor sampling budget is forbidden",
          any("roles.tutor.temperature" in s for s in RC.tutor_only_drift(base_temp, primary)))
    base_prov = copy.deepcopy(primary)
    stu_prov = base_prov["roles"]["student"].get("provider") or base_prov.get("provider")
    base_prov.setdefault("providers", {}).setdefault(stu_prov, {})["base_url"] = "http://drift"
    check("changing a student-used provider is forbidden",
          any("providers." in s for s in RC.tutor_only_drift(base_prov, primary)))


# ============================================================= invocation-aware resume
def test_cell_meta_mismatch():
    print("\n[cross-model: invocation-aware resume guard]")
    d = RC.LOGS_DIR / "conf-s999003-metatest-r0"
    d.mkdir(parents=True, exist_ok=True)
    base_meta = {"condition": "conv", "replicate_id": 0, "seed": 5, "backend": "live",
                 "max_train_turns": 4, "models_config": "configs/models.gpt.yaml",
                 "base": "gpt", "tutor_model": "gpt-x", "freeze": {"head": "abc123def456"}}
    (d / "confirmatory_meta.json").write_text(json.dumps(base_meta))
    match = {"condition": "conv", "replicate_id": 0, "seed": 5, "backend": "live",
             "max_train_turns": 4, "models_config": "configs/models.gpt.yaml",
             "base": "gpt", "tutor_model": "gpt-x", "freeze_head": "abc123def456"}
    check("matching invocation -> no mismatch", RC.cell_meta_mismatch(d, match) is None)
    bad_model = dict(match, tutor_model="gpt-y")
    check("different tutor_model -> mismatch", (RC.cell_meta_mismatch(d, bad_model) or "").startswith("tutor_model"))
    bad_cfg = dict(match, models_config="configs/models.other.yaml")
    check("different models_config -> mismatch", (RC.cell_meta_mismatch(d, bad_cfg) or "").startswith("models_config"))
    bad_freeze = dict(match, freeze_head="deadbeefcafe9")
    check("different freeze head -> mismatch", "freeze head" in (RC.cell_meta_mismatch(d, bad_freeze) or ""))
    # a legacy/primary meta missing base + tutor_model is NOT a false mismatch
    legacy = {"condition": "conv", "replicate_id": 0, "seed": 5, "backend": "mock",
              "max_train_turns": 4, "models_config": "configs/models.yaml",
              "freeze": {"head": "abc123def456"}}
    (d / "confirmatory_meta.json").write_text(json.dumps(legacy))
    exp_primary = {"condition": "conv", "replicate_id": 0, "seed": 5, "backend": "mock",
                   "max_train_turns": 4, "models_config": "configs/models.yaml",
                   "base": None, "tutor_model": "claude-sonnet-4-6"}
    check("legacy meta (no base/tutor_model keys) -> no false mismatch on a PRIMARY invocation",
          RC.cell_meta_mismatch(d, exp_primary) is None)
    # but a BASE invocation REQUIRES base + tutor_model present: the same meta is flagged
    exp_base = {"condition": "conv", "replicate_id": 0, "seed": 5, "backend": "mock",
                "max_train_turns": 4, "models_config": "configs/models.yaml",
                "base": "gpt", "tutor_model": "gpt-x"}
    check("base invocation: meta missing base -> mismatch (require_present)",
          (RC.cell_meta_mismatch(d, exp_base, require_present=("base", "tutor_model")) or "").startswith("base"))
    shutil.rmtree(d, ignore_errors=True)


# ============================================================= protocol-knob guard
def test_protocol_knob_drift():
    print("\n[cross-model: live base must match the registered protocol]")
    from types import SimpleNamespace
    def ns(**kw):
        base = dict(domain="domain/algebra/problems.yaml", replicates=10, base_seed=0,
                    max_train_turns=4)
        base.update(kw)
        return SimpleNamespace(**base)
    check("registered knobs -> no drift",
          RC.protocol_knob_drift(ns(), ["cold", "conv", "ped"]) == [])
    check("wrong domain -> drift",
          any("--domain" in s for s in RC.protocol_knob_drift(ns(domain="other.yaml"),
                                                              ["cold", "conv", "ped"])))
    check("dropping cold from conditions -> drift",
          any("--conditions" in s for s in RC.protocol_knob_drift(ns(), ["conv", "ped"])))
    check("wrong replicate count -> drift",
          any("--replicates" in s for s in RC.protocol_knob_drift(ns(replicates=5),
                                                                 ["cold", "conv", "ped"])))
    check("wrong base-seed -> drift",
          any("--base-seed" in s for s in RC.protocol_knob_drift(ns(base_seed=7),
                                                                ["cold", "conv", "ped"])))
    check("wrong turn budget -> drift",
          any("--max-train-turns" in s for s in RC.protocol_knob_drift(ns(max_train_turns=6),
                                                                       ["cold", "conv", "ped"])))


# ============================================================= base-pooling guard
def test_base_pooling_guard():
    print("\n[cross-model: compute_metrics refuses pooling two bases]")
    from analysis import compute_metrics as CM
    models_cfg = load_models_config("configs/models.yaml")
    problems_list = RC.load_problems("domain/algebra/problems.yaml")
    fm = {"head": "test", "dirty": True, "at_freeze_commit": False}
    pc = {"condition": "conv", "replicate": 0, "seed": SEED_BASE,
          "run_id": RC.cell_run_id(SEED_BASE, "conv", 0)}
    bc = {"condition": "conv", "replicate": 0, "seed": SEED_BASE,
          "run_id": RC.cell_run_id(SEED_BASE, "conv", 0, "gpt")}
    RC.run_cell(pc, problems_list, models_cfg, "mock", 2, fm, "configs/models.yaml")
    RC.run_cell(bc, problems_list, models_cfg, "mock", 2, fm, "configs/models.yaml", base="gpt")
    check("untagged session base = 'primary'", CM._session_base(_read_calls(pc["run_id"])) == "primary")
    check("base-tagged session base = 'gpt'", CM._session_base(_read_calls(bc["run_id"])) == "gpt")
    out = RC.LOGS_DIR / "conf-s999003-poolout"

    def _run(run_ids):
        saved = sys.argv
        sys.argv = ["compute_metrics", *[str(RC.LOGS_DIR / x) for x in run_ids],
                    "--out", str(out)]
        try:
            CM.main()
            return False
        except SystemExit:
            return True
        finally:
            sys.argv = saved

    check("two distinct bases in one analysis -> REFUSED",
          _run([pc["run_id"], bc["run_id"]]))
    check("a single base -> allowed (no refusal)", not _run([bc["run_id"]]))
    summ = json.loads((out / "metrics_summary.json").read_text())
    check("single-base analysis stamps base in metrics_summary", summ.get("base") == "gpt")
    shutil.rmtree(out, ignore_errors=True)


# ============================================================= resume
def test_resume_missing_only():
    print("\n[resume: only missing cells; partial dir cleared]")
    models_cfg = load_models_config("configs/models.yaml")
    problems_list = RC.load_problems("domain/algebra/problems.yaml")
    freeze_meta = {"head": "test", "dirty": True, "at_freeze_commit": False}
    cells = RC.plan_cells(["cold", "conv"], replicates=1, base_seed=SEED_RESUME)

    # initially nothing is complete
    check("no cells complete before running",
          all(not RC.cell_complete(RC.LOGS_DIR / c["run_id"]) for c in cells))

    # run just the cold cell
    cold = next(c for c in cells if c["condition"] == "cold")
    RC.run_cell(cold, problems_list, models_cfg, "mock", 2, freeze_meta, "configs/models.yaml")
    done = [c for c in cells if RC.cell_complete(RC.LOGS_DIR / c["run_id"])]
    todo = [c for c in cells if c not in done]
    check("after running cold, exactly cold is complete",
          [c["condition"] for c in done] == ["cold"])
    check("resume todo = the still-missing cell(s)",
          [c["condition"] for c in todo] == ["conv"])

    # a PARTIAL cell dir (calls.jsonl but no result json) must be detected incomplete
    # and CLEARED on re-run -- not appended to (no mixing / duplication).
    conv = next(c for c in cells if c["condition"] == "conv")
    cdir = RC.LOGS_DIR / conv["run_id"]
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "calls.jsonl").write_text('{"seq": 1, "marker": "STALE_PARTIAL"}\n')
    check("partial cell (no result json) is detected incomplete",
          not RC.cell_complete(cdir))
    RC.run_cell(conv, problems_list, models_cfg, "mock", 2, freeze_meta, "configs/models.yaml")
    txt = (cdir / "calls.jsonl").read_text()
    check("partial dir was cleared before re-run (stale line gone)",
          "STALE_PARTIAL" not in txt)
    check("re-run cell is now complete", RC.cell_complete(cdir))
    # single replicate_id only (no mixing): every call tags replicate_id = 0
    calls = _read_calls(conv["run_id"])
    check("re-run cell has exactly one replicate_id (no mixing)",
          {(c.get("tags") or {}).get("replicate_id") for c in calls} == {0})

    # confirmatory_meta.json is the completion sentinel: a cell with result+calls but no
    # meta (a crash in the write gap) must read INCOMPLETE so resume re-runs it -- never
    # skipped without its freeze provenance.
    meta_path = cdir / "confirmatory_meta.json"
    saved = meta_path.read_text()
    meta_path.unlink()
    check("cell missing confirmatory_meta.json is incomplete (sentinel)",
          not RC.cell_complete(cdir))
    meta_path.write_text(saved)
    check("cell is complete again once the meta sentinel is restored",
          RC.cell_complete(cdir))


# ============================================================= frozen inputs unchanged
FROZEN_INPUTS = (
    "domain/algebra/problems.yaml",
    "configs/models.yaml",
    "configs/conv_tutor.yaml",
    "configs/ped_full.yaml",
    "supplement/judge_rubric.md",
    "supplement/independence_rubric.md",
    "supplement/prompts.md",
)


def _hash_frozen() -> dict:
    out = {}
    for rel in FROZEN_INPUTS:
        p = REPO_ROOT / rel
        if p.exists():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_frozen_inputs_untouched():
    print("\n[frozen inputs byte-identical before/after a run]")
    before = _hash_frozen()
    check("frozen inputs found to hash", len(before) >= 3)
    models_cfg = load_models_config("configs/models.yaml")
    problems_list = RC.load_problems("domain/algebra/problems.yaml")
    freeze_meta = {"head": "test", "dirty": True, "at_freeze_commit": False}
    cell = {"condition": "ped", "replicate": 0, "seed": SEED_FROZEN,
            "run_id": RC.cell_run_id(SEED_FROZEN, "ped", 0)}
    RC.run_cell(cell, problems_list, models_cfg, "mock", 2, freeze_meta, "configs/models.yaml")
    after = _hash_frozen()
    check("every frozen input unchanged after a mock run", before == after)


def test_preflight_gate_exit():
    print("\n[preflight: live CHECK exits non-zero; mock never fails]")
    check("live + all gates pass -> exit 0",
          PF.preflight_exit_code("live", {"a": True, "b": True}) == 0)
    check("live + a failing gate -> exit 1",
          PF.preflight_exit_code("live", {"a": True, "b": False}) == 1)
    check("live + a None (n/a) gate is ignored -> exit 0",
          PF.preflight_exit_code("live", {"a": True, "b": None}) == 0)
    check("mock never fails even with a failing gate -> exit 0",
          PF.preflight_exit_code("mock", {"a": False}) == 0)


def test_provider_key_precheck():
    print("\n[live provider-key precheck]")
    import os
    cfg = load_models_config("configs/models.yaml")  # student -> openrouter (OPENROUTER_API_KEY)
    saved = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        miss = RC.missing_provider_keys(cfg, ("student",))
        check("unset student key is reported (role/provider/env)",
              any(e == "OPENROUTER_API_KEY" for _, _, e in miss))
        os.environ["OPENROUTER_API_KEY"] = "x"
        miss2 = RC.missing_provider_keys(cfg, ("student",))
        check("set key -> not reported", all(e != "OPENROUTER_API_KEY" for _, _, e in miss2))
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)
        if saved is not None:
            os.environ["OPENROUTER_API_KEY"] = saved


# ============================================================= #5 ablation conditions
def test_ablation_run_ids():
    print("\n[#5 ablation: run-id namespacing + pairing]")
    # ablation ids use the abl- namespace, disjoint from the primary conf- cells at the
    # same seed, so a primary glob (logs/conf-s0-*) never picks up an ablation cell.
    check("ablation run id is abl-namespaced",
          RC.cell_run_id(0, "ped_no_gate", 0, ablation=True) == "abl-s0-ped_no_gate-r0")
    check("ablation id is disjoint from the primary id at the same (seed,cond-family)",
          RC.cell_run_id(0, "conv_socratic", 2, ablation=True) != RC.cell_run_id(0, "conv", 2))
    check("primary ids are byte-stable when ablation=False (default unchanged)",
          RC.cell_run_id(5, "conv", 2) == "conf-s5-conv-r2")
    # plan_cells pairs each ablation replicate r with seed = base_seed + r (same schedule
    # as the primary), tagged replicate_id = r, so it pairs with the frozen primary cell.
    cells = RC.plan_cells(list(RC.ABLATION_CONDITIONS), replicates=2, base_seed=0, ablation=True)
    check("ablation grid size = conds x replicates",
          len(cells) == len(RC.ABLATION_CONDITIONS) * 2)
    for r in range(2):
        seeds = {c["seed"] for c in cells if c["replicate"] == r}
        check(f"ablation replicate {r}: all conditions share seed = 0+{r}", seeds == {r})
    check("all ablation ids carry the abl- segment",
          all(c["run_id"].startswith("abl-s") for c in cells))
    primary = RC.plan_cells(["cold", "conv", "ped"], replicates=2, base_seed=0)
    check("ablation ids are disjoint from the primary ids at the same seed",
          set(c["run_id"] for c in cells).isdisjoint(c["run_id"] for c in primary))


def test_ablation_build_tutor():
    print("\n[#5 ablation: build_tutor maps condition -> (agent, config)]")
    from agents.conv_tutor import ConvTutor
    from agents.ped_ablations import PedTutorVariant
    cli = RC.TaggingClient(models_cfg=load_models_config("configs/models.yaml"),
                           backend="mock", logger=None, base_tags={})
    check("cold -> None (no tutor)", RC.build_tutor("cold", cli) is None)
    check("conv -> minimal ConvTutor (default prompt, byte-stable path)",
          type(RC.build_tutor("conv", cli)) is ConvTutor)
    cs = RC.build_tutor("conv_socratic", cli)
    check("conv_socratic -> ConvTutor with the socratic prompt config",
          isinstance(cs, ConvTutor) and "Socratic" in cs.system_prompt)
    for cond, variant in (("ped_no_gate", "no_gate"), ("ped_no_tracker", "no_tracker"),
                          ("ped_no_cascade", "no_cascade")):
        pv = RC.build_tutor(cond, cli)
        check(f"{cond} -> PedTutorVariant(variant={variant})",
              isinstance(pv, PedTutorVariant) and pv.variant == variant)


def test_ablation_end_to_end_tags():
    print("\n[#5 ablation: each condition runs on mock with the correct tags + recognized turns]")
    models_cfg = load_models_config("configs/models.yaml")
    problems_list = RC.load_problems("domain/algebra/problems.yaml")
    freeze_meta = {"head": "test", "dirty": True, "at_freeze_commit": False}
    # expected per-visible-turn model-call count per condition (metrics n_model_calls per turn)
    per_turn_calls = {"conv_socratic": 1, "conv_no_final_answer": 1,
                      "ped_no_gate": 2, "ped_no_cascade": 2, "ped_no_tracker": 1}
    dropped = {"ped_no_gate": "deferral_gate", "ped_no_cascade": "hint_cascade",
               "ped_no_tracker": "state_tracker"}
    for cond in RC.ABLATION_CONDITIONS:
        run_id = RC.cell_run_id(SEED_ABL, cond, 0, ablation=True)
        cell = {"condition": cond, "replicate": 0, "seed": SEED_ABL, "run_id": run_id}
        RC.run_cell(cell, problems_list, models_cfg, backend="mock", max_train_turns=2,
                    freeze_meta=freeze_meta, models_path="configs/models.yaml")
        calls = _read_calls(run_id)
        check(f"{cond}: produced calls", len(calls) > 0)
        check(f"{cond}: condition tagged on every call",
              all((c.get("tags") or {}).get("condition") == cond for c in calls))
        check(f"{cond}: metrics.infer_condition reads the ablation tag",
              M.infer_condition(calls) == cond)
        check(f"{cond}: is a full-protocol session", M.is_full_protocol(calls))
        check(f"{cond}: NO base tag (ablations are primary-base, never pooled away)",
              all("base" not in (c.get("tags") or {}) for c in calls))
        # the visible training turns are recognized by metrics, with the per-variant call
        # count (use the canonical seq-sorted + problem-id-resolved path, as analyze_session
        # does -- raw unsorted calls would group across problems on a null pid).
        mcalls = M.load_calls(RC.LOGS_DIR / run_id)
        M.resolve_problem_ids(mcalls)
        vts = M.visible_tutor_turns(mcalls)
        check(f"{cond}: visible tutor turns recognized", len(vts) > 0)
        check(f"{cond}: per-visible-turn n_model_calls == {per_turn_calls[cond]}",
              all(v.n_model_calls == per_turn_calls[cond] for v in vts))
        # ped node-drops: the dropped node's tag never appears in any logged call
        if cond in dropped:
            nodes = {(c.get("tags") or {}).get("node") for c in calls if c.get("role") == "tutor"}
            check(f"{cond}: dropped node {dropped[cond]} never logged",
                  dropped[cond] not in nodes)
        # meta records the ablation condition (completion sentinel)
        meta = json.loads((RC.LOGS_DIR / run_id / "confirmatory_meta.json").read_text())
        check(f"{cond}: meta records the condition + replicate", meta.get("condition") == cond
              and meta.get("replicate_id") == 0 and "base" not in meta)


def test_ablation_guards():
    print("\n[#5 ablation: invocation guards (mixing / --base / off-protocol)]")
    saved = sys.argv

    def _status_exits(argv):
        sys.argv = ["run_confirmatory", "--status", "--backend", "mock", *argv]
        try:
            RC.main()
            return False
        except SystemExit:
            return True
        finally:
            sys.argv = saved

    check("mixing primary + ablation conditions -> refused",
          _status_exits(["--conditions", "conv,ped_no_gate"]))
    check("--base with an ablation condition -> refused",
          _status_exits(["--conditions", "ped_no_gate", "--base", "gpt"]))
    check("an all-ablation --status run is allowed (no refusal)",
          not _status_exits(["--conditions", "ped_no_gate,conv_socratic", "--replicates", "1"]))
    check("an unknown condition is still refused",
          _status_exits(["--conditions", "ped_no_banana"]))

    # the live ablation protocol guard (knobs the freeze guard does not see)
    from types import SimpleNamespace

    def ns(**kw):
        base = dict(domain="domain/algebra/problems.yaml", replicates=10, base_seed=0,
                    max_train_turns=4, models="configs/models.yaml")
        base.update(kw)
        return SimpleNamespace(**base)
    abl = list(RC.ABLATION_CONDITIONS)
    check("registered ablation knobs -> no drift", RC.ablation_protocol_drift(ns(), abl) == [])
    check("a non-ablation condition -> drift",
          any("not pre-registered" in s for s in RC.ablation_protocol_drift(ns(), abl + ["conv"])))
    check("a cross-model --models config -> drift (ablations use the primary)",
          any("--models" in s for s in RC.ablation_protocol_drift(ns(models="configs/models.gpt.yaml"), abl)))
    check("wrong replicate count -> drift",
          any("--replicates" in s for s in RC.ablation_protocol_drift(ns(replicates=5), abl)))
    # ablation freeze-tag fallback is the ablation freeze, never the confirmatory one
    check("resolve_freeze_commit honors a non-default (ablation) tag arg",
          RC.resolve_freeze_commit("abc123def456", REPO_ROOT, RC.ABLATION_FREEZE_TAG) == "abc123def456")


def main():
    try:
        test_freeze_guard()
        test_pairing()
        test_tagging_every_call()
        test_tagging_client_merge()
        test_base_namespacing()
        test_tutor_only_drift()
        test_cell_meta_mismatch()
        test_protocol_knob_drift()
        test_base_pooling_guard()
        test_resume_missing_only()
        test_frozen_inputs_untouched()
        test_preflight_gate_exit()
        test_provider_key_precheck()
        test_ablation_run_ids()
        test_ablation_build_tutor()
        test_ablation_end_to_end_tags()
        test_ablation_guards()
    finally:
        _cleanup()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
