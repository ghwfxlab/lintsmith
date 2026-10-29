"""Read a repository's Super-Linter configuration.

Sources: env files (VALIDATE_*=true lines) and GitHub Actions workflows (the
`env:` of the workflow, the job and the Super-Linter step).

Semantics follow upstream lib/functions/validation.sh:
    - no VALIDATE_<LANGUAGE> variable set: every linter is enabled
    - any set to true and none to false: only those are enabled
    - any set to false and none to true: every linter except those is enabled
    - mixing true and false is an error
"""

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

NON_LINTER = {"ALL_CODEBASE"}
SETTINGS = ("FILTER_REGEX_INCLUDE", "FILTER_REGEX_EXCLUDE", "LINTER_RULES_PATH")


class ConfigError(Exception):
    pass


def parse_env_text(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m:
            out[m.group(1)] = m.group(2).strip("\"'")
    return out


def parse_env_files(paths: Iterable[str | Path]) -> dict[str, str]:
    out = {}
    for p in paths:
        out.update(parse_env_text(Path(p).read_text()))
    return out


def parse_workflow(path: str | Path) -> dict[str, str]:
    """Merge the env of every Super-Linter step found in a workflow."""
    import yaml  # PyYAML is on GitHub-hosted runners

    doc = yaml.safe_load(Path(path).read_text()) or {}
    out, found = {}, False
    base = {k: str(v) for k, v in (doc.get("env") or {}).items()}
    for job in (doc.get("jobs") or {}).values():
        job_env = {k: str(v) for k, v in (job.get("env") or {}).items()}
        for step in job.get("steps") or []:
            uses = str(step.get("uses", ""))
            if not uses.startswith("super-linter/super-linter"):
                continue
            found = True
            step_env = {k: str(v) for k, v in (step.get("env") or {}).items()}
            out.update({**base, **job_env, **step_env})
    if not found:
        raise ConfigError(f"no super-linter/super-linter step found in {path}")
    return out


def effective_flags(env: Mapping[str, str], all_flags: Iterable[str]) -> list[str]:
    """Flags that run, given the environment and the full list of upstream flags."""
    set_true: set[str] = set()
    set_false: set[str] = set()
    for key, value in env.items():
        m = re.fullmatch(r"VALIDATE_([A-Z0-9_]+)", key)
        if not m or m.group(1) in NON_LINTER:
            continue
        flag = m.group(1)
        v = value.strip().lower()
        if v not in ("true", "false"):
            raise ConfigError(f"{key} must be true or false, got {value!r}")
        (set_true if v == "true" else set_false).add(flag)
    if set_true and set_false:
        raise ConfigError("VALIDATE_* variables mix true and false: " + ", ".join(sorted(set_true | set_false)))
    if set_true:
        return sorted(set_true)
    if set_false:
        return sorted(set(all_flags) - set_false)
    return sorted(all_flags)
