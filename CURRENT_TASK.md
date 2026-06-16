Day 19: OpenTelemetry Export for Replay Results
You have a fully functional replay system (Days 15–18) that can test server changes and report mismatches. But the results are currently siloed – they live in the terminal or the local database. For teams with existing observability stacks (Jaeger, Tempo, Datadog), they want to see replay results as traces alongside their service metrics.

Day 19 adds OpenTelemetry export for replay results – converting replay runs into trace data that can be visualised in Jaeger, Grafana, or any OTLP-compatible backend. This allows teams to:

Track regression trends – see how mismatch counts change over time (via trace attributes).

Correlate with deployments – tie replay failures to specific server versions.

Alert on regressions – OTLP exporters can integrate with alerting systems.

By the end of Day 19, you can run:

bash
mcp-debugger replay 42 --server "..." --otlp-endpoint http://jaeger:4317
and see a trace in Jaeger showing each replayed message as a span, with diff summaries as span attributes/events.

🎯 Core Objective
Extend the replay command (and optionally replay show) with OpenTelemetry export:

Feature	Description
OTLP export	Send replay results to an OTLP collector (gRPC or HTTP) using the OpenTelemetry SDK.
Trace structure	Each replay run = a trace. Each replayed message = a span (or a pair of request/response spans).
Attributes	Include mismatch status, latency, method name, tool name, diff summary (truncated).
Events	For mismatched responses, add an event with the diff details.
Flags	--otlp-endpoint, --otlp-insecure, --otlp-service-name, --otlp-export (or detect automatically if OTEL_EXPORTER_OTLP_ENDPOINT env var is set).
Fallback	If OTLP export fails (e.g., collector unreachable), still complete replay and print a warning.
Deliverables by end of day:

src/mcp_debugger/exporters/otlp_replay_exporter.py – module to convert ReplayResult to OTLP spans.

Integration with replay command (new options).

Unit tests for OTLP exporter (mocked gRPC).

Documentation.

🧠 Expected Behaviour
1. OpenTelemetry Integration Design
Trace root: One trace per replay run. Use the replay_id or a generated UUID as the trace ID.

Spans:

Root span: Represents the entire replay run. Attributes: replay.source_session_id, replay.target_server_command, replay.total_messages, replay.mismatches, replay.timeouts, replay.errors, replay.match_percentage.

Child spans: For each replayed message (or pair of request/response), create a child span.

Span name: mcp.replay.{method} (e.g., mcp.replay.tools/call).

Attributes:

mcp.method (string)

mcp.direction (always client_to_server for replay)

mcp.tool.name (if method is tools/call)

mcp.replay.matched (boolean)

mcp.replay.latency_ms (float)

mcp.replay.original_response_hash (optional, for grouping)

mcp.replay.diff_summary (truncated diff string, max 255 chars)

Events:

If mismatched: add an event mcp.replay.diff with the diff as a structured attribute (or as a JSON string).

Span status: If any mismatch or error, set span status to Error with description.

2. Export Configuration
Endpoint: Use --otlp-endpoint (default http://localhost:4317 for gRPC, or http://localhost:4318/v1/traces for HTTP). The user can also set OTEL_EXPORTER_OTLP_ENDPOINT env var.

Protocol: Support both gRPC and HTTP/protobuf. Use opentelemetry-exporter-otlp-proto-grpc and opentelemetry-exporter-otlp-proto-http as optional dependencies.

Service name: --otlp-service-name (default mcp-debugger).

Insecure: --otlp-insecure (disable TLS for local testing).

3. Integration with replay Command
Add new options to mcp-debugger replay:

Option	Type	Default	Description
--otlp-export	flag	False	Enable OTLP export (if not set, no export).
--otlp-endpoint	str	http://localhost:4317	OTLP collector endpoint.
--otlp-insecure	flag	False	Disable TLS.
--otlp-service-name	str	mcp-debugger	Service name for traces.
If --otlp-export is given but the OTLP libraries are not installed, print a helpful error and suggest pip install mcp-debugger[otlp].

Behaviour:

After replay completes, export the trace asynchronously (do not block the CLI).

If export fails (e.g., connection refused), print a warning but do not affect exit code (unless --otlp-export is required, but keep it optional).

The trace should be exported even if there are mismatches – that’s the point.

4. Export Replay Results from Saved Replays
Add --otlp-export to replay show as well – this allows re‑exporting a saved replay without re‑running the server. The exporter will read from the replay_messages table and generate the same trace structure.

🔗 Integration with Previous Days
Day 15/17 (Replay): ReplayResult contains all data needed for export.

Day 3 (Database): If exporting from saved replays, fetch data from replays and replay_messages.

Day 16 (Diff): Diff data is stored/available for mismatched messages.

⚙️ Production Considerations
Dependencies
Add to pyproject.toml as optional otlp group:

toml
[project.optional-dependencies]
otlp = [
    "opentelemetry-api>=1.20.0",
    "opentelemetry-sdk>=1.20.0",
    "opentelemetry-exporter-otlp-proto-grpc>=1.20.0",
    "opentelemetry-exporter-otlp-proto-http>=1.20.0",
]
Performance
Exporting a trace with hundreds of spans can be slow. The exporter should send spans in batches (the SDK handles this).

Use opentelemetry.sdk.trace.export.BatchSpanProcessor to avoid blocking.

Error Handling
If OTLP endpoint is unreachable, log error but do not crash the replay.

If the user does not have the OTLP dependencies installed, print clear instructions.

Span Attributes Limits
The diff summary could be long. Truncate to 255 characters.

The full diff can be stored as an event with a JSON payload (but OTLP limits event size). Keep it optional.

Backward Compatibility
The replay command remains functional without OTLP. No required changes.

✅ Day 19 Verification Checklist
#	Check	How to verify
1	OTLP export is optional; replay works without --otlp-export	Run replay without flag – no OTLP libraries attempted.
2	When --otlp-export is given, trace appears in Jaeger	Run Jaeger locally (e.g., docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one), replay with --otlp-export, view in Jaeger UI.
3	Trace root span has correct attributes (session id, mismatches, etc.)	Inspect in Jaeger.
4	Each message has a child span with method name, matched flag, latency	Check Jaeger.
5	Mismatched messages have an event with diff	View span events.
6	Span status is Error if mismatch or timeout	Jaeger shows red spans for errors.
7	--otlp-endpoint overrides default	Export to a different collector works.
8	--otlp-insecure disables TLS (for local testing)	Works with local HTTP endpoint.
9	Export from saved replay (replay show --otlp-export) works	Same trace structure as live replay.
10	Missing OTLP dependencies show helpful error	Install base package without [otlp], run --otlp-export – error message appears.
11	Unit tests for exporter (mock OTLP)	pytest tests/test_exporters.py::test_otlp_replay passes.
12	Integration test: replay with OTLP export to a mock collector	Check that spans are sent.
13	mypy --strict passes (with stubs for OTLP)	–
14	ruff check passes	–
15	Documentation updated (docs/replay.md with OTLP section)	–
16	Commit with message feat(otlp): add OpenTelemetry export for replay results	–
🚀 After Day 19 – Immediate Next Steps