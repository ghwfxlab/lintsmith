"""Shared test constants and helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "src" / "lintsmith" / "data"
WORKFLOW_FIXTURE = ROOT / "tests" / "fixtures" / "ghwm-workflow.yml"

UPSTREAM_TAG = "v9.0.0"
FLAG_YAML = "YAML"
FLAG_JSON = "JSON"
ENV_YAML = "VALIDATE_YAML"
ENV_JSON = "VALIDATE_JSON"
ENV_TRUE = "true"
ENV_FALSE = "false"
PYTHON_BASE = "python:3.13-alpine3.22"
UPSTREAM_DOCKERFILE_TEXT = f"FROM {PYTHON_BASE} AS python-base\n"


def load_mapping() -> dict[str, Any]:
    mapping: dict[str, Any] = json.loads((DATA_DIR / "linters.json").read_text())
    return mapping


def load_filetypes() -> dict[str, Any]:
    table: dict[str, Any] = json.loads((DATA_DIR / "filetypes.json").read_text())
    return table


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def bench_row(
    kind: str,
    pull_s: float,
    uncompressed_mb: int = 700,
    compressed_mb: int = 150,
    mode: str = "cold",
) -> dict[str, Any]:
    return {
        "variant": f"p/{kind}",
        "mode": mode,
        "pull_s": pull_s,
        "uncompressed_bytes": uncompressed_mb * 1048576,
        "compressed_bytes": compressed_mb * 1048576,
    }


UPSTREAM_TAG_NEWER = "v9.1.0"
UPSTREAM_TAG_NEWEST = "v9.2.0"
PUBLISHED_LONG_AGO = "2026-09-01T12:00:00Z"
PUBLISHED_LAST_MONTH = "2026-10-01T12:00:00Z"
PUBLISHED_YESTERDAY = "2026-10-12T12:00:00Z"


def release_entry(tag: str, published_at: str, *, draft: bool = False, prerelease: bool = False) -> dict[str, Any]:
    """One entry of the GitHub releases API."""
    return {"tag_name": tag, "published_at": published_at, "draft": draft, "prerelease": prerelease}
