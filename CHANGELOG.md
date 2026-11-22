# Changelog

All notable changes to `mcp-debugger` are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.2.0] — 2026-11-22

Major release introducing Causal Failure Attribution, Multi-Agent Hierarchy & Handoff Tracking, Cassette-Backed Handoff Replay, Enterprise CI/CD Gates, Compliance Exporters (SARIF & JUnit XML), Token Cost Attribution, and PostgreSQL Team Storage.

### Added

#### Causal Failure Attribution & Step Ablation
- `mcp-debugger attribute <session_id>`: isolate root cause step and Point-of-Commitment (PoC) using counterfactual step ablation.
- `AblationEngine`: offline VCR cassette perturbation with empty results and tool errors.
- `LiveCounterfactualEngine`: preflight cost estimator, live token sampling, and counterfactual branch re-execution.
- `FailureClassifier`: heuristic rules classifying failure boundaries (`agent`, `tool`, `protocol`, `none`).

#### Multi-Agent Hierarchy & Handoff Tracking
- `mcp-debugger agents <session_id>`: visualize agent delegation hierarchy with interactive Rich trees (`--tree`), handoff transitions (`--handoffs`), and JSON export (`--json`).
- Relational `agents` schema and `steps.agent_id` tracking foreign key hierarchy.
- SDK context tracking: `@trace_handoff` and `trace_handoff_context` capturing context state diffs (`added`, `removed`, `modified`).
- Multi-agent framework adapters: `CrewAITracker` / `trace_crewai`, `LangChainTracker` / `trace_langchain`, and `OpenAITracker` / `trace_openai`.

#### Cassette-Backed Handoff Replay
- `HandoffReplayEngine` (ADR 0003): re-execute downstream agents against static upstream execution history cassettes without non-deterministic divergence or re-execution cost.

#### Enterprise CI/CD Quality Gates
- `mcp-debugger ci <sessions...>`: tiered build gating across multiple session IDs or database files.
- Deterministic exit codes: exit 1 on protocol schema violations, tool execution errors, and replay regressions; exit 0 with non-blocking latency/cost warnings unless `--strict` is enabled.
- SARIF v2.1.0 exporter (`--sarif`): maps protocol violations, causal PoC findings, and replay regressions for native GitHub Code Scanning integration.
- JUnit XML exporter (`--junit`): standard test report XML (`<testsuites>`, `<testsuite>`, `<testcase>`) for CI/CD runners (GitHub Actions, Jenkins, GitLab CI).

#### Token & Cost Attribution Engine
- `CostCalculator`: model pricing registry supporting GPT-4o, Claude 3.5 Sonnet, Gemini 1.5/2.0, DeepSeek V3/R1, and custom models.
- Per-step token accounting and per-agent rollups with orchestrator/worker categorization and cost share percentages.
- Automated anomaly detection for token spikes (>3x step average) and budget exceedance (`--max-cost`).
- Integrated into `mcp-debugger stats` and `mcp-debugger ci`.

#### Team Storage & PostgreSQL Backend
- `PostgresDatabase` (ADR 0003): optional PostgreSQL backend using `asyncpg` with connection pooling.
- Unified backend routing via `get_database()` supporting `MCP_DEBUGGER_DATABASE_URL` and `config.toml` with zero-config fallback to local SQLite.
- Relational schemas for `sessions`, `messages`, `steps`, `agents`, `attributions`, `tools`, `errors`, and `replays`.

---

## [0.1.1] — 2026-06-29

### Added
- Created programmatically generated terminal demo GIF and embedded in README.
- Added scripts/generate_demo_gif.py.

### Fixed
- Fixed command prompt encoding and icon mapping issues for Windows environment.
- Resolved PyPI release duplicate release issue by bumping to 0.1.1.

## [0.1.0] — 2026-06-29

Initial release. Full-featured MCP session debugger with proxy recording, inspection, validation, replay, export, and analytics.

### Added

#### Core Proxy
- `proxy` command: transparent asyncio stdio proxy that records all MCP JSON-RPC messages to SQLite
- Session naming via `--name` / `-n`
- Verbose logging via `--verbose` / `-v`
- Graceful shutdown on `Ctrl+C` / EOF with guaranteed database cleanup (`try...finally`)
- 10 MB `StreamReader` limit to handle large MCP payloads without crashing

#### Session Management
- `list` command: browse historical sessions with status, message count, and timestamps
- Filter by status (`running`, `completed`, `error`) and limit via `--limit`
- JSON output mode (`--json`) for scripting and automation

#### Inspection
- `inspect` command: syntax-highlighted, formatted message browser using Rich
- Filter by method name (`--method`), direction (`--direction`), substring (`--search`)
- Pagination via `--limit` and `--offset`
- Output to file via `--output`

#### Protocol Validation
- `validate` command: rule-based MCP protocol compliance checker
- Live server validation (`--server`) and recorded session validation (`SESSION_ID`)
- Rules: handshake order, method name validity, tool schema format (JSON Schema Draft-07), error code validity
- JSON output for CI/CD integration (`--json`)
- Exit code `0` (pass) / `1` (critical failure)

#### Analytics
- `stats` command: comprehensive session dashboard — message counts, latency (p50/p95/p99), tool usage, error rates
- `compare` command: delta report between two sessions — latency regression, error rate changes, new/missing tools
- `errors` command: classified error list with category filter (`protocol`, `tool_execution`, `timeout`, `connection`, `unknown`)
- `tools` command: discovered tool list with call counts; full schema view via `--detail`

#### Replay & Regression Testing
- `replay` command: re-sends recorded client messages to a target server, compares responses with inline diffs
- Filter by method (`--filter-method`), limit messages (`--max-messages`), custom timeout (`--timeout`)
- JSON report output (`--json`) and file output (`--output`)
- Save replay results to database (`--save`)
- Exit codes: `0` (all match) / `1` (mismatches) / `2` (server crash)

#### Export
- `export` command with three formats:
  - **JSON** — structured machine-readable dump
  - **Markdown** — human-readable report with optional raw message blocks (`--include-raw`)
  - **OTLP** — OpenTelemetry traces sent to a Jaeger/Grafana/DataDog collector
- Per-format options: `--output`, `--pretty`, `--endpoint`, `--insecure`, `--service-name`, `--limit`
- OTLP requires optional install: `pip install "mcp-debugger[export]"`

#### Configuration
- `config` command with subcommands: `init`, `get`, `set`, `unset`, `list`, `reset`
- TOML config file at `~/.mcp-debugger/config.toml` (Linux/macOS) or `%APPDATA%\mcp-debugger\config.toml` (Windows)
- Dot-notation keys: `replay.timeout`, `aliases.fs`, `export.default_format`, etc.
- Server aliases for short-hand replay and proxy usage
- Graceful fallback to defaults on missing or corrupt config file
- CLI flag always overrides config file value

#### Environment Diagnostics
- `doctor` command: checks Python version, SQLite version, database directory, file permissions, schema version, Node.js, npx, git, PATH, config validity
- Exit code `0` (all good) / `1` (critical failure)

#### Storage
- SQLite database with 6 tables: `sessions`, `messages`, `tools`, `errors`, `replays`, `replay_messages`
- Async access via `aiosqlite` — non-blocking, event-loop friendly
- Schema version tracking via `PRAGMA user_version = 1`
- WAL mode for safe concurrent access

#### Test Suite
- 247 tests across unit, integration, property-based, and stress categories
- **96.54% line coverage**
- Tests run on Python 3.11 and 3.12, Ubuntu and Windows via GitHub Actions
- Property-based tests using `hypothesis` for schema round-trips and diff symmetry
- Stress tests: 10k-message sessions, large payload (50 MB), concurrent proxies

#### Documentation
- `README.md` with badges, feature overview, quickstart, and links
- `docs/commands.md` — full command reference with all options and examples
- `docs/architecture.md` — component overview, data flow, design decisions
- `docs/tutorials.md` — 5 step-by-step workflow guides
- `docs/faq.md` — 15+ Q&As covering installation, usage, and troubleshooting
- `docs/config.md` — full configuration key reference
- `docs/contributing.md` — development setup, test structure, CI details
- `CONTRIBUTING.md` — contributor quick-start

---

## Roadmap

These features are planned for future releases:

- **v0.2.0** — PyPI publish, `pip install mcp-debugger` from the public index
- **v0.3.0** — Web UI for browsing sessions in a browser (optional, via `mcp-debugger serve`)
- **v0.4.0** — Diff ignore paths configuration for non-deterministic replay fields
- **v0.5.0** — MCP schema version tracking and automatic upgrade migrations
