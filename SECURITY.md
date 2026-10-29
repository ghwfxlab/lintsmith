# Security Policy

## Supported Versions

We actively support and patch the latest release of `lintsmith`.

| Version | Supported          |
| ------- | ------------------ |
| v0.x    | :white_check_mark: |

## Reporting a Vulnerability

If you discover a potential security vulnerability in this project, please open
an issue using our **Security Report** template.

We will acknowledge your report within 48 hours and provide a timeline for
addressing the issue. Thank you for helping keep this project secure!

## Scope notes

- The `drift` command and the reusable drift-blocker workflow never run
  repository code. They read the Super-Linter workflow and the list of changed
  files only.
- `generate` installs extra npm packages with `--ignore-scripts`, at image build
  time, from the package registries.
