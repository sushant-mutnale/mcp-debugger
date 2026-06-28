# Architecture Overview

This document explains how `mcp-debugger` is designed — for contributors, maintainers, and anyone who wants to understand the internals.

---

## High-Level Design

`mcp-debugger` is a **transparent stdio proxy**. It intercepts the JSON-RPC 2.0 messages that flow between an MCP client (e.g. Claude Desktop) and an MCP server, logging them to a local SQLite database without adding visible latency.

```
┌────────────────┐        stdin/stdout        ┌──────────────────────┐        stdin/stdout        ┌──────────────┐
│   MCP Client   │ ◄────────────────────────► │  mcp-debugger proxy  │ ◄────────────────────────► │  MCP Server  │
│ (Claude, etc.) │                            │                      │                            │ (filesystem, │
└────────────────┘                            │  ┌────────────────┐  │                            │  GitHub, ..) │
                                              │  │  SQLite DB     │  │                            └──────────────┘
                                              │  │  sessions.db   │  │
                                              │  └────────────────┘  │
                                              └──────────────────────┘
```

Key design principles:

- **Zero-latency forwarding**: messages are forwarded immediately; database writes happen concurrently as background tasks
- **Local-first**: no network calls, no cloud dependency, no signup
- **Read-only replay**: recorded sessions can be replayed to test new server versions without side effects on the original data

---

## Module Structure

```
src/mcp_debugger/
├── __init__.py
├── cli.py                  # Typer CLI — all subcommands
├── analytics.py            # Aggregation logic for stats/compare
├── config.py               # TOML config — load, get, set, save
├── validate_live.py        # Live server validation harness
│
├── proxy/
│   └── stdio_proxy.py      # Core asyncio stdio proxy
│
├── storage/
│   └── database.py         # SQLite CRUD via aiosqlite
│
├── protocol/
│   ├── schemas.py          # Pydantic models for JSON-RPC + MCP types
│   ├── validator.py        # Rule-based protocol compliance checker
│   └── error_classifier.py # Categorise errors by type/severity
│
├── replay/
│   ├── engine.py           # Replay loop — send messages, collect responses
│   └── diff.py             # JSON diff utility for response comparison
│
├── exporters/
│   ├── __init__.py
│   ├── json_exporter.py    # Export session as JSON
│   ├── markdown_exporter.py # Export session as Markdown report
│   ├── otlp_exporter.py    # Export as OpenTelemetry traces (live)
│   └── otlp_replay_exporter.py # OTLP for replay results
│
└── display/
    └── __init__.py         # Rich UI helper utilities
```

---

## Component Details

### 1. Proxy (`proxy/stdio_proxy.py`)

The core of the tool. When `mcp-debugger proxy` runs:

1. Spawns the MCP server as an `asyncio` subprocess
2. Reads `stdin` from the client and forwards it to the server's `stdin`
3. Reads `stdout` from the server and forwards it to the client's `stdout`
4. On each message, launches a **background task** to parse and persist it to SQLite
5. On `Ctrl+C` / EOF, shuts down the subprocess and closes the database

**StreamReader limit:** Set to 10 MB to handle large MCP payloads without crashing.

**Thread safety:** All database calls use `aiosqlite` (async SQLite), so the asyncio event loop is never blocked.

### 2. Storage (`storage/database.py`)

A single SQLite file at `~/.mcp-debugger/sessions.db` (or `%APPDATA%\mcp-debugger\sessions.db` on Windows).

#### Tables

| Table | Description |
|---|---|
| `sessions` | One row per proxy run — name, start time, status |
| `messages` | One row per JSON-RPC message — direction, method, latency, raw JSON |
| `tools` | Tools discovered from `tools/list` responses |
| `errors` | Classified errors from messages |
| `replays` | Replay run metadata (when `--save` is used) |
| `replay_messages` | Per-message replay results and diffs |

#### Schema version

The `PRAGMA user_version` is set to `1`. The `doctor` command checks this to warn if the DB is stale.

### 3. Protocol (`protocol/`)

- **`schemas.py`** — Pydantic v2 models for `JSONRPCRequest`, `JSONRPCResponse`, `JSONRPCNotification`, tool definitions, and MCP-specific types. Used for parsing and validation.
- **`validator.py`** — Rule-based engine. Each rule is a callable that receives the message list and returns a `ValidationResult`. Rules check: handshake order, method name validity, schema format, error code validity.
- **`error_classifier.py`** — Maps error codes and patterns to categories: `protocol`, `tool_execution`, `timeout`, `connection`, `unknown`.

### 4. Replay (`replay/`)

- **`engine.py`** — Reads recorded client messages from the DB, sends them to a new server subprocess in order, collects responses, and compares them to the originals using `diff.py`.
- **`diff.py`** — JSON-aware diff. Computes field-level diffs between two JSON objects, ignoring ordering differences and optionally ignoring configured paths (e.g. timestamps).

### 5. Exporters (`exporters/`)

Each exporter takes a session ID, fetches data from the database, and outputs in the target format:

- **JSON** — structured dump suitable for scripts, CI pipelines, and downstream processing
- **Markdown** — human-readable report with message tables and optional raw JSON blocks
- **OTLP** — OpenTelemetry traces, one span per message, sent to a Jaeger/Grafana/DataDog collector

### 6. CLI (`cli.py`)

Built with [Typer](https://typer.tiangolo.com/) + [Rich](https://github.com/Textualize/rich). All subcommands are in a single file for discoverability. Each subcommand:

1. Resolves the database path from config or environment
2. Opens a database connection
3. Calls the relevant module (storage, analytics, exporter, etc.)
4. Renders output with Rich or plain JSON
5. Closes the database in a `try...finally` block (guaranteed cleanup)

### 7. Config (`config.py`)

TOML file at `~/.mcp-debugger/config.toml`. The `Config` class:
- Loads with `tomllib` (Python 3.11+ stdlib)
- Saves with `tomli_w`
- Supports dot-notation keys: `replay.timeout`, `aliases.fs`, etc.
- Falls back to hardcoded defaults if the file is missing or corrupt

**Precedence:** `CLI flag > config file > hardcoded default`

---

## Data Flow: Recording a Session

```
1. User runs: mcp-debugger proxy --server "npx ..." --name "test"

2. CLI parses args → calls stdio_proxy.run()

3. stdio_proxy:
   ├── Opens DB → creates session row (status=running)
   ├── Spawns server subprocess
   └── Starts 3 asyncio tasks:
       ├── client_to_server_loop:  stdin → parse → DB write (bg) → server.stdin
       ├── server_to_client_loop:  server.stdout → parse → DB write (bg) → stdout
       └── monitor_loop:          watches for server exit

4. On Ctrl+C / EOF:
   ├── Sends EOF to server
   ├── Waits for server to exit (with timeout)
   ├── Updates session status → completed
   └── db.close()
```

## Data Flow: Replaying a Session

```
1. User runs: mcp-debugger replay 42 --server "node new_server.js"

2. CLI → replay.engine.run_replay(session_id=42, server_cmd=...)

3. Engine:
   ├── Fetches client messages from DB (direction=client_to_server)
   ├── Spawns server subprocess
   ├── For each message:
   │   ├── Sends to server stdin
   │   ├── Reads server response (with timeout)
   │   └── Compares response to original → diff
   └── Renders diff report (or JSON)

4. Exit code: 0 (all match) | 1 (mismatches) | 2 (server crash)
```

---

## Design Decisions

### Why SQLite?

- Zero-infrastructure: no server process required, works out of the box
- Sufficient for the data volumes involved (thousands to millions of messages)
- Readable by many tools (`sqlite3`, DB Browser, datasette)
- `aiosqlite` provides async access without blocking the event loop

### Why asyncio?

MCP sessions are I/O-bound: reading from stdin/stdout, writing to the database. Asyncio allows concurrent forwarding in both directions on a single thread with minimal overhead.

### Why Typer + Rich?

Typer generates a clean CLI from Python type annotations with zero boilerplate. Rich provides beautiful terminal output (panels, tables, syntax highlighting) with no extra configuration.

### Why a single `cli.py`?

All subcommands are in one file to keep the codebase navigable. At ~2000 lines, it is long but cohesive. Future versions may split into `cli/` subpackages if it grows further.

---

## Testing Architecture

```
tests/
├── conftest.py              # Shared fixtures: in-memory DB, temp dirs
├── test_cli/                # CLI command tests via typer.testing.CliRunner
├── test_storage/            # Database CRUD tests (async, real SQLite)
├── test_protocol/           # Schema parsing, validation rules, classifier
├── test_proxy/              # Proxy lifecycle with mock subprocesses
├── test_replay/             # Engine and diff logic
├── test_exporters/          # JSON, Markdown, OTLP exporters
├── test_config/             # Config load/save/get/set
├── test_integration/        # End-to-end: proxy → inspect → export → replay
├── test_property.py         # Hypothesis property-based tests
└── test_stress.py           # Concurrency and large-payload stress tests
```

Coverage target: **>90%** across all modules. See [Contributing](contributing.md) for how to run the test suite.
