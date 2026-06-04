# Glossary

This document defines core terms and concepts used across the **MCP Debugger** codebase and documentation, accompanied by concrete examples.

---

### 1. Transparent Proxy (Stdio Proxy)
A middleman service that intercepts communication streams without either endpoints (client or server) being aware of its presence.
* **Context**: `mcp-debugger` operates as a transparent stdio proxy. It runs the real MCP server inside a subprocess, intercepts standard input (`stdin`) and standard output (`stdout`) pipes, validates/logs messages, and forwards them instantly.
* **Example**:
  Instead of launching the server directly:
  ```bash
  npx -y @modelcontextprotocol/server-filesystem /tmp
  ```
  The client launches the proxy:
  ```bash
  mcp-debugger proxy --server "npx -y @modelcontextprotocol/server-filesystem /tmp"
  ```

---

### 2. Session
A single, complete lifecycle run of the proxy, from initial server startup to client disconnect or shutdown.
* **Context**: Each invocation of `mcp-debugger proxy` generates a unique session stored in the database, containing attributes like started time, exit statuses, and a collection of chronological messages.
* **Example**: A development session between Claude Desktop and a filesystem server that logs 25 requests and lasts for 3 minutes before closing.

---

### 3. Replay
The process of loading previously captured client-to-server messages from the database and re-sending them to a fresh instance of the server to compare the new outputs against the old logs.
* **Context**: Used to detect regressions and behavior drift when server code is modified.
* **Example**: Replaying Session `42` where the client originally queried `tools/call` for `read_file`, and checking if the updated server code returns the identical file bytes.

---

### 4. Deep Diff
A recursive, structural comparison between two JSON documents or dictionaries, highlighting additions, removals, and modifications while skipping negligible noise like unique IDs or timestamps.
* **Context**: Used in Replay Mode to check if a replayed response matches the recorded history.
* **Example**:
  - Original Response: `{"jsonrpc": "2.0", "id": 10, "result": {"content": [{"text": "Hello"}], "timestamp": 1718228000}}`
  - Replayed Response: `{"jsonrpc": "2.0", "id": 10, "result": {"content": [{"text": "Hello World"}], "timestamp": 1718229000}}`
  - Deep Diff Result:
    - *Modified*: `result.content[0].text` changed from `"Hello"` to `"Hello World"`.
    - *Ignored*: `timestamp` value changes are bypassed.

---

### 5. Capability Negotiation
The initial exchange of client and server metadata and capability lists during the handshake.
* **Context**: Defines what features (like tool calling, prompts, or resource templates) both endpoints support.
* **Example**:
  - A client declares it supports `sampling` (asking the client to generate prompts).
  - A server responds that it supports `tools` and `resources`.

---

### 6. Protocol Conformance Validator
A validation rules engine that checks whether the exchanged payloads follow the formal rules defined in the MCP specification.
* **Context**: Flags incorrect initialization orders, missing fields, or invalid input schemas.
* **Example**: Flagging a critical warning if a server attempts to respond to a tool call *before* completing the initialization sequence.
