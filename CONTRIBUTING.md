# Contributing to lintsmith

Thank you for your interest in contributing to `lintsmith`! This document
explains how to set up your environment, run the quality checks, write tests and
submit your contribution.

Before you begin, read the [Architecture documentation](docs/ARCHITECTURE.md) and
the [AI/Developer agent guide](AGENTS.md). Automated developer agents can find
pre-configured coding and testing standards under [.agents/skills/](.agents/skills/).

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Prerequisites](#prerequisites)
- [Development Setup](#development-setup)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Testing Standards](#testing-standards)
- [Extending the mapping](#extending-the-mapping)
- [Pull Request Process](#pull-request-process)

---

## Code of Conduct

By participating in this project, you agree to maintain a respectful, welcoming
and inclusive environment. Please report unacceptable behavior to the maintainers.

## Prerequisites

1. **Python 3.12** or newer.
2. **[uv](https://docs.astral.sh/uv/)** to manage the environment.
3. **Node.js and npx** for prose linting of the documentation.
4. **Docker** (optional) for the container-based super-linter run.
5. **[APM](https://github.com/microsoft/apm)** (optional) to restore the agent skills.
6. **[ghwm](https://github.com/ghwfxlab/ghwm)** (optional) to update the managed workflows.

---

## Development Setup

```sh
git clone https://github.com/ghwfxlab/lintsmith.git
cd lintsmith
make install            # uv sync
make setup-precommit    # install the pre-commit hooks
apm install             # optional: restore .agents/skills
```

---

## Development Workflow

Use the [Makefile](Makefile) targets:

| Target | What it does |
| :--- | :--- |
| `make test` | pytest with coverage (keep it at 90% or higher). |
| `make lint` | Ruff check. |
| `make format` | Ruff formatter. |
| `make type-check` | mypy in strict mode; every function needs full type hints. |
| `make lang` / `make lang-fix` | textlint for the documentation. |
| `make precommit` | Run every pre-commit hook against all files. |
| `make super-linter` / `make super-linter-fix` | Run Super-Linter via Docker, without or with autofix. |
| `make build` | Build the sdist and wheel. |

The pre-commit hooks run `make super-linter-fix` and `make test` before each commit.

The `super-linter`, `auto-assign-pr` and `auto-release` workflows are managed with
ghwm (`ghwm.yml`, `ghwm.lock`). Do not edit the workflow files; change the versions in
`ghwm.yml` and run `ghwm install` (or `ghwm upgrade`). Their config files are ours to edit.

---

## Coding Standards

- Prefer small functions and plain data over hidden state; write explicit branching.
- Keep command-line parsing in each command's `main`; put behavior in the module that owns it ([config](src/lintsmith/config.py), [generate](src/lintsmith/generate.py), [drift](src/lintsmith/drift.py), [mapping_sync](src/lintsmith/mapping_sync.py), [release_notes](src/lintsmith/release_notes.py)).
- Do not run bulk renames over source files: shell and Dockerfile text lives in strings.
- Keep the linter mapping complete: `lintsmith sync-mapping` must report no missing flags for the pinned upstream version.
- Nothing that follows upstream may run unless upstream has a newer release.
- If you change public behavior, update the [readme](README.md), [docs/reference/cli.md](docs/reference/cli.md) and, where relevant, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Testing Standards

All tests live in [tests/](tests):

- **Arrange / Act / Assert**: structure each test in those three parts.
- **Naming**: `test_<feature>_should_<expected_behavior>_when_<state_under_test>`.
- **File alignment**: test `src/lintsmith/drift.py` in `tests/test_drift.py`, and so on.
- **No network and no Docker**: use `tmp_path` and small fake upstream checkouts.
- **Edge cases**: include failure paths (invalid values, mixed `true`/`false`, missing files, unknown flags).

---

## Extending the mapping

`src/lintsmith/data/linters.json` maps each `VALIDATE_*` flag to what the
image needs from the upstream image. An entry can have:

| Key | Meaning |
| --- | --- |
| `bins` | Binaries to copy, for example `/usr/bin/gitleaks`. |
| `venvs` | Python virtualenvs under `/venvs` to copy. |
| `npm` | Groups from `npm_groups` (npm packages to keep in `/node_modules`). |
| `dirs` | Directories to copy as they are. |
| `apk` | Alpine packages the tool needs at runtime. |
| `path`, `env`, `links` | Extra `PATH` entries, environment variables and symlinks. |
| `upstream`, `baseline` | Set to `standard` when the tool exists only in upstream's standard image. |
| `check` | Commands run inside the built image (`checks.sh`). Every entry needs at least one. |
| `draft` | Set by `sync-mapping`; remove it once a person has verified the entry. |

To add or fix an entry:

1. Check out the upstream release in question and run
   `lintsmith sync-mapping --upstream <checkout> --report report.md`. With
   `--write` it adds draft entries for missing flags and lists what it could not
   place.
2. Find the tool in upstream's `Dockerfile` (`COPY --from`, `/venvs`,
   `dependencies/package.json`) and fill in the keys above. Prefer the
   narrowest copy that works.
3. Generate an image with the flag, build it and run its `checks.sh`; for a
   linter with an upstream fixture, `lintsmith smoke` also runs a good and a
   bad file through the real entrypoint.
4. Update `tests/test_mapping_sync.py` or `tests/test_generate.py` if the
   derivation or the output changed. `lintsmith sync-mapping` must report
   no missing flags for the pinned upstream version.

## Pull Request Process

External contributors fork the repository, then:

```sh
git remote add upstream https://github.com/ghwfxlab/lintsmith.git
git checkout -b type/description
```

Open the pull request against `main`. The repository only allows squash merges,
so the **pull request title becomes the commit message** and must follow
conventional commits (`feat`, `fix`, `docs`, `test`, `ci`, `chore`, `refactor`).

### Branching conventions

- `feat/description` - new features
- `fix/description` - bugfixes
- `docs/description` - documentation
- `test/description` - tests
- `ci/description` - workflows and GitHub configuration
- `chore/description` - dependencies, tooling, refactorings

### Commit messages

Use conventional commit prefixes, for example:

- `feat: add a --report option to generate`
- `fix(generate): restore the symlink test in the generated Dockerfile`
- `docs: describe the repository settings`

### Submission checklist

```sh
make test && make lint && make type-check && make super-linter
make lang
```

1. All tests pass and coverage stays at 90% or higher.
2. mypy and Ruff report nothing.
3. Super-Linter and textlint report nothing.
4. `git status` lists only the intended files.
