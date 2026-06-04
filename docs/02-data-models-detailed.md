# Data Models Detailed

This document outlines the Pydantic data schemas used for runtime message validation and the corresponding database tables mapping the session history in SQLite.

---

## Pydantic Validation Models

Located in: [src/mcp_debugger/protocol/schemas.py](file:///d:/python/MCP_DEBUG/src/mcp_debugger/protocol/schemas.py)

### 1. `JSONRPCRequest`
Represents a standard JSON-RPC 2.0 Request message.

| Field | Type | Required | Description |
|---|---|---|---|
| `jsonrpc` | `Literal["2.0"]` | **Yes** | Must be exactly `"2.0"`. |
| `id` | `int | str` | **Yes** | Request ID used to match request-response pairs. Cannot be null. |
| `method` | `str` | **Yes** | The MCP method being called (e.g. `tools/list`, `tools/call`). |
| `params` | `dict | None` | No | Optional arguments associated with the method. |

**Validation Rules:**
- `jsonrpc` must evaluate to `"2.0"`.
- `id` must be present (cannot be a JSON-RPC notification which lacks an `id`).
- `method` must be a non-empty string.

---

### 2. `JSONRPCResponse`
Represents a successful JSON-RPC 2.0 Response message.

| Field | Type | Required | Description |
|---|---|---|---|
| `jsonrpc` | `Literal["2.0"]` | **Yes** | Must be exactly `"2.0"`. |
| `id` | `int | str` | **Yes** | Must match the `id` of the original request. |
| `result` | `Any` | **Yes** | The payload returned by the server on success. |

**Validation Rules:**
- `jsonrpc` must evaluate to `"2.0"`.
- `result` must be present. (If it is an error response, it must follow the `JSONRPCError` schema instead).

---

### 3. `JSONRPCNotification`
Represents a JSON-RPC 2.0 Notification message (which does not expect a response).

| Field | Type | Required | Description |
|---|---|---|---|
| `jsonrpc` | `Literal["2.0"]` | **Yes** | Must be exactly `"2.0"`. |
| `method` | `str` | **Yes** | The notification method (e.g. `notifications/initialized`). |
| `params` | `dict | None` | No | Notification parameters. |

---

### 4. `JSONRPCError`
Represents a failed JSON-RPC 2.0 Response.

| Field | Type | Required | Description |
|---|---|---|---|
| `jsonrpc` | `Literal["2.0"]` | **Yes** | Must be exactly `"2.0"`. |
| `id` | `int | str | None` | **Yes** | Matches the request ID (or null if parsing failed). |
| `error` | `ErrorDetails` | **Yes** | Sub-object containing `code`, `message`, and optional `data`. |

**`ErrorDetails` Fields:**
- `code` (`int`): JSON-RPC error code (e.g., `-32601` for method not found).
- `message` (`str`): Short description of the error.
- `data` (`Any`, optional): Structured error context or stack traces.

---

### 5. MCP Tool Call Params (`CallToolParams`)
Specific schema for params passed during `tools/call`.

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | **Yes** | The name of the tool to be called (must match a tool declared in the session's `tools/list` response). |
| `arguments` | `dict | None` | No | Key-value arguments conforming to the tool's defined `inputSchema`. |

---

## Database Models (SQLite Schema)

All tables are maintained in `~/.mcp-debugger/sessions.db`.

### 1. Table: `sessions`
Tracks each independent proxy execution.

```sql
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid TEXT UNIQUE NOT NULL,
    server_command TEXT NOT NULL,
    server_name TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    status TEXT DEFAULT 'running', -- running, completed, error, terminated
    client_info TEXT, -- JSON string
    server_info TEXT, -- JSON string
    protocol_version TEXT,
    total_messages INTEGER DEFAULT 0,
    total_tools_discovered INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0
);
```

### 2. Table: `messages`
Stores individual JSON-RPC log units flowing in either direction.

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    message_id TEXT, -- JSON-RPC id (NULL for notifications)
    direction TEXT NOT NULL CHECK(direction IN ('client_to_server', 'server_to_client')),
    method TEXT, -- e.g., "initialize", "tools/call"
    params TEXT, -- JSON string representation
    result TEXT, -- JSON string (NULL for requests or notifications)
    error TEXT, -- JSON string error payload (NULL on success)
    timestamp REAL NOT NULL, -- Monotonic clock timestamp for sequencing
    latency_ms REAL, -- Calculated time delta between request and response
    message_type TEXT CHECK(message_type IN ('request', 'response', 'notification'))
);

-- Recommended Indexes for Fast Rendering & Sorting
CREATE INDEX idx_messages_session_time ON messages(session_id, timestamp);
CREATE INDEX idx_messages_method ON messages(method);
CREATE INDEX idx_messages_direction ON messages(direction);
```

### 3. Table: `tools`
Keeps track of tool definitions advertised by servers.

```sql
CREATE TABLE tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    name TEXT NOT NULL,
    description TEXT,
    input_schema TEXT NOT NULL, -- JSON Schema string
    output_schema TEXT, -- optional output schema
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4. Table: `errors`
Aggregates and categorizes error messages for rapid diagnostics.

```sql
CREATE TABLE errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    message_id INTEGER REFERENCES messages(id),
    error_code INTEGER, -- JSON-RPC error code
    error_type TEXT, -- classified (e.g. protocol, tool_execution, timeout)
    error_message TEXT,
    stack_trace TEXT,
    classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
