# Verifying a pulled image

The image that `self-image.yaml` publishes (`ghcr.io/ghwfxlab/lintsmith/super-linter-lean`) carries two proofs
of where it came from. Both are stored next to the image in GHCR, so they cost nothing when you pull it.

| Proof | What it says | Made by |
| :--- | :--- | :--- |
| Signature | This digest was pushed by the `self-image.yaml` workflow of this repository. | `cosign sign` with a keyless GitHub OIDC identity, logged in the public Sigstore transparency log. |
| Build provenance | This digest was built by that workflow run, from this commit. | `actions/attest-build-provenance` (SLSA provenance). |

Verify the digest you run, not a moving tag. `latest` and `<upstream tag>` move with every rebuild; the
`<upstream tag>-<short sha>` tag is immutable. Resolve a tag to a digest first:

```sh
image=ghcr.io/ghwfxlab/lintsmith/super-linter-lean
digest="$(docker buildx imagetools inspect "$image:latest" --format '{{.Manifest.Digest}}')"
```

## Signature

```sh
cosign verify \
  --certificate-identity "https://github.com/ghwfxlab/lintsmith/.github/workflows/self-image.yaml@refs/heads/main" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  "$image@$digest"
```

The command fails when the image was not signed by that workflow on `main`. Anyone who can push to GHCR cannot forge
the identity; only that workflow can obtain a certificate for it.

## Build provenance

```sh
gh attestation verify "oci://$image@$digest" --repo ghwfxlab/lintsmith
```

The output names the workflow, the commit and the run that built the image.

## Your own images

An image you build with the composite action (`action.yml`) is not signed by it: pushing, signing and recording the
tag stay with your workflow, as the action needs no secrets. Copy the sign and attest steps of `self-image.yaml`, and
give the job the `id-token: write` and `attestations: write` permissions.

## Benchmarks

Signatures and attestations are separate OCI artifacts that point at the image digest. The image manifest, its
layers and the tags that the benchmark pulls do not change, and `--provenance=false --sbom=false` stays on the
benchmark builds so that those images stay plain OCI images.
