# CLI Reference

```text
lintsmith <command> [options]
lintsmith --version
```

Run `lintsmith <command> --help` for the full option list of a command.

## `generate`

Generate a lean image build context from `VALIDATE_*` flags.

| Option | Description |
| :--- | :--- |
| `--env FILE` | Env file with `VALIDATE_*=true` lines (repeatable). |
| `--workflow FILE` | Read the flags from the Super-Linter step of a workflow (repeatable). |
| `--all` | Select every flag in the mapping. |
| `--exclude FLAG` | Drop a flag, with or without the `VALIDATE_` prefix (repeatable). |
| `--extra-apk`, `--extra-npm`, `--extra-pip` | Extra packages installed at build time (repeatable). |
| `--extra-check CMD` | Command that must succeed in the built image (repeatable). |
| `--upstream-tag TAG` | Upstream release, for example `v9.0.0` (required). |
| `--upstream-dockerfile FILE` | The upstream Dockerfile at that tag (required). |
| `--out DIR` | Output directory (required). |
| `--mapping FILE` | Mapping to use instead of the bundled `linters.json`. |

Writes `Dockerfile`, `prune-node-modules.js`, `checks.sh` and `plan.json` to
`--out` and prints the upstream baseline variant (`slim` or `standard`).

## `drift`

Fail when changed files are not covered by the configured linters.

| Option | Description |
| :--- | :--- |
| `--workflow FILE`, `--env FILE` | Where the configuration comes from (repeatable). |
| `--base REF` | Diff against this Git ref. |
| `--files-from FILE` | File with one changed path per line. |
| `--root DIR` | Repository root (default: current directory). |
| `--allow-ext EXT` | Extension or filename you deliberately do not lint (repeatable). |
| `--warn-only` | Report but exit `0`. |
| `--report FILE` | Write a Markdown report. |

Exit codes: `0` all covered, `1` uncovered files, `2` configuration error.

## `sync-mapping`

Compare the bundled mapping with an upstream checkout and add draft entries.

| Option | Description |
| :--- | :--- |
| `--upstream DIR` | Upstream Super-Linter checkout (required). |
| `--write` | Add draft entries to the mapping file. |
| `--report FILE` | Write a Markdown report. |
| `--mapping FILE` | Mapping to update instead of the bundled one. |

Exit codes: `0` nothing missing, `10` drafts were added or flags need a manual mapping.

## `release-notes`

Write release notes comparing the benchmarks of two upstream versions.

| Option | Description |
| :--- | :--- |
| `--old-tag`, `--old-dir` | Previous upstream tag and its `bench-*.jsonl` directory (required). |
| `--new-tag`, `--new-dir` | New upstream tag and its results directory (required). |
| `--profiles A,B` | Limit the comparison to these profiles. |
| `--mapping-diff FILE` | Append the mapping changes between the versions. |
| `--out FILE` | Also write the notes to a file. |

## `bench`

Time `docker pull` and the container start of an image. Used by the benchmark workflow.

```text
lintsmith bench IMAGE [RUNS] VARIANT RUNNER [--mode cold|warm] [--out FILE] [--split]
```

| Option | Description |
| :--- | :--- |
| `RUNS` | Number of runs (default 5). |
| `VARIANT`, `RUNNER` | Labels written to every row, normally `<profile>/<kind>` and the runner environment. |
| `--mode` | `cold` (default, `$BENCH_MODE`): before every run remove the image and every other unused image and the build cache, so no variant can reuse another's layers. `warm`: the image stays; a first unmeasured pull makes sure it is there. |
| `--out FILE` | JSON lines file to append to (default `bench-results.jsonl`, `$BENCH_OUT`). Each row is also printed. |
| `--split` | Also time a download-only pull with crane and a `docker load` in cold mode (`BENCH_SPLIT=1`); a rough download against unpack split. |

Rows carry `image`, `variant`, `runner`, `mode`, `run`, `pull_s`, `start_s`, `download_s`, `load_s`, `compressed_bytes`
(read with crane when installed) and `uncompressed_bytes`.

Exit codes: `0` done, `1` a Docker call failed, `2` a bad argument.

## `compare`

Markdown tables from benchmark results: lean against the upstream baseline, per profile.

```text
lintsmith compare FILE.jsonl...
```

Reads the `bench-*.jsonl` and `build-*.jsonl` files written by the benchmark workflow (one run per line, `variant`
is `<profile>/<kind>`). Prints a cold-pull table (median pull time, speedup, sizes, baseline drift, build time) and a
warm-pull table. Percentages round half away from zero, so a small negative change prints as `-0%`; a baseline drift
above 15% is marked `WARN`.

Exit codes: `0` printed, `2` no file given or a file could not be read.

## `summarize`

One row per runner, mode and variant, with the median and the range of the runs.

```text
lintsmith summarize FILE.jsonl...
```

Same input and exit codes as `compare`. Rows without a runner (the build timings) print `null` and come first.

## `repository-settings`

Print or apply the repository settings in [repository-settings.md](../repository-settings.md). Maintainer tooling.

```text
lintsmith repository-settings OWNER/REPO [--apply]
```

Without `--apply` it prints the `gh api` calls it would make. With `--apply` it runs them through the `gh` CLI,
which must be logged in as an administrator of the repository: the merge options, the Actions permissions
(commit-pinned actions, a read-only default token, workflows cannot approve pull requests) and the default-branch
ruleset (sent on stdin). A failing call is reported and the rest still run.

Exit codes: `0` done, `1` a call failed, `2` the repository is not `OWNER/REPO`.

## `select-upstream`

Pick the upstream Super-Linter release to sync to.

```text
lintsmith select-upstream --pinned-file upstream-version.txt [--force-tag TAG] [--cooldown-days N] [--repo OWNER/REPO]
```

| Option | Description |
| :--- | :--- |
| `--pinned-file FILE` | The file with the pinned upstream tag. |
| `--force-tag TAG` | Use this tag, even if it is not the latest, and skip reading the releases. |
| `--cooldown-days N` | Only consider releases at least `N` days old (default `0`). |
| `--repo OWNER/REPO` | The upstream repository (default `super-linter/super-linter`). |

Reads the releases with the `gh` CLI and takes the newest published one (no draft, no pre-release) that is old enough. A
target that is not newer than the pinned version counts as current. Prints a summary line and, when `GITHUB_OUTPUT`
is set, writes `pinned`, `latest` and `behind` (`true` or `false`) to it.

Exit codes: `0` done, `2` a bad argument or the releases could not be read.

## `smoke`

Lint upstream's good and bad fixtures with a built image, one linter at a time.

```text
lintsmith smoke <image> <plan.json> <upstream-dir> [--mapping linters.json] [--jobs N]
```

| Argument | Description |
| :--- | :--- |
| `image` | The image to test, for example the one built from `generate`'s output. |
| `plan.json` | Written by `generate`; its `flags` list says which linters to test. |
| `upstream-dir` | A Super-Linter checkout at the tag the image was built from (only `test/linters`, `.editorconfig` and `.github/linters` are read). |
| `--jobs` | Test this many flags at the same time (default `1`). The table keeps the order of the plan; one progress line per flag goes to stderr. |
| `--mapping` | The `linters.json` whose flags are mapped (default: the bundled one). Mapped flags that are not in the plan are the disabled linters. |

Prints a Markdown table with one row per flag. A flag passes when the good files pass and the bad files fail
in the Super-Linter summary; a linter that found no files counts as a failure. Flags without a fixture
directory are reported, not failed. Files in a fixture directory that are neither good nor bad (a `package-info.java`,
an `.editorconfig`, a `.sqlfluff`) are support files and go into both runs; the few upstream files that a linter reads
(`.editorconfig` for ktlint and dotnet format, the clj-kondo and ESLint config in `.github/linters`) are copied first, so a
fixture can override them. A few fixtures do not behave on upstream's own image either (the good Checkov and biome
format files, the bad pre-commit file); they are listed as skipped.

After the table it enables every flag of the plan at once and puts the bad fixtures of the mapped linters that are
not in the plan into the repository. None of those linters may appear in the summary: a disabled linter is skipped,
not run and not failing. The line below the table says `Disabled linters: ok (N skipped)`, or names the linters
that ran anyway. An image with every mapped linter has nothing to skip.

Exit codes: `0` every flag behaved and the disabled linters were skipped, `1` at least one did not, `2` the plan could not be read.
