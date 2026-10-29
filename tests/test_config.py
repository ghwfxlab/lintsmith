"""Tests for lintsmith.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from lintsmith import config as slconfig
from tests.shared import ENV_FALSE, ENV_JSON, ENV_TRUE, ENV_YAML, FLAG_JSON, FLAG_YAML, WORKFLOW_FIXTURE

TEST_ALL_CODEBASE = "VALIDATE_ALL_CODEBASE"
TEST_RULES_PATH = "LINTER_RULES_PATH"
TEST_RULES_DIRECTORY = ".github/linters"


class TestEffectiveFlags:
    def test_effective_flags_should_enable_everything_when_no_validate_variable_is_set(
        self, upstream_flags: set[str]
    ) -> None:
        flags = slconfig.effective_flags({}, upstream_flags)

        assert set(flags) == upstream_flags

    def test_effective_flags_should_return_only_true_flags_when_some_are_true(self, upstream_flags: set[str]) -> None:
        env = {ENV_YAML: ENV_TRUE, ENV_JSON: ENV_TRUE}

        flags = slconfig.effective_flags(env, upstream_flags)

        assert flags == [FLAG_JSON, FLAG_YAML]

    def test_effective_flags_should_remove_false_flags_when_only_false_flags_are_set(
        self, upstream_flags: set[str]
    ) -> None:
        env = {ENV_YAML: ENV_FALSE}

        flags = slconfig.effective_flags(env, upstream_flags)

        assert set(flags) == upstream_flags - {FLAG_YAML}

    def test_effective_flags_should_raise_when_true_and_false_are_mixed(self, upstream_flags: set[str]) -> None:
        env = {ENV_YAML: ENV_TRUE, ENV_JSON: ENV_FALSE}

        with pytest.raises(slconfig.ConfigError) as exc_info:
            slconfig.effective_flags(env, upstream_flags)

        assert "mix true and false" in str(exc_info.value)

    def test_effective_flags_should_ignore_all_codebase_when_it_is_the_only_other_variable(
        self, upstream_flags: set[str]
    ) -> None:
        env = {TEST_ALL_CODEBASE: ENV_TRUE, ENV_YAML: ENV_TRUE}

        flags = slconfig.effective_flags(env, upstream_flags)

        assert flags == [FLAG_YAML]

    def test_effective_flags_should_raise_when_value_is_not_a_boolean(self, upstream_flags: set[str]) -> None:
        env = {ENV_YAML: "yes"}

        with pytest.raises(slconfig.ConfigError) as exc_info:
            slconfig.effective_flags(env, upstream_flags)

        assert "must be true or false" in str(exc_info.value)


class TestParseEnvText:
    def test_parse_env_text_should_strip_quotes_when_values_are_quoted(self) -> None:
        text = f"{ENV_YAML}={ENV_TRUE}\n{TEST_RULES_PATH}=\"{TEST_RULES_DIRECTORY}\"\nOTHER='x'\n"

        parsed = slconfig.parse_env_text(text)

        assert parsed == {ENV_YAML: ENV_TRUE, TEST_RULES_PATH: TEST_RULES_DIRECTORY, "OTHER": "x"}

    def test_parse_env_text_should_skip_comments_and_blank_lines_when_text_has_them(self) -> None:
        text = f"# comment\n\n{ENV_JSON}={ENV_TRUE}\n"

        parsed = slconfig.parse_env_text(text)

        assert parsed == {ENV_JSON: ENV_TRUE}

    def test_parse_env_files_should_let_later_files_win_when_a_key_repeats(self, tmp_path: Path) -> None:
        first = tmp_path / "first.env"
        second = tmp_path / "second.env"
        first.write_text(f"{ENV_YAML}={ENV_FALSE}\nA=1\n")
        second.write_text(f"{ENV_YAML}={ENV_TRUE}\n")

        parsed = slconfig.parse_env_files([first, second])

        assert parsed == {ENV_YAML: ENV_TRUE, "A": "1"}


class TestParseWorkflow:
    def test_parse_workflow_should_read_step_env_when_workflow_has_a_super_linter_step(self) -> None:
        env = slconfig.parse_workflow(WORKFLOW_FIXTURE)

        assert env["VALIDATE_PYTHON_RUFF"] == ENV_TRUE
        assert env[TEST_RULES_PATH] == TEST_RULES_DIRECTORY

    def test_parse_workflow_should_merge_workflow_job_and_step_env_when_all_define_values(self, tmp_path: Path) -> None:
        workflow = tmp_path / "w.yml"
        workflow.write_text(
            "env:\n  A: workflow\n  B: workflow\n"
            "jobs:\n  lint:\n    env:\n      B: job\n      C: job\n    steps:\n"
            "      - uses: super-linter/super-linter@v9\n        env:\n          C: step\n"
        )

        env = slconfig.parse_workflow(workflow)

        assert env == {"A": "workflow", "B": "job", "C": "step"}

    def test_parse_workflow_should_raise_when_no_super_linter_step_exists(self, tmp_path: Path) -> None:
        workflow = tmp_path / "w.yml"
        workflow.write_text("jobs:\n  build:\n    steps:\n      - run: echo hi\n")

        with pytest.raises(slconfig.ConfigError) as exc_info:
            slconfig.parse_workflow(workflow)

        assert "no super-linter" in str(exc_info.value)
