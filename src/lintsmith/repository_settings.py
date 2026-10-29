"""Apply the repository settings described in docs/repository-settings.md.

Usage:
    lintsmith repository-settings OWNER/REPO            print what would be sent
    lintsmith repository-settings OWNER/REPO --apply    apply (needs the gh CLI, logged in as an administrator)

Maintainer tooling: the settings are not stored in Git, so this keeps them reproducible.

Exit code: 0 done (or printed), 1 a call failed, 2 a bad argument.
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

REPOSITORY = re.compile(r"^[\w.-]+/[\w.-]+$")

RULESET: dict[str, Any] = {
    "name": "Enforce Main Protections",
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "rules": [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "required_linear_history"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews_on_push": True,
                "require_code_owner_review": False,
                "require_last_push_approval": True,
                "required_review_thread_resolution": True,
                "allowed_merge_methods": ["squash"],
            },
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [
                    {"context": "Lint, type-check, test"},
                    {"context": "Run Super-Linter"},
                    {"context": "Validate PR Title"},
                ],
            },
        },
    ],
}


@dataclass(frozen=True)
class Call:
    """One GitHub API call. `typed` fields are sent with -F (true/false become booleans), `raw` with -f."""

    title: str
    method: str
    path: str
    typed: dict[str, str] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] | None = None

    def arguments(self, repository: str) -> list[str]:
        args = ["api", "--method", self.method, f"repos/{repository}/{self.path}"]
        for key, value in self.typed.items():
            args += ["-F", f"{key}={value}"]
        for key, value in self.raw.items():
            args += ["-f", f"{key}={value}"]
        if self.body is not None:
            args += ["--input", "-"]
        return args


def calls() -> list[Call]:
    return [
        Call(
            "Repository merge and feature settings",
            "PATCH",
            "",
            typed={
                "allow_squash_merge": "true",
                "allow_merge_commit": "false",
                "allow_rebase_merge": "false",
                "allow_auto_merge": "false",
                "delete_branch_on_merge": "true",
                "allow_update_branch": "true",
                "has_wiki": "false",
                "has_projects": "false",
            },
            raw={"squash_merge_commit_title": "PR_TITLE", "squash_merge_commit_message": "PR_BODY"},
        ),
        Call(
            "GitHub Actions: pin actions to commit SHAs",
            "PUT",
            "actions/permissions",
            typed={"enabled": "true", "sha_pinning_required": "true"},
            raw={"allowed_actions": "all"},
        ),
        Call(
            "GitHub Actions: read-only default token, workflows cannot approve pull requests",
            "PUT",
            "actions/permissions/workflow",
            typed={"can_approve_pull_request_reviews": "false"},
            raw={"default_workflow_permissions": "read"},
        ),
        Call("Branch ruleset for the default branch", "POST", "rulesets", body=RULESET),
    ]


def run(call: Call, repository: str) -> int:
    """Send the call through the gh CLI; return its exit code."""
    stdin = json.dumps(call.body) if call.body is not None else None
    completed = subprocess.run(["gh", *call.arguments(repository)], input=stdin, text=True, check=False)
    return completed.returncode


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repository", help="OWNER/REPO")
    ap.add_argument("--apply", action="store_true", help="send the calls (default: print them)")
    args = ap.parse_args(argv)
    if not REPOSITORY.match(args.repository):
        print(f"::error::expected OWNER/REPO, got '{args.repository}'")
        return 2

    status = 0
    for call in calls():
        print(call.title)
        if not args.apply:
            print("would run: gh " + " ".join(call.arguments(args.repository)))
            continue
        code = run(call, args.repository)
        if code != 0:
            print(f"::error::gh api failed with exit code {code}: {call.title}")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
