# Project Context (MCP Debugger)

This file provides a quick, structured summary of **MCP Debugger** for AI coding assistants to quickly bootstrap context.

---

## 1. Project Overview & Vision
- **Name**: `mcp-debugger`
- **Description**: A local-first, transparent man-in-the-middle stdio proxy CLI tool designed to debug, intercept, record, and replay sessions between Model Context Protocol (MCP) clients and servers.
- **Primary stack**: Python 3.11+, Pydantic v2, Typer, Rich, SQLite (`sqlite3`).

---

## 2. Directory Layout & Module Index

```text
mcp-debugger/
├── pyproject.toml              # Build settings (hatchling backend), dependencies & tool configurations
├── CONTRIBUTING.md             # Developer workflow, style policies & pre-commit guides
├── PROJECT_CONTEXT.md          # This file (AI bootstrap details)
├── src/
│   └── mcp_debugger/
│       ├── __init__.py         # Package entry, exposes version (v0.1.0)
│       ├── cli.py              # Typer CLI application entry point
│       ├── proxy/              # Interception and stdio pipe routing logic
│       ├── protocol/           # Pydantic validation schemas & spec compliance checker
│       ├── storage/            # SQLite interface layer & history schemas
│       ├── replay/             # Replay simulation engine & deep diff tools
│       ├── exporters/          # Exporters mapping database logs to JSON, Markdown, or OTLP
│       └── display/            # Rich console output panel formats & tables
└── tests/                      # Pytest suite
    ├── test_cli.py             # CLI version assertions
    ├── fixtures/               # Test payload assets
    ├── sample_sessions/        # Sample SQLite traces
    └── mock_servers/           # Mock subprocess targets
```

---

## 3. Configured Development Tooling

- **Build Backend**: Hatchling (`hatchling.build`)
- **Package Manager**: UV or standard Pip
- **Linting & Formatting**: Ruff (target version: `py311`, line length: 100)
- **Static Type Checking**: MyPy (enabled in strict mode)
- **Testing**: Pytest (configured for asynchronous checks via `pytest-asyncio` auto mode)

---

## 4. Current Implementation State
- **CLI Base**: Typer CLI set up in `cli.py` mapped to entry script `mcp-debugger`.
- **Commands**:
  - `mcp-debugger version`: Displays version inside a Rich panel. Safely defaults if terminal doesn't support emojis.
- **Tests**: `test_version` validated and passes.
- **Quality Checks**: Code formatting and typing are verified green.
- **Skeletons**: All sub-package directories exist and have empty `__init__.py` initializers.
