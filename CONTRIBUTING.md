# Contributing

## Supported development environment

- Python 3.11 and 3.12 are the supported CI versions.
- The test suite and core analyzer must work without a model provider or API key.
- Provider tests must mock HTTP calls. Never use a real key in tests or fixtures.

## Local setup

    python -m venv .venv
    # Activate the environment, then:
    python -m pip install -r requirements.txt
    python -m pip install -e .
    python -m pip install pytest ruff mypy build

## Required local checks

Run these before opening a pull request:

    python -m pytest tests/ -q
    python -m ruff check astra/ tests/ dashboard_app.py
    python -m mypy astra/ dashboard_app.py
    python coverage.py
    python -m build

For the container smoke path:

    docker build -t sl-astracore .

## Engineering rules

1. Preserve the local-first analyzer path. Indexing, parsing, graph construction,
   and context retrieval must remain usable with no provider configured.
2. Keep provider credentials server-side. Tests must assert that secrets never
   appear in API responses, logs, snapshots, or generated artifacts.
3. AI-generated edits are proposals. Do not make review endpoints write files;
   applying must remain a separate explicit operation with stale-file checks.
4. Keep repository paths confined to the registered repository root. Add tests
   for traversal, symlinks, ambiguous imports, and unreadable files when touching
   scanner, resolver, or patch code.
5. Preserve cross-platform behavior. Add regression coverage for Linux, macOS,
   and Windows rather than assuming POSIX path or process semantics.
6. Do not weaken the coverage threshold, skip a failing test, or make a CI job
   non-blocking merely to get a green run. Fix the underlying issue.
7. Update the implementation status and known limitations when behavior or
   verified gates change. Do not copy old benchmark numbers forward without
   re-running the benchmark on the current commit.

## Pull request and CI policy

The required workflow is **CI required gate**. It aggregates the OS/Python test
matrix, lint, typing, wheel build/install, coverage, Docker smoke test, CodeQL,
and dependency audit. A pull request is not ready to merge unless this gate is
green on the exact head commit.

The repository's branch-protection settings are separate from workflow code.
See [Branch protection](docs/BRANCH_PROTECTION.md) for the required main-branch
settings. Direct pushes may still be technically possible until those settings
are enabled by a repository administrator.

No Vercel deployment is part of this repository workflow.
