"""Smoke-test a built image against Super-Linter's own good and bad fixtures.

Usage:
    superlint-lean smoke <image> <plan.json> <upstream-dir> [--mapping linters.json] [--jobs N]

    plan.json
        written by ``superlint-lean generate`` (its "flags" list)
    upstream-dir
        a Super-Linter checkout at the tag the image was built from; only
        ``test/linters`` and ``.editorconfig`` are read (MIT licensed, never
        copied into this repository or the image)

Each flag uses ``test/linters/<flag in lower case>``. Files with "good" in their
path must pass and files with "bad" must fail (files with neither are support
files and are copied to both runs), judged by the Super-Linter summary, so a linter that found no files to lint does not count as a pass.
Only that one linter is enabled, so the run also shows that the image lints
with a lean flag set. Upstream's own ``TEST_CASE_RUN`` mode cannot be used: it
refuses to run unless every validation is enabled.

Then it enables every flag of the plan at once, puts the bad fixtures of the
mapped linters that are not enabled into the repository, and checks that none
of them shows up in the summary: a disabled linter is skipped, not run and not
failing.

Prints a Markdown table. Exit code: 0 every flag behaved, 1 at least one did
not, 2 a bad argument.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MAPPING = Path(__file__).resolve().parent / "data" / "linters.json"

# these linters only look at files under one directory of the repository
FLAG_DIRECTORIES = {
    "GITHUB_ACTIONS": Path(".github") / "workflows",
    "GITHUB_ACTIONS_ZIZMOR": Path(".github") / "workflows",
    "ANSIBLE": Path("ansible"),
}
SUMMARY = Path("super-linter-output") / "super-linter-summary.md"

# Files of the upstream repository that a linter reads from the repository it lints.
UPSTREAM_CONFIG = {
    "EDITORCONFIG": (".editorconfig",),
    "CSHARP": (".editorconfig",),
    "DOTNET_SLN_FORMAT_WHITESPACE": (".editorconfig",),
    "KOTLIN": (".editorconfig",),
    "CLOJURE": (".github/linters/.clj-kondo",),
    "JSONC": (".github/linters/eslint.config.mjs",),
    "VUE": (".github/linters/eslint.config.mjs",),
}

# Fixtures that do not behave on upstream's own image either (checked against ghcr.io/super-linter/super-linter:v9.0.0):
# CKV_K8S_14 fails a good Kubernetes fixture, the bad pre-commit fixture is accepted, and the biome.json
# next to the good biome fixture is itself linted and fails the formatter.
KNOWN_FIXTURE_ISSUES = frozenset({("CHECKOV", "good"), ("PRE_COMMIT", "bad"), ("BIOME_FORMAT", "good")})

CLEAN = "pass"
ERRORS = "fail"
NOT_LINTED = "not-linted"
NO_FILES = "no-files"
KNOWN_ISSUE = "known-issue"


def fixture_dir(upstream: Path, flag: str) -> Path:
    return upstream / "test" / "linters" / flag.lower()


def destination(repo: Path, flag: str) -> Path:
    return repo / FLAG_DIRECTORIES.get(flag, Path())


def copy_fixtures(source: Path, kind: str, dest: Path) -> int:
    """Copy the fixtures for a `kind` ("good" or "bad") run; return how many files are of that kind.

    Files of the other kind stay out. Files that are neither good nor bad (a package-info.java,
    an .editorconfig, a .sqlfluff) are support files of the fixtures and come along.
    """
    other = "bad" if kind == "good" else "good"
    copied = 0
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        relative = path.relative_to(source)
        name = relative.as_posix().lower()
        if other in name:
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if kind in name:
            copied += 1
    return copied


def verdict(summary: str, flag: str) -> str:
    """What the Super-Linter summary says about `flag`: pass, fail or not-linted."""
    for line in summary.splitlines():
        match = re.match(rf"^\|\s*{re.escape(flag)}\s*\|(.*)\|", line)
        if match:
            if "Pass" in match.group(1):
                return CLEAN
            if "Fail" in match.group(1):
                return ERRORS
    return NOT_LINTED


def docker_command(image: str, repo: Path, flags: Sequence[str]) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "-e",
        "RUN_LOCAL=true",
        "-e",
        "DEFAULT_BRANCH=main",
        "-e",
        "VALIDATE_ALL_CODEBASE=true",
        "-e",
        "MULTI_STATUS=false",
        "-e",
        "ENABLE_GITHUB_PULL_REQUEST_SUMMARY_COMMENT=false",
        "-e",
        "SAVE_SUPER_LINTER_SUMMARY=true",
        "-e",
        "LOG_LEVEL=ERROR",
        *[arg for flag in flags for arg in ("-e", f"VALIDATE_{flag}=true")],
        "-v",
        f"{repo}:/tmp/lint",
        image,
    ]


def init_repository(repo: Path) -> None:
    """Super-Linter lints a git repository; commit the copied fixtures.

    Add them with -f: the commitlint fixtures bring a .gitignore that ignores everything, which
    would hide every other fixture once they share a repository.
    """
    for args in (
        ["init", "-q", "-b", "main"],
        ["remote", "add", "origin", "https://github.com/example/fixtures.git"],
        ["add", "-A", "-f"],
        ["-c", "user.email=smoke@example.com", "-c", "user.name=smoke", "commit", "-qm", "fixtures"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def run_image(image: str, repo: Path, flags: Sequence[str]) -> None:
    """Run the image on `repo`. A failing lint exits non-zero; the verdict comes from the summary."""
    subprocess.run(docker_command(image, repo, flags), check=False, capture_output=True)


def clear_directory(image: str, work: Path) -> None:
    """The container runs as root, so remove its output from inside an image."""
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{work}:/work",
            "--entrypoint",
            "sh",
            image,
            "-c",
            "rm -rf /work/* /work/.[!.]*",
        ],
        check=False,
        capture_output=True,
    )
    shutil.rmtree(work, ignore_errors=True)


def add_upstream_config(upstream: Path, repo: Path, flags: Sequence[str]) -> None:
    """Copy the upstream files the `flags` read from the repository they are tested in.

    Copy them before the fixtures: a fixture directory may bring its own .editorconfig,
    which has to win. Only the files a linter needs go in: the others would be linted as
    part of the repository (biome rejects the .editorconfig and the files of .github/linters).
    """
    repo.mkdir(parents=True, exist_ok=True)
    for relative in sorted({path for flag in flags for path in UPSTREAM_CONFIG.get(flag, ())}):
        source = upstream / relative
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        elif source.is_file():
            shutil.copy2(source, target)


def result(image: str, flag: str, kind: str, source: Path, upstream: Path, work: Path) -> str:
    """pass, fail, not-linted, no-files when the fixtures have no `kind` file, or known-issue."""
    if (flag, kind) in KNOWN_FIXTURE_ISSUES:
        return KNOWN_ISSUE
    repo = work / f"{flag}-{kind}"
    add_upstream_config(upstream, repo, [flag])
    if copy_fixtures(source, kind, destination(repo, flag)) == 0:
        return NO_FILES
    init_repository(repo)
    run_image(image, repo, [flag])
    summary = repo / SUMMARY
    return verdict(summary.read_text() if summary.exists() else "", flag)


def skipped(image: str, enabled: Sequence[str], mapped: Sequence[str], upstream: Path, work: Path) -> tuple[str, bool]:
    """Run every enabled linter on the bad files of the disabled ones; the disabled must not appear."""
    disabled = [flag for flag in mapped if flag not in enabled and fixture_dir(upstream, flag).is_dir()]
    if not disabled:
        return "Disabled linters: none to test", True
    repo = work / "disabled"
    add_upstream_config(upstream, repo, enabled)
    for flag in disabled:
        copy_fixtures(fixture_dir(upstream, flag), "bad", destination(repo, flag))
    probe = next((flag for flag in enabled if fixture_dir(upstream, flag).is_dir()), "")
    if probe:
        copy_fixtures(fixture_dir(upstream, probe), "good", destination(repo, probe))
    init_repository(repo)
    run_image(image, repo, enabled)
    summary = repo / SUMMARY
    text = summary.read_text() if summary.exists() else ""
    if probe and verdict(text, probe) == NOT_LINTED:
        return f"Disabled linters: FAIL (the image did not lint: {probe} is missing from the summary)", False
    ran = [flag for flag in disabled if verdict(text, flag) != NOT_LINTED]
    if ran:
        return f"Disabled linters: FAIL (ran although disabled: {', '.join(ran)})", False
    return f"Disabled linters: ok ({len(disabled)} skipped)", True


def cell(outcome: str, expected: str, label: str) -> tuple[str, bool]:
    """Table cell and whether it is a failure."""
    if outcome == expected:
        return "ok", False
    if outcome == NO_FILES:
        return f"no {label} file", False
    if outcome == KNOWN_ISSUE:
        return "skipped (known upstream issue)", False
    return f"FAIL ({outcome})", True


def check_flag(image: str, flag: str, upstream: Path, work: Path) -> tuple[str, bool]:
    """The table row of `flag` and whether it failed; progress goes to stderr."""
    source = fixture_dir(upstream, flag)
    if not source.is_dir():
        row, failed = f"| {flag} | no fixture | no fixture |", False
    else:
        good, good_failed = cell(result(image, flag, "good", source, upstream, work), CLEAN, "good")
        bad, bad_failed = cell(result(image, flag, "bad", source, upstream, work), ERRORS, "bad")
        row, failed = f"| {flag} | {good} | {bad} |", good_failed or bad_failed
    print(f"{flag}: {'FAIL' if failed else 'done'}", file=sys.stderr, flush=True)
    return row, failed


def work_directory() -> Path:
    """A new directory the Docker daemon can mount.

    On GitHub Actions it is under RUNNER_TEMP: the daemon of a self-hosted runner does not always see /tmp.
    """
    return Path(tempfile.mkdtemp(dir=os.environ.get("RUNNER_TEMP") or None))


def smoke(
    image: str, flags: Sequence[str], upstream: Path, mapped: Sequence[str] = (), jobs: int = 1
) -> tuple[list[str], bool]:
    """The Markdown lines and whether every flag behaved and the disabled linters were skipped.

    Up to `jobs` flags are tested at the same time; the rows keep the order of `flags`.
    """
    lines = ["| Flag | Good file | Bad file |", "| --- | --- | --- |"]
    work = work_directory()
    try:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            checked = list(pool.map(lambda flag: check_flag(image, flag, upstream, work), flags))
        ok = not any(failed for _row, failed in checked)
        lines += [row for row, _failed in checked]
        line, skipped_ok = skipped(image, flags, mapped, upstream, work)
        ok = ok and skipped_ok
        lines += ["", line]
    finally:
        clear_directory(image, work)
    return lines, ok


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", help="the image to test")
    ap.add_argument("plan", help="plan.json written by `superlint-lean generate`")
    ap.add_argument("upstream", help="a Super-Linter checkout at the tag the image was built from")
    ap.add_argument(
        "--mapping", default=str(MAPPING), help="linters.json; its flags that are not in the plan must be skipped"
    )
    ap.add_argument("--jobs", type=int, default=1, help="test this many flags at the same time (default: %(default)s)")
    args = ap.parse_args(argv)
    if args.jobs < 1:
        print(f"::error::--jobs must be at least 1, got {args.jobs}")
        return 2

    try:
        flags: list[str] = json.loads(Path(args.plan).read_text())["flags"]
        mapped: list[str] = list(json.loads(Path(args.mapping).read_text())["linters"])
    except (OSError, ValueError, KeyError) as e:
        print(f"::error::cannot read the flags from {args.plan} or {args.mapping}: {e}")
        return 2
    lines, ok = smoke(args.image, flags, Path(args.upstream), mapped, args.jobs)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
