"""Check that public packaging retains evidence and excludes local coordination."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import build_submission_artifact as builder
from tools import scan_sensitive as scanner
from artifact import verify_artifact as verifier


class PublicPackagingTests(unittest.TestCase):
    def test_readme_entrypoints_are_in_the_archive(self):
        self.assertTrue({"CITATION.cff", "Dockerfile", ".dockerignore",
                         ".github/workflows/ci.yml"} <= set(builder.TOP_LEVEL))

    def test_local_records_stay_out_if_restored_or_regenerated(self):
        local = (
            "supplement/human-validation/COORDINATOR.md",
            "supplement/HANDOFF_2026-10-11.md",
            "supplement/ANALYSIS_HANDOFF_2026-10-11.md",
            "supplement/CONTINUE_REVIEW_NOTES_2026-10-11.md",
            "tools/.local-archive/old_source.py",
        )
        evidence = (
            "paper-plan.md", "decisions-log.md",
            "supplement/human-validation-plan-2026-10-04.md",
            "supplement/human-validation/author-review-2026-10-11.md",
            "results/judge_robustness/gpt-5.6-sol/sonnet/plan.json",
            "results/judge_robustness/gpt-5.6-sol/sonnet/provenance.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in local + evidence:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n")
            with patch.object(builder, "REPO_ROOT", root):
                included = {p.relative_to(root).as_posix() for p in root.rglob("*")
                            if builder.acceptable(p)}
            self.assertEqual(included, set(evidence))

    def test_scanner_omits_local_archives_but_keeps_public_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (".local-archive/record.txt", "output/preparation.txt",
                         "tmp/scratch.txt", "agents/client.py", "supplement/record.md"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with patch.object(scanner, "REPO_ROOT", root):
                included = {p.relative_to(root).as_posix() for p in scanner._all_files()}
            self.assertEqual(included, {"agents/client.py", "supplement/record.md"})

    def test_existing_account_redaction_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "routing.json").write_text(
                '{"user_id": "<redacted-account-handle>"}\n')
            with patch.object(verifier, "ROOT", root):
                self.assertEqual(verifier.sensitive_findings(), [])

    def test_redaction_does_not_hide_a_later_account_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = dict(user_id="<redacted-account-handle>", account_id="fixture-123")
            (root / "routing.json").write_text(json.dumps(record))
            with patch.object(verifier, "ROOT", root):
                findings = verifier.sensitive_findings()
            self.assertEqual(findings, ["routing.json:1: provider account identifier"])


if __name__ == "__main__":
    unittest.main()
