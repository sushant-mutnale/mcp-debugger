# 0002. Dual-Mode Trace Ingestion and Dynamic MCP Protocol Dialect Negotiation

## Context

Instrumenting agent runs requires capturing telemetry from within the agent's Python execution runtime, unlike proxying external stdio processes. Furthermore, while the MCP 2026-07-28 specification eliminates the `initialize` handshake in favor of per-request `_meta`, existing production clients (Claude Desktop, Cursor) and tools rely exclusively on the 2025-03-26 handshake.

## Decision

1. **Dual-Mode Trace Ingestion**:
   - **Direct SQLite (Default)**: In-process Python SDK (`@trace_agent`, `@trace_mcp`) and framework adapters write directly to `~/.mcp-debugger/sessions.db` via `aiosqlite`/`sqlite3` for zero-configuration, zero-latency, daemon-free local development.
   - **OTLP / HTTP Ingestion (Secondary)**: For containerized, remote, or multi-process environments, the SDK can route traces over standard OTLP/HTTP to the `mcp-debugger` ingestion endpoint.

2. **Wire Dialect Auto-Detection**:
   - The proxy inspects the initial request on the wire:
     - If `method == "initialize"`, the proxy executes legacy 2025-03-26 protocol validation (handshake sequence, session state).
     - If the request contains `_meta.protocolVersion` (or invokes `server/discover`), the proxy activates 2026-07-28 stateless validation (per-request capability and identity checking).

3. **Deterministic-First Failure Classification**:
   - Failure analysis defaults to deterministic, rule-based heuristic inspectors (schema drift, loop detection, empty result traps). An LLM-as-a-judge semantic evaluation pass is provided as an opt-in parameter (`--judge`).

## Consequences

- Zero friction for local agent development; no need to launch a local server before running an agent script.
- Full backward compatibility: developers can debug legacy 2025 MCP servers and modern 2026 stateless servers using the same tool.
- Fast, cost-free diagnostic execution by default.
