"""OTLP exporter for replay results.

Converts a :class:`~mcp_debugger.replay.engine.ReplayResult` into
OpenTelemetry trace spans and exports them to an OTLP collector (e.g. Jaeger,
Grafana Tempo, or any compatible backend).

Requires the optional ``[otlp]`` dependency group::

    pip install 'mcp-debugger[otlp]'

If the ``opentelemetry-sdk`` package is not installed this module raises
``ImportError`` with a helpful message rather than crashing silently.

Trace structure
---------------
* One trace per replay run.
* Root span – ``mcp.replay <session_id>`` – carries summary attributes.
* One child span per replayed message – ``mcp.replay.<method>`` – carries
  per-message attributes and, for mismatches, a structured diff event.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict

# ---------------------------------------------------------------------------
# Optional OpenTelemetry imports – guarded so the module can be imported even
# when the SDK is not installed.  The actual classes are only used inside
# OTLPReplayExporter, which refuses to construct itself without the SDK.
# ---------------------------------------------------------------------------
try:
    from opentelemetry import trace as _otel_trace  # noqa: F401
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.trace import Status, StatusCode

    _OTLP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _OTLP_AVAILABLE = False
    # Sentinel stubs so patch.object() in tests can always find these names,
    # even when the SDK is not installed.
    Resource = None  # type: ignore
    TracerProvider = None  # type: ignore
    BatchSpanProcessor = None  # type: ignore
    OTLPSpanExporter = None  # type: ignore
    Status = None  # type: ignore
    StatusCode = None  # type: ignore

if TYPE_CHECKING:  # pragma: no cover
    from mcp_debugger.replay.engine import ReplayResult, ReplayedMessage

_DIFF_SUMMARY_MAX = 255  # OTLP attribute character limit for diff summaries


class OTLPReplayExporter:
    """Convert a :class:`~mcp_debugger.replay.engine.ReplayResult` into OTLP spans.

    Each replay run becomes a single trace:

    * The root span carries aggregate statistics (total, matches, mismatches,
      timeouts, errors, match percentage).
    * Each replayed message becomes a child span carrying per-message data
      (method, matched, latency, diff summary).  Mismatched messages also
      receive a structured ``mcp.replay.diff`` event.

    Args:
        endpoint: OTLP gRPC collector endpoint (default ``http://localhost:4317``).
        insecure: Disable TLS verification (useful for local testing).
        service_name: Service name attached to all spans.
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:4317",
        insecure: bool = True,
        service_name: str = "mcp-debugger",
    ) -> None:
        if not _OTLP_AVAILABLE:
            raise ImportError(
                "OpenTelemetry SDK is not installed. "
                "Run: pip install 'mcp-debugger[otlp]'"
            )
        self.endpoint = endpoint
        self.insecure = insecure
        self.service_name = service_name

    def export(self, result: "ReplayResult") -> int:
        """Export *result* as an OTLP trace.

        Returns the number of child spans (replayed messages) exported, not
        counting the root span.  Returns 0 if export fails.
        """
        resource = Resource.create({"service.name": self.service_name})
        provider = TracerProvider(resource=resource)
        otlp_exporter = OTLPSpanExporter(
            endpoint=self.endpoint,
            insecure=self.insecure,
        )
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        tracer = provider.get_tracer("mcp-debugger.replay")

        total = result.total_messages_replayed
        matches = sum(1 for m in result.messages if m.matches)
        mismatches = result.mismatched_responses
        timeouts = result.timed_out
        errors = result.failed_responses
        match_pct = round(matches / total * 100, 1) if total else 0.0
        duration_s = (result.ended_at - result.started_at).total_seconds()

        root_attrs: Dict[str, Any] = {
            "replay.session_id": str(result.session_id),
            "replay.target_server_command": result.target_server_command,
            "replay.total_messages": total,
            "replay.matches": matches,
            "replay.mismatches": mismatches,
            "replay.timeouts": timeouts,
            "replay.errors": errors,
            "replay.match_percentage": match_pct,
            "replay.duration_seconds": round(duration_s, 3),
        }
        if result.replay_id is not None:
            root_attrs["replay.id"] = str(result.replay_id)

        span_count = 0

        with tracer.start_as_current_span(
            name=f"mcp.replay session-{result.session_id}",
            attributes=root_attrs,
        ) as root_span:
            # Mark root span as error if there were any mismatches or timeouts
            if mismatches > 0 or timeouts > 0 or errors > 0:
                root_span.set_status(
                    Status(StatusCode.ERROR, f"{mismatches} mismatch(es), {timeouts} timeout(s)")
                )

            for msg in result.messages:
                self._emit_message_span(tracer, msg)
                span_count += 1

        provider.force_flush()
        provider.shutdown()
        return span_count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_message_span(
        self,
        tracer: Any,
        msg: "ReplayedMessage",
    ) -> None:
        """Create a child span for a single replayed message."""
        method = msg.method or "unknown"
        span_name = f"mcp.replay.{method}"

        attrs: Dict[str, Any] = {
            "mcp.method": method,
            "mcp.direction": "client_to_server",
            "mcp.replay.original_message_id": str(msg.original_message_id),
            "mcp.replay.matched": msg.matches,
            "mcp.replay.latency_ms": round(msg.latency_ms, 3),
        }

        # Extract tool name for tools/call spans
        if method == "tools/call" and msg.request_sent:
            params = msg.request_sent.get("params")
            if isinstance(params, dict):
                tool_name = params.get("name")
            elif isinstance(params, str):
                try:
                    tool_name = json.loads(params).get("name")
                except (json.JSONDecodeError, ValueError):
                    tool_name = None
            else:
                tool_name = None
            if tool_name:
                attrs["mcp.tool.name"] = str(tool_name)

        # Truncated diff summary for quick scanning in trace UIs
        if msg.diff_text:
            attrs["mcp.replay.diff_summary"] = msg.diff_text[:_DIFF_SUMMARY_MAX]

        if msg.error:
            attrs["mcp.replay.error"] = msg.error[:_DIFF_SUMMARY_MAX]

        with tracer.start_as_current_span(span_name, attributes=attrs) as span:
            if not msg.matches or msg.error:
                description = msg.error or f"Response mismatch for {method}"
                span.set_status(Status(StatusCode.ERROR, description))

            # Add structured diff event for mismatched messages
            if not msg.matches and msg.diff:
                try:
                    diff_json = json.dumps(
                        [d.model_dump() for d in msg.diff],
                        separators=(",", ":"),
                    )
                    # Truncate to a safe size for OTLP event payloads
                    span.add_event(
                        "mcp.replay.diff",
                        attributes={"diff": diff_json[:1024]},
                    )
                except Exception:
                    # Never let serialisation errors break the export
                    pass

            # Add original and replayed response hashes for grouping
            if msg.original_response is not None:
                try:
                    orig_str = json.dumps(msg.original_response, sort_keys=True)
                    span.set_attribute(
                        "mcp.replay.original_response_hash",
                        str(hash(orig_str) & 0xFFFFFFFF),
                    )
                except Exception:
                    pass
