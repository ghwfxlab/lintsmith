# Run the lean image with the ghwm registry workflows

The ghwm registry ships two workflows that work together with superlint-lean:

| Workflow | What it does |
| --- | --- |
| `super-linter` 2.0.0 | Runs Super-Linter. When `SUPER_LINTER_CUSTOM_IMAGE` is set it runs that image instead of the upstream one, and the slim and full jobs are skipped. |
| `super-linter-lean` 1.0.0 | Builds the lean image from `.github/super-linter.env` with the superlint-lean action, scans it with Trivy, pushes it to GHCR and records its tag in the `SUPER_LINTER_CUSTOM_IMAGE` repository variable. |

`super-linter` 2.0.0 is in the registry. `super-linter-lean` is in review as
[ghwm-registry#42](https://github.com/ghwfxlab/ghwm-registry/pull/42).

## Set it up

1. Declare both workflows in `ghwm.yml`:

   ```yaml
   source: ghwfxlab/ghwm-registry
   workflows:
     - name: super-linter
       version: 2.0.0
     - name: super-linter-lean
       version: 1.0.0
   ```

2. Run `ghwm install --update-envs`. Without `--update-envs`, an upgrade of an
   existing `super-linter` workflow keeps your old `env:` block and does not add
   `SUPER_LINTER_CUSTOM_IMAGE`.
3. In `.github/workflows/super-linter.yaml` point the image at the variable the
   lean workflow writes:

   ```yaml
   env:
     SUPER_LINTER_CUSTOM_IMAGE: ${{ vars.SUPER_LINTER_CUSTOM_IMAGE }}
   ```

4. Run the `super-linter-lean` workflow once. It pushes the image and writes its
   tag to the variable, which needs the `GH_APP_ID` and `GH_APP_PRIVATE_KEY`
   secrets. Without them the job summary prints the `gh variable set` command to
   run yourself.

While the variable is empty, `super-linter` runs the upstream image chosen by
`RUN_SUPER_LINTER_SLIM`. Once it is set, only `Run Super-Linter Custom Image` runs.

## Proof that it works

The registry branch of #42 was installed into this repository on a throwaway
branch, `test/registry-42-lean`, with `ghwm install --local --update-envs`. The
only manual changes were a temporary push trigger and the env line from step 3.

| Run | Result |
| --- | --- |
| [`super-linter-lean`](https://github.com/ghwfxlab/superlint-lean/actions/runs/39211817075) | Built, smoke-tested every enabled linter, passed the Trivy report and gate, pushed `latest`, `v9.0.0` and `v9.0.0-<sha>`. No App secrets, so it took the warning path. |
| [`super-linter`](https://github.com/ghwfxlab/superlint-lean/actions/runs/39211817052) | `setup` chose the custom job; `Run Super-Linter Custom Image` pulled the pushed tag and passed; the slim and full jobs were skipped. |

The first custom-image run was red on a zizmor error that the slim run showed too,
because the Trivy action was pinned to a tag object instead of a commit. It is
pinned to the commit in the registry, and the runs above are green.

## Verify the image

Images from this repository's own `self-image.yaml` are signed and carry build
provenance; see [verifying-images.md](verifying-images.md). The registry workflow
does not sign its image yet.
