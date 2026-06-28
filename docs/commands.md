# Command Reference

Complete reference for every `mcp-debugger` CLI command.

## Overview

```
mcp-debugger <command> [OPTIONS]
```

| Command | Description |
|---|---|
| [`proxy`](#proxy) | Record MCP session traffic via stdio proxy |
| [`list`](#list) | List historical debugging sessions |
| [`inspect`](#inspect) | Browse messages from a recorded session |
| [`tools`](#tools) | View discovered tools and schemas |
| [`errors`](#errors) | List classified errors from a session |
| [`stats`](#stats) | Statistical dashboard for a session |
| [`compare`](#compare) | Delta report between two sessions |
| [`validate`](#validate) | Check MCP protocol compliance |
| [`replay`](#replay) | Replay a session against a server |
| [`export`](#export) | Export session to JSON / Markdown / OTLP |
| [`config`](#config) | Manage user preferences |
| [`doctor`](#doctor) | Environment diagnostics |
| [`version`](#version) | Show installed version |

---

## `proxy`

Launch a transparent stdio proxy that sits between an MCP client and server, logging every message to SQLite.

```bash
mcp-debugger proxy --server <command> [OPTIONS]
```

### Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--server` | `-s` | `TEXT` | required | Shell command to launch the MCP server |
| `--name` | `-n` | `TEXT` | `None` | Friendly label for this session |
| `--verbose` | `-v` | flag | `False` | Print debug information to stderr |

### Examples

```bash
# Record a filesystem server session
mcp-debugger proxy --server "npx -y @modelcontextprotocol/server-filesystem /tmp" --name "fs-test"

# Record with verbose logging
mcp-debugger proxy --server "python my_server.py" --name "dev" --verbose

# Use a config alias instead of a full command
mcp-debugger config set aliases.fs "npx -y @modelcontextprotocol/server-filesystem /tmp"
mcp-debugger proxy --server "$(mcp-debugger config get aliases.fs)"
```

### How it works

```
[MCP Client] ←─stdin/stdout─→ [mcp-debugger proxy] ←─stdin/stdout─→ [MCP Server]
                                         │
                                         ▼
                                  [~/.mcp-debugger/sessions.db]
```

Press `Ctrl+C` to stop the proxy and close the session.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Session ended cleanly |
| `1` | Server failed to start or crashed |

---

## `list`

List all recorded debugging sessions, newest first.

```bash
mcp-debugger list [OPTIONS]
```

### Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--limit` | `-l` | `INTEGER` | `20` | Maximum number of sessions to display |
| `--status` | | `TEXT` | `None` | Filter by status: `running`, `completed`, `error` |
| `--json` | | flag | `False` | Output as a JSON array for scripting |

### Examples

```bash
# List last 20 sessions
mcp-debugger list

# List last 50 sessions
mcp-debugger list --limit 50

# Show only completed sessions
mcp-debugger list --status completed

# Output JSON for use in scripts
mcp-debugger list --json | jq '.[0].session_id'
```

---

## `inspect`

Browse and filter messages from a specific recorded session with syntax-highlighted, formatted output.

```bash
mcp-debugger inspect <session_id> [OPTIONS]
```

### Arguments

| Argument | Type | Description |
|---|---|---|
| `session_id` | `INTEGER` | ID of the session to inspect (required) |

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--method` | `TEXT` | `None` | Filter by method name (e.g. `tools/call`) |
| `--direction` | `TEXT` | `None` | Filter by direction: `client_to_server` or `server_to_client` |
| `--search` | `TEXT` | `None` | Substring search in the JSON body |
| `--limit` | `INTEGER` | `None` | Maximum number of messages to show |
| `--offset` | `INTEGER` | `None` | Skip the first N messages |
| `--json` | flag | `False` | Output raw JSON instead of rich terminal format |
| `--output` / `-o` | `TEXT` | `None` | Write output to a file |

### Examples

```bash
# Inspect all messages in session 3
mcp-debugger inspect 3

# Only show tool calls
mcp-debugger inspect 3 --method tools/call

# Only show messages from client to server
mcp-debugger inspect 3 --direction client_to_server

# Search for a specific tool name
mcp-debugger inspect 3 --search "read_file"

# Page through results
mcp-debugger inspect 3 --limit 20 --offset 40

# Save output to file
mcp-debugger inspect 3 --output session3.txt
```

---

## `tools`

View all tools discovered during a session, including their input schemas and call counts.

```bash
mcp-debugger tools <session_id> [OPTIONS]
```

### Arguments

| Argument | Type | Description |
|---|---|---|
| `session_id` | `INTEGER` | ID of the session (required) |

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--detail` | `TEXT` | `None` | Show full input schema for a specific tool name |
| `--json` | flag | `False` | Output raw JSON array for scripting |

### Examples

```bash
# List all tools discovered in session 5
mcp-debugger tools 5

# Show full schema for a specific tool
mcp-debugger tools 5 --detail read_file

# Output as JSON
mcp-debugger tools 5 --json
```

---

## `errors`

List and filter classified errors recorded during a session, including protocol violations and tool failures.

```bash
mcp-debugger errors <session_id> [OPTIONS]
```

### Arguments

| Argument | Type | Description |
|---|---|---|
| `session_id` | `INTEGER` | ID of the session (required) |

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--category` | `TEXT` | `None` | Filter by: `protocol`, `tool_execution`, `timeout`, `connection`, `unknown` |
| `--json` | flag | `False` | Output raw JSON array |

### Examples

```bash
# All errors in session 5
mcp-debugger errors 5

# Only tool execution failures
mcp-debugger errors 5 --category tool_execution

# JSON output for CI scripting
mcp-debugger errors 5 --json
```

---

## `stats`

Display a comprehensive statistical dashboard for a session: message counts, latency, tool usage, error rates.

```bash
mcp-debugger stats <session_id> [OPTIONS]
```

### Arguments

| Argument | Type | Description |
|---|---|---|
| `session_id` | `INTEGER` | ID of the session (required) |

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--limit` | `INTEGER` | `10` | Number of top tools to show |
| `--json` | flag | `False` | Output raw JSON |
| `--output` | `TEXT` | `None` | Write report to a file |

### Examples

```bash
# Terminal dashboard
mcp-debugger stats 5

# Top 3 tools only
mcp-debugger stats 5 --limit 3

# Save as Markdown
mcp-debugger stats 5 --output report.md

# JSON for scripting
mcp-debugger stats 5 --json
```

---

## `compare`

Generate a delta report between two sessions: latency regression, error rate changes, new/missing tool calls.

```bash
mcp-debugger compare <session_id_a> <session_id_b> [OPTIONS]
```

### Arguments

| Argument | Type | Description |
|---|---|---|
| `session_id_a` | `INTEGER` | Baseline session (before) |
| `session_id_b` | `INTEGER` | Target session (after) |

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--json` | flag | `False` | Output raw JSON |

### Examples

```bash
# Compare session 5 (baseline) vs session 6 (new)
mcp-debugger compare 5 6

# JSON output
mcp-debugger compare 5 6 --json
```

---

## `validate`

Check a live server or recorded session for MCP protocol compliance (handshake order, method names, JSON schemas).

```bash
mcp-debugger validate [SESSION_ID] [OPTIONS]
```

### Arguments

| Argument | Type | Description |
|---|---|---|
| `session_id` | `INTEGER` | Recorded session ID (optional — use instead of `--server`) |

### Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--server` | `-s` | `TEXT` | `None` | Live server command to spin up and test |
| `--json` | | flag | `False` | Output results as JSON array |

### Examples

```bash
# Validate a live server
mcp-debugger validate --server "npx -y @modelcontextprotocol/server-filesystem /tmp"

# Validate a previously recorded session
mcp-debugger validate 42

# JSON output for CI/CD
mcp-debugger validate --server "python my_server.py" --json
```

### JSON output format

```json
[
  {
    "rule_name": "initialize_first",
    "passed": true,
    "severity": "critical",
    "message": "First request from client was 'initialize'",
    "suggestion": null,
    "context": null
  }
]
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All critical rules passed (warnings allowed) |
| `1` | One or more critical failures found |

---

## `replay`

Replay client messages from a recorded session against a target server, comparing responses and generating diff reports.

```bash
mcp-debugger replay <session_id> --server <command> [OPTIONS]
```

### Arguments

| Argument | Type | Description |
|---|---|---|
| `session_id` | `INTEGER` | Session to replay (required) |

### Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--server` | `-s` | `TEXT` | required | Server command to replay against |
| `--timeout` | | `INTEGER` | `5000` | Per-request timeout in milliseconds |
| `--max-messages` | | `INTEGER` | `None` | Replay only the first N messages |
| `--filter-method` | | `TEXT` | `None` | Replay only messages matching this method |
| `--verbose` | `-v` | flag | `False` | Show all messages, not just mismatches |
| `--json` | | flag | `False` | Output raw JSON report |
| `--output` / `-o` | | `TEXT` | `None` | Write output to a file |
| `--save` | | flag | `False` | Save replay results to the database |
| `--no-diff` | | flag | `False` | Show counts only, no inline diffs |

### Examples

```bash
# Regression test a new server version
mcp-debugger replay 42 --server "python build/my_server.py"

# Only replay tool calls
mcp-debugger replay 42 --server "node server.js" --filter-method tools/call

# JSON output for CI
mcp-debugger replay 42 --server "node server.js" --json

# Save results to DB for later comparison
mcp-debugger replay 42 --server "node server.js" --save
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All replayed messages matched |
| `1` | Completed but one or more responses mismatched |
| `2` | Server crashed, timed out, or failed to start |

---

## `export`

Export a recorded session to JSON, Markdown, or OpenTelemetry (OTLP) traces.

```bash
mcp-debugger export <session_id> --format {json,markdown,otlp} [OPTIONS]
```

### Arguments

| Argument | Type | Description |
|---|---|---|
| `session_id` | `INTEGER` | Session to export (required) |

### Options

| Option | Applies to | Default | Description |
|---|---|---|---|
| `--format` | all | `json` | `json`, `markdown`, or `otlp` |
| `--output` | json, markdown | `None` | Write to file instead of stdout |
| `--pretty` | json, markdown | `False` | Pretty-print JSON / include headers |
| `--include-raw` | markdown | `False` | Add collapsible raw JSON blocks per message |
| `--endpoint` | otlp | `http://localhost:4317` | OTLP collector endpoint |
| `--insecure` | otlp | `False` | Disable TLS |
| `--service-name` | otlp | `mcp-debugger` | Service name in traces |
| `--limit` | all | `None` | Export only the first N messages |

### Examples

```bash
# Export as JSON to stdout
mcp-debugger export 5 --format json

# Pretty JSON to file
mcp-debugger export 5 --format json --pretty --output session.json

# Markdown report
mcp-debugger export 5 --format markdown --output report.md

# Markdown with raw message JSON
mcp-debugger export 5 --format markdown --include-raw --output full-report.md

# Send traces to local Jaeger
docker run -p 4317:4317 jaegertracing/all-in-one
mcp-debugger export 5 --format otlp --endpoint http://localhost:4317 --insecure
```

---

## `config`

Manage persistent user preferences stored in `~/.mcp-debugger/config.toml`.

```bash
mcp-debugger config <subcommand> [OPTIONS]
```

### Subcommands

| Subcommand | Description |
|---|---|
| `init` | Create the default config file |
| `get <key>` | Print the value of a config key |
| `set <key> <value>` | Set a config key and save |
| `unset <key>` | Delete a key (reverts to default) |
| `list` | Show all config values |
| `reset` | Overwrite config with factory defaults |

### Examples

```bash
# Create config file
mcp-debugger config init

# See all values
mcp-debugger config list

# Set a server alias
mcp-debugger config set aliases.fs "npx -y @modelcontextprotocol/server-filesystem /tmp"

# Set default replay timeout
mcp-debugger config set replay.timeout 10000

# Read a value
mcp-debugger config get replay.timeout

# Remove a key (go back to default)
mcp-debugger config unset replay.timeout

# Reset everything
mcp-debugger config reset
```

See [Configuration Reference](config.md) for all available keys.

---

## `doctor`

Run environment diagnostics: Python version, SQLite version, database file permissions, Node.js, npx, git.

```bash
mcp-debugger doctor
```

### What it checks

1. Python 3.11+ installed
2. SQLite 3.35.0+ available
3. `~/.mcp-debugger/` directory is writable
4. `sessions.db` file permissions (warns if not `600` on Linux/macOS)
5. Database schema version
6. `npx` available on PATH
7. `node` available on PATH
8. `git` available on PATH
9. `PATH` environment variable summary
10. Config file validity

### Example output

```
╭─ 🔍 MCP Debugger Environment Check ───────────────────╮
│ ✓ Python version: 3.11.9 (required >=3.11)            │
│ ✓ SQLite version: 3.45.1                              │
│ ✓ Database directory: /home/user/.mcp-debugger [writable] │
│ ✓ Database schema version: 1                          │
│ ✓ npx command found: /usr/bin/npx                     │
│ ✓ Node.js found: /usr/bin/node                        │
│ ✓ git command found: /usr/bin/git                     │
╰────────────────────────────────────────────────────────╯
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All checks passed |
| `1` | One or more critical checks failed |

---

## `version`

Show the installed version and exit.

```bash
mcp-debugger version
```
