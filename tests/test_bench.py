"""Tests for lintsmith.bench."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from lintsmith import bench, cli

TEST_IMAGE = "ghcr.io/o/r/lean:v1"
TEST_VARIANT = "p/lean-gzip"
TEST_BASELINE_VARIANT = "p/baseline"
TEST_RUNNER = "github-hosted"
TEST_MANIFEST = json.dumps({"layers": [{"size": 100}, {"size": 250}]})
TEST_COMPRESSED_BYTES = 350
TEST_UNCOMPRESSED_BYTES = 4096
TEST_ROW_KEYS = [
    "image",
    "variant",
    "runner",
    "mode",
    "run",
    "pull_s",
    "start_s",
    "download_s",
    "load_s",
    "compressed_bytes",
    "uncompressed_bytes",
]
PULL = "docker pull --quiet"
CLEARING = ["docker image rm", "docker image prune", "docker builder prune"]


class FakeDocker:
    """Stands in for bench.run: records commands and answers like docker and crane would."""

    def __init__(self, fail: tuple[str, ...] = (), manifest: str = TEST_MANIFEST) -> None:
        self.commands: list[list[str]] = []
        self.fail = fail
        self.manifest = manifest

    def __call__(self, command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        key = " ".join(command[:3])
        code = 1 if any(key.startswith(prefix) for prefix in self.fail) else 0
        if code and check:
            raise bench.BenchError(f"{key} failed: boom")
        output = ""
        if command[:3] == ["docker", "image", "inspect"]:
            output = f"{TEST_UNCOMPRESSED_BYTES}\n"
        elif command[:2] == ["crane", "manifest"]:
            output = self.manifest
        return subprocess.CompletedProcess(command, code, stdout=output, stderr="")

    def verbs(self) -> list[str]:
        return [" ".join(command[:3]) for command in self.commands]


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    fake = FakeDocker()
    monkeypatch.setattr(bench, "run", fake)
    monkeypatch.setattr(bench, "have_crane", lambda: True)
    clock = iter(float(tick) * 0.5 for tick in range(1000))
    monkeypatch.setattr(bench.time, "perf_counter", lambda: next(clock))
    return fake


class TestBench:
    def test_bench_should_clear_images_before_every_pull_when_the_mode_is_cold(
        self, docker: FakeDocker, tmp_path: Path
    ) -> None:
        bench.bench(TEST_IMAGE, 2, TEST_VARIANT, TEST_RUNNER, "cold", tmp_path / "out.jsonl", split=False)

        verbs = docker.verbs()
        pull_positions = [position for position, verb in enumerate(verbs) if verb == PULL]
        assert len(pull_positions) == 2
        for position in pull_positions:
            assert verbs[position - 3 : position] == CLEARING

    def test_bench_should_pull_once_unmeasured_and_not_clear_when_the_mode_is_warm(
        self, docker: FakeDocker, tmp_path: Path
    ) -> None:
        rows = bench.bench(
            TEST_IMAGE, 2, TEST_BASELINE_VARIANT, TEST_RUNNER, "warm", tmp_path / "out.jsonl", split=False
        )

        verbs = docker.verbs()
        assert verbs.count(PULL) == 3
        assert "docker image rm" not in verbs
        assert [row["mode"] for row in rows] == ["warm", "warm"]

    def test_bench_should_write_rows_with_the_expected_keys_when_a_run_finishes(
        self, docker: FakeDocker, tmp_path: Path
    ) -> None:
        rows = bench.bench(TEST_IMAGE, 1, TEST_VARIANT, TEST_RUNNER, "cold", tmp_path / "out.jsonl", split=False)

        assert list(rows[0]) == TEST_ROW_KEYS

    def test_bench_should_record_the_sizes_and_no_split_timings_when_split_is_off(
        self, docker: FakeDocker, tmp_path: Path
    ) -> None:
        rows = bench.bench(TEST_IMAGE, 1, TEST_VARIANT, TEST_RUNNER, "cold", tmp_path / "out.jsonl", split=False)

        row = rows[0]
        assert row["compressed_bytes"] == TEST_COMPRESSED_BYTES
        assert row["uncompressed_bytes"] == TEST_UNCOMPRESSED_BYTES
        assert row["download_s"] is None
        assert row["load_s"] is None

    def test_bench_should_append_the_row_to_the_file_and_print_it_when_the_file_already_has_rows(
        self, docker: FakeDocker, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output_file = tmp_path / "out.jsonl"
        output_file.write_text('{"earlier": true}\n')

        bench.bench(TEST_IMAGE, 1, TEST_VARIANT, TEST_RUNNER, "cold", output_file, split=False)

        lines = output_file.read_text().splitlines()
        appended_row = json.loads(lines[1])
        printed = capsys.readouterr().out.strip()
        assert lines[0] == '{"earlier": true}'
        assert appended_row["variant"] == TEST_VARIANT
        assert printed == lines[1]

    def test_bench_should_time_the_pull_and_the_start_separately_when_the_clock_advances_per_call(
        self, docker: FakeDocker, tmp_path: Path
    ) -> None:
        rows = bench.bench(TEST_IMAGE, 1, TEST_VARIANT, TEST_RUNNER, "cold", tmp_path / "out.jsonl", split=False)

        assert rows[0]["pull_s"] == 0.5
        assert rows[0]["start_s"] == 0.5

    def test_bench_should_measure_download_and_load_when_split_is_on_in_cold_mode(
        self, docker: FakeDocker, tmp_path: Path
    ) -> None:
        rows = bench.bench(
            TEST_IMAGE, 1, TEST_BASELINE_VARIANT, TEST_RUNNER, "cold", tmp_path / "out.jsonl", split=True
        )

        assert rows[0]["download_s"] == 0.5
        assert rows[0]["load_s"] == 0.5

    def test_bench_should_run_crane_pull_and_docker_load_when_split_is_on_in_cold_mode(
        self, docker: FakeDocker, tmp_path: Path
    ) -> None:
        bench.bench(TEST_IMAGE, 1, TEST_BASELINE_VARIANT, TEST_RUNNER, "cold", tmp_path / "out.jsonl", split=True)

        verbs = docker.verbs()
        assert "crane pull --platform" in verbs
        assert "docker load --quiet" in verbs

    def test_bench_should_skip_the_split_when_crane_is_not_installed(
        self, docker: FakeDocker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(bench, "have_crane", lambda: False)

        rows = bench.bench(
            TEST_IMAGE, 1, TEST_BASELINE_VARIANT, TEST_RUNNER, "cold", tmp_path / "out.jsonl", split=True
        )

        crane_commands = [verb for verb in docker.verbs() if verb.startswith("crane")]
        assert rows[0]["download_s"] is None
        assert rows[0]["compressed_bytes"] is None
        assert crane_commands == []

    def test_bench_should_keep_going_when_the_split_download_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(bench, "run", FakeDocker(fail=("crane pull",)))
        monkeypatch.setattr(bench, "have_crane", lambda: True)

        rows = bench.bench(
            TEST_IMAGE, 1, TEST_BASELINE_VARIANT, TEST_RUNNER, "cold", tmp_path / "out.jsonl", split=True
        )

        assert rows[0]["download_s"] is not None

    def test_bench_should_raise_when_the_pull_fails(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(bench, "run", FakeDocker(fail=("docker pull",)))
        monkeypatch.setattr(bench, "have_crane", lambda: False)

        with pytest.raises(bench.BenchError):
            bench.bench(TEST_IMAGE, 1, TEST_BASELINE_VARIANT, TEST_RUNNER, "cold", tmp_path / "out.jsonl", split=False)


class TestCompressedBytes:
    def test_compressed_bytes_should_sum_the_layer_sizes_when_the_manifest_is_valid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bench, "run", FakeDocker())
        monkeypatch.setattr(bench, "have_crane", lambda: True)

        size = bench.compressed_bytes(TEST_IMAGE)

        assert size == TEST_COMPRESSED_BYTES

    def test_compressed_bytes_should_be_none_when_the_manifest_is_not_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bench, "run", FakeDocker(manifest="not json"))
        monkeypatch.setattr(bench, "have_crane", lambda: True)

        size = bench.compressed_bytes(TEST_IMAGE)

        assert size is None

    def test_compressed_bytes_should_be_none_when_crane_is_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(bench, "have_crane", lambda: False)

        size = bench.compressed_bytes(TEST_IMAGE)

        assert size is None


class TestMain:
    def test_main_should_default_to_five_runs_when_the_runs_argument_is_left_out(
        self, docker: FakeDocker, tmp_path: Path
    ) -> None:
        output_file = tmp_path / "out.jsonl"

        code = bench.main([TEST_IMAGE, TEST_BASELINE_VARIANT, TEST_RUNNER, "--out", str(output_file)])

        assert code == 0
        assert len(output_file.read_text().splitlines()) == 5

    def test_main_should_use_the_environment_when_no_options_are_given(
        self, docker: FakeDocker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        output_file = tmp_path / "env.jsonl"
        monkeypatch.setenv("BENCH_OUT", str(output_file))
        monkeypatch.setenv("BENCH_MODE", "warm")

        code = bench.main([TEST_IMAGE, "2", TEST_BASELINE_VARIANT, TEST_RUNNER])

        modes = [json.loads(line)["mode"] for line in output_file.read_text().splitlines()]
        assert code == 0
        assert modes == ["warm", "warm"]

    def test_main_should_return_one_when_a_docker_call_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(bench, "run", FakeDocker(fail=("docker pull",)))
        monkeypatch.setattr(bench, "have_crane", lambda: False)

        code = bench.main([TEST_IMAGE, "1", TEST_BASELINE_VARIANT, TEST_RUNNER, "--out", str(tmp_path / "o.jsonl")])

        assert code == 1
        assert "docker pull" in capsys.readouterr().out

    def test_main_should_return_two_when_variant_and_runner_are_missing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = bench.main([TEST_IMAGE, "3", "only-a-variant"])

        assert code == 2
        assert "usage: lintsmith bench" in capsys.readouterr().out

    def test_cli_should_list_bench_when_usage_is_printed(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.main([])

        assert "bench" in capsys.readouterr().out


class TestRun:
    def test_run_should_return_the_output_when_the_command_succeeds(self) -> None:
        completed = bench.run([sys.executable, "-c", "print('ok')"])

        assert completed.stdout.strip() == "ok"

    def test_run_should_raise_with_the_error_text_when_a_checked_command_fails(self) -> None:
        failing_command = [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"]

        with pytest.raises(bench.BenchError, match="boom"):
            bench.run(failing_command)

    def test_run_should_return_the_failure_when_the_check_is_off(self) -> None:
        completed = bench.run([sys.executable, "-c", "import sys; sys.exit(3)"], check=False)

        assert completed.returncode == 3


class TestTimed:
    def test_timed_should_return_the_elapsed_seconds_rounded_to_two_decimals_when_the_clock_advances(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ticks = iter([10.0, 10.1234])
        monkeypatch.setattr(bench.time, "perf_counter", lambda: next(ticks))

        elapsed = bench.timed(lambda: None)

        assert elapsed == 0.12
