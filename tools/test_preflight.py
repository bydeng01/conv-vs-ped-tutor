"""Offline tests for the preflight exit-code policy and the cross-model leakage diagnostic
(experiments/preflight.py). No keys, no network.

Covers the cross-model change: ConvTutor leakage is an ADVISORY (recorded, non-blocking)
gate for a base, while EVERY other gate stays blocking and the primary's hard-gate semantics
are unchanged (default advisory_gates=()). Plus the leakage_diagnostic provenance record.

Run:  python tools/test_preflight.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from experiments import preflight as P  # noqa: E402

_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}")


ALL_OK = {"isolated_cold_low": True, "marker_rate": True,
          "convtutor_leaky": True, "student_served_by_groq": True}

# ================================================================ exit-code policy (primary = hard gate)
print("preflight_exit_code: primary hard-gate semantics (default, no advisory)")
check("all gates pass -> 0", P.preflight_exit_code("live", ALL_OK) == 0)
check("ConvTutor leakage absent -> 1 (BLOCKING for the primary)",
      P.preflight_exit_code("live", {**ALL_OK, "convtutor_leaky": False}) == 1)
check("cold gate fail -> 1", P.preflight_exit_code("live", {**ALL_OK, "isolated_cold_low": False}) == 1)
check("served-provider fail -> 1",
      P.preflight_exit_code("live", {**ALL_OK, "student_served_by_groq": False}) == 1)
check("None gate ignored (e.g. served on mock)",
      P.preflight_exit_code("live", {**ALL_OK, "student_served_by_groq": None}) == 0)
check("mock backend always 0", P.preflight_exit_code("mock", {**ALL_OK, "convtutor_leaky": False}) == 0)

# ================================================================ advisory: ONLY ConvTutor leakage is non-blocking
print("preflight_exit_code: cross-model base advisory (convtutor_leaky non-blocking)")
ADV = ("convtutor_leaky",)
check("leakage ABSENT is advisory -> 0 (recorded, non-blocking)",
      P.preflight_exit_code("live", {**ALL_OK, "convtutor_leaky": False}, ADV) == 0)
check("cold STILL blocks under advisory -> 1",
      P.preflight_exit_code("live", {**ALL_OK, "convtutor_leaky": False, "isolated_cold_low": False}, ADV) == 1)
check("marker STILL blocks under advisory -> 1",
      P.preflight_exit_code("live", {**ALL_OK, "marker_rate": False}, ADV) == 1)
check("served-provider STILL blocks under advisory -> 1",
      P.preflight_exit_code("live", {**ALL_OK, "student_served_by_groq": False}, ADV) == 1)
check("advisory downgrades ONLY the named gate, not a blanket pass",
      P.preflight_exit_code("live", {**ALL_OK, "convtutor_leaky": False, "marker_rate": False}, ADV) == 1)
check("all pass under advisory -> 0", P.preflight_exit_code("live", ALL_OK, ADV) == 0)

# ================================================================ leakage diagnostic record (full read + provenance)
print("leakage_diagnostic: numerator/denominator/rate + provenance, references the pin record")
diag = P.leakage_diagnostic(
    base_slug="gpt", backend="live", tutor_model="gpt-5.5-2026-04-23",
    models_config="configs/models.gpt.yaml",
    problems_path="domain/algebra/problems.yaml", problems_sha256="abc123",
    repo_commit="deadbeef", timestamp="2026-06-27T00:00:00+00:00",
    leak_turns=27, tutor_turns=52, leak_rate=27 / 52, raw_log_dir="logs/preflight-x/",
    pin_record_ref="2026-06-27 PIN RECORD: OpenAI base (gpt)")
check("records numerator + denominator (not just present/absent)",
      diag["leak_turns"] == 27 and diag["tutor_turns"] == 52)
check("records the rate", abs(diag["leak_rate"] - 27 / 52) < 1e-9)
check("advisory + non-blocking flags set", diag["advisory"] is True and diag["blocking"] is False)
check("records backend so mock can't pose as a live read", diag["backend"] == "live")
check("references the immutable pin record (does not embed/edit it)",
      diag["pin_record_ref"] == "2026-06-27 PIN RECORD: OpenAI base (gpt)")
check("carries full provenance",
      all(diag[k] for k in ("tutor_model", "models_config", "problems_path",
                            "problems_sha256", "repo_commit", "timestamp", "raw_log_dir")))
check("note states report-don't-tune", "report, don't tune" in diag["note"].lower()
      or ("not a reason to tune" in diag["note"].lower()))

# absent-leakage diagnostic still records the read (0/N), advisory
zero = P.leakage_diagnostic(
    base_slug="gemini", backend="live", tutor_model="gemini-3.1-pro-preview",
    models_config="configs/models.gemini.yaml",
    problems_path="domain/algebra/problems.yaml", problems_sha256="abc123", repo_commit="deadbeef",
    timestamp="t", leak_turns=0, tutor_turns=48, leak_rate=0.0, raw_log_dir="logs/preflight-y/",
    pin_record_ref=None)
check("absent leakage recorded as 0/N (a finding, not a stop)",
      zero["leak_turns"] == 0 and zero["tutor_turns"] == 48 and zero["leak_rate"] == 0.0)

# ================================================================ provenance helpers
print("provenance helpers")
check("_sha256_file hashes an existing file",
      isinstance(P._sha256_file(REPO_ROOT / "domain/algebra/problems.yaml"), str)
      and len(P._sha256_file(REPO_ROOT / "domain/algebra/problems.yaml")) == 64)
check("_sha256_file -> None for a missing file", P._sha256_file(REPO_ROOT / "does/not/exist.x") is None)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
