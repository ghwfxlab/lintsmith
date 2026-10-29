"""Tests for lintsmith.generate."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lintsmith import generate
from tests.shared import (
    ENV_JSON,
    ENV_TRUE,
    ENV_YAML,
    FLAG_JSON,
    FLAG_YAML,
    PYTHON_BASE,
    UPSTREAM_TAG,
    WORKFLOW_FIXTURE,
    load_mapping,
)

TEST_STANDARD_IMAGE = f"ghcr.io/super-linter/super-linter:{UPSTREAM_TAG}"
TEST_SLIM_IMAGE = f"ghcr.io/super-linter/super-linter:slim-{UPSTREAM_TAG}"
TEST_EXTRA_NPM = "left-pad@1.3.0"
TEST_EXTRA_PIP = "yq==3.4.3"
TEST_EXTRA_CHECK = "tree --version"
TEST_SHELL_NOT_FOUND = "echo 'sh: tool: not found'"
TEST_TOOL_PRINTING_NOT_FOUND_IN_TITLE_CASE = "echo 'LuaLanes: Not found'"
TEST_PERL_MISSING_MODULE = 'echo "Can\'t locate Pod/PlainText.pm in @INC"'
TEST_MISSING_LIBRARY = "echo 'error while loading shared libraries: libx.so'"


def generate_arguments(out: Path, upstream_dockerfile: Path, *args: str) -> list[str]:
    return ["--upstream-tag", UPSTREAM_TAG, "--upstream-dockerfile", str(upstream_dockerfile), "--out", str(out), *args]


def generate_plan(out: Path, upstream_dockerfile: Path, *args: str) -> dict[str, Any]:
    code = generate.main(generate_arguments(out, upstream_dockerfile, *args))
    if code != 0:
        raise RuntimeError(f"generate exited with {code}")
    plan: dict[str, Any] = json.loads((out / "plan.json").read_text())
    return plan


@pytest.fixture
def yaml_env(tmp_path: Path) -> Path:
    path = tmp_path / "yaml.env"
    path.write_text(f"{ENV_YAML}={ENV_TRUE}\nVALIDATE_ALL_CODEBASE={ENV_TRUE}\n")
    return path


def run_check(command: str) -> str:
    """Run the generated `run_check` function on `command` in bash and return what it printed."""
    bash = shutil.which("bash") or "bash"
    script = f'{generate.CHECK_FUNC}\nrun_check "$1"\n'
    completed = subprocess.run([bash, "-c", script, "check", command], capture_output=True, text=True, check=True)
    return completed.stdout


class TestCheckFunction:
    def test_run_check_should_fail_when_the_shell_reports_a_missing_tool(self) -> None:
        printed = run_check(TEST_SHELL_NOT_FOUND)

        assert printed.startswith("FAIL (0)")

    def test_run_check_should_fail_when_a_shared_library_cannot_be_loaded(self) -> None:
        printed = run_check(TEST_MISSING_LIBRARY)

        assert printed.startswith("FAIL (0)")

    def test_run_check_should_fail_when_perl_cannot_locate_a_module(self) -> None:
        printed = run_check(TEST_PERL_MISSING_MODULE)

        assert printed.startswith("FAIL (0)")

    def test_run_check_should_pass_when_a_working_tool_prints_not_found_in_title_case(self) -> None:
        printed = run_check(TEST_TOOL_PRINTING_NOT_FOUND_IN_TITLE_CASE)

        assert printed.startswith("ok:")


class TestMappingFindingsOfTheSmokeTest:
    """Gaps the smoke test found in the lean image: files that upstream installs outside the usual paths."""

    def test_mapping_should_copy_the_pod_modules_that_perl_critic_needs_when_perl_is_enabled(self) -> None:
        perl_dirs = load_mapping()["linters"]["PERL"]["dirs"]

        assert "/usr/share/perl5/core_perl/Pod/PlainText.pm" in perl_dirs

    def test_mapping_should_check_that_perl_critic_loads_when_perl_is_enabled(self) -> None:
        perl_checks = load_mapping()["linters"]["PERL"]["check"]

        assert "perl -MPerl::Critic -e 1" in perl_checks

    def test_mapping_should_copy_the_powershell_modules_directory_when_powershell_is_enabled(self) -> None:
        powershell_dirs = load_mapping()["linters"]["POWERSHELL"]["dirs"]

        assert "/usr/local/share/powershell" in powershell_dirs

    def test_mapping_should_keep_react_for_the_import_check_when_the_react_linters_are_enabled(self) -> None:
        react_packages = load_mapping()["npm_groups"]["eslint_react"]

        assert "react" in react_packages


class TestGenerateOutputs:
    def test_generate_should_write_the_build_context_when_one_env_file_is_given(
        self, tmp_path: Path, upstream_dockerfile: Path, yaml_env: Path
    ) -> None:
        out = tmp_path / "out"

        generate_plan(out, upstream_dockerfile, "--env", str(yaml_env))

        written = {path.name for path in out.iterdir()}
        assert written == {"Dockerfile", "checks.sh", "plan.json", "prune-node-modules.js"}

    def test_generate_should_pin_the_upstream_image_when_a_tag_is_given(
        self, tmp_path: Path, upstream_dockerfile: Path, yaml_env: Path
    ) -> None:
        out = tmp_path / "out"

        plan = generate_plan(out, upstream_dockerfile, "--env", str(yaml_env))

        assert plan["upstream_image"] == TEST_SLIM_IMAGE
        assert plan["baseline_variant"] == "slim"
        assert f"FROM {PYTHON_BASE}" in (out / "Dockerfile").read_text()

    def test_generate_should_set_the_build_variables_when_the_image_is_generated(
        self, tmp_path: Path, upstream_dockerfile: Path, yaml_env: Path
    ) -> None:
        out = tmp_path / "out"

        generate_plan(out, upstream_dockerfile, "--env", str(yaml_env))

        dockerfile = (out / "Dockerfile").read_text()
        assert "ARG BUILD_VERSION=9.0.0" in dockerfile
        assert "ENV BUILD_VERSION=$BUILD_VERSION BUILD_REVISION=$BUILD_REVISION BUILD_DATE=$BUILD_DATE" in dockerfile

    def test_generate_should_ignore_all_codebase_when_it_is_set_in_the_env_file(
        self, tmp_path: Path, upstream_dockerfile: Path, yaml_env: Path
    ) -> None:
        plan = generate_plan(tmp_path / "out", upstream_dockerfile, "--env", str(yaml_env))

        assert plan["flags"] == [FLAG_YAML]

    def test_generate_should_test_symlinks_with_a_valid_operator_when_copying_upstream_paths(
        self, tmp_path: Path, upstream_dockerfile: Path, yaml_env: Path
    ) -> None:
        out = tmp_path / "out"

        generate_plan(out, upstream_dockerfile, "--env", str(yaml_env))

        assert '[ -L "$p" ]' in (out / "Dockerfile").read_text()

    def test_generate_should_use_the_standard_image_when_a_linter_needs_it(
        self, tmp_path: Path, upstream_dockerfile: Path
    ) -> None:
        env = tmp_path / "arm.env"
        env.write_text(f"VALIDATE_ARM={ENV_TRUE}\n")

        plan = generate_plan(tmp_path / "out", upstream_dockerfile, "--env", str(env))

        assert plan["upstream_image"] == TEST_STANDARD_IMAGE
        assert plan["baseline_variant"] == "standard"

    def test_generate_should_write_one_check_per_tool_when_linters_define_checks(
        self, tmp_path: Path, upstream_dockerfile: Path, yaml_env: Path
    ) -> None:
        out = tmp_path / "out"

        generate_plan(out, upstream_dockerfile, "--env", str(yaml_env))

        assert "run_check 'yamllint -c" in (out / "checks.sh").read_text()


class TestGenerateSelection:
    def test_generate_should_stack_flags_when_several_env_files_are_given(
        self, tmp_path: Path, upstream_dockerfile: Path, yaml_env: Path
    ) -> None:
        json_env = tmp_path / "json.env"
        json_env.write_text(f"{ENV_JSON}={ENV_TRUE}\n{ENV_YAML}={ENV_TRUE}\n")

        plan = generate_plan(tmp_path / "out", upstream_dockerfile, "--env", str(yaml_env), "--env", str(json_env))

        assert plan["flags"] == [FLAG_YAML, FLAG_JSON]

    def test_generate_should_drop_flags_when_exclude_is_given(
        self, tmp_path: Path, upstream_dockerfile: Path, yaml_env: Path
    ) -> None:
        json_env = tmp_path / "json.env"
        json_env.write_text(f"{ENV_JSON}={ENV_TRUE}\n")

        plan = generate_plan(
            tmp_path / "out",
            upstream_dockerfile,
            "--env",
            str(yaml_env),
            "--env",
            str(json_env),
            "--exclude",
            ENV_JSON,
        )

        assert plan["flags"] == [FLAG_YAML]

    def test_generate_should_read_flags_from_the_workflow_when_workflow_is_given(
        self, tmp_path: Path, upstream_dockerfile: Path
    ) -> None:
        plan = generate_plan(tmp_path / "out", upstream_dockerfile, "--workflow", str(WORKFLOW_FIXTURE))

        assert len(plan["flags"]) == 12
        assert "PYTHON_RUFF" in plan["flags"]

    def test_generate_should_select_every_mapped_flag_when_all_is_given(
        self, tmp_path: Path, upstream_dockerfile: Path, upstream_flags: set[str]
    ) -> None:
        plan = generate_plan(tmp_path / "out", upstream_dockerfile, "--all")

        assert set(plan["flags"]) == upstream_flags - {"ALL_CODEBASE"}

    def test_generate_should_exit_when_nothing_is_selected(self, tmp_path: Path, upstream_dockerfile: Path) -> None:
        arguments = generate_arguments(tmp_path / "out", upstream_dockerfile)

        with pytest.raises(SystemExit) as exc_info:
            generate.main(arguments)

        assert "give at least one" in str(exc_info.value)

    def test_generate_should_exit_when_a_flag_has_no_mapping(self, tmp_path: Path, upstream_dockerfile: Path) -> None:
        env = tmp_path / "bad.env"
        env.write_text(f"VALIDATE_NOT_A_LINTER={ENV_TRUE}\n")
        arguments = generate_arguments(tmp_path / "out", upstream_dockerfile, "--env", str(env))

        with pytest.raises(SystemExit) as exc_info:
            generate.main(arguments)

        assert "no mapping for: NOT_A_LINTER" in str(exc_info.value)

    def test_generate_should_exit_when_the_workflow_has_no_super_linter_step(
        self, tmp_path: Path, upstream_dockerfile: Path
    ) -> None:
        workflow = tmp_path / "w.yml"
        workflow.write_text("jobs:\n  a:\n    steps:\n      - run: echo\n")
        arguments = generate_arguments(tmp_path / "out", upstream_dockerfile, "--workflow", str(workflow))

        with pytest.raises(SystemExit) as exc_info:
            generate.main(arguments)

        assert "no super-linter" in str(exc_info.value)

    def test_generate_should_exit_when_upstream_dockerfile_has_no_python_base(
        self, tmp_path: Path, yaml_env: Path
    ) -> None:
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM alpine\n")
        arguments = generate_arguments(tmp_path / "out", dockerfile, "--env", str(yaml_env))

        with pytest.raises(SystemExit) as exc_info:
            generate.main(arguments)

        assert "python-base" in str(exc_info.value)


class TestGenerateExtras:
    def test_generate_should_record_the_extras_in_the_plan_when_extra_flags_are_given(
        self, tmp_path: Path, upstream_dockerfile: Path, yaml_env: Path
    ) -> None:
        plan = generate_plan(
            tmp_path / "out",
            upstream_dockerfile,
            "--env",
            str(yaml_env),
            "--extra-apk",
            "tree",
            "--extra-npm",
            TEST_EXTRA_NPM,
            "--extra-pip",
            TEST_EXTRA_PIP,
            "--extra-check",
            TEST_EXTRA_CHECK,
        )

        assert plan["extras"] == {
            "apk": ["tree"],
            "npm": [TEST_EXTRA_NPM],
            "pip": [TEST_EXTRA_PIP],
            "check": [TEST_EXTRA_CHECK],
        }

    def test_generate_should_install_extras_in_their_own_layers_when_extra_flags_are_given(
        self, tmp_path: Path, upstream_dockerfile: Path, yaml_env: Path
    ) -> None:
        out = tmp_path / "out"

        generate_plan(
            out,
            upstream_dockerfile,
            "--env",
            str(yaml_env),
            "--extra-npm",
            TEST_EXTRA_NPM,
            "--extra-pip",
            TEST_EXTRA_PIP,
        )

        dockerfile = (out / "Dockerfile").read_text()
        assert "AS extra-npm" in dockerfile
        assert "--ignore-scripts" in dockerfile
        assert "AS extra-pip" in dockerfile

    def test_generate_should_read_extras_from_the_env_file_when_extra_variables_are_set(
        self, tmp_path: Path, upstream_dockerfile: Path, yaml_env: Path
    ) -> None:
        extras_env = tmp_path / "extras.env"
        extras_env.write_text(f'EXTRA_APK="tree jq"\nEXTRA_CHECK="{TEST_EXTRA_CHECK}"\nEXTRA_CHECK="jq --version"\n')

        plan = generate_plan(tmp_path / "out", upstream_dockerfile, "--env", str(yaml_env), "--env", str(extras_env))

        assert plan["extras"]["apk"] == ["tree", "jq"]
        assert plan["extras"]["check"] == [TEST_EXTRA_CHECK, "jq --version"]

    def test_generate_should_include_node_pruning_when_a_linter_needs_npm_packages(
        self, tmp_path: Path, upstream_dockerfile: Path
    ) -> None:
        env = tmp_path / "md.env"
        env.write_text(f"VALIDATE_MARKDOWN={ENV_TRUE}\n")
        out = tmp_path / "out"

        plan = generate_plan(out, upstream_dockerfile, "--env", str(env))

        assert plan["npm_roots"]
        assert "AS npm-prune" in (out / "Dockerfile").read_text()
