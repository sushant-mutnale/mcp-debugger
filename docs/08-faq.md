# Frequently Asked Questions (FAQ)

Here are answers to common questions and troubleshooting topics for **MCP Debugger**.

---

### Q: Does running mcp-debugger add latency to my LLM agent sessions?
**A**: Minimal to none. The stdio proxy uses asynchronous I/O (`asyncio.gather` and non-blocking stream readers) to pipe data. Database persistence and protocol validations are executed out-of-band as background tasks. The message is forwarded immediately to the client or server before the database write completes, ensuring zero latency overhead.

---

### Q: Where are my debug sessions stored?
**A**: By default, all session logs, discovered tools, and errors are stored in a local SQLite file:
`~/.mcp-debugger/sessions.db`
No data ever leaves your computer or is uploaded to the cloud. You can clear your session history at any time by simply deleting this database file.

---

### Q: Does mcp-debugger support Windows?
**A**: Phase 1 targets Linux/macOS compatibility. However, because the CLI and proxy logic are written using standard Python 3.11+ asynchronous libraries, many features will work on Windows in PowerShell or Command Prompt. Note that Windows stdio pipe handling occasionally has platform-specific buffering behaviors that may require custom adjustment.

---

### Q: How do I configure mcp-debugger with Claude Desktop?
**A**: Open your Claude Desktop configuration file (typically located at `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or `%APPDATA%\Claude\claude_desktop_config.json` on Windows).

Prepend the proxy command to your existing server definition:
```json
{
  "mcpServers": {
    "my-filesystem": {
      "command": "mcp-debugger",
      "args": [
        "proxy",
        "--server",
        "npx -y @modelcontextprotocol/server-filesystem /path/to/dir"
      ]
    }
  }
}
```

---

### Q: What happens if my server outputs standard logs (like Python's print statements) mixed in with JSON-RPC stdout messages?
**A**: Standard MCP servers must write non-JSON-RPC logs exclusively to `sys.stderr` to prevent protocol corruption. If a server incorrectly writes debug text or raw print outputs to `sys.stdout`, the proxy will log a warning, register the raw output as a malformed message in the database, and forward the raw text transparently to prevent the client connection from breaking.

---

### Q: How does the replay command handle stateful actions (like database writes or file deletions)?
**A**: The replay engine repeats the historical client-to-server requests sequentially. If those requests trigger state changes (e.g. creating a file, writing to a database), the replay action *will* execute those changes on the target server. It is recommended to run replays against sandbox/testing configurations to avoid side effects in production environments.
