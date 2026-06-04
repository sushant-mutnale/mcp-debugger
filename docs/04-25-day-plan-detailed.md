# 25-Day Build Plan (Detailed)

This document provides a day-by-day blueprint for building the **MCP Debugger** (`mcp-debugger`) CLI application over a 25-day sprint cycle.

---

## Week 1: Foundation (Days 1-7)
**Theme**: Get the project skeleton, proxy core, and database working end-to-end.

### Day 1: Project Bootstrap & Environment
- **Goal**: Establish the repository layout, CLI version command, linting rules, and local unit test environment.
- **Tasks**:
  - [x] Initialize project with `uv init` (generate `pyproject.toml`, `.python-version`).
  - [x] Configure standard dev dependencies: `typer`, `rich`, `pydantic`, `pytest`, `pytest-asyncio`, `ruff`, `mypy`.
  - [x] Create project layout package structure and core directories (`proxy/`, `protocol/`, `storage/`, `replay/`, `exporters/`, `display/`).
  - [x] Write package initialization containing `__version__ = "0.1.0"`.
  - [x] Write Typer `cli.py` featuring a `version` command formatted inside a green `rich` panel.
  - [x] Setup and execute tests using `pytest` verifying version command exit states.
- **Verification**: `mcp-debugger version` executes and outputs formatted info. `ruff check` and `pytest` pass.

### Day 2: MCP Protocol Types & Pydantic Models
- **Goal**: Implement JSON-RPC 2.0 and MCP spec validation schemas using Pydantic.
- **Tasks**:
  - [ ] Implement [src/mcp_debugger/protocol/schemas.py](file:///d:/python/MCP_DEBUG/src/mcp_debugger/protocol/schemas.py) matching MCP 2025-03-26 specs.
  - [ ] Define message envelope types: `JSONRPCRequest`, `JSONRPCResponse`, `JSONRPCNotification`, `JSONRPCError`.
  - [ ] Define core MCP capabilities models: `InitializeRequest`, `InitializeResult`, `ClientCapabilities`, `ServerCapabilities`, `Tool`, `CallToolParams`, `ListToolsResult`.
  - [ ] Implement envelope helper checks (e.g. `is_request()`, `is_notification()`).
  - [ ] Write unit tests checking valid / invalid message structures.
- **Verification**: `pytest tests/test_protocol.py` passes with >90% coverage.

### Day 3: SQLite Database & Schema
- **Goal**: Implement the SQLite storage layers and database manager interfaces.
- **Tasks**:
  - [ ] Create database connection helper in `src/mcp_debugger/storage/database.py`.
  - [ ] Write raw SQL schemas for tables: `sessions`, `messages`, `tools`, `errors`.
  - [ ] Implement database interactions: `init_db()`, `create_session()`, `log_message()`, `log_tool()`, `log_error()`, `close_session()`.
  - [ ] Configure automatic database file creation under target `~/.mcp-debugger/sessions.db`.
  - [ ] Write database tests.
- **Verification**: Scheme initialized successfully and `pytest tests/test_storage.py` runs green.

### Day 4: Stdio Proxy Core — The Heart
- **Goal**: Build the asynchronous stdio man-in-the-middle proxy engine.
- **Tasks**:
  - [ ] Write proxy core in `src/mcp_debugger/proxy/stdio_proxy.py`.
  - [ ] Implement server subprocess instantiation using `asyncio.subprocess`.
  - [ ] Build concurrently running reader/writer loops using `asyncio.gather` to pipe client `stdin` <-> server `stdin` and server `stdout` <-> client `stdout`.
  - [ ] Ensure non-blocking database log hooks intercept and log messages without causing stdio latency.
  - [ ] Handle subprocess exits, client terminations, and malformed outputs cleanly.
- **Verification**: Standard pipes function correctly when communicating with a dummy target (e.g., `cat`).

### Day 5: CLI Commands — proxy and list
- **Goal**: Expose active proxy intercepting and session history listing commands.
- **Tasks**:
  - [ ] Hook up `mcp-debugger proxy --server "<command>"` execution path in CLI.
  - [ ] Implement OS signal listeners (like `SIGINT` / `Ctrl+C`) to clean up subprocesses.
  - [ ] Build the `mcp-debugger list` command rendering historical sessions in a table utilizing `rich`.
  - [ ] Implement filters by status (`running`, `completed`, `error`) and limits.
- **Verification**: Active sessions start, run, and shutdown cleanly on signal interrupts. `mcp-debugger list` displays tables correctly.

### Day 6: CLI Command — inspect
- **Goal**: Implement the detailed session inspection utility.
- **Tasks**:
  - [ ] Create `mcp-debugger inspect <session_id>` command.
  - [ ] Render session summaries, total metrics, and message logs using syntax-highlighted console outputs.
  - [ ] Code-color events (e.g. blue for handshake, green for tool calls, yellow for warnings, red for errors).
  - [ ] Implement filters: `--method`, `--direction`, and pipeline-friendly `--json`.
- **Verification**: Inspectors render beautiful output and formatting handles heavy payloads.

### Day 7: Week 1 Integration Test & Polish
- **Goal**: Assemble and test end-to-end flows.
- **Tasks**:
  - [ ] Write integration pipeline tests (start mock server -> intercept client payload -> verify DB write -> run inspect verify output).
  - [ ] Create `mcp-debugger doctor` command to diagnostic configurations, paths, and server availability.
  - [ ] Author documentation for installation and quickstart.
- **Verification**: Complete test pipelines run successfully.

---

## Week 2: Deep Debugging (Days 8-14)
**Theme**: Tool discovery, protocol validation, and error classification.

### Day 8: Tool Discovery & Extraction
- **Goal**: Automatically audit and log tool schemas discovered during sessions.
- **Tasks**:
  - [ ] Intercept server responses matching `tools/list` method.
  - [ ] Parse individual tools and save schema data to SQLite `tools` table.
  - [ ] Implement `mcp-debugger tools <session_id>` command showing discovered tools and schema summaries.
  - [ ] Add deep schema details display command: `mcp-debugger tools <session_id> --detail <tool_name>`.
- **Verification**: Discovered tools populate DB on proxy startup and render on command requests.

### Day 9: Protocol Validator Core
- **Goal**: Build the rules engine ensuring protocol spec compliance.
- **Tasks**:
  - [ ] Create compliance checker rules in `src/mcp_debugger/protocol/validator.py`.
  - [ ] Validate initialize hands, method syntax, schema structures, and capability rules.
  - [ ] Build diagnostic feedback formats: `ValidationResult` storing checks, messages, and suggestions.
- **Verification**: Invalid sequences or schema errors trigger structured alerts during execution.

### Day 10: CLI Command — validate
- **Goal**: Expose compliance checks for automated CI test setups.
- **Tasks**:
  - [ ] Implement `mcp-debugger validate --server "<command>"` executing a full connection test suite.
  - [ ] Automate client initialize queries, list tools requests, check schemas, and score compliance.
  - [ ] Format terminal audit logs; use `exit 0` on compliance and `exit 1` on failures.
- **Verification**: Validator runs against target server command and outputs diagnostic compliance scores.

### Day 11: Error Classification Engine
- **Goal**: Map and parse errors into human-actionable alerts.
- **Tasks**:
  - [ ] Write mapping tables in `src/mcp_debugger/protocol/error_classifier.py`.
  - [ ] Catch protocol errors (`-32601`), tool call failures, network timeouts, and subprocess exceptions.
  - [ ] Incorporate error suggestions (e.g. schema mismatches, misspelled tools) and display them in inspector alerts.
- **Verification**: Invalid tool requests or server errors parse and present colored warnings.

### Day 12: Session Statistics & Analytics
- **Goal**: Extract telemetry, latency metrics, and performance charts.
- **Tasks**:
  - [ ] Calculate tool call latencies, error frequencies, and query counters.
  - [ ] Render Sparklines in CLI dashboard.
  - [ ] Create `mcp-debugger stats` and comparative query command `mcp-debugger compare <id_a> <id_b>`.
- **Verification**: Metrics match DB values, comparators trace latency differences cleanly.

### Day 13: Export Formats — JSON & Markdown
- **Goal**: Export session data to JSON and Markdown format.
- **Tasks**:
  - [ ] Build exporters mapping DB logs into text dumps.
  - [ ] Ensure output JSON structures are compatible with frontend readers (e.g., AgentPrism).
  - [ ] Create `mcp-debugger export <session_id> --format <json|markdown> --output <filepath>` CLI paths.
- **Verification**: Exported files match requested specs and validate successfully.

### Day 14: Week 2 Integration & Testing with Real MCP Servers
- **Goal**: Test compatibility against real public MCP servers.
- **Tasks**:
  - [ ] Run proxy setups against `@modelcontextprotocol/server-filesystem`, `@modelcontextprotocol/server-fetch`, and `postgresql`.
  - [ ] Log potential server compatibility quirks and write corresponding documentation pages.
- **Verification**: Proxy and inspector run without errors when hooked to live MCP servers.

---

## Week 3: Replay & Advanced Features (Days 15-21)
**Theme**: Session replay, diff comparison, and OpenTelemetry export.

### Day 15: Replay Engine Core
- **Goal**: Replay captured sessions to local server instances.
- **Tasks**:
  - [ ] Write logic in `src/mcp_debugger/replay/engine.py`.
  - [ ] Read client request sequences and forward them to newly spun server subprocesses.
  - [ ] Capture output responses and map them back to request chains.
- **Verification**: Sequence replays preserve order and log new server outputs correctly.

### Day 16: CLI Command — replay
- **Goal**: Expose replay execution and support selective replaying.
- **Tasks**:
  - [ ] Create `mcp-debugger replay <session_id> --server "<command>"` command.
  - [ ] Add progress indicators showing active replaying steps.
  - [ ] Add flags: `--interactive` (pauses step-by-step) and `--speed` parameters.
- **Verification**: Interactive and automated replays complete cleanly.

### Day 17: Diff Engine
- **Goal**: Compare replayed server responses with historical traces.
- **Tasks**:
  - [ ] Write deep comparison engine in `src/mcp_debugger/replay/diff.py`.
  - [ ] Ignore noise variations (like request IDs or system timestamps).
  - [ ] Color difference tables (green for added properties, red for missing values).
- **Verification**: Schema or parameter changes show up as formatted diff highlights.

### Day 18: Replay + Diff Integration
- **Goal**: Integrate replay and validation for CI regression testing.
- **Tasks**:
  - [ ] Build combined command: `mcp-debugger replay <session_id> --diff`.
  - [ ] Calculate total regression similarity scores.
  - [ ] Exit with appropriate codes (`0` for matching, `1` for divergence) for pipeline builds.
- **Verification**: CI pipeline executes regression suites and flags unexpected changes correctly.

### Day 19: OpenTelemetry OTLP Exporter
- **Goal**: Map session flows to OpenTelemetry trace structures.
- **Tasks**:
  - [ ] Build OTLP client mapping MCP messages to span networks (sessions = trace root, requests = span scopes, tool calls = sub-spans).
  - [ ] Send traces directly to OTLP collector endpoints.
- **Verification**: Traces display within visualization engines (like Jaeger or Tempo).

### Day 20: Configuration Management
- **Goal**: Expose global settings management.
- **Tasks**:
  - [ ] Build parser in `src/mcp_debugger/config.py` loading `~/.mcp-debugger/config.toml`.
  - [ ] Store settings: default db path, OTLP collectors, color outputs, and server commands shortcuts (aliases).
  - [ ] Expose settings configuration command: `mcp-debugger config set <key> <value>`.
- **Verification**: CLI tools read settings and aliases execute target configurations correctly.

### Day 21: Week 3 Polish — Performance & Edge Cases
- **Goal**: Benchmarking, batch insertions, and robust error checking.
- **Tasks**:
  - [ ] Optimize database interactions using query batching.
  - [ ] Support massive JSON messages (>1MB) and raw binary outputs.
  - [ ] Add verbosity controllers (`--verbose`, `--quiet`).
- **Verification**: System processes massive payload volumes without performance loss.

---

## Week 4: Testing, Documentation & Launch Prep (Days 22-25)
**Theme**: Make it rock-solid, documented, and ready for GitHub.

### Day 22: Comprehensive Test Suite
- **Goal**: Run test audits and aim for test coverage metrics > 80%.
- **Tasks**:
  - [ ] Configure `pytest-cov` inside `pyproject.toml`.
  - [ ] Author property-based checks using `hypothesis` targeting message serialization round-trips.
  - [ ] Perform stress testing: run 10k messages and check concurrent session bounds.
- **Verification**: Tests run, pass, and hit code coverage milestones.

### Day 23: Documentation & README
- **Goal**: Polish documentation directories and README files.
- **Tasks**:
  - [ ] Write detailed command tables inside `docs/commands.md`.
  - [ ] Polish root README adding screenshots or interactive logs.
  - [ ] Complete inline docstrings across codebases.
- **Verification**: Documentation links and markdown pages are readable and render correctly.

### Day 24: Packaging & Distribution
- **Goal**: Finalize wheel distributions and setup automated GitHub Actions.
- **Tasks**:
  - [ ] Validate wheel production setups using `uv build`.
  - [ ] Implement GitHub Action files: test runs on PR merges, tag updates trigger wheel publications to PyPI.
- **Verification**: Package installs cleanly into blank virtual environments and runs.

### Day 25: Final Polish & GitHub Launch
- **Goal**: Perform reviews, resolve debug TODOs, tag releases, and push to main.
- **Tasks**:
  - [ ] Review codes and fix remaining console issues.
  - [ ] Push codebase tag `v0.1.0`.
  - [ ] Prepare launch writeups.
- **Verification**: Codebase is clean, tagged, pushed, and runs in PyPI environments.
