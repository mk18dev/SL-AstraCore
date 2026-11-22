<div align="center">

<img src="docs/logo.png" width="128" alt="SL-AstraCore logo"/>

# SL-AstraCore

**Repository Observatory — turn any codebase into a navigable knowledge graph**

Scan → Parse → Graph → Enrich → Context Packs, behind a live star-chart dashboard.

[![CI](https://github.com/Mk18dev/SL-AstraCore/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Mk18dev/SL-AstraCore/actions/workflows/ci.yml)
[![mypy](https://img.shields.io/badge/mypy-clean-blue)](#quality)
[![ruff](https://img.shields.io/badge/ruff-clean-blue)](#quality)
[![Python](https://img.shields.io/badge/python-3.11+-informational)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-windows%20%7C%20linux%20%7C%20macOS-lightgrey)](#install)

</div>

---

**SL-AstraCore** indexes a repository into a persistent knowledge graph — files,
functions, classes and their import relationships — then answers natural-language
queries with ranked, token-budgeted context packs ready to hand to any AI coding
agent.

The dashboard renders your repository as a **star chart**: every file is a star,
every import a constellation line, patterns and conflicts are marked in the log.

## Features

- **11 parser adapters over 22 file extensions** — Python via `ast`; JavaScript, TypeScript, TSX, Go, Rust, Java, C, C++, C#, Ruby and PHP via tree-sitter; Markdown with wiki-link semantics
- **Persistent knowledge graph** — DuckDB (default) or SQLite, incremental indexing with atomic batch upserts
- **Graph enrichment** — design-pattern detection (`repository`, `factory`, …), naming-convention analysis and cross-module naming-conflict detection, all wired into the index pipeline
- **Context engine** — intent analysis, keyword/seed ranking, BFS dependency expansion, hard token budgets
- **Model provider** — configure an OpenAI-compatible chat endpoint from the dashboard (hosted APIs or local Ollama); API keys stay server-side and are never returned by the settings API
- **Agent loop** — builds repository context, calls the configured model, reviews proposed edits against real files, and refuses unanchored or unparsable changes; applying is a separate, explicit step
- **Live dashboard** — SSE event stream, interactive canvas star chart, file explorer, patch review, execution monitor, telemetry sparklines

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/Mk18dev/SL-AstraCore.git
cd SL-AstraCore
pip install -r requirements.txt
pip install -e .
```

Or run everything in Docker:

```bash
docker compose up --build     # dashboard on http://localhost:8780
```

## Quick start

```bash
# 1. launch the observatory — it prints a local URL and bearer token separately
python dashboard_app.py
#   Open  http://127.0.0.1:8780/
#   Access token: <printed separately in the terminal>

# 2. add a repository from the UI, or use the CLI:
astra index F:\path\to\repo
astra context F:\path\to\repo "how does authentication work"
astra serve --port 8780
```

### Ask a question and get a reviewed edit

The agent loop takes the answer from whatever model you use, reviews it against
the real files, and writes nothing until you say so:

```bash
# run your model however you like, then review its reply
astra propose F:\path\to\repo "why does charge subtract one" \
    --reply reply.json --emit proposal.json

# read it, then apply it
astra apply F:\path\to\repo proposal.json
```

The same review is `POST /api/agent/propose`, which takes a supplied model
reply. The dashboard's **Run AI review** action uses the configured provider
through `POST /api/agent/run`, builds repository context, and returns reviewed
proposals. Both return diffs, risk, and rejection reasons. An edit whose
`old_text` is not verbatim in the file it names is refused rather than applied,
and `astra apply` refuses a proposal whose file changed since the review.

Open **Model settings** in the dashboard to configure an OpenAI-compatible
endpoint and model ID. Leave the API key field blank to preserve a saved key.
The key is stored in `~/.astra/providers.json` (or
`$ASTRA_HOME/providers.json`) with POSIX mode `0600` where supported. It is
plaintext at rest, never returned by the settings API, and should be protected
with local filesystem permissions. Remote endpoints require HTTPS; HTTP is
allowed only for loopback providers such as Ollama.

The dashboard mints an access token at startup and requires a bearer header on
every API call. The HTML shell is public but never contains the token; paste the
token printed separately in the terminal when the dashboard prompts. It is kept
in the current tab's session storage and is never placed in a URL. Pin a stable
token with `ASTRA_TOKEN=...`; authentication cannot be disabled.

Repository data lives in `~/.astra` (override with the `ASTRA_HOME` environment
variable). Each repo gets its own deterministic graph database.

## Dashboard

| Panel | What it shows |
|---|---|
| **Explorer** | full filesystem tree of the registered repo |
| **Star Chart** | knowledge graph as an interactive star map — degree-sized stars, selection reticle, zoom/pan |
| **Inspector** | spectral breakdown of the selected node: dependencies, dependents |
| **Context** | live context packs: tokens, nodes, confidence + top-ranked files |
| **Monitor** | pipeline progress from the SSE stream |
| **Patch Review** | per-file review with apply/reject actions |
| **Runtime / Telemetry / Signal Log** | store health, memory gauge, latency sparks, live event feed |

## Architecture

```text
RepositoryScanner → ParserRegistry → ImportResolver → DuckDB/SQLite
                                                    ↓
                                        Pattern/Conflict Enrichment
                                                    ↓
                       ContextEngine ← RuntimeOrchestrator
                              ↓
                     FastAPI Dashboard (SSE)
```

| Module | Responsibility |
|---|---|
| `astra/scanner` | streaming walk, hash checkpoint resume, ignore rules |
| `astra/parser` | per-language adapters behind one registry; graceful text fallback |
| `astra/resolver` | imports → intra-repo graph edges |
| `astra/graph` | mutator diffing, pattern/conflict enrichment |
| `astra/storage` | DuckDB/SQLite backends, set-based upserts |
| `astra/context` | task analysis, ranking, token budgeting |
| `astra/runtime` | orchestrator, event bus, replayable execution journal |
| `astra/patch` | semantic diff and risk scoring for a proposed edit |
| `astra/agent` | the loop: pack → model → reviewed edit → explicit apply |

## Quality

```bash
python -m pytest tests/ -q
python -m mypy astra/ dashboard_app.py          # Success: no issues in 96 files
python -m ruff check astra/ tests/ dashboard_app.py   # All checks passed
```

The codebase is type-clean under mypy and lint-clean under the project Ruff
ruleset. The last fully verified run (#45082074980) reported 498 passing tests,
95.3% line coverage (5,176 / 5,434 executable lines), and green checks on Linux,
Windows and macOS with Python 3.11 and 3.12.

The required workflow gate includes tests, lint, type checking, wheel
build/install smoke tests, Docker smoke tests, CodeQL, dependency audit, and a
minimum 95% line coverage threshold for the `astra/` package.

### Known limitations

Deliberate, not accidental:

- **Single-user access control.** The dashboard is protected by a per-process
  bearer token, not by accounts or roles. Direct launches bind to
  `127.0.0.1` by default; setting `ASTRA_HOST` explicitly opts into a
  different bind address. Docker binds to `0.0.0.0` inside the container, so
  publish it only behind a trusted TLS-terminating proxy and firewall.
- **Provider scope.** Only OpenAI-compatible chat completions are implemented;
  native Anthropic/Gemini protocols and model streaming are not.
- **API key storage.** Provider keys are plaintext at rest in the local config
  file, protected by POSIX mode `0600` where supported. They are not encrypted.
- **Estimated token counts.** Context budgets use a conservative UTF-8
  heuristic, not a model-specific tokenizer; exact provider token counts are
  not guaranteed.
- **Branch protection.** The CI gate is green, but GitHub branch-protection
  settings are not confirmed active. See
  [the required main-branch settings](docs/BRANCH_PROTECTION.md).
- **A re-index reads the whole node table.** Unchanged files are not parsed
  again, which makes a re-index with nothing to do about 3x faster than a full
  one, but the write still reads every node, so a run with one changed file
  costs about the same as a full index.
- **Config keys are indexed, values are not.** `.json` / `.yaml` / `.toml` are
  parsed for their key paths (`server.port`), so a question about a setting
  finds the file that declares it. The values themselves are not in the graph.
- **BLIND_MAX depth.** Source nested deeper than ~900 levels (minified
  JavaScript) is skipped by the tree-sitter traversal.

## Project and security documents

- [Implementation status](IMPLEMENTATION_STATUS.md)
- [Open issues and verified gaps](ISSUES.md)
- [Contributing and quality policy](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Required main branch protection](docs/BRANCH_PROTECTION.md)

## License

MIT — see [LICENSE](LICENSE).
