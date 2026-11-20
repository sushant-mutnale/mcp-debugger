# 0003. Multi-Agent Hierarchy Data Model, Static Web Packaging, and Storage Extensibility

## Context

Expanding the debugger to support multi-agent systems (Sprint 5) requires representing multi-level agent delegation and inter-agent handoffs. Additionally, deploying the Web UI with React/AgentPrism must not add runtime dependencies for Python users, CI/CD gates need unambiguous failure criteria, and team collaboration necessitates central database options beyond SQLite.

## Decision

1. **Relational Agent Hierarchy**:
   - Introduce an `agents` table (`id`, `session_id`, `parent_agent_id`, `name`, `role`, `framework`) linked via foreign key to `sessions`.
   - Update `agent_steps` to reference `agent_id`, enabling recursive graph querying, role-coverage metrics, and state-diff tracking across handoffs.

2. **Cassette-Backed Handoff Replay**:
   - "Replay from handoff" loads upstream execution history as a static VCR cassette to feed identical initial state to the downstream agent under test. Only the downstream agent executes live, preventing cascading re-execution costs and non-deterministic divergence.

3. **Pre-Compiled Static Web Distribution**:
   - React and AgentPrism assets are compiled to static production bundles during wheel build and packaged under `src/mcp_debugger/web/static/dist/`.
   - `mcp-debugger web` serves these static assets directly via FastAPI, requiring zero Node.js/npm runtime dependencies for end users.

4. **Tiered CI/CD Quality Gates**:
   - `mcp-debugger ci` exits with code `1` (build failure) only on deterministic protocol schema violations, unhandled tool/server exceptions, and replay regression diffs against golden baselines.
   - Latency anomalies, token budget warnings, and minor prompt drift are surfaced as non-blocking warnings in SARIF and JUnit XML outputs.

5. **Extensible Storage Architecture**:
   - Provide an optional PostgreSQL backend configured via `[database] url = "postgresql+asyncpg://..."` in `config.toml` for team sharing and persistent CI histories.
   - Zero-config local SQLite remains the default for individual developer workflows.

## Consequences

- Clean separation between agent hierarchy and wire messages.
- Effortless installation and operation for developers (`pip install mcp-debugger` remains self-contained).
- Actionable CI/CD gates that avoid flakiness from stochastic LLM variance.
- Simple, friction-free migration path from solo local debugging to shared team infrastructure.
