"""Compare the bundled linters.json with an upstream Super-Linter checkout and add
draft entries for linters the mapping does not know yet.

Usage:
    lintsmith sync-mapping --upstream path/to/super-linter [--write] [--report report.md]

Reads from the upstream checkout:
    lib/globals/languages.sh        every VALIDATE_* flag (LANGUAGE_ARRAY)
    lib/functions/linterCommands.sh the command each flag runs
    Dockerfile                      where each binary is copied from
    dependencies/python/*.txt       one virtualenv per file
    dependencies/package.json       npm packages

For each flag missing from the mapping it derives a draft entry (marked
"draft": true) by locating the command in the Dockerfile, the virtualenvs or the
npm dependencies. Anything it cannot place is listed as unresolved in the report
and left out of the mapping, so a human can map it. Drafts are verified by the
tool checks when the image is built (see the upstream-sync workflow).

Exit code: 0 when nothing is missing, 10 when drafts were added or unresolved
flags remain, so a workflow can tell the mapping needs attention.
"""

import argparse
import json
import re
import sys
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent / "data"


def upstream_flags(root: Path) -> list[str]:
    text = (root / "lib/globals/languages.sh").read_text()
    m = re.search(r"LANGUAGE_ARRAY=\((.*?)\n\)", text, re.S)
    if not m:
        sys.exit("could not find LANGUAGE_ARRAY in lib/globals/languages.sh")
    body = re.sub(r"#.*", "", m.group(1))
    return re.findall(r"['\"]?([A-Z][A-Z0-9_]*)['\"]?", body)


def upstream_commands(root: Path) -> dict[str, str | None]:
    """flag -> first word of its command, or None if it is built from a variable."""
    text = (root / "lib/functions/linterCommands.sh").read_text()
    out = {}
    for flag, rest in re.findall(r"^LINTER_COMMANDS_ARRAY_([A-Z0-9_]+)=\((.*)$", text, re.M):
        m = re.match(r'"?([A-Za-z][A-Za-z0-9_.\-]*)"?(?:\s|\)|$)', rest)
        out[flag] = m.group(1) if m and not rest.lstrip().startswith('"$') else None
    return out


def dockerfile_binaries(root: Path) -> dict[str, str]:
    """basename -> destination path for every COPY --from=<stage> in the Dockerfile."""
    text = (root / "Dockerfile").read_text().replace("\\\n", " ")
    out: dict[str, str] = {}
    for src, dest in re.findall(r"^COPY\s+--from=\S+\s+(?:--\S+\s+)*(\S+)\s+(\S+)\s*$", text, re.M):
        name = Path(src).name
        dest = dest + name if dest.endswith("/") else dest
        out.setdefault(Path(dest).name, dest)
        out.setdefault(name, dest)
    return out


def npm_packages(root: Path) -> list[str]:
    pkg = json.loads((root / "dependencies/package.json").read_text())
    return sorted({**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})})


def derive(
    flag: str,
    cmd: str | None,
    root: Path,
    bins: Mapping[str, str],
    venv_names: Collection[str],
    npm_pkgs: Iterable[str],
) -> dict[str, Any] | None:
    """Return a draft mapping entry for `cmd`, or None."""
    if cmd is None:
        return None
    check = [f"{cmd} --version"]
    if cmd in venv_names or any(v.startswith(cmd) for v in venv_names):
        v = cmd if cmd in venv_names else next(v for v in venv_names if v.startswith(cmd))
        return {"venvs": [v], "check": check}
    if cmd in bins:
        return {"bins": [bins[cmd]], "check": check}
    for pkg in npm_pkgs:
        bare = pkg.split("/")[-1]
        if bare in (cmd, f"{cmd}-cli") or bare.startswith(cmd + "-lint"):
            return {"npm": [f"__group:{cmd}:{pkg}"], "check": check}
    return None


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream", required=True, help="upstream Super-Linter checkout")
    ap.add_argument("--mapping", default=str(HERE / "linters.json"))
    ap.add_argument("--write", action="store_true", help="add draft entries to the mapping file")
    ap.add_argument("--report", help="write a Markdown report here")
    args = ap.parse_args(argv)

    root = Path(args.upstream)
    path = Path(args.mapping)
    mapping = json.loads(path.read_text())
    table = mapping["linters"]

    flags = upstream_flags(root)
    commands = upstream_commands(root)
    bins = dockerfile_binaries(root)
    venv_names = {p.stem for p in (root / "dependencies/python").glob("*.txt")}
    npm_pkgs = npm_packages(root)

    missing = [f for f in flags if f not in table]
    removed = [f for f in table if f not in flags]
    drafts, unresolved = {}, []
    for f in missing:
        d = derive(f, commands.get(f), root, bins, venv_names, npm_pkgs)
        if d is None:
            unresolved.append((f, commands.get(f)))
            continue
        d["draft"] = True
        drafts[f] = d

    if args.write and drafts:
        for f, d in drafts.items():
            for i, ref in enumerate(d.get("npm", [])):
                if ref.startswith("__group:"):
                    _, grp, pkg = ref.split(":", 2)
                    mapping["npm_groups"].setdefault(grp, [pkg])
                    d["npm"][i] = grp
            table[f] = d
        mapping["linters"] = dict(sorted(table.items()))
        path.write_text(json.dumps(mapping, indent=2) + "\n")

    lines = [
        "### Mapping sync",
        "",
        f"- upstream flags: {len(flags)}",
        f"- mapped flags: {len(table)}",
        f"- new flags with a draft entry: {len(drafts)}",
        f"- new flags needing a manual mapping: {len(unresolved)}",
        f"- mapped flags no longer in upstream: {len(removed)}",
        "",
    ]
    if drafts:
        lines += ["**Drafts (verified only by the tool checks, review before merging):**", ""]
        lines += [f"- `{f}`: `{json.dumps(d)}`" for f, d in drafts.items()] + [""]
    if unresolved:
        lines += ["**Needs a manual mapping (command not found in the Dockerfile, virtualenvs or npm deps):**", ""]
        lines += [f"- `{f}` (command: `{c}`)" for f, c in unresolved] + [""]
    if removed:
        lines += ["**Removed upstream (delete from the mapping if intended):**", ""]
        lines += [f"- `{f}`" for f in removed] + [""]
    report = "\n".join(lines)
    print(report)
    if args.report:
        Path(args.report).write_text(report + "\n")
    return 10 if (drafts or unresolved or removed) else 0


if __name__ == "__main__":
    sys.exit(main())
