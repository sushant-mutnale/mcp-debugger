"""OTLP exporter – converts MCP session messages into OpenTelemetry spans.

Requires the optional ``[export]`` dependency group::

    pip install mcp-debugger[export]

If the ``opentelemetry-sdk`` package is not installed this module raises
``ImportError`` with a helpful message rather than crashing silently.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTLP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _OTLP_AVAILABLE = False


def _parse_json_dict(val: Any) -> dict[str, Any] | None:
    """Safely parse a dict or JSON-encoded dict."""
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _extract_target(method: str, params: Any) -> str | None:
    """Extract semantic target from params (e.g. tool name, resource uri, prompt name)."""
    p_dict = _parse_json_dict(params)
    if not p_dict:
        return None

    if method == "tools/call":
        name = p_dict.get("name")
        return str(name) if name is not None else None
    elif method in ("resources/read", "resources/subscribe", "resources/unsubscribe"):
        uri = p_dict.get("uri")
        return str(uri) if uri is not None else None
    elif method in ("prompts/get",):
        name = p_dict.get("name")
        return str(name) if name is not None else None
    return None


def _get_tool_name(params_raw: Any) -> str | None:
    """Extract tool name from a serialised ``params`` JSON string or dict."""
    return _extract_target("tools/call", params_raw)


def _extract_genai_attributes(
    method: str,
    params: Any = None,
    result: Any = None,
    session: dict[str, Any] | None = None,
    message_id: Any = None,
) -> dict[str, Any]:
    """Extract OpenTelemetry GenAI semantic convention attributes."""
    attrs: dict[str, Any] = {
        "gen_ai.system": "mcp",
    }

    p_dict = _parse_json_dict(params) or {}
    r_dict = _parse_json_dict(result) or {}

    if method == "tools/call":
        attrs["gen_ai.operation.name"] = "execute_tool"
        tool_name = p_dict.get("name")
        if tool_name is not None:
            attrs["gen_ai.tool.name"] = str(tool_name)
    elif method.startswith("prompts/"):
        attrs["gen_ai.operation.name"] = "prompt"
    else:
        attrs["gen_ai.operation.name"] = method

    if message_id is not None:
        attrs["gen_ai.tool.call.id"] = str(message_id)

    # Request model extraction
    req_meta = p_dict.get("_meta") if isinstance(p_dict.get("_meta"), dict) else {}
    req_model = (
        req_meta.get("model")
        or req_meta.get("request_model")
        or req_meta.get("gen_ai.request.model")
        or p_dict.get("model")
    )
    if not req_model and session:
        client_info = _parse_json_dict(session.get("client_info")) or {}
        req_model = client_info.get("model") or session.get("model")
    if req_model:
        attrs["gen_ai.request.model"] = str(req_model)

    # Response model extraction
    resp_meta = r_dict.get("_meta") if isinstance(r_dict.get("_meta"), dict) else {}
    resp_model = (
        resp_meta.get("model")
        or resp_meta.get("response_model")
        or resp_meta.get("gen_ai.response.model")
        or r_dict.get("model")
    )
    if resp_model:
        attrs["gen_ai.response.model"] = str(resp_model)

    # Token usage extraction
    usage = (
        resp_meta.get("usage")
        or r_dict.get("usage")
        or req_meta.get("usage")
        or p_dict.get("usage")
    )
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
        if input_tokens is not None:
            try:
                attrs["gen_ai.usage.input_tokens"] = int(input_tokens)
            except (ValueError, TypeError):
                pass

        output_tokens = usage.get("output_tokens") or usage.get("completion_tokens")
        if output_tokens is not None:
            try:
                attrs["gen_ai.usage.output_tokens"] = int(output_tokens)
            except (ValueError, TypeError):
                pass

        total_tokens = usage.get("total_tokens")
        if total_tokens is not None:
            try:
                attrs["gen_ai.usage.total_tokens"] = int(total_tokens)
            except (ValueError, TypeError):
                pass

    return attrs


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
        limit: int | None = None,
    ) -> None:
        if not _OTLP_AVAILABLE:
            raise ImportError(
                "OpenTelemetry SDK is not installed. Run: pip install 'mcp-debugger[export]'"
            )
        self.endpoint = endpoint
        self.insecure = insecure
        self.service_name = service_name
        self.limit = limit

    def export(
        self,
        session: dict[str, Any],
        messages: list[dict[str, Any]],
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
        root_attrs: dict[str, Any] = {
            "gen_ai.system": "mcp",
            "mcp.session.id": str(session_id),
            "mcp.server.command": str(session.get("server_command") or ""),
            "mcp.session.status": str(session.get("status") or ""),
        }
        if session.get("protocol_version"):
            root_attrs["mcp.protocol_version"] = str(session["protocol_version"])
        server_info = _parse_json_dict(session.get("server_info"))
        if server_info and "capabilities" in server_info:
            root_attrs["mcp.capabilities"] = json.dumps(server_info["capabilities"], sort_keys=True)

        with tracer.start_as_current_span(
            name=f"mcp-session {session_name}",
            attributes=root_attrs,
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
        messages: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
        """Match requests with their responses by message_id.

        Notifications (no message_id) are emitted as solo pairs ``(msg, None)``.
        Responses without a matching request are skipped.
        """
        request_map: dict[str, dict[str, Any]] = {}
        pairs: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

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
        req: dict[str, Any],
        resp: dict[str, Any] | None,
        session: dict[str, Any],
    ) -> None:
        method = req.get("method") or "unknown"
        target = _extract_target(method, req.get("params"))
        span_name = f"{method} {target}" if target else method
        latency_ms = resp.get("latency_ms") if resp else None

        # Build attributes
        attrs: dict[str, Any] = {
            "mcp.method": method,
            "mcp.direction": str(req.get("direction") or ""),
            "mcp.server.command": str(session.get("server_command") or ""),
        }

        if method == "tools/call" and target:
            attrs["mcp.tool.name"] = target

        # GenAI semantic attributes
        genai_attrs = _extract_genai_attributes(
            method=method,
            params=req.get("params"),
            result=resp.get("result") if resp else None,
            session=session,
            message_id=req.get("message_id") or req.get("id"),
        )
        attrs.update(genai_attrs)

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
                    result = (
                        json.loads(resp["result"])
                        if isinstance(resp["result"], str)
                        else resp["result"]
                    )
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
