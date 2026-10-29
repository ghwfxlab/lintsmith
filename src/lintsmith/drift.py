"""Fail a pull request that adds files the repository's lean image does not lint.

Usage:
    lintsmith drift --workflow .github/workflows/linter.yml --base origin/main
    lintsmith drift --env super-linter.env --files-from changed.txt

The configuration comes from a workflow (--workflow, the env of the
super-linter step) and/or env files (--env). The changed files come from git
(--base: files added, copied, modified or renamed since that ref) or a list
(--files-from). A file is "uncovered" when upstream would lint it with at
least one linter but none of those linters is enabled in the configuration.
Files matching FILTER_REGEX_EXCLUDE (or not matching FILTER_REGEX_INCLUDE) are
skipped, as Super-Linter skips them.

Exit code: 0 all covered, 1 uncovered files found, 2 configuration error.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from lintsmith import config as slconfig

HERE = Path(__file__).resolve().parent / "data"


def file_flags(path: str, table: dict[str, Any], root: str | None = None) -> list[str]:
    """Flags upstream would run on `path` (file-type specific ones only)."""
    p = path.replace("\\", "/")
    base = p.rsplit("/", 1)[-1].lower()
    ext = base.rsplit(".", 1)[-1] if "." in base else ""
    flags, first_line = [], None
    for rule in table["rules"]:
        ok = False
        if "ext" in rule and ext in rule["ext"] and ("path" not in rule or re.search(rule["path"], p)):
            ok = True
        if "name" in rule and re.search(rule["name"], base):
            ok = True
        if "path" in rule and "ext" not in rule and re.search(rule["path"], p):
            ok = True
        if "shebang" in rule and ext == "" and root is not None:
            if first_line is None:
                try:
                    with open(os.path.join(root, path), errors="ignore") as fh:
                        first_line = fh.readline()
                except OSError:
                    first_line = ""
            if re.search(rule["shebang"], first_line):
                ok = True
        if ok and "exclude_path" in rule and re.search(rule["exclude_path"], p):
            ok = False
        if ok:
            flags += [f for f in rule["flags"] if f not in flags]
    return flags


def selected(path: str, env: Mapping[str, str]) -> bool:
    inc, exc = env.get("FILTER_REGEX_INCLUDE"), env.get("FILTER_REGEX_EXCLUDE")
    target = "/" + path
    if inc and not re.search(inc, target):
        return False
    if exc and re.search(exc, target):
        return False
    return True


def changed_files(base: str, root: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", root, "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        # fall back to a two-dot diff, e.g. for shallow clones
        out = subprocess.run(
            ["git", "-C", root, "diff", "--name-only", "--diff-filter=ACMR", base, "HEAD"],
            capture_output=True,
            text=True,
        )
    if out.returncode != 0:
        raise slconfig.ConfigError(f"git diff against {base} failed: {out.stderr.strip()}")
    return [line for line in out.stdout.splitlines() if line]


def check(
    env: Mapping[str, str],
    files: Iterable[str],
    upstream_flags: Collection[str],
    table: dict[str, Any],
    root: str | None = None,
    allow_ext: Collection[str] = (),
) -> list[dict[str, Any]]:
    enabled = set(slconfig.effective_flags(env, upstream_flags))
    findings = []
    for f in files:
        if not selected(f, env):
            continue
        base = f.rsplit("/", 1)[-1].lower()
        ext = base.rsplit(".", 1)[-1] if "." in base else ""
        if ext in allow_ext or base in allow_ext:
            continue
        flags = [x for x in file_flags(f, table, root) if x in upstream_flags]
        if flags and not (set(flags) & enabled):
            findings.append({"file": f, "flags": flags})
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workflow", action="append", default=[], help="workflow with a super-linter step (repeatable)")
    ap.add_argument("--env", action="append", default=[], help="env file with VALIDATE_* lines (repeatable)")
    ap.add_argument("--base", help="git ref to diff against, e.g. origin/main")
    ap.add_argument("--files-from", help="file with one changed path per line")
    ap.add_argument("--root", default=".", help="repository root (default: current directory)")
    ap.add_argument(
        "--allow-ext",
        action="append",
        default=[],
        metavar="EXT",
        help="file extension or file name you deliberately do not lint, e.g. txt or dockerfile (repeatable)",
    )
    ap.add_argument("--warn-only", action="store_true", help="report but exit 0")
    ap.add_argument("--mapping", default=str(HERE / "linters.json"))
    ap.add_argument("--filetypes", default=str(HERE / "filetypes.json"))
    ap.add_argument("--report", help="write a Markdown report here")
    args = ap.parse_args(argv)

    try:
        env = {}
        for w in args.workflow:
            env.update(slconfig.parse_workflow(w))
        env.update(slconfig.parse_env_files(args.env))
        if not env:
            raise slconfig.ConfigError("give --workflow or --env")
        if args.files_from:
            files = [line.strip() for line in Path(args.files_from).read_text().splitlines() if line.strip()]
        elif args.base:
            files = changed_files(args.base, args.root)
        else:
            raise slconfig.ConfigError("give --base or --files-from")
        upstream_flags = set(json.loads(Path(args.mapping).read_text())["linters"])
        table = json.loads(Path(args.filetypes).read_text())
        findings = check(env, files, upstream_flags, table, args.root, [e.lower().lstrip(".") for e in args.allow_ext])
    except slconfig.ConfigError as e:
        print(f"::error::{e}")
        return 2

    lines = [
        "### Lean image drift check",
        "",
        f"Checked {len(files)} changed file(s); {len(findings)} not covered by the configured linters.",
        "",
    ]
    for f in findings:
        opts = ", ".join(f"`VALIDATE_{x}`" for x in f["flags"])
        msg = (
            f"{f['file']} would be linted by Super-Linter ({', '.join(f['flags'])}), but none of those linters "
            f"is enabled, so the lean image does not contain them and the file would go unchecked. "
            f"Enable one of: {', '.join('VALIDATE_' + x for x in f['flags'])} and rebuild the image, "
            f"or add the extension to the allow list if the file should not be linted."
        )
        print(f"::error file={f['file']}::{msg}")
        lines.append(f"- `{f['file']}`: enable one of {opts}")
    if findings:
        lines += [
            "",
            "To fix: enable one of the listed linters in the Super-Linter configuration (the lean image is "
            "rebuilt from it), or pass `--allow-ext <ext>` for file types you do not want linted.",
        ]
    report = "\n".join(lines)
    print(report)
    if args.report:
        Path(args.report).write_text(report + "\n")
    if findings and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
