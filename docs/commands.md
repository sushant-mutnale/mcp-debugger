# CLI Commands Reference

This document describes all command line subcommands provided by `mcp-debugger`, with particular focus on the `validate` command.

## Subcommands Overview

*   `proxy`: Start transparent stdio proxy log capture.
*   `list`: View historical sessions.
*   `inspect`: Detailed inspect log lines of a session.
*   `tools`: Show discovered tools.
*   `errors`: List and filter classified errors from a session.
*   `validate`: Verify spec compliance on live servers or historical logs.
*   `stats`: Display a statistical performance and reliability dashboard for a session.
*   `compare`: Compare statistics and performance deltas between two sessions.
*   `export`: Export session data as JSON, Markdown, or OpenTelemetry (OTLP) traces.

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

---

## The `errors` Command

The `errors` command queries and lists categorized runtime errors recorded during a session, including both protocol errors and tool-execution failures.

### Usage Options

```bash
mcp-debugger errors [SESSION_ID] [OPTIONS]
```

*   `[SESSION_ID]`: The recorded session ID to retrieve errors from (required).
*   `--category <name>`: Filter errors by category: `protocol`, `tool_execution`, `timeout`, `connection`, or `unknown`.
*   `--json`: Outputs error results as a JSON array (useful for CI/CD scripting or integration).

### Examples

#### 1. Listing All Errors in a Session
```bash
mcp-debugger errors 5
```

#### 2. Filtering by Category
To display only tool execution failures:
```bash
mcp-debugger errors 5 --category tool_execution
```

#### 3. Output as JSON
```bash
mcp-debugger errors 5 --json
```

---

## The `stats` Command

The `stats` command aggregates and displays statistical reports of session performance, message sizes, tool call counts, latency trends, and category error distributions.

### Usage Options

```bash
mcp-debugger stats [SESSION_ID] [OPTIONS]
```

*   `[SESSION_ID]`: The recorded session ID to calculate statistics for (required).
*   `--limit <number>`: Limit the number of top active tools shown (default: 10).
*   `--json`: Output raw aggregated stats as JSON.
*   `--output <file>`: Write the report to a file (Markdown or JSON depending on the extension).

### Examples

#### 1. Visual single-session dashboard
```bash
mcp-debugger stats 5
```

#### 2. Limit top tools shown
```bash
mcp-debugger stats 5 --limit 3
```

#### 3. Write Markdown report to a file
```bash
mcp-debugger stats 5 --output report.md
```

---

## The `compare` Command

The `compare` command calculates deltas (differences) between two debugging sessions. This is ideal for testing regressions in latency, error rates, message sizes, and detecting newly introduced or missing tool calls.

### Usage Options

```bash
mcp-debugger compare [SESSION_ID_A] [SESSION_ID_B] [OPTIONS]
```

*   `[SESSION_ID_A]`: The baseline session (old).
*   `[SESSION_ID_B]`: The target session (new).
*   `--json`: Output raw comparison statistics as a JSON payload.

### Examples

#### 1. Compare two sessions
```bash
mcp-debugger compare 5 6
```

```bash
mcp-debugger compare 5 6 --json
```

---

## The `export` Command

The `export` command converts a recorded session into one of three formats:

- **JSON** – machine-readable, structured output for CI/CD pipelines and scripts.
- **Markdown** – human-readable report for documentation, code reviews, or email.
- **OTLP** – OpenTelemetry traces sent to a Jaeger / Grafana Tempo / DataDog collector.

### Usage

```bash
mcp-debugger export <session_id> --format {json,markdown,otlp} [OPTIONS]
```

### Options

| Option | Applies to | Description |
| :----- | :--------- | :---------- |
| `--format` | all | `json` (default), `markdown`, or `otlp` |
| `--output FILE` | json, markdown | Write to file instead of stdout |
| `--pretty` | json, markdown | Indent JSON / pretty-print raw blocks |
| `--include-raw` | markdown | Add `<details>` JSON blocks per message |
| `--endpoint URL` | otlp | OTLP endpoint (default `http://localhost:4317`) |
| `--insecure` | otlp | Disable TLS (for local testing) |
| `--service-name NAME` | otlp | Service name in traces (default `mcp-debugger`) |
| `--limit N` | all | Export only the first N messages |

### Examples

#### 1. Export as JSON to stdout
```bash
mcp-debugger export 5 --format json
```

#### 2. Export as pretty JSON to a file
```bash
mcp-debugger export 5 --format json --pretty --output session.json
```

#### 3. Generate a Markdown report
```bash
mcp-debugger export 5 --format markdown --output report.md
```

#### 4. Generate a Markdown report with full raw message JSON
```bash
mcp-debugger export 5 --format markdown --include-raw --output report.md
```

#### 5. Send traces to a local Jaeger instance
```bash
docker run -p 4317:4317 jaegertracing/all-in-one
mcp-debugger export 5 --format otlp --endpoint http://localhost:4317
```

### Installing OTLP support

The base package does not require OpenTelemetry libraries.  Install the optional group:

```bash
pip install 'mcp-debugger[export]'
```


