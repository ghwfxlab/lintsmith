"""Tests for lintsmith.repository_settings."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from lintsmith import cli, repository_settings

REPOSITORY = "owner/repo"


class FakeGh:
    """Stands in for subprocess.run: records the gh calls and returns a chosen exit code."""

    def __init__(self, codes: list[int] | None = None) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.codes = codes or []

    def __call__(self, command: list[str], input: str | None, text: bool, check: bool) -> Any:
        self.calls.append((command, input))
        code = self.codes[len(self.calls) - 1] if len(self.calls) <= len(self.codes) else 0
        return subprocess.CompletedProcess(command, code)


class TestCalls:
    def test_calls_should_cover_merge_settings_actions_settings_and_the_ruleset_when_the_settings_are_built(
        self,
    ) -> None:
        calls = repository_settings.calls()

        paths = [call.path for call in calls]
        assert paths == ["", "actions/permissions", "actions/permissions/workflow", "rulesets"]

    def test_calls_should_keep_workflows_from_approving_pull_requests_when_the_settings_are_built(self) -> None:
        calls = repository_settings.calls()

        workflow = calls[2]
        assert workflow.typed["can_approve_pull_request_reviews"] == "false"
        assert workflow.raw["default_workflow_permissions"] == "read"

    def test_calls_should_allow_only_squash_merges_with_the_pr_title_and_body_when_the_settings_are_built(
        self,
    ) -> None:
        calls = repository_settings.calls()

        merge = calls[0]
        assert merge.typed["allow_squash_merge"] == "true"
        assert merge.typed["allow_merge_commit"] == "false"
        assert merge.typed["allow_rebase_merge"] == "false"
        assert merge.raw["squash_merge_commit_title"] == "PR_TITLE"

    def test_ruleset_should_require_the_checks_and_a_squash_only_pull_request_when_the_ruleset_is_built(self) -> None:
        rules = {rule["type"]: rule for rule in repository_settings.RULESET["rules"]}

        required = rules["required_status_checks"]["parameters"]["required_status_checks"]
        checks = [check["context"] for check in required]
        assert checks == ["Lint, type-check, test", "Run Super-Linter", "Validate PR Title"]
        assert rules["pull_request"]["parameters"]["allowed_merge_methods"] == ["squash"]
        assert "required_linear_history" in rules


class TestArguments:
    def test_arguments_should_send_typed_fields_with_dash_big_f_and_raw_with_dash_f_when_both_are_set(self) -> None:
        call = repository_settings.Call("t", "PUT", "x", typed={"a": "true"}, raw={"b": "all"})

        args = call.arguments(REPOSITORY)

        assert args == ["api", "--method", "PUT", "repos/owner/repo/x", "-F", "a=true", "-f", "b=all"]

    def test_arguments_should_read_the_body_from_stdin_when_the_call_has_one(self) -> None:
        call = repository_settings.Call("t", "POST", "rulesets", body={"name": "n"})

        args = call.arguments(REPOSITORY)

        assert args[-2:] == ["--input", "-"]


class TestMain:
    def test_main_should_print_the_calls_and_not_run_gh_when_apply_is_not_given(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gh = FakeGh()
        monkeypatch.setattr(repository_settings.subprocess, "run", gh)

        code = repository_settings.main([REPOSITORY])

        output = capsys.readouterr().out
        assert code == 0
        assert gh.calls == []
        assert "would run: gh api --method POST repos/owner/repo/rulesets --input -" in output

    def test_main_should_send_every_call_through_gh_when_apply_is_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gh = FakeGh()
        monkeypatch.setattr(repository_settings.subprocess, "run", gh)

        code = repository_settings.main([REPOSITORY, "--apply"])

        methods = [command[3] for command, _stdin in gh.calls]
        ruleset_body = json.loads(gh.calls[-1][1] or "{}")
        assert code == 0
        assert methods == ["PATCH", "PUT", "PUT", "POST"]
        assert ruleset_body["name"] == "Enforce Main Protections"

    def test_main_should_return_one_and_keep_going_when_a_call_fails(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gh = FakeGh(codes=[0, 1, 0, 0])
        monkeypatch.setattr(repository_settings.subprocess, "run", gh)

        code = repository_settings.main([REPOSITORY, "--apply"])

        sent_calls = len(gh.calls)
        output = capsys.readouterr().out
        assert code == 1
        assert sent_calls == 4
        assert "gh api failed with exit code 1" in output

    def test_main_should_return_two_when_the_repository_has_no_slash(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = repository_settings.main(["noslash"])

        assert code == 2
        assert "expected OWNER/REPO" in capsys.readouterr().out

    def test_main_should_return_two_when_the_repository_has_two_slashes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = repository_settings.main(["a/b/c"])

        assert code == 2
        assert "expected OWNER/REPO" in capsys.readouterr().out

    def test_main_should_return_two_when_the_repository_name_is_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = repository_settings.main(["owner/"])

        assert code == 2
        assert "expected OWNER/REPO" in capsys.readouterr().out

    def test_main_should_return_two_when_the_owner_is_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = repository_settings.main(["/repo"])

        assert code == 2
        assert "expected OWNER/REPO" in capsys.readouterr().out

    def test_main_should_return_two_when_the_repository_contains_a_space(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = repository_settings.main(["o wner/repo"])

        assert code == 2
        assert "expected OWNER/REPO" in capsys.readouterr().out

    def test_cli_should_dispatch_to_repository_settings_when_the_command_is_given(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cli.main(["repository-settings", REPOSITORY])

        assert code == 0
        assert "Branch ruleset for the default branch" in capsys.readouterr().out
