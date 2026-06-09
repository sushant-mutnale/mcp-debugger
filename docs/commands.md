# CLI Commands Reference

This document describes all command line subcommands provided by `mcp-debugger`, with particular focus on the `validate` command.

## Subcommands Overview

*   `proxy`: Start transparent stdio proxy log capture.
*   `list`: View historical sessions.
*   `inspect`: Detailed inspect log lines of a session.
*   `tools`: Show discovered tools.
*   `validate`: Verify spec compliance on live servers or historical logs.

---

## The `validate` Command

The `validate` command analyzes Model Context Protocol (MCP) message compliance with the official v2025-03-26 specification.

### Usage Options

```bash
mcp-debugger validate [SESSION_ID] [OPTIONS]
```

*   `[SESSION_ID]`: Optional positional argument representing the recorded session ID to validate.
*   `-s, --server <command>`: Live MCP server command line to spin up and test.
*   `--json`: Outputs validation results as a raw JSON array of validation objects (useful for CI/CD scripting).

---

### Examples

#### 1. Validating a Live Server
Spins up the filesystem server, executes the handshake sequence (`initialize` request -> `initialize` response -> `notifications/initialized` notification -> `tools/list` request -> response), and prints a color-coded rich compliance report.

```bash
mcp-debugger validate --server "npx -y @modelcontextprotocol/server-filesystem /tmp"
```

#### 2. Validating a Recorded Session
Performs post-mortem sequence validation on a previously recorded session stored in the SQLite debugger database:

```bash
mcp-debugger validate 42
```

#### 3. Output as JSON for CI/CD Pipelines
Validates a server and outputs JSON formatting:

```bash
mcp-debugger validate --server "python my_server.py" --json
```

**Output format:**
```json
[
  {
    "rule_name": "initialize_first",
    "passed": true,
    "severity": "critical",
    "message": "First request from client was 'initialize'",
    "suggestion": null,
    "context": null
  },
  {
    "rule_name": "tool_schema_validity",
    "passed": false,
    "severity": "critical",
    "message": "Tool 'write_file' inputSchema is not a valid JSON schema...",
    "suggestion": "Ensure inputSchema matches Draft-07 format standards",
    "context": { ... }
  }
]
```

### Exit Codes
*   `0`: Compliance check succeeded (no **critical** rule failures found. Warnings are allowed).
*   `1`: Compliance check failed (one or more **critical** failures found, or subprocess failed to launch).
