"""Command line entry point for ``lintsmith``."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from lintsmith import (
    __version__,
    bench,
    drift,
    generate,
    mapping_sync,
    release_notes,
    report,
    repository_settings,
    smoke,
    upstream,
)

COMMANDS: dict[str, tuple[Callable[[Sequence[str] | None], int | None], str]] = {
    "generate": (generate.main, "Generate a lean image build context from VALIDATE_* flags."),
    "drift": (drift.main, "Fail when changed files are not covered by the configured linters."),
    "sync-mapping": (mapping_sync.main, "Compare the linter mapping with an upstream checkout and add drafts."),
    "release-notes": (release_notes.main, "Write release notes comparing benchmarks of two upstream versions."),
    "bench": (bench.main, "Time cold or warm pulls and container start of an image."),
    "compare": (report.main_compare, "Compare lean images with their upstream baseline from benchmark results."),
    "summarize": (report.main_summarize, "Summarize benchmark results, one row per variant."),
    "repository-settings": (repository_settings.main, "Print or apply the repository settings (maintainers)."),
    "smoke": (smoke.main, "Lint upstream's good and bad fixtures with a built image."),
    "select-upstream": (upstream.main, "Pick the upstream release to sync to, honouring a cooldown."),
}


def usage() -> str:
    width = max(len(name) for name in COMMANDS)
    lines = ["usage: lintsmith <command> [options]", "", "commands:"]
    lines += [f"  {name:<{width}}  {help_text}" for name, (_, help_text) in COMMANDS.items()]
    lines += [
        "",
        "Run 'lintsmith <command> --help' for the options of a command.",
        "  --version  show the version",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    if args[0] == "--version":
        print(f"lintsmith {__version__}")
        return 0
    command = args[0]
    if command not in COMMANDS:
        print(f"lintsmith: unknown command '{command}'\n\n{usage()}", file=sys.stderr)
        return 2
    return COMMANDS[command][0](args[1:]) or 0
