"""Tests for lintsmith.mapping_sync."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lintsmith import mapping_sync

LANGUAGES_SH = """\
LANGUAGE_ARRAY=(
    'YAML'
    'RUBY'  # a comment
    'MYSTERY'
)
"""
LINTER_COMMANDS_SH = """\
LINTER_COMMANDS_ARRAY_YAML=(yamllint -c "${CONFIG}")
LINTER_COMMANDS_ARRAY_RUBY=(rubocop --config "${CONFIG}")
LINTER_COMMANDS_ARRAY_MYSTERY=(mystery-tool)
LINTER_COMMANDS_ARRAY_DYNAMIC=("${CMD}" --fix)
"""
DOCKERFILE = "FROM alpine AS final\nCOPY --from=builder /usr/local/bin/rubocop /usr/bin/rubocop\n"


@pytest.fixture
def upstream_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "upstream"
    (root / "lib/globals").mkdir(parents=True)
    (root / "lib/functions").mkdir(parents=True)
    (root / "dependencies/python").mkdir(parents=True)
    (root / "lib/globals/languages.sh").write_text(LANGUAGES_SH)
    (root / "lib/functions/linterCommands.sh").write_text(LINTER_COMMANDS_SH)
    (root / "Dockerfile").write_text(DOCKERFILE)
    (root / "dependencies/python/yamllint.txt").write_text("yamllint==1.0\n")
    (root / "dependencies/package.json").write_text(json.dumps({"dependencies": {"prettier": "3"}}))
    return root


@pytest.fixture
def mapping_file(tmp_path: Path) -> Path:
    path = tmp_path / "linters.json"
    path.write_text(json.dumps({"npm_groups": {}, "linters": {"YAML": {"venvs": ["yamllint"]}, "GONE": {}}}))
    return path


class TestUpstreamParsing:
    def test_upstream_flags_should_ignore_comments_when_the_array_has_them(self, upstream_checkout: Path) -> None:
        flags = mapping_sync.upstream_flags(upstream_checkout)

        assert flags == ["YAML", "RUBY", "MYSTERY"]

    def test_upstream_flags_should_exit_when_the_language_array_is_missing(self, tmp_path: Path) -> None:
        (tmp_path / "lib/globals").mkdir(parents=True)
        (tmp_path / "lib/globals/languages.sh").write_text("nothing here\n")

        with pytest.raises(SystemExit) as exc_info:
            mapping_sync.upstream_flags(tmp_path)

        assert "LANGUAGE_ARRAY" in str(exc_info.value)

    def test_upstream_commands_should_return_none_when_the_command_comes_from_a_variable(
        self, upstream_checkout: Path
    ) -> None:
        commands = mapping_sync.upstream_commands(upstream_checkout)

        assert commands["YAML"] == "yamllint"
        assert commands["DYNAMIC"] is None

    def test_dockerfile_binaries_should_map_basename_to_destination_when_copy_from_is_used(
        self, upstream_checkout: Path
    ) -> None:
        binaries = mapping_sync.dockerfile_binaries(upstream_checkout)

        assert binaries["rubocop"] == "/usr/bin/rubocop"


class TestDerive:
    def test_derive_should_return_a_venv_entry_when_command_matches_a_virtualenv(self, tmp_path: Path) -> None:
        entry = mapping_sync.derive("YAML", "yamllint", tmp_path, {}, {"yamllint"}, [])

        assert entry == {"venvs": ["yamllint"], "check": ["yamllint --version"]}

    def test_derive_should_return_a_bin_entry_when_command_is_a_copied_binary(self, tmp_path: Path) -> None:
        entry = mapping_sync.derive("X", "tool", tmp_path, {"tool": "/usr/bin/tool"}, set(), [])

        assert entry == {"bins": ["/usr/bin/tool"], "check": ["tool --version"]}

    def test_derive_should_return_an_npm_entry_when_command_matches_a_package(self, tmp_path: Path) -> None:
        entry = mapping_sync.derive("X", "stylelint", tmp_path, {}, set(), ["@scope/stylelint", "other"])

        assert entry is not None
        assert entry["npm"] == ["__group:stylelint:@scope/stylelint"]

    def test_derive_should_return_none_when_the_command_matches_nothing_upstream(self, tmp_path: Path) -> None:
        entry = mapping_sync.derive("X", "unknown", tmp_path, {}, set(), [])

        assert entry is None

    def test_derive_should_return_none_when_the_flag_has_no_command(self, tmp_path: Path) -> None:
        entry = mapping_sync.derive("X", None, tmp_path, {}, set(), [])

        assert entry is None


class TestMain:
    def test_main_should_return_ten_and_report_when_flags_are_missing_or_removed(
        self, upstream_checkout: Path, mapping_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = mapping_sync.main(["--upstream", str(upstream_checkout), "--mapping", str(mapping_file)])

        output = capsys.readouterr().out
        assert code == 10
        assert "`RUBY`" in output
        assert "`MYSTERY`" in output
        assert "`GONE`" in output

    def test_main_should_add_drafts_when_write_is_given(self, upstream_checkout: Path, mapping_file: Path) -> None:
        mapping_sync.main(["--upstream", str(upstream_checkout), "--mapping", str(mapping_file), "--write"])

        written: dict[str, Any] = json.loads(mapping_file.read_text())
        assert written["linters"]["RUBY"]["draft"] is True
        assert "MYSTERY" not in written["linters"]

    def test_main_should_create_an_npm_group_when_a_draft_uses_an_npm_package(
        self, upstream_checkout: Path, mapping_file: Path
    ) -> None:
        (upstream_checkout / "lib/globals/languages.sh").write_text("LANGUAGE_ARRAY=(\n    'YAML'\n    'PRETTIER'\n)\n")
        (upstream_checkout / "lib/functions/linterCommands.sh").write_text(
            "LINTER_COMMANDS_ARRAY_PRETTIER=(prettier --check)\n"
        )

        mapping_sync.main(["--upstream", str(upstream_checkout), "--mapping", str(mapping_file), "--write"])

        written = json.loads(mapping_file.read_text())
        assert written["linters"]["PRETTIER"]["npm"] == ["prettier"]
        assert written["npm_groups"]["prettier"] == ["prettier"]

    def test_main_should_return_zero_when_the_mapping_is_complete(
        self, tmp_path: Path, upstream_checkout: Path
    ) -> None:
        (upstream_checkout / "lib/globals/languages.sh").write_text("LANGUAGE_ARRAY=(\n    'YAML'\n)\n")
        mapping = tmp_path / "complete.json"
        mapping.write_text(json.dumps({"npm_groups": {}, "linters": {"YAML": {}}}))

        code = mapping_sync.main(["--upstream", str(upstream_checkout), "--mapping", str(mapping)])

        assert code == 0

    def test_main_should_write_the_report_when_report_path_is_given(
        self, tmp_path: Path, upstream_checkout: Path, mapping_file: Path
    ) -> None:
        report = tmp_path / "report.md"

        mapping_sync.main(
            ["--upstream", str(upstream_checkout), "--mapping", str(mapping_file), "--report", str(report)]
        )

        assert report.read_text().startswith("### Mapping sync")
