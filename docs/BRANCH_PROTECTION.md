# Main branch protection

The workflow itself is implemented in .github/workflows/ci.yml. GitHub branch
protection is a separate repository setting and must be enabled for main.

## Required settings

Use either classic branch protection or a repository ruleset targeting the
main branch, with enforcement set to Active.

- Require a pull request before merging.
- Required approving reviews: 0 while this is a single-maintainer repository;
  raise to 1 when another maintainer is available.
- Require status checks to pass before merging.
- Select the exact required check: CI required gate.
- Require branches to be up to date before merging.
- Require conversation resolution before merging.
- Block force pushes.
- Block branch deletion.
- Apply the rules to administrators as well; do not add a broad bypass list.

The CI required gate aggregates the platform/Python matrix, lint, typing,
coverage, wheel build and install, Docker smoke test, CodeQL, and dependency
audit. Requiring the aggregate gate avoids maintaining a second, drifting list
of individual job names in repository settings.

## Verification

After enabling protection, inspect the main branch settings and confirm that
the rule is Active and that CI required gate appears in required status checks.
Open a test pull request and verify that merge remains blocked until the gate
is green on the exact pull-request head commit.

## Current state

As of 2026-11-23, the CI workflow and aggregate gate exist, but branch
protection has not been confirmed as active. The connected GitHub integration
can read repository content and workflow state but does not expose the
administration write operation needed to create or change branch-protection
rules. A green Actions run must not be described as proof that main is
protected.
