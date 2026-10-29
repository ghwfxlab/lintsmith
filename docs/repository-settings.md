# Repository settings

The settings below limit how people and automation can interact with the
repository. They mirror the ghwm repository and are not stored in Git, so
`lintsmith repository-settings` applies them with the `gh` CLI:

```sh
lintsmith repository-settings OWNER/REPO            # print what would be sent
lintsmith repository-settings OWNER/REPO --apply    # apply (needs admin rights)
```

## Merging

| Setting | Value | Why |
| :--- | :--- | :--- |
| Squash merge | allowed (title: PR title, message: PR body) | One conventional commit per pull request. |
| Merge commit, rebase merge | disabled | Keeps history linear. |
| Auto-merge | disabled | A person decides when to merge. |
| Delete branch on merge | enabled | No stale branches. |
| Update branch | allowed | Contributors can bring a pull request up to date. |
| Wiki, projects | disabled | Documentation lives in `docs/`. |

## GitHub Actions

| Setting | Value | Why |
| :--- | :--- | :--- |
| SHA pinning required | enabled | Every action is pinned to a commit SHA; dependabot proposes updates. |
| Default workflow token | read-only | Workflows request the permissions they need per job. |
| Approve pull requests from workflows | disabled | Automation cannot approve its own changes. |

The weekly `upstream-sync` opens its pull request with the `SYNC_PR_TOKEN`
secret, a fine-grained token limited to this repository with "Pull requests:
write" (and "Contents: read"). It is not `GITHUB_TOKEN`, so the setting above
stays disabled, and the pull request starts the tests and the lint. Without the
secret the branch is pushed but no pull request is opened. A fine-grained token
expires; renew it before then (a GitHub App token would not).

Workflows start with `permissions: {}` and grant per-job permissions. Pull
request workflows must never run on a self-hosted runner.

## Default branch ruleset

- No deletion and no force pushes.
- Linear history required.
- Pull request required: one approving review, stale approvals dismissed on push, approval of the last push, resolved review threads, squash merge only.
- Required status checks (branch must be up to date): `Lint, type-check, test`, `Run Super-Linter`, `Validate PR Title`.

Optional on top, when the owner enables them: code scanning (CodeQL) and code
quality gates, a required reviewing team with a bypass for pull requests, and a
tag ruleset for `v*` tags that only the release app may create.
