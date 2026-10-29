"""Tests for lintsmith.release_notes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lintsmith import release_notes
from tests.shared import bench_row, write_jsonl

TEST_OLD_TAG = "v1"
TEST_NEW_TAG = "v2"
TEST_PROFILE = "p"


def run_notes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
    extra_args: list[str] | None = None,
) -> str:
    for name, rows in (("old", old_rows), ("new", new_rows)):
        (tmp_path / name).mkdir()
        write_jsonl(tmp_path / name / "bench-p.jsonl", rows)
    release_notes.main(
        [
            "--old-tag",
            TEST_OLD_TAG,
            "--old-dir",
            str(tmp_path / "old"),
            "--new-tag",
            TEST_NEW_TAG,
            "--new-dir",
            str(tmp_path / "new"),
            "--profiles",
            TEST_PROFILE,
            *(extra_args or []),
        ]
    )
    return capsys.readouterr().out


class TestReleaseNotes:
    def test_release_notes_should_show_before_and_after_when_both_versions_have_results(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        old_rows = [bench_row("lean-gzip", 10.0), bench_row("lean-zstd", 5.0), bench_row("baseline", 70.0, 5000)]
        new_rows = [bench_row("lean-gzip", 9.0), bench_row("lean-zstd", 5.0), bench_row("baseline", 72.0, 5200)]

        text = run_notes(tmp_path, capsys, old_rows, new_rows)

        assert "| p | 10.0 s | 9.0 s | -10% |" in text
        assert "| p | 70.0 s | 72.0 s | +3% | 5000 MB | 5200 MB | +4% |" in text

    def test_release_notes_should_report_nothing_to_compare_when_old_version_has_no_results(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = run_notes(tmp_path, capsys, [], [bench_row("lean-gzip", 9.0)])

        assert "nothing to compare" in text

    def test_release_notes_should_use_the_median_when_a_profile_has_several_runs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        old_rows = [bench_row("lean-gzip", seconds) for seconds in (10.0, 30.0, 11.0)]
        new_rows = [bench_row("lean-gzip", 11.0)]

        text = run_notes(tmp_path, capsys, old_rows, new_rows)

        assert "| p | 11.0 s | 11.0 s | +0% |" in text

    def test_release_notes_should_print_na_when_a_variant_has_no_measurement(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = run_notes(tmp_path, capsys, [bench_row("lean-gzip", 10.0)], [bench_row("lean-gzip", 9.0)])

        assert "| p | n/a | n/a | n/a |" in text

    def test_release_notes_should_append_mapping_changes_when_a_diff_file_is_given(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mapping_diff = tmp_path / "mapping.diff"
        mapping_diff.write_text("+ NEW_LINTER\n")

        text = run_notes(
            tmp_path,
            capsys,
            [bench_row("lean-gzip", 10.0)],
            [bench_row("lean-gzip", 9.0)],
            ["--mapping-diff", str(mapping_diff)],
        )

        assert "### Mapping changes" in text
        assert "+ NEW_LINTER" in text

    def test_release_notes_should_write_the_notes_when_out_is_given(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "notes.md"

        run_notes(tmp_path, capsys, [bench_row("lean-gzip", 10.0)], [bench_row("lean-gzip", 9.0)], ["--out", str(out)])

        assert out.read_text().startswith(f"## Upstream Super-Linter {TEST_OLD_TAG} to {TEST_NEW_TAG}")

    def test_release_notes_should_list_profiles_without_old_results_when_they_are_new(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "old").mkdir()
        (tmp_path / "new").mkdir()
        write_jsonl(tmp_path / "old" / "bench-p.jsonl", [bench_row("lean-gzip", 10.0)])
        write_jsonl(tmp_path / "new" / "bench-p.jsonl", [bench_row("lean-gzip", 9.0)])
        write_jsonl(tmp_path / "new" / "bench-q.jsonl", [{**bench_row("lean-gzip", 9.0), "variant": "q/lean-gzip"}])

        release_notes.main(
            [
                "--old-tag",
                TEST_OLD_TAG,
                "--old-dir",
                str(tmp_path / "old"),
                "--new-tag",
                TEST_NEW_TAG,
                "--new-dir",
                str(tmp_path / "new"),
            ]
        )

        assert f"Not compared (no results for {TEST_OLD_TAG}): q." in capsys.readouterr().out
