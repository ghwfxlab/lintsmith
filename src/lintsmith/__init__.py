"""Lean, pinned Super-Linter images generated from VALIDATE_* flags."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lintsmith")
except PackageNotFoundError:  # pragma: no cover - running from a source tree without metadata
    __version__ = "0.0.0"
