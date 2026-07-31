"""Structured logging.

Two artifacts per run, under logs/<run_id>/:
  - calls.jsonl   : one JSON object per model call (full request + response +
                    token usage). This is the canonical record. Metrics are
                    computed POST-HOC from these logs; nothing is recomputed on
                    the fly (build brief, Engineering conventions).
  - transcript_<session_id>.txt : human-readable transcript for eyeballing.

Never log secrets. The API key is never written to logs.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .config import REPO_ROOT


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}"


class RunLogger:
    """Append-only logger for a single experiment run."""

    def __init__(self, run_id: str, base_dir: str | Path = "logs"):
        self.run_id = run_id
        self.dir = (REPO_ROOT / base_dir / run_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.calls_path = self.dir / "calls.jsonl"
        self._call_seq = 0

    def log_call(self, record: dict[str, Any]) -> None:
        """Append a full model-call record to calls.jsonl."""
        self._call_seq += 1
        record = {
            "seq": self._call_seq,
            "ts": time.time(),
            "run_id": self.run_id,
            **record,
        }
        with open(self.calls_path, "a") as f:
            f.write(json.dumps(record, default=_json_default) + "\n")

    def write_transcript(self, session_id: str, header: dict[str, Any], turns: list) -> Path:
        """Write a readable transcript file for one session."""
        path = self.dir / f"transcript_{session_id}.txt"
        lines = [f"# Transcript: {session_id}", ""]
        for k, v in header.items():
            lines.append(f"{k}: {v}")
        lines.append("")
        lines.append("=" * 70)
        for t in turns:
            t = t if isinstance(t, dict) else asdict(t)
            speaker = t.get("speaker", "?").upper()
            text = t.get("text", "")
            extra = t.get("meta", {})
            lines.append(f"\n[{speaker}]")
            lines.append(text.strip())
            if extra:
                lines.append(f"   (meta: {json.dumps(extra, default=_json_default)})")
        lines.append("\n" + "=" * 70)
        path.write_text("\n".join(lines))
        return path

    def write_json(self, name: str, obj: Any) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(obj, indent=2, default=_json_default))
        return path


def _json_default(o: Any) -> Any:
    if is_dataclass(o):
        return asdict(o)
    return str(o)
