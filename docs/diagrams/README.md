# MCP Debugger Diagrams & Architecture Visualizations

This directory contains visual Mermaid diagrams explaining the Model Context Protocol (MCP) Debugger's architecture, data models, system flows, and subcommand hierarchies.

---

## 1. System Architecture & Component Flow

The proxy operates as an asynchronous man-in-the-middle stdio pipe between the MCP Client (like Claude Desktop) and the target MCP Server subprocess.

```mermaid
graph TD
    Client[Client e.g. Claude Desktop] <-->|stdio pipes| Proxy[mcp-debugger proxy]
    Proxy <-->|stdio pipes| Server[Target MCP Server Subprocess]
    Proxy -->|async out-of-band log| DB[(SQLite Local DB)]

    subgraph Core Engine
        Proxy
        Validator[Protocol Validator]
        Recorder[Session Recorder]
        Replay[Replay Engine]
    end

    Proxy -.->|validates| Validator
    Proxy -.->|records| Recorder
    Recorder --> DB
    Replay -->|read session traces| DB
    Replay -->|spawns & executes| Server
```

---

## 2. Database Entity-Relationship Diagram (ERD)

All historical sessions, protocol messages, tool specifications, and classified errors are persisted under `~/.mcp-debugger/sessions.db`.

```mermaid
erDiagram
    sessions ||--o{ messages : "logs many"
    sessions ||--o{ tools : "discovers many"
    sessions ||--o{ errors : "tracks many"
    messages ||--o{ errors : "originates (optional)"

    sessions {
        INTEGER id PK "Auto-increment ID"
        TEXT session_uuid UK "Unique session UUID4"
        TEXT server_command "Command executed to launch target server"
        TEXT server_name "Name parsed from client initialization"
        TIMESTAMP started_at "Creation timestamp"
        TIMESTAMP ended_at "Session termination timestamp"
        TEXT status "running | completed | error | terminated"
        TEXT client_info "JSON metadata matching client capabilities"
        TEXT server_info "JSON metadata matching server capabilities"
        TEXT protocol_version "MCP protocol version negotiation string"
        INTEGER total_messages "Total messages counter"
        INTEGER total_tools_discovered "Total unique tools count"
        INTEGER total_errors "Total errors logged"
    }

    messages {
        INTEGER id PK "Auto-increment ID"
        INTEGER session_id FK "References sessions.id (ON DELETE CASCADE)"
        TEXT message_id "JSON-RPC message id (NULL for notifications)"
        TEXT direction "client_to_server | server_to_client"
        TEXT method "MCP method (e.g. tools/call)"
        TEXT params "JSON string representation of parameters"
        TEXT result "JSON string success payload"
        TEXT error "JSON string error payload"
        REAL timestamp "Monotonic epoch milliseconds"
        REAL latency_ms "Latency elapsed between Request and Response"
        TEXT message_type "request | response | notification"
    }

    tools {
        INTEGER id PK "Auto-increment ID"
        INTEGER session_id FK "References sessions.id (ON DELETE CASCADE)"
        TEXT name "Unique tool name per session"
        TEXT description "Textual summary of what the tool accomplishes"
        TEXT input_schema "JSON Schema detailing valid arguments"
        TEXT output_schema "Optional return JSON Schema"
        TIMESTAMP first_seen_at "Creation timestamp"
    }

    errors {
        INTEGER id PK "Auto-increment ID"
        INTEGER session_id FK "References sessions.id (ON DELETE CASCADE)"
        INTEGER message_id FK "Optional link to triggering messages.id (ON DELETE SET NULL)"
        INTEGER error_code "JSON-RPC error code number"
        TEXT error_type "Classified category (e.g. protocol, execution, timeout)"
        TEXT error_message "Summary of the error occurrence"
        TEXT stack_trace "Detailed debugging trace information"
        TIMESTAMP classified_at "Creation timestamp"
    }
```

---

## 3. Communication & Logging Sequence Diagram

This sequence traces the initialization phase where the proxy routes messages, logs them async to SQLite, and maintains transparent communication.

```mermaid
sequenceDiagram
    autonumber
    actor Client as Client (Claude)
    participant Proxy as mcp-debugger proxy
    participant DB as SQLite DB
    participant Server as Target MCP Server

    Client->>Proxy: stdio: initialize Request (id: 1)
    Proxy->>DB: async write: log_message(request)
    Proxy->>Server: stdio: initialize Request (id: 1)
    Server->>Proxy: stdio: initialize Response (id: 1)
    Proxy->>DB: async write: log_message(response)
    Note over Proxy,DB: Matches request ID & computes latency
    Proxy->>Client: stdio: initialize Response (id: 1)

    Client->>Proxy: stdio: notifications/initialized
    Proxy->>DB: async write: log_message(notification)
    Proxy->>Server: stdio: notifications/initialized
```

---

## 4. CLI Subcommand Structure

```mermaid
graph TD
    Root[mcp-debugger] --> Version[version]
    Root --> ProxyCommand[proxy]
    Root --> List[list]
    Root --> Inspect[inspect]
    Root --> Tools[tools]
    Root --> Validate[validate]
    Root --> ReplayCommand[replay]
    Root --> Doctor[doctor]
    Root --> Config[config]

    classDef default fill:#f9f9f9,stroke:#333,stroke-width:1px;
    classDef main fill:#d4edda,stroke:#28a745,stroke-width:2px;
    class Root main;
```
