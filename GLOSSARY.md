# MCP Debugger Domain Glossary

Debugging, tracing, and causal failure attribution for Model Context Protocol (MCP) clients, servers, and multi-agent workflows.

## Core Concepts

**Session**:
A single execution lifecycle of the debugger proxy or instrumented agent run, serving as the top-level container for recorded interactions.
_Avoid_: Connection, socket lifecycle, conversation

**Trajectory**:
An ordered, timestamped sequence of execution steps (LLM inferences, tool calls, state handoffs) performed by an agent to accomplish a task.
_Avoid_: Trace history, run log, transcript

**Step**:
An atomic unit of action or decision within an agent trajectory, encompassing an LLM invocation, MCP tool call, or inter-agent handoff.
_Avoid_: Event, span, message

**Trace Ingestion**:
The mechanism by which agent telemetry is captured and persisted into storage, supporting direct database writes locally and OTLP streaming remotely.
_Avoid_: Logging, metric pushing, event sinking

## Multi-Agent Systems

**Agent Hierarchy**:
A structured graph of agent instances operating under parent-child relationships to decompose and delegate sub-tasks within a single session.
_Avoid_: Agent swarm, sub-agent tree, agent pool

**Handoff**:
The explicit transfer of execution control, conversation state, and contextual metadata from an upstream agent to a downstream agent.
_Avoid_: Delegation, transition, message pass

**Handoff Replay**:
A debugging technique where pre-handoff steps are served verbatim from recorded cassettes while the downstream agent is re-executed live from the received state.
_Avoid_: Partial replay, sub-agent simulation, checkpoint resumption

## Protocol & Interception

**Protocol Dialect**:
The structural version of the MCP wire format, distinguishing between legacy handshake-oriented communication (2025-03-26) and per-request metadata negotiation (2026-07-28).
_Avoid_: Protocol mode, API version

**Dialect Auto-Detection**:
Runtime inspection of incoming wire messages to dynamically select between handshake validation and stateless capability validation rules.
_Avoid_: Version sniffing, protocol fallback

## Attribution & Analysis

**Causal Step Attribution**:
The process of isolating the specific step in an agent trajectory that causally determined a failure by evaluating counterfactual outcomes when steps are ablated.
_Avoid_: Root cause analysis, fault localization, error blame

**Step Ablation**:
A counterfactual perturbation where a recorded step is neutralized (replaced with a no-op or default output) during replay to measure its marginal impact on failure probability.
_Avoid_: Step deletion, mocking, mutation

**Point of Commitment**:
The earliest step in a trajectory whose counterfactual removal flips the final outcome from failure to success, regardless of where the mechanical error occurred.
_Avoid_: Fault site, crash site, trigger point

**Failure Classification**:
Categorization of a detected fault across the boundary into agent reasoning failure, tool execution failure, or protocol specification violation.
_Avoid_: Error categorisation, bug triage
