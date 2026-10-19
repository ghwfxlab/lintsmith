# superlint-lean

Generate lean, pinned [Super-Linter](https://github.com/super-linter/super-linter)
images that contain only the linters a repository uses, to cut the cold
pull-and-unpack time in CI.

Status: working, early. On GitHub-hosted runners a lean image pulls 5x to 8x
faster than upstream `slim`:

| Stack | Upstream slim | Lean | Faster |
| --- | --- | --- | --- |
| ghwm | 70.7 s | 10.7 s | 6.6x |
| python | 67.9 s | 11.6 s | 5.9x |
| frontend-react | 68.7 s | 10.4 s | 6.6x |
| dotnet (against upstream standard) | 91.0 s | 16.9 s | 5.4x |

Cold pull, median of 3, upstream v9.0.0. All profiles, the method and the
caveats are in [docs/benchmarks](docs/benchmarks/README.md).

## Idea

1. A repository declares the linters it needs, or they are discovered from the
   `VALIDATE_*` flags in its Super-Linter workflow.
2. A compiler builds an overlay image: same Python/Alpine base as upstream, plus
   only the needed tool paths copied from the upstream release image.
3. A PR check fails when a change adds file types the current image does not
   cover.
4. A scheduled job rebuilds when upstream publishes a new release.
5. The workflows are distributed through the ghwm registry; see
   [Run the lean image with the ghwm registry workflows](docs/using-with-ghwm.md).

## Install

The CLI is a Python package, managed with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install superlint-lean    # or: pipx install superlint-lean
uvx superlint-lean --help         # run without installing
```

The latest unreleased code is available with
`uvx --from git+https://github.com/ghwfxlab/superlint-lean superlint-lean --help`.

Commands:

| Command | Purpose |
| --- | --- |
| `superlint-lean generate` | `VALIDATE_*` flags (env files or a workflow) -> Dockerfile, tool self-checks and plan |
| `superlint-lean drift` | PR drift check: fails when changed files are not covered by the enabled linters |
| `superlint-lean sync-mapping` | Compare the linter mapping with an upstream checkout and add draft entries |
| `superlint-lean release-notes` | Release notes with before/after benchmarks of two upstream versions |
| `superlint-lean compare`, `summarize` | Markdown tables from benchmark results: lean against baseline, and every variant on its own |
| `superlint-lean repository-settings` | Print or apply the repository settings in `docs/repository-settings.md` (maintainers) |
| `superlint-lean bench` | Time cold or warm pulls and container start of an image (the benchmark workflow) |
| `superlint-lean select-upstream` | Pick the upstream release to sync to, honouring a cooldown |
| `superlint-lean smoke` | Lint upstream's good and bad fixtures with a built image, one linter at a time |

## Layout

| Path | Purpose |
| --- | --- |
| `src/superlint_lean/` | The package: `cli.py`, `generate.py`, `drift.py`, `config.py` (reads workflows and env files with upstream's `VALIDATE_*` semantics), `mapping_sync.py`, `release_notes.py` |
| `src/superlint_lean/data/` | `linters.json` (flag -> upstream paths, venvs, npm and apk packages), `filetypes.json` (file type rules transcribed from upstream), `prune-node-modules.js` |
| `tests/` | pytest suite (Arrange/Act/Assert), using the ghwm workflow as a fixture |
| `base/opinionated.env` | The opinionated base: the checks almost every repository wants (EditorConfig, env, actionlint, zizmor, gitleaks, JSON, Markdown, natural language, YAML, shell, hadolint) |
| `toolchains/` | Example toolchains on top of the base: python, Java, dotnet, rust, c-cpp, frontend-{vanilla,react,vue,angular,svelte}, base-only |
| `examples/` | `ghwm.env` (a real repository's exact flags, without the base) and `with-extras.env` |
| `.github/workflows/` | `tests`, `profiles` (benchmarks), `upstream-sync`, `release`, `self-image` (this repository's own lean image), and the reusable `drift-blocker` |

## Development

```sh
make install          # uv sync
make setup-precommit  # pre-commit hooks (super-linter and the tests)
make test             # pytest with coverage
make lint             # ruff
make type-check       # mypy
make lang             # textlint for the docs
make super-linter     # super-linter via Docker
make build            # sdist and wheel
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow, [AGENTS.md](AGENTS.md)
for the guide used by coding agents, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
and [docs/reference/cli.md](docs/reference/cli.md) for the internals and the
command reference, [docs/verifying-images.md](docs/verifying-images.md) to
check a pulled image, and [docs/repository-settings.md](docs/repository-settings.md)
for the repository settings. Report vulnerabilities as described in
[SECURITY.md](SECURITY.md).

## Configuration

Nothing is fixed. The base and the toolchains are plain env files with
`VALIDATE_*=true` lines, and the generator takes any combination of them:

- leave the base out, or write your own
- stack several toolchains (`--env toolchains/python.env --env toolchains/rust.env`)
- drop single linters from a combination with `--exclude NATURAL_LANGUAGE`
- add tools Super-Linter does not ship: Alpine packages (`--extra-apk`), npm
  packages (`--extra-npm`) and pip packages (`--extra-pip`), plus `--extra-check`
  commands that must succeed in the built image. They can also be written in an
  env file (`EXTRA_APK=`, `EXTRA_NPM=`, `EXTRA_PIP=`, `EXTRA_CHECK=`), see
  `examples/with-extras.env`. Extras are installed at build time from the
  package registries, in their own layers (`/opt/extras`), and npm installs run
  with `--ignore-scripts`

The toolchains in this repository, and the numbers in
[docs/benchmarks](docs/benchmarks/README.md), are examples of combinations, not
the supported set.

The reason for an opinionated base is that a repository using one linter has no
use for Super-Linter. The value is in running a broad set of checks, so the base
is broad and each toolchain adds a stack on top.

## Block pull requests that outgrow the image

The image only contains the linters you enabled. If a pull request adds a file
type whose linters are not enabled (a `.rs` file when no Rust linter is on),
Super-Linter would silently skip it. The drift blocker fails that pull request
and says which linter to enable:

```yaml
jobs:
  drift:
    permissions:
      contents: read
    uses: ghwfxlab/superlint-lean/.github/workflows/drift-blocker.yml@main
    with:
      workflow: .github/workflows/super-linter.yaml   # the workflow with the super-linter step
      allow_ext: "txt lock"                    # file types you deliberately do not lint
```

The configuration is read from the `env:` of the Super-Linter step, with the
upstream rules: if any `VALIDATE_X` is `true`, only those linters run; if only
`false` values are set, everything else runs. `FILTER_REGEX_INCLUDE` and
`FILTER_REGEX_EXCLUDE` are respected. The same discovery works in the compiler:
`superlint-lean generate --workflow .github/workflows/super-linter.yaml ...`. Content-based
detections (OpenAPI, CloudFormation, Kubernetes, ARM, AWS States, Ansible) are
not modelled, so a YAML file of those kinds is only checked as plain YAML.

## Try it locally

```sh
superlint-lean generate --env base/opinionated.env --env toolchains/python.env \
  --upstream-tag v9.0.0 --upstream-dockerfile <upstream Dockerfile at that tag> --out build/python
docker buildx build build/python -t lean-python
docker run --rm -v "$PWD/build/python/checks.sh:/checks.sh:ro" --entrypoint bash lean-python /checks.sh
```

Profiles marked as needing the upstream `standard` image (dotnet, rust) are
compared against `standard`, not `slim`. Upstream has no Svelte-specific linter,
so the Svelte profile covers the JS, TS, CSS and HTML around it.

## Limitations

- Only linters in the mapping (`src/superlint_lean/data/linters.json`, 95 flags
  for upstream v9.0.0) can be selected. An unknown flag stops `generate` with a
  message, and new upstream linters start as drafts that need a review (see
  [CONTRIBUTING.md](CONTRIBUTING.md#extending-the-mapping)).
- The generator reads upstream's published image and `Dockerfile`. A release
  that moves tools around can break the mapping; `upstream-sync` reports it
  before the pin moves.
- The image is rebuilt after a change reaches `main`. A pull request that
  changes the enabled linters is still linted with the previous image, and the
  drift check only catches file types that no enabled linter covers.
- The saving comes from leaving linters out. With every mapped linter enabled the
  image is only about 11% smaller than upstream standard.
- A runner that already holds the upstream image gains nothing: the pull is a
  no-op either way.
- Pulling a private image needs credentials: `packages: read` for GHCR in the
  same organization, otherwise a registry login.
- Only `linux/amd64` is tested. Images are not signed yet.
- zstd layers are published and pull 0% to 15% faster than gzip; that is small next to leaving linters out.

## Licence

This repository is MIT licensed (see [LICENSE](LICENSE)). It contains no
third-party linters. A generated image is built by copying files out of the
published Super-Linter image, so it contains Super-Linter (MIT) and the linters
you select, each under its own licence. If you publish such an image you
redistribute those tools and must follow their licences; check them for the
linters you pick. The smoke test reads Super-Linter's test fixtures at build
time and does not copy them into this repository or into an image.
