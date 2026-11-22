# SL-AstraCore — implementation status

Last verified code commit: `ec7d3b1c7c9835d789037787d07348209d462b0b`
Verification date: 2026-11-23

This file replaces the October 1 status snapshot. Historical performance
numbers from that snapshot are not treated as current measurements.

## What the project is

SL-AstraCore is a local-first Repository Intelligence Engine. Its core job is
to scan a repository, parse supported languages, build a persistent
intermediate representation and dependency graph, then retrieve ranked,
source-grounded context for a query.

The analyzer works without an API key. A model provider is an optional adapter
for the separate AI review workflow; it is not required for indexing or
context retrieval.

## Verified CI baseline

GitHub Actions run [#45082074980](https://github.com/Mk18dev/SL-AstraCore/actions/runs/45082074980)
completed successfully on the code commit above.

| Gate | Verified result |
|---|---|
| Tests | 498 passed on Ubuntu / Python 3.11 |
| OS and Python matrix | Ubuntu, macOS, Windows × Python 3.11 and 3.12 — 6/6 green |
| Ruff | Passed |
| mypy | Passed |
| Line coverage for astra/ | 95.3% — 5,176 / 5,434 executable lines |
| Wheel | Built and installed outside the source tree on the matrix |
| Docker | Build and smoke test passed |
| CodeQL | Passed |
| Pinned dependency audit | Passed |
| Aggregate CI required gate | Passed |

Coverage is measured by the repository's standard-library line tracer. It is
line coverage, not branch coverage or model-token accuracy. The enforced
minimum is 95.0%; the last measured result was 95.3%.

## Implemented capabilities

- Unified repository ingestion and filesystem scanning, including ignore rules,
  deterministic file identities, incremental metadata, and persistent
  checkpoint/manifest state.
- Parser registry and language adapters feeding the repository IR.
- Import/dependency resolution that preserves ambiguity rather than inventing
  a unique target when multiple candidates remain.
- Persistent graph/storage backends and source-grounded context retrieval.
- Ranked context packs with a bounded estimated-token budget.
- Authenticated local dashboard/API, explicit repository confinement, and
  bearer-authenticated runtime streaming.
- Dashboard provider settings for OpenAI-compatible chat-completions endpoints.
  The API key is never returned by the settings API.
- AI review builds context, calls the configured model, and reviews proposed
  edits against repository files. Review does not write files; apply remains a
  separate explicit operation.
- Wheel build/install checks and Docker smoke testing in CI.

## Security and deployment posture

- Direct dashboard launches bind to `127.0.0.1` by default. Network binding
  requires an explicit `ASTRA_HOST` setting.
- Docker binds inside the container to `0.0.0.0`; publish only behind a trusted
  TLS-terminating reverse proxy and firewall.
- Provider keys are stored in `$ASTRA_HOME/providers.json` (default
  `~/.astra/providers.json`). POSIX mode is set to `0600`; the secret is
  plaintext at rest. Windows operators must protect the directory with ACLs.
- The dashboard is single-user bearer-token auth, not multi-user RBAC.
- Branch protection is not confirmed active. The required settings are
  documented in [docs/BRANCH_PROTECTION.md](docs/BRANCH_PROTECTION.md), but the
  connected GitHub integration exposes read operations only for those
  administration settings.

## Known limitations — not represented as completed

1. Provider protocol support is OpenAI-compatible chat completions only.
   Native Anthropic/Gemini protocols and streaming model responses are not
   implemented.
2. The context budget uses a conservative UTF-8 heuristic, not a
   model-specific tokenizer. The bound is enforced against that estimator; it
   is not a guarantee of exact provider token counts.
3. API keys are permission-restricted but not encrypted at rest.
4. No built-in TLS termination, user accounts, or RBAC.
5. Branch protection must be enabled and verified by a repository
   administrator.
6. Performance benchmarks have not been rerun on this current code baseline.
   Numbers in older status documents are historical and must not be used as
   current performance claims.
7. Parser and graph relation coverage is language- and fixture-dependent.
   Presence of a parser does not imply complete call-graph or reference
   extraction for every language.

## Deployment boundary

No Vercel integration or deployment has been created. That remains outside the
approved scope.
