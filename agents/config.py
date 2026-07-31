"""YAML config loading and merging.

All model strings and parameters are read from config at runtime; nothing is
hardcoded in agent code (per the build brief). Paths in config files are
resolved relative to the repository root.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Repo root = parent of this file's directory (agents/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent


def repo_path(p: str | os.PathLike) -> Path:
    """Resolve a possibly-relative path against the repo root."""
    p = Path(p)
    return p if p.is_absolute() else (REPO_ROOT / p)


def load_yaml(path: str | os.PathLike) -> dict[str, Any]:
    with open(repo_path(path), "r") as f:
        return yaml.safe_load(f) or {}


def load_models_config(path: str | os.PathLike = "configs/models.yaml") -> dict[str, Any]:
    """Load the per-role model configuration."""
    cfg = load_yaml(path)
    assert "roles" in cfg, "models config must define 'roles'"
    for role in ("tutor", "student", "judge"):
        assert role in cfg["roles"], f"models config missing role: {role}"
    return cfg


def role_spec(models_cfg: dict[str, Any], role: str) -> dict[str, Any]:
    """Return {model, temperature, max_tokens} for a role."""
    return models_cfg["roles"][role]


def resolve_backend(models_cfg: dict[str, Any], override: str | None = None) -> str:
    """Backend precedence: CLI override > env CVP_BACKEND > config > 'mock'."""
    if override:
        return override
    return os.environ.get("CVP_BACKEND") or models_cfg.get("backend") or "mock"
