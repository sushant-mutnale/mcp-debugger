# Frequently Asked Questions

---

## Installation & Setup

### Q: What Python version do I need?

**A:** Python 3.11 or later. `mcp-debugger` uses `tomllib` (stdlib since 3.11) and requires `asyncio` features available in 3.11+.

---

### Q: Do I need Node.js?

**A:** Only if you want to use `npx`-based MCP servers (e.g. `@modelcontextprotocol/server-filesystem`). If you're connecting to a Python MCP server, Node.js is not required. Run `mcp-debugger doctor` to check your environment.

---

### Q: Where are my sessions stored?

**A:** All data is stored locally in a SQLite file:

| Platform | Path |
|---|---|
| Linux / macOS | `~/.mcp-debugger/sessions.db` |
| Windows | `%APPDATA%\mcp-debugger\sessions.db` |

No data is sent to any cloud service. To clear all sessions, delete the file — it will be recreated on next run.

---

### Q: Does mcp-debugger work on Windows?

**A:** Yes. It is tested in CI on `windows-latest` (Python 3.11 and 3.12). Windows stdio pipe buffering works correctly with the tool's async I/O implementation. One difference: file permission checks (the `0o600` DB file warning) are skipped on Windows since POSIX permissions don't apply.

---

## Using the Proxy

### Q: Does the proxy add latency to my sessions?

**A:** Minimal to none. Messages are forwarded immediately; database writes happen concurrently as background asyncio tasks. The roundtrip overhead is typically sub-millisecond on local machines.

---

### Q: How do I use mcp-debugger with Claude Desktop?

**A:** Edit your Claude Desktop config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "my-server": {
      "command": "mcp-debugger",
      "args": [
        "proxy",
        "--server",
        "npx -y @modelcontextprotocol/server-filesystem /path/to/dir",
        "--name",
        "claude-session"
      ]
    }
  }
}
```

Every message between Claude and your server will be recorded transparently.

---

### Q: What happens if my server writes debug output to stdout instead of stderr?

**A:** MCP servers must write all non-JSON-RPC output to `stderr` only. If your server accidentally writes text to `stdout`, the proxy will:
1. Log a warning
2. Record the malformed line in the database as a raw message
3. Forward it to the client (to avoid breaking the connection)

Fix: redirect all `print()` / `logging` to `sys.stderr` in your server.

---

### Q: Can I run multiple proxy sessions at the same time?

**A:** Yes. Each proxy run creates a new session row in the database. The database uses `aiosqlite` with WAL mode to safely handle concurrent writes.

---

## Validate & Replay

### Q: Replay says responses don't match, but my server hasn't changed!

**A:** Some response fields are non-deterministic by nature — timestamps, random IDs, session tokens. Options:

1. Identify the varying field and configure it to be ignored (feature coming in a future version)
2. Compare only the fields you care about using `--json` output and a custom script
3. Use `mcp-debugger stats` + `compare` to check aggregate metrics (latency, error rates) instead of per-message diffs

---

### Q: Can I replay only specific message types?

**A:** Yes, use `--filter-method`:

```bash
# Only replay tool calls
mcp-debugger replay 5 --server "python server.py" --filter-method tools/call
```

---

### Q: Validate shows a warning about tool schemas. What does that mean?

**A:** The MCP spec requires tool `inputSchema` to be a valid JSON Schema (Draft-07). Common issues:

- Missing `type: object` at the top level
- `properties` defined without `type`
- Using unsupported JSON Schema keywords

Run `mcp-debugger validate --server ... --json` to get the exact error message and suggestion.

---

## Export & OTLP

### Q: How do I install OTLP export support?

**A:**

```bash
pip install "mcp-debugger[export]"
```

Then send traces to a local Jaeger instance:

```bash
docker run -p 4317:4317 jaegertracing/all-in-one
mcp-debugger export 5 --format otlp --endpoint http://localhost:4317 --insecure
```

---

### Q: The export command produces no output. What's wrong?

**A:** Check that:
1. The session ID exists: `mcp-debugger list`
2. The session has messages: `mcp-debugger inspect <id>`
3. You are not accidentally piping to a pager that suppresses output

If using `--format otlp`, check that the OTLP endpoint is reachable and `mcp-debugger[export]` is installed.

---

## Configuration

### Q: How do I set a default server so I don't have to type it every time?

**A:**

```bash
mcp-debugger config set replay.default_server "python -m my_package.server"
mcp-debugger replay 5   # --server not needed
```

---

### Q: Config keeps getting reset. Why?

**A:** If the config file has invalid TOML, `mcp-debugger` logs a warning and uses defaults (it never crashes on a bad config file). Run:

```bash
mcp-debugger config list
```

If this shows defaults, your config file is invalid. Fix it with:

```bash
mcp-debugger config reset
mcp-debugger config set <key> <value>  # re-apply your settings
```

---

## Troubleshooting

### Q: `mcp-debugger doctor` shows a warning about DB file permissions

**A:** On Linux/macOS, the sessions database should have permissions `600` (owner read/write only) to protect server command strings that may contain credentials. Fix with:

```bash
chmod 600 ~/.mcp-debugger/sessions.db
```

---

### Q: The proxy exits immediately with "Server failed to start"

**A:** The server command could not be launched. Check:

1. The command works when run directly: `npx -y @modelcontextprotocol/server-filesystem /tmp`
2. `npx` / `node` is on your PATH: `mcp-debugger doctor`
3. The server directory / file exists
4. Try with `--verbose` to see the full error: `mcp-debugger proxy --server "..." --verbose`

---

### Q: How do I report a bug or request a feature?

**A:** Open an issue at [github.com/sushant-mutnale/mcp-debugger/issues](https://github.com/sushant-mutnale/mcp-debugger/issues). Please include:
- `mcp-debugger version` output
- `mcp-debugger doctor` output
- The exact command you ran
- The full error message or unexpected output
