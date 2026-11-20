# MCP Debugger Modernization Roadmap & Active Sprint

Parent Spec: [Issue #1](https://github.com/sushant-mutnale/mcp-debugger/issues/1)

---

## Sprint 1: Protocol Modernization & Telemetry Foundation (COMPLETED :white_check_mark:)

- [x] **#2 Wire Dialect Detector & Dual-Protocol Validator**
  - Dynamic wire dialect detection (`legacy_2025_03_26` vs `stateless_2026_07_28`) with zero user configuration.
  - Dual-protocol schema and lifecycle validation in `ProtocolValidator`.
  - Protocol version tracking in SQLite `sessions` table.
- [x] **#3 `server/discover` RPC Handling & Validation**
  - Schema validation for stateless discovery RPC requests and responses.
  - Proxy interception, capability caching, and Rich CLI inspection banners (`mcp-debugger inspect`).
- [x] **#4 `subscriptions/listen` Channel & Notification Filtering**
  - Schema validation for topic-based pub/sub notifications.
  - Session validation tracking active subscriptions and flagging unsolicited notification leaks.
  - Statistical tracking for notification counts and active channels in `SessionStats`.
- [x] **#5 Stateless Error Handling (-32003 & Missing Capabilities)**
  - Intercepted JSON-RPC `-32003` as protocol violation with upgrade guidance for older servers.
  - Intercepted `-32004` and missing capability responses with granular capability key extraction.
  - Error classification integration with non-zero exit codes.
- [x] **#6 OpenTelemetry GenAI Semantic Convention Export**
  - Span names follow official `{mcp.method.name} {target}` format (e.g. `tools/call echo`, `resources/read file:///...`).
  - Comprehensive extraction of `gen_ai.*` attributes (`gen_ai.system`, `gen_ai.operation.name`, `gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.*`).
  - Implemented across both live/recorded sessions (`OTLPExporter`) and replay traces (`OTLPReplayExporter`).

---

## Sprint 2: Core Python SDK & Framework Adapters (COMPLETED :white_check_mark:)

- [x] **#7 Trajectory Storage & Step Data Model**
  - SQLite `steps` table schema with `session_id`, `step_index`, `step_type` (`llm_call`, `tool_call`, `thought`, `handoff`), `agent_name`, `input`, `output`, `content_hash`, `tokens_input`, `tokens_output`, `latency_ms`.
  - Content-hash deduplication (SHA-256 over `agent_name:step_type:input`) per ADR 0001.
  - Database operations `log_step` and `get_steps` with cascade deletion on session removal.
- [x] **#8 Core Python SDK @trace_agent and @trace_mcp Decorators**
  - Zero-boilerplate `@trace_agent` and `@trace_mcp` decorators for synchronous and asynchronous agent functions/methods.
  - Task/thread-safe execution context propagation via `contextvars.ContextVar`.
  - Automatic latency measurement, argument formatting, return value interception, and exception capture.
  - Transparent zero-overhead fallback when tracing is inactive.
- [x] **#9 Direct SQLite In-Process Trace Ingestion**
  - In-process session manager `start_trace(...)` and `TraceSession` writing directly to SQLite (`~/.mcp-debugger/sessions.db` or configured path) without requiring a daemon per ADR 0002.
  - Synchronous and asynchronous context manager support (`with start_trace(...)` and `async with start_trace(...)`).
  - `atexit` clean exit handler for automatic buffer flush and session completion.
  - Enhanced `mcp-debugger inspect <session_id>` CLI command with Rich formatted Trajectory Steps table and `--json` support.
- [x] **#10 OpenAI Agents SDK Framework Adapter**
  - `OpenAIAgentTracker` lifecycle hooks (`on_llm_start`, `on_llm_end`, `on_tool_start`, `on_tool_end`, `on_handoff`).
  - `trace_openai_agent` wrapper for OpenAI agents and runners.
  - Automatic extraction of token metrics (`prompt_tokens`, `completion_tokens`) and role handoffs.
- [x] **#11 LangChain v0.2+ Callback Handler Adapter**
  - `MCPDebuggerCallbackHandler` subclassing `BaseCallbackHandler`.
  - Hooks into chain lifecycle (`thought`), tool lifecycle (`tool_call`), and LLM lifecycle (`llm_call`).
  - Extraction of model names and generation token counts.

---

## Sprint 3: Causal Step Attribution Engine & Counterfactual Ablation (UPCOMING)

Scope:
- Counterfactual step ablation algorithm (`mcp-debugger attribute <session_id>`).
- Point of Commitment (PoC) identification for doomed trajectories.
- Local VCR-style replay default (zero-cost) with optional `--live` LLM re-execution per ADR 0001.
- Deterministic heuristic failure classification (loops, empty results, schema drift) per ADR 0002.
- Interactive CLI attribution timeline report.

---

## Quality Metrics

- **Tests Passing**: 294 passed, 1 skipped (0 failures).
- **Code Coverage**: 92% across all modules.
- **Linter**: 100% clean `ruff` compliance.
