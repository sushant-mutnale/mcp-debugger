# Launch Announcements: mcp-debugger

This document contains drafts for the public launch of `mcp-debugger`.

---

## 1. Hacker News (Show HN)

**Title:** Show HN: mcp-debugger – Local CLI to debug, record, and replay MCP sessions

**Body:**
Hi HN,

I built `mcp-debugger`, a local-first, zero-dependency-at-runtime CLI tool designed to record, inspect, validate, and replay Model Context Protocol (MCP) sessions.

### Why I built it
Developing MCP servers (like filesystem access, database interfaces, memory systems) can be tricky because the JSON-RPC traffic between the LLM client (e.g., Claude Desktop) and the server is fully standard I/O based. When things go wrong—such as schema mismatches, handshake order failures, or silent exceptions—debugging stdout/stderr streams is painful. 

`mcp-debugger` acts as a transparent proxy between the client and the server. It captures all JSON-RPC traffic, persists it to a local SQLite database, and offers rich analysis and replay capabilities.

### Key Features
* **Transparent Proxying**: Runs client-to-server traffic inline with a 10MB streaming limit.
* **Syntax-Highlighted Inspection**: View JSON-RPC frames, schema properties, and error states directly in the terminal via a Rich-powered CLI.
* **Protocol Compliance Validator**: Asserts protocol states, handshake order, error schemas, and checks tool definitions against JSON Schema Draft-07.
* **Regression Testing via Session Replay**: Replays client requests to a target server and diffs response payloads to capture regressions.
* **Performance Analytics**: Tracks message rates, p50/p95/p99 latency, tool usage statistics, and classified error codes.
* **Export Formats**: Export sessions to standard JSON, clean Markdown reports, or OpenTelemetry (OTLP) traces to inspect in Jaeger or Zipkin.
* **Fully Local-First**: Written in Python 3.12, fully type-hinted, and requires no external accounts.

### Tech Stack
* **Runtime**: Python 3.11/3.12 (asyncio architecture)
* **Metadata Parsing & Config**: TOML with dot-notation CLI override support
* **Database**: SQLite (WAL mode, non-blocking via `aiosqlite`)
* **Terminal UI**: `rich` and `click`

Github: https://github.com/sushant-mutnale/mcp-debugger
PyPI: https://pypi.org/project/mcp-debugger/

I’d love to hear your thoughts and suggestions on how you debug your LLM tool/MCP server integrations!

---

## 2. Reddit

### Subreddits: r/Python, r/LocalLLaMA, r/MCP

**Title:** I built mcp-debugger: A local CLI tool to record, validate, and replay Model Context Protocol sessions

**Post:**
Hey everyone,

I wanted to share `mcp-debugger`, an open-source command-line tool I've been working on to solve debugging pains when building servers for Anthropic's Model Context Protocol (MCP).

If you've built MCP servers, you know that because they communicate over stdin/stdout, diagnosing bugs, checking protocol compliance, or doing regression testing can be extremely difficult.

`mcp-debugger` intercepts, logs, and analyzes this JSON-RPC traffic transparently:

* 🔍 **Record**: Intercept and store all client-server exchanges in a local SQLite db.
* 📋 **Inspect**: Syntax-highlighted, paginated browsing of message history.
* ✅ **Validate**: Check compliance rules (proper initialization, valid JSON Schemas for tools, error specifications).
* 🔄 **Replay**: Re-run recorded client message flows against your server to test updates, showing inline delta diffs.
* 📊 **Analytics & Latency**: Detailed summaries showing p50/p95/p99 latency, tool invoke counts, and error classifications.
* 📤 **Telemetry**: Export logs to standard formats or stream traces via OpenTelemetry (OTLP) to Grafana or Jaeger.

### Quick Start
```bash
pip install mcp-debugger

# Start the transparent recording proxy
mcp-debugger proxy --server "npx -y @modelcontextprotocol/server-filesystem /tmp" --name "my-session"

# Inspect recorded sessions
mcp-debugger list
mcp-debugger inspect 1

# Check compliance
mcp-debugger validate --session 1

# Replay messages to regression test changes
mcp-debugger replay 1 --server "npx -y @modelcontextprotocol/server-filesystem /tmp"
```

The codebase is fully typed (mypy strict), linted, and includes a comprehensive test suite (247 unit and integration tests with >96% coverage).

* **GitHub:** [sushant-mutnale/mcp-debugger](https://github.com/sushant-mutnale/mcp-debugger)
* **PyPI:** [mcp-debugger](https://pypi.org/project/mcp-debugger/)

Would appreciate any feedback or feature requests!

---

## 3. Twitter / X

### Teaser Thread

**Tweet 1:**
Building servers for Anthropic's Model Context Protocol (MCP) but finding it hard to debug stdin/stdout JSON-RPC traffic? 

Say hello to `mcp-debugger` — a local-first CLI tool to record, inspect, validate, and replay your MCP sessions! 🚀

[GitHub Link]

**Tweet 2:**
Here is what you can do with it:
1️⃣ Run transparent proxy logging to a local SQLite DB
2️⃣ Browse traffic in terminal using a syntax-highlighted inspector
3️⃣ Verify protocol compliance (handshakes, schemas, error formats)
4️⃣ Regression-test servers by replaying flows

**Tweet 3:**
Need performance stats or telemetry?
📊 Get p50/p95/p99 latency metrics and error rates.
📤 Export sessions to JSON, Markdown, or OpenTelemetry (OTLP) traces to view in Jaeger/Grafana.

Install in one line:
`pip install mcp-debugger`
👉 Check it out: https://github.com/sushant-mutnale/mcp-debugger
