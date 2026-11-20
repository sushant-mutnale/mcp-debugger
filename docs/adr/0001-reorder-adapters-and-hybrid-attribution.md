# 0001. Reorder Framework Adapters Before Step Attribution with Hybrid Replay and Dual Session Model

## Context

The initial 90-day plan placed Causal Step Attribution in Sprint 2 and Framework Adapters in Sprint 5. However, step attribution requires full agent trajectories (LLM prompts, reasoning steps, tool calls) to accurately compute counterfactuals, whereas the proxy only captures MCP JSON-RPC wire messages. Additionally, the transition to stateless MCP (2026-07-28) challenged the database schema's central `sessions` concept, and pure live counterfactual replay presents severe LLM cost and non-determinism issues.

## Decision

1. **Sprint Reordering**: Reorder Sprint 5 (Python SDK & Framework Adapters) to precede Sprint 2 (Causal Step Attribution Engine). Step attribution will be implemented against real trajectory structures emitted by the SDK rather than synthetic or proxy-only message data.
2. **Dual Session Concept**: Retain `Session` as an operational container (a single proxy run or instrumented agent execution) in the database and CLI, while decoupling it from the MCP protocol layer where per-request `_meta` is validated per the stateless specification.
3. **Hybrid Counterfactual Replay**: Step ablation defaults to local VCR-style replay (replay recorded steps verbatim, neutralizing ablated steps without re-invoking LLMs) for fast, deterministic, zero-cost analysis. Live LLM re-execution is supported via an explicit `--live` flag with cost estimation.
4. **Append-Only Step Storage**: Store trajectory steps in an append-only SQLite table with content-hash deduplication rather than a Merkle-linked chain until multi-tenant audit requirements necessitate cryptographic chaining.

## Consequences

- Sprint 2 can now test attribution against authentic multi-step traces from day one.
- Preserves backward compatibility of CLI inspection commands and database relationships.
- Avoids unexpected LLM billing during local CLI debugging while retaining full causal precision when requested.
