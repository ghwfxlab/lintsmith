# AGENTS.md

## Purpose

`lintsmith` is a Python CLI that generates lean, pinned Super-Linter images
from `VALIDATE_*` flags, blocks pull requests that outgrow the image, and keeps
its linter mapping in step with upstream Super-Linter releases.

The core lifecycle is:

1. Read the `VALIDATE_*` flags (env files, or the Super-Linter step of a workflow)
2. Resolve the enabled linters with upstream's semantics
3. Generate the build context (Dockerfile, `checks.sh`, `plan.json`) or check a pull request against it
4. Keep `linters.json` complete when upstream publishes a new release

Read `docs/ARCHITECTURE.md` before making structural changes.

## Agent skills

To guide automated developer agents, this repository provides workspace skills
under `.agents/skills/`, managed with [APM](https://github.com/microsoft/apm)
(`apm.yml`, locked in `apm.lock.yaml`; restore them with `apm install`):

- [python-coding-standards](.agents/skills/python-coding-standards/SKILL.md): typing, error handling, subprocess safety, module boundaries.
- [testing-standards](.agents/skills/testing-standards/SKILL.md): Arrange/Act/Assert, mock isolation, naming conventions.
- [tdd](.agents/skills/tdd/SKILL.md): red-green loop and vertical slicing.
- [code review](.agents/skills/code-review/SKILL.md): review changes against the repository standards.

Agents should read and follow these standards for all contributions.

## Repository layout

- `src/lintsmith/cli.py` - entry point that dispatches the sub-commands
- `src/lintsmith/generate.py` - flags -> Dockerfile, checks.sh, plan.json
- `src/lintsmith/drift.py` - PR drift check (changed files vs enabled linters)
- `src/lintsmith/config.py` - reads env files and workflows; upstream `VALIDATE_*` semantics
- `src/lintsmith/mapping_sync.py` - adds draft mapping entries for new upstream linters
- `src/lintsmith/release_notes.py` - before/after benchmark release notes
- `src/lintsmith/data/` - `linters.json`, `filetypes.json`, `prune-node-modules.js`
- `base/`, `toolchains/`, `examples/` - env files (the opinionated base and example combinations)
- `scripts/` - benchmark shell scripts used by the workflows
- `tests/` - module-aligned pytest suite
- `docs/ARCHITECTURE.md` - architecture and data-flow notes
- `docs/reference/cli.md` - command and option reference
- `docs/repository-settings.md` - the repository settings that limit interactions
- `apm.yml`, `apm.lock.yaml` - agent skills managed with APM
- `ghwm.yml`, `ghwm.lock` - workflows managed with ghwm (`super-linter`, `auto-assign-pr`, `auto-release`); never hand-edit the managed workflow files
- `upstream-version.txt` - the pinned upstream Super-Linter release

## Development commands

- `make install` - sync dependencies with `uv`
- `make test` - run pytest with coverage
- `make lint` - run Ruff
- `make type-check` - run mypy in strict mode
- `make format` - run the Ruff formatter
- `make build` - build sdist and wheel
- `make lang` - run textlint for prose/docs
- `make super-linter` - run super-linter via Docker
- `make setup-precommit` - install the pre-commit hooks

For Python changes, run:

```sh
make test && make lint && make type-check && make super-linter
```

For documentation changes, run:

```sh
make lang
```

## Code conventions

- Target Python **3.12**.
- Keep type hints complete; mypy runs in **strict** mode.
- Keep CLI parsing thin. Put behavior in the module that owns it.
- Prefer small functions and plain data over hidden state.
- Match the existing style: simple functions, explicit branching, no unnecessary abstraction.
- Do not run `sed`-style bulk renames over source files; shell and Dockerfile text lives in strings (a rename of `L` once broke `[ -L "$p" ]` in the generated Dockerfile).

## Rules

- Nothing that follows upstream may run unless upstream has a newer release (see `.github/workflows/upstream-sync.yaml`).
- Everything stays configurable: the base and toolchains are examples, not the supported set.
- Keep the mapping complete: `lintsmith sync-mapping` must report no missing flags for the pinned upstream version.

## Behavior invariants

When changing code, preserve these unless the task explicitly changes them.

### Flag semantics

- No `VALIDATE_<LANGUAGE>` variable set: every linter is enabled.
- Any set to `true` and none to `false`: only those are enabled.
- Any set to `false` and none to `true`: every linter except those is enabled.
- Mixing `true` and `false` is a `ConfigError`; so is a value that is not `true` or `false`.
- `VALIDATE_ALL_CODEBASE` is not a linter.
- Later env files override earlier ones; a workflow merges workflow, job and step `env:` (step wins).

### Drift check

- Exit code `0` all covered, `1` uncovered files, `2` configuration error.
- A file is uncovered only when upstream would lint it and none of those linters is enabled.
- `FILTER_REGEX_INCLUDE` and `FILTER_REGEX_EXCLUDE` are respected; `--allow-ext` skips an extension or filename.
- The check never runs repository code; it reads the workflow and the changed filenames (and the first line of extension-less files).

### Generate

- The generated image is pinned to the upstream tag; `slim` is the baseline unless a selected linter needs `standard`.
- Extras (`EXTRA_APK`, `EXTRA_NPM`, `EXTRA_PIP`, `EXTRA_CHECK`) are installed at build time in their own layers, and npm installs use `--ignore-scripts`.
- Every flag in the selection must have a mapping entry; unknown flags exit with a message.

### Mapping sync

- Exit code `0` nothing to do, `10` drafts were added or flags remain unresolved.
- Added entries are marked `"draft": true`; anything that cannot be placed is reported, not guessed.

## Testing guidance

- Add or update tests in the module-aligned file under `tests/`.
- Structure tests with the Arrange / Act / Assert pattern.
- Name tests as `test_<feature>_should_<expected_behavior>_when_<state_under_test>`.
- Prefer `tmp_path` fixtures and small fake upstream checkouts over real network access or Docker.
- Add negative-path coverage when changing config parsing, the drift check or the mapping sync.
- If you change flag semantics, update `tests/test_config.py`.
- If you change file type detection or the drift report, update `tests/test_drift.py`.
- If you change Dockerfile, `checks.sh` or `plan.json` output, update `tests/test_generate.py`.
- If you change upstream parsing or draft derivation, update `tests/test_mapping_sync.py`.
- If you change command dispatch or output, update `tests/test_cli.py`.
- Keep coverage at 90% or higher.

## Documentation guidance

- Update `README.md` for user-facing CLI behavior, flags, or workflow examples, and call it the readme in prose.
- Update `docs/reference/cli.md` when a command or option changes.
- Update `docs/ARCHITECTURE.md` for module-boundary or data-flow changes.
