"""Tests for lintsmith.upstream."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from lintsmith import upstream
from tests.shared import (
    PUBLISHED_LAST_MONTH,
    PUBLISHED_LONG_AGO,
    PUBLISHED_YESTERDAY,
    UPSTREAM_TAG,
    UPSTREAM_TAG_NEWER,
    UPSTREAM_TAG_NEWEST,
    release_entry,
)

TEST_NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
TEST_REPOSITORY = "owner/repo"
TEST_COOLDOWN_WEEK = 7
TEST_COOLDOWN_FAR_FUTURE = "36500"
TEST_COOLDOWN_NOT_A_NUMBER = "soon"
TEST_DRAFT_TAG = "v9.3.0"
TEST_PRERELEASE_TAG = "v9.3.0-rc1"
TEST_OLDER_MINOR_TAG = "v9.9.0"
TEST_TWO_DIGIT_MINOR_TAG = "v9.10.0"
TEST_TAG_WITHOUT_NUMBERS = "latest"
TEST_GH_RELEASES_JSON = '[{"tag_name": "v9.0.0"}]'
TEST_RELEASES = [
    release_entry(UPSTREAM_TAG_NEWEST, PUBLISHED_YESTERDAY),
    release_entry(UPSTREAM_TAG_NEWER, PUBLISHED_LAST_MONTH),
    release_entry(UPSTREAM_TAG, PUBLISHED_LONG_AGO),
]

ServeReleases = Callable[[list[dict[str, Any]]], None]


@pytest.fixture
def pinned_file(tmp_path: Path) -> Path:
    path = tmp_path / "upstream-version.txt"
    path.write_text(f"{UPSTREAM_TAG}\n")
    return path


@pytest.fixture
def github_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(path))
    return path


@pytest.fixture
def serve_releases(monkeypatch: pytest.MonkeyPatch) -> ServeReleases:
    """Make `fetch_releases` return the given releases instead of calling gh."""

    def serve(releases: list[dict[str, Any]]) -> None:
        monkeypatch.setattr(upstream, "fetch_releases", lambda repo: releases)

    return serve


@pytest.fixture
def fetched_repositories(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the repositories whose releases are read; the fake answers with `TEST_RELEASES`."""
    repositories: list[str] = []

    def fake_fetch(repo: str) -> list[dict[str, Any]]:
        repositories.append(repo)
        return TEST_RELEASES

    monkeypatch.setattr(upstream, "fetch_releases", fake_fetch)
    return repositories


class TestVersionKey:
    def test_version_key_should_return_the_numbers_of_the_tag_when_the_tag_has_a_v_prefix(self) -> None:
        key = upstream.version_key(UPSTREAM_TAG)

        assert key == (9, 0, 0)

    def test_version_key_should_sort_a_two_digit_minor_after_a_one_digit_minor_when_the_keys_are_compared(self) -> None:
        tags = [TEST_TWO_DIGIT_MINOR_TAG, TEST_OLDER_MINOR_TAG]

        ordered_tags = sorted(tags, key=upstream.version_key)

        assert ordered_tags == [TEST_OLDER_MINOR_TAG, TEST_TWO_DIGIT_MINOR_TAG]

    def test_version_key_should_return_an_empty_tuple_when_the_tag_has_no_number(self) -> None:
        key = upstream.version_key(TEST_TAG_WITHOUT_NUMBERS)

        assert key == ()


class TestEligible:
    def test_eligible_should_return_the_newest_release_when_the_cooldown_is_zero(self) -> None:
        tag = upstream.eligible(TEST_RELEASES, 0, TEST_NOW)

        assert tag == UPSTREAM_TAG_NEWEST

    def test_eligible_should_skip_releases_younger_than_the_cooldown_when_an_older_one_is_old_enough(self) -> None:
        tag = upstream.eligible(TEST_RELEASES, TEST_COOLDOWN_WEEK, TEST_NOW)

        assert tag == UPSTREAM_TAG_NEWER

    def test_eligible_should_accept_a_release_exactly_as_old_as_the_cooldown_when_the_ages_are_equal(self) -> None:
        releases = [release_entry(UPSTREAM_TAG_NEWER, "2026-10-06T12:00:00Z")]

        tag = upstream.eligible(releases, TEST_COOLDOWN_WEEK, TEST_NOW)

        assert tag == UPSTREAM_TAG_NEWER

    def test_eligible_should_return_an_empty_string_when_every_release_is_younger_than_the_cooldown(self) -> None:
        tag = upstream.eligible(TEST_RELEASES, int(TEST_COOLDOWN_FAR_FUTURE), TEST_NOW)

        assert tag == ""

    def test_eligible_should_skip_a_draft_when_it_is_the_newest_release(self) -> None:
        releases = [release_entry(TEST_DRAFT_TAG, PUBLISHED_YESTERDAY, draft=True), *TEST_RELEASES]

        tag = upstream.eligible(releases, 0, TEST_NOW)

        assert tag == UPSTREAM_TAG_NEWEST

    def test_eligible_should_skip_a_pre_release_when_it_is_the_newest_release(self) -> None:
        releases = [release_entry(TEST_PRERELEASE_TAG, PUBLISHED_YESTERDAY, prerelease=True), *TEST_RELEASES]

        tag = upstream.eligible(releases, 0, TEST_NOW)

        assert tag == UPSTREAM_TAG_NEWEST


class TestIsBehind:
    def test_is_behind_should_return_true_when_the_latest_is_newer_than_the_pinned_tag(self) -> None:
        behind = upstream.is_behind(UPSTREAM_TAG, UPSTREAM_TAG_NEWER)

        assert behind is True

    def test_is_behind_should_return_false_when_the_latest_equals_the_pinned_tag(self) -> None:
        behind = upstream.is_behind(UPSTREAM_TAG, UPSTREAM_TAG)

        assert behind is False

    def test_is_behind_should_return_false_when_the_latest_is_older_than_the_pinned_tag(self) -> None:
        behind = upstream.is_behind(UPSTREAM_TAG_NEWER, UPSTREAM_TAG)

        assert behind is False


class TestWriteOutputs:
    def test_write_outputs_should_append_the_three_values_when_github_output_is_set(self, github_output: Path) -> None:
        upstream.write_outputs(UPSTREAM_TAG, UPSTREAM_TAG_NEWER, True)

        written = github_output.read_text()
        assert written == f"pinned={UPSTREAM_TAG}\nlatest={UPSTREAM_TAG_NEWER}\nbehind=true\n"

    def test_write_outputs_should_write_nothing_when_github_output_is_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.chdir(tmp_path)

        upstream.write_outputs(UPSTREAM_TAG, UPSTREAM_TAG_NEWER, True)

        created_files = list(tmp_path.iterdir())
        assert created_files == []


class TestFetchReleases:
    def test_fetch_releases_should_parse_the_json_printed_by_gh_when_the_call_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(command: list[str], capture_output: bool, text: bool, check: bool) -> Any:
            return subprocess.CompletedProcess(command, 0, stdout=TEST_GH_RELEASES_JSON)

        monkeypatch.setattr(subprocess, "run", fake_run)

        releases = upstream.fetch_releases(TEST_REPOSITORY)

        assert releases == [{"tag_name": UPSTREAM_TAG}]

    def test_fetch_releases_should_ask_gh_for_the_releases_of_the_repository_when_it_is_called(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        commands: list[list[str]] = []

        def fake_run(command: list[str], capture_output: bool, text: bool, check: bool) -> Any:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="[]")

        monkeypatch.setattr(subprocess, "run", fake_run)

        upstream.fetch_releases(TEST_REPOSITORY)

        assert commands == [["gh", "api", f"repos/{TEST_REPOSITORY}/releases?per_page=50"]]

    def test_fetch_releases_should_raise_when_gh_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_run(command: list[str], capture_output: bool, text: bool, check: bool) -> Any:
            raise subprocess.CalledProcessError(1, command)

        monkeypatch.setattr(subprocess, "run", failing_run)

        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            upstream.fetch_releases(TEST_REPOSITORY)

        assert exc_info.value.returncode == 1


class TestMain:
    def test_main_should_return_zero_when_upstream_is_ahead(
        self, pinned_file: Path, github_output: Path, serve_releases: ServeReleases
    ) -> None:
        serve_releases(TEST_RELEASES)

        code = upstream.main(["--pinned-file", str(pinned_file)])

        assert code == 0

    def test_main_should_write_the_newest_tag_and_behind_true_when_upstream_is_ahead(
        self, pinned_file: Path, github_output: Path, serve_releases: ServeReleases
    ) -> None:
        serve_releases(TEST_RELEASES)

        upstream.main(["--pinned-file", str(pinned_file)])

        written = github_output.read_text()
        assert written == f"pinned={UPSTREAM_TAG}\nlatest={UPSTREAM_TAG_NEWEST}\nbehind=true\n"

    def test_main_should_report_that_the_pin_is_behind_when_upstream_is_ahead(
        self,
        pinned_file: Path,
        github_output: Path,
        serve_releases: ServeReleases,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        serve_releases(TEST_RELEASES)

        upstream.main(["--pinned-file", str(pinned_file)])

        printed = capsys.readouterr().out
        assert printed == f"Pinned {UPSTREAM_TAG} is behind upstream {UPSTREAM_TAG_NEWEST}. Running the sync.\n"

    def test_main_should_write_behind_false_when_the_pinned_tag_is_the_newest(
        self, pinned_file: Path, github_output: Path, serve_releases: ServeReleases
    ) -> None:
        serve_releases([release_entry(UPSTREAM_TAG, PUBLISHED_LONG_AGO)])

        upstream.main(["--pinned-file", str(pinned_file)])

        written = github_output.read_text()
        assert written == f"pinned={UPSTREAM_TAG}\nlatest={UPSTREAM_TAG}\nbehind=false\n"

    def test_main_should_report_that_there_is_nothing_to_do_when_the_pinned_tag_is_the_newest(
        self,
        pinned_file: Path,
        github_output: Path,
        serve_releases: ServeReleases,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        serve_releases([release_entry(UPSTREAM_TAG, PUBLISHED_LONG_AGO)])

        upstream.main(["--pinned-file", str(pinned_file)])

        printed = capsys.readouterr().out
        assert printed == f"Pinned {UPSTREAM_TAG} is current (upstream {UPSTREAM_TAG}). Nothing to do.\n"

    def test_main_should_keep_the_pinned_tag_as_latest_when_no_release_is_old_enough(
        self, pinned_file: Path, github_output: Path, serve_releases: ServeReleases
    ) -> None:
        serve_releases(TEST_RELEASES)

        upstream.main(["--pinned-file", str(pinned_file), "--cooldown-days", TEST_COOLDOWN_FAR_FUTURE])

        written = github_output.read_text()
        assert written == f"pinned={UPSTREAM_TAG}\nlatest={UPSTREAM_TAG}\nbehind=false\n"

    def test_main_should_report_none_as_eligible_when_no_release_is_old_enough(
        self,
        pinned_file: Path,
        github_output: Path,
        serve_releases: ServeReleases,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        serve_releases(TEST_RELEASES)

        upstream.main(["--pinned-file", str(pinned_file), "--cooldown-days", TEST_COOLDOWN_FAR_FUTURE])

        printed = capsys.readouterr().out
        assert "newest eligible upstream release is 'none'" in printed

    def test_main_should_use_the_forced_tag_when_force_tag_is_given(
        self, pinned_file: Path, github_output: Path, serve_releases: ServeReleases
    ) -> None:
        serve_releases(TEST_RELEASES)

        upstream.main(["--pinned-file", str(pinned_file), "--force-tag", UPSTREAM_TAG_NEWER])

        written = github_output.read_text()
        assert written == f"pinned={UPSTREAM_TAG}\nlatest={UPSTREAM_TAG_NEWER}\nbehind=true\n"

    def test_main_should_not_read_the_releases_when_force_tag_is_given(
        self, pinned_file: Path, github_output: Path, fetched_repositories: list[str]
    ) -> None:
        upstream.main(["--pinned-file", str(pinned_file), "--force-tag", UPSTREAM_TAG_NEWER])

        assert fetched_repositories == []

    def test_main_should_read_the_releases_of_the_given_repository_when_repo_is_given(
        self, pinned_file: Path, github_output: Path, fetched_repositories: list[str]
    ) -> None:
        upstream.main(["--pinned-file", str(pinned_file), "--repo", TEST_REPOSITORY])

        assert fetched_repositories == [TEST_REPOSITORY]

    def test_main_should_return_zero_when_github_output_is_not_set(
        self, pinned_file: Path, serve_releases: ServeReleases, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        serve_releases(TEST_RELEASES)

        code = upstream.main(["--pinned-file", str(pinned_file)])

        assert code == 0

    def test_main_should_return_two_when_the_cooldown_is_not_a_whole_number(self, pinned_file: Path) -> None:
        code = upstream.main(["--pinned-file", str(pinned_file), "--cooldown-days", TEST_COOLDOWN_NOT_A_NUMBER])

        assert code == 2

    def test_main_should_name_the_bad_cooldown_in_the_error_when_it_is_not_a_whole_number(
        self, pinned_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        upstream.main(["--pinned-file", str(pinned_file), "--cooldown-days", TEST_COOLDOWN_NOT_A_NUMBER])

        printed = capsys.readouterr().out
        assert printed == f"::error::cooldown_days must be a whole number, got '{TEST_COOLDOWN_NOT_A_NUMBER}'\n"

    def test_main_should_return_two_when_the_pinned_file_is_missing(self, tmp_path: Path) -> None:
        missing_file = tmp_path / "missing.txt"

        code = upstream.main(["--pinned-file", str(missing_file)])

        assert code == 2

    def test_main_should_name_the_pinned_file_in_the_error_when_it_is_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing_file = tmp_path / "missing.txt"

        upstream.main(["--pinned-file", str(missing_file)])

        printed = capsys.readouterr().out
        assert f"::error::cannot read {missing_file}" in printed

    def test_main_should_return_two_when_the_releases_cannot_be_read(
        self, pinned_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing_fetch(repo: str) -> list[dict[str, Any]]:
            raise subprocess.CalledProcessError(1, "gh")

        monkeypatch.setattr(upstream, "fetch_releases", failing_fetch)

        code = upstream.main(["--pinned-file", str(pinned_file)])

        assert code == 2

    def test_main_should_name_the_repository_in_the_error_when_the_releases_cannot_be_read(
        self, pinned_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def failing_fetch(repo: str) -> list[dict[str, Any]]:
            raise subprocess.CalledProcessError(1, "gh")

        monkeypatch.setattr(upstream, "fetch_releases", failing_fetch)

        upstream.main(["--pinned-file", str(pinned_file), "--repo", TEST_REPOSITORY])

        printed = capsys.readouterr().out
        assert f"::error::cannot read the releases of {TEST_REPOSITORY}" in printed
