"""Tests for lintsmith.cli."""

from __future__ import annotations

import subprocess
import sys

import pytest

from lintsmith import __version__, cli

TEST_UNKNOWN_COMMAND = "frobnicate"
TEST_USAGE_HEADER = "usage: lintsmith"


class TestMain:
    def test_main_should_print_usage_and_return_zero_when_no_arguments_are_given(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cli.main([])

        output = capsys.readouterr().out
        listed_commands = [command for command in cli.COMMANDS if command in output]
        assert code == 0
        assert listed_commands == list(cli.COMMANDS)

    def test_main_should_print_usage_when_the_short_help_flag_is_given(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cli.main(["-h"])

        assert code == 0
        assert TEST_USAGE_HEADER in capsys.readouterr().out

    def test_main_should_print_usage_when_the_long_help_flag_is_given(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = cli.main(["--help"])

        assert code == 0
        assert TEST_USAGE_HEADER in capsys.readouterr().out

    def test_main_should_print_usage_when_the_help_word_is_given(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = cli.main(["help"])

        assert code == 0
        assert TEST_USAGE_HEADER in capsys.readouterr().out

    def test_main_should_print_the_version_when_version_flag_is_given(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = cli.main(["--version"])

        assert code == 0
        assert capsys.readouterr().out.strip() == f"lintsmith {__version__}"

    def test_main_should_return_two_when_the_command_is_unknown(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = cli.main([TEST_UNKNOWN_COMMAND])

        assert code == 2
        assert f"unknown command '{TEST_UNKNOWN_COMMAND}'" in capsys.readouterr().err

    def test_main_should_dispatch_to_the_command_when_it_is_known(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = cli.main(["drift", "--base", "origin/main"])

        assert code == 2
        assert "give --workflow or --env" in capsys.readouterr().out


class TestModuleEntryPoint:
    def test_module_entry_point_should_print_the_version_when_run_with_python_dash_m(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "lintsmith", "--version"], capture_output=True, text=True, check=False
        )

        assert result.returncode == 0
        assert result.stdout.strip() == f"lintsmith {__version__}"
