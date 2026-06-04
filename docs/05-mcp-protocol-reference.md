# MCP Protocol Reference (Spec Version: 2025-03-26)

This document provides a reference sheet for the Model Context Protocol (MCP) message envelopes, common lifecycle methods, capabilities exchange, and standard error codes.

---

## JSON-RPC 2.0 Envelope Base

All communications under the MCP specification are wrapped in standard JSON-RPC 2.0 messages.

### 1. Request Envelope
Sent when a response is expected.
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "some/method",
  "params": {}
}
```

### 2. Response Envelope (Success)
Returned by the receiver upon successful execution.
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {}
}
```

### 3. Response Envelope (Error)
Returned on execution failure.
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32601,
    "message": "Method not found",
    "data": {}
  }
}
```

### 4. Notification Envelope
Sent without expecting any response. Does not contain an `id` field.
```json
{
  "jsonrpc": "2.0",
  "method": "some/notification",
  "params": {}
}
```

---

## Core Lifecycle Methods & Payloads

### 1. The Initialize Handshake

Before any resource, prompt, or tool commands can be run, the client and server must negotiate versioning and capabilities.

#### Request (`initialize` - Client -> Server)
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-03-26",
    "capabilities": {
      "sampling": {}
    },
    "clientInfo": {
      "name": "test-client",
      "version": "1.0.0"
    }
  }
}
```

#### Response (`initialize` - Server -> Client)
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-03-26",
    "capabilities": {
      "tools": {},
      "resources": {},
      "prompts": {}
    },
    "serverInfo": {
      "name": "filesystem-server",
      "version": "0.1.0"
    }
  }
}
```

#### Notification (`notifications/initialized` - Client -> Server)
Sent by the client immediately after receiving initialize results, signaling readiness to make tool/resource calls.
```json
{
  "jsonrpc": "2.0",
  "method": "notifications/initialized"
}
```

---

### 2. Tool Discovery

#### Request (`tools/list` - Client -> Server)
Queries the list of tools the server makes available.
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list"
}
```

#### Response (`tools/list` - Server -> Client)
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "read_file",
        "description": "Read the complete contents of a file from the system.",
        "inputSchema": {
          "type": "object",
          "properties": {
            "path": {
              "type": "string",
              "description": "Absolute path to the target file."
            }
          },
          "required": ["path"]
        }
      }
    ]
  }
}
```

---

### 3. Tool Execution

#### Request (`tools/call` - Client -> Server)
Invokes a specific tool.
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "read_file",
    "arguments": {
      "path": "/tmp/example.txt"
    }
  }
}
```

#### Response (`tools/call` - Server -> Client)
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "File contents are printed here."
      }
    ],
    "isError": false
  }
}
```

---

## Standard Error Codes

MCP errors implement the standard JSON-RPC 2.0 error specification.

| Code | Label | Meaning / Context |
|---|---|---|
| `-32700` | Parse error | Invalid JSON received by the server. |
| `-32600` | Invalid Request | The JSON sent is not a valid JSON-RPC Request object. |
| `-32601` | Method not found | The method requested does not exist or is unsupported. |
| `-32602` | Invalid params | Invalid method parameters (e.g. schema validation failed). |
| `-32603` | Internal error | Internal JSON-RPC / MCP server error. |

*Note: Custom application errors or tool execution failures can be returned in custom code ranges (e.g., matching standard execution error structures or returning `isError: true` inside tool responses).*
