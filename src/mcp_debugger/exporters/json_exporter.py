"""JSON exporter – serialises a full session into a structured JSON document."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, IO, List, Optional

from mcp_debugger.analytics import SessionStats


def _iso(ts_ms: Optional[float]) -> Optional[str]:
    """Convert a float millisecond timestamp to an ISO-8601 UTC string."""
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()


class JSONExporter:
    """Convert session data into a structured JSON document.

    The exporter is intentionally decoupled from the database; all data is
    passed in as plain Python objects so the class is easy to unit-test.

    Output shape::

        {
            "session":  { ... },
            "messages": [ ... ],
            "tools":    [ ... ],
            "errors":   [ ... ],
            "stats":    { ... }
        }
    """

    def __init__(self, pretty: bool = False, include_raw: bool = False) -> None:
        """Initialise the exporter.

        Args:
            pretty: If ``True`` use ``indent=2`` when serialising JSON.
            include_raw: Unused here (kept for interface symmetry with the
                Markdown exporter).  All message fields are always included.
        """
        self.pretty = pretty
        self.include_raw = include_raw
        self._indent: Optional[int] = 2 if pretty else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(
        self,
        session: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        errors: List[Dict[str, Any]],
        stats: SessionStats,
        out: IO[str],
    ) -> None:
        """Serialise all session data and write to *out*.

        Args:
            session: Row dict from ``Database.get_session()``.
            messages: List of message row dicts from ``Database.get_messages()``.
            tools: List of tool row dicts from ``Database.get_tools()``.
            errors: List of error row dicts from ``Database.get_errors()``.
            stats: Pre-computed ``SessionStats`` (from Day 12 analytics).
            out: Writable text stream (file or ``io.StringIO``).
        """
        document = self._build(session, messages, tools, errors, stats)
        json.dump(document, out, indent=self._indent, default=str)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build(
        self,
        session: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        errors: List[Dict[str, Any]],
        stats: SessionStats,
    ) -> Dict[str, Any]:
        return {
            "session": self._build_session(session),
            "messages": [self._build_message(m) for m in messages],
            "tools": [self._build_tool(t, stats) for t in tools],
            "errors": [self._build_error(e) for e in errors],
            "stats": self._build_stats(stats),
        }

    @staticmethod
    def _build_session(session: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": session.get("id"),
            "friendly_name": session.get("friendly_name"),
            "server_command": session.get("server_command"),
            "started_at": session.get("started_at"),
            "ended_at": session.get("ended_at"),
            "duration_seconds": session.get("duration_seconds"),
            "status": session.get("status"),
        }

    @staticmethod
    def _build_message(msg: Dict[str, Any]) -> Dict[str, Any]:
        # params / result / error are stored as JSON strings; decode them.
        def _decode(raw: Any) -> Any:
            if isinstance(raw, str):
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    return raw
            return raw

        return {
            "id": msg.get("id"),
            "direction": msg.get("direction"),
            "method": msg.get("method"),
            "timestamp": _iso(msg.get("timestamp")),
            "latency_ms": msg.get("latency_ms"),
            "params": _decode(msg.get("params")),
            "result": _decode(msg.get("result")),
            "error": _decode(msg.get("error")),
            "message_type": msg.get("message_type"),
        }

    @staticmethod
    def _build_tool(tool: Dict[str, Any], stats: SessionStats) -> Dict[str, Any]:
        name = tool.get("name") or ""
        # Look up per-tool metrics from the pre-computed stats
        tool_metric = next((t for t in stats.top_tools if t.name == name), None)
        call_count = tool_metric.calls if tool_metric else 0
        avg_latency = (
            round(tool_metric.avg_latency_ms, 2)
            if (tool_metric and tool_metric.avg_latency_ms is not None)
            else None
        )

        raw_schema = tool.get("input_schema") or "{}"
        try:
            schema = json.loads(raw_schema) if isinstance(raw_schema, str) else raw_schema
        except (json.JSONDecodeError, ValueError):
            schema = {}

        return {
            "name": name,
            "description": tool.get("description"),
            "input_schema": schema,
            "call_count": call_count,
            "avg_latency_ms": avg_latency,
        }

    @staticmethod
    def _build_error(err: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": err.get("id"),
            "type": err.get("error_type"),
            "code": err.get("error_code"),
            "message": err.get("error_message"),
            "suggestion": err.get("suggestion"),
        }

    @staticmethod
    def _build_stats(stats: SessionStats) -> Dict[str, Any]:
        total_errors = sum(stats.errors_by_category.values())
        total_msgs = stats.total_messages
        error_rate = round(total_errors / total_msgs, 4) if total_msgs > 0 else 0.0
        return {
            "total_messages": total_msgs,
            "client_to_server": stats.client_to_server_count,
            "server_to_client": stats.server_to_client_count,
            "total_errors": total_errors,
            "error_rate": error_rate,
            "tools_called": len(stats.top_tools),
            "avg_latency_ms": round(stats.latency_avg, 2)
            if stats.latency_avg is not None
            else None,
        }
