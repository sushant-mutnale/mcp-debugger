"""OTLP exporter – converts MCP session messages into OpenTelemetry spans.

Requires the optional ``[export]`` dependency group::

    pip install mcp-debugger[export]

If the ``opentelemetry-sdk`` package is not installed this module raises
``ImportError`` with a helpful message rather than crashing silently.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

try:
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    _OTLP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _OTLP_AVAILABLE = False


def _get_tool_name(params_raw: Optional[str]) -> Optional[str]:
    """Extract tool name from a serialised ``params`` JSON string."""
    if not params_raw:
        return None
    try:
        params = json.loads(params_raw)
        if isinstance(params, dict):
            return params.get("name")
    except (json.JSONDecodeError, ValueError):
        pass
    return None


class OTLPExporter:
    """Convert a session's messages into OpenTelemetry spans and export them.

    Each request–response pair becomes one span.  Notifications (no ID)
    become zero-duration spans.  All message spans are children of a root
    session span so the full timeline is visible in one trace.

    Args:
        endpoint: OTLP gRPC collector endpoint (default ``http://localhost:4317``).
        insecure: Disable TLS verification (useful for local testing).
        service_name: Service name attached to all spans.
        limit: If given, export only the first *limit* messages.
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:4317",
        insecure: bool = True,
        service_name: str = "mcp-debugger",
        limit: Optional[int] = None,
    ) -> None:
        if not _OTLP_AVAILABLE:
            raise ImportError(
                "OpenTelemetry SDK is not installed. "
                "Run: pip install 'mcp-debugger[export]'"
            )
        self.endpoint = endpoint
        self.insecure = insecure
        self.service_name = service_name
        self.limit = limit

    def export(
        self,
        session: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> int:
        """Build and export spans for all request–response pairs.

        Returns the number of spans exported (excluding the root span).
        """
        msgs = messages[: self.limit] if self.limit is not None else messages

        resource = Resource.create({"service.name": self.service_name})
        provider = TracerProvider(resource=resource)
        exporter_obj = OTLPSpanExporter(
            endpoint=self.endpoint,
            insecure=self.insecure,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter_obj))
        tracer = provider.get_tracer("mcp-debugger")

        session_id = session.get("id", 0)
        session_name = session.get("friendly_name") or f"session-{session_id}"

        # --- root session span ---
        with tracer.start_as_current_span(
            name=f"mcp-session {session_name}",
            attributes={
                "mcp.session.id": str(session_id),
                "mcp.server.command": str(session.get("server_command") or ""),
                "mcp.session.status": str(session.get("status") or ""),
            },
        ):
            pairs = self._pair_messages(msgs)
            span_count = 0
            for req, resp in pairs:
                self._emit_span(tracer, req, resp, session)
                span_count += 1

        provider.shutdown()
        return span_count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pair_messages(
        messages: List[Dict[str, Any]],
    ) -> List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
        """Match requests with their responses by message_id.

        Notifications (no message_id) are emitted as solo pairs ``(msg, None)``.
        Responses without a matching request are skipped.
        """
        request_map: Dict[str, Dict[str, Any]] = {}
        pairs: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]] = []

        for msg in messages:
            direction = msg.get("direction")
            msg_type = msg.get("message_type")
            msg_id = msg.get("message_id")

            if msg_type == "notification":
                pairs.append((msg, None))
            elif msg_type == "request" and direction == "client_to_server":
                if msg_id:
                    request_map[msg_id] = msg
                else:
                    pairs.append((msg, None))
            elif msg_type == "response" and direction == "server_to_client":
                if msg_id and msg_id in request_map:
                    pairs.append((request_map.pop(msg_id), msg))

        # Any unmatched requests (no response received)
        for req in request_map.values():
            pairs.append((req, None))

        return pairs

    def _emit_span(
        self,
        tracer: Any,
        req: Dict[str, Any],
        resp: Optional[Dict[str, Any]],
        session: Dict[str, Any],
    ) -> None:
        method = req.get("method") or "unknown"
        span_name = f"mcp.{method}"
        latency_ms = resp.get("latency_ms") if resp else None

        # Build attributes
        attrs: Dict[str, Any] = {
            "mcp.method": method,
            "mcp.direction": str(req.get("direction") or ""),
            "mcp.server.command": str(session.get("server_command") or ""),
        }

        if method == "tools/call":
            tool_name = _get_tool_name(req.get("params"))
            if tool_name:
                attrs["mcp.tool.name"] = tool_name

        has_error = False
        if resp:
            if resp.get("error"):
                has_error = True
                attrs["mcp.error"] = True
                err_raw = resp.get("error")
                if isinstance(err_raw, str):
                    try:
                        err_dict = json.loads(err_raw)
                        code = err_dict.get("code")
                        if code is not None:
                            attrs["mcp.error_code"] = int(code)
                    except (json.JSONDecodeError, ValueError):
                        pass
            elif resp.get("result"):
                try:
                    result = json.loads(resp["result"]) if isinstance(resp["result"], str) else resp["result"]
                    if isinstance(result, dict) and result.get("isError"):
                        has_error = True
                        attrs["mcp.error"] = True
                except (json.JSONDecodeError, ValueError):
                    pass

        if not has_error:
            attrs["mcp.error"] = False

        if latency_ms is not None:
            attrs["mcp.latency_ms"] = float(latency_ms)

        with tracer.start_as_current_span(span_name, attributes=attrs):
            pass  # span lifecycle managed by context manager
