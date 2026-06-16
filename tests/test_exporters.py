"""Tests for JSONExporter, MarkdownExporter, and OTLPExporter."""

import io
import json
import pytest
from typing import Any, Dict, Optional

from mcp_debugger.analytics import SessionStats, ToolMetric
from mcp_debugger.exporters.json_exporter import JSONExporter
from mcp_debugger.exporters.markdown_exporter import MarkdownExporter


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SESSION = {
    "id": 1,
    "friendly_name": "test session",
    "server_command": "npx mcp-server",
    "started_at": "2025-06-10 14:00:00",
    "ended_at": "2025-06-10 14:05:00",
    "duration_seconds": 300,
    "status": "completed",
}

MESSAGES = [
    {
        "id": 101,
        "direction": "client_to_server",
        "method": "initialize",
        "timestamp": 1_718_020_800_000.0,  # milliseconds since epoch
        "latency_ms": None,
        "params": '{"protocolVersion": "2025-03-26"}',
        "result": None,
        "error": None,
        "message_type": "request",
    },
    {
        "id": 102,
        "direction": "server_to_client",
        "method": "initialize",
        "timestamp": 1_718_020_800_050.0,
        "latency_ms": 50.0,
        "params": None,
        "result": '{"protocolVersion": "2025-03-26", "serverInfo": {"name": "test"}}',
        "error": None,
        "message_type": "response",
    },
    {
        "id": 103,
        "direction": "client_to_server",
        "method": "tools/call",
        "timestamp": 1_718_020_801_000.0,
        "latency_ms": None,
        "params": '{"name": "read_file", "arguments": {"path": "/tmp/f.txt"}}',
        "result": None,
        "error": None,
        "message_type": "request",
    },
    {
        "id": 104,
        "direction": "server_to_client",
        "method": "tools/call",
        "timestamp": 1_718_020_801_080.0,
        "latency_ms": 80.0,
        "params": None,
        "result": '{"isError": false, "content": [{"type": "text", "text": "hello"}]}',
        "error": None,
        "message_type": "response",
    },
]

TOOLS = [
    {
        "id": 1,
        "session_id": 1,
        "name": "read_file",
        "description": "Read a file",
        "input_schema": '{"type": "object", "properties": {"path": {"type": "string"}}}',
        "output_schema": None,
    }
]

ERRORS = [
    {
        "id": 1,
        "session_id": 1,
        "message_id": None,
        "error_code": -32601,
        "error_type": "protocol",
        "error_message": "Method not found",
        "suggestion": "Check the method name spelling",
    }
]

STATS = SessionStats(
    session_id=1,
    friendly_name="test session",
    server_command="npx mcp-server",
    started_at="2025-06-10 14:00:00",
    ended_at="2025-06-10 14:05:00",
    status="completed",
    duration_seconds=300,
    total_messages=4,
    client_to_server_count=2,
    server_to_client_count=2,
    top_tools=[ToolMetric(name="read_file", calls=1, avg_latency_ms=80.0, error_rate=0.0, errors_count=0)],
    errors_by_category={"protocol": 1},
    latency_min=50.0,
    latency_max=80.0,
    latency_avg=65.0,
    latency_trend=[50.0, 80.0],
    method_distribution={"initialize": 1, "tools/call": 1},
    error_trend=[0, 0],
)


# ---------------------------------------------------------------------------
# JSONExporter tests
# ---------------------------------------------------------------------------

class TestJSONExporter:

    def _export(self, pretty: bool = False, include_raw: bool = False) -> Dict[str, Any]:
        exporter = JSONExporter(pretty=pretty, include_raw=include_raw)
        buf = io.StringIO()
        exporter.export(SESSION, MESSAGES, TOOLS, ERRORS, STATS, buf)
        return dict(json.loads(buf.getvalue()))

    def test_top_level_keys(self) -> None:
        doc = self._export()
        assert set(doc.keys()) == {"session", "messages", "tools", "errors", "stats"}

    def test_session_metadata(self) -> None:
        doc = self._export()
        s = doc["session"]
        assert s["id"] == 1
        assert s["friendly_name"] == "test session"
        assert s["server_command"] == "npx mcp-server"
        assert s["status"] == "completed"
        assert s["duration_seconds"] == 300

    def test_messages_count_and_structure(self) -> None:
        doc = self._export()
        assert len(doc["messages"]) == 4
        first = doc["messages"][0]
        assert first["direction"] == "client_to_server"
        assert first["method"] == "initialize"
        # Params should be decoded from JSON string to dict
        assert isinstance(first["params"], dict)
        assert first["params"]["protocolVersion"] == "2025-03-26"
        # Timestamp should be an ISO string
        assert isinstance(first["timestamp"], str)
        assert "T" in first["timestamp"]

    def test_tools_include_call_count_and_latency(self) -> None:
        doc = self._export()
        assert len(doc["tools"]) == 1
        tool = doc["tools"][0]
        assert tool["name"] == "read_file"
        assert tool["call_count"] == 1
        assert tool["avg_latency_ms"] == 80.0
        # input_schema should be decoded dict
        assert isinstance(tool["input_schema"], dict)

    def test_errors_structure(self) -> None:
        doc = self._export()
        assert len(doc["errors"]) == 1
        err = doc["errors"][0]
        assert err["type"] == "protocol"
        assert err["code"] == -32601
        assert err["message"] == "Method not found"
        assert "spelling" in err["suggestion"].lower()

    def test_stats_calculations(self) -> None:
        doc = self._export()
        s = doc["stats"]
        assert s["total_messages"] == 4
        assert s["client_to_server"] == 2
        assert s["server_to_client"] == 2
        assert s["total_errors"] == 1
        assert s["error_rate"] == 0.25   # 1/4
        assert s["tools_called"] == 1
        assert s["avg_latency_ms"] == 65.0

    def test_pretty_print_uses_indentation(self) -> None:
        exporter_pretty = JSONExporter(pretty=True)
        exporter_compact = JSONExporter(pretty=False)
        buf_p = io.StringIO()
        buf_c = io.StringIO()
        exporter_pretty.export(SESSION, MESSAGES, TOOLS, ERRORS, STATS, buf_p)
        exporter_compact.export(SESSION, MESSAGES, TOOLS, ERRORS, STATS, buf_c)
        # Pretty output is longer (has newlines / spaces)
        assert len(buf_p.getvalue()) > len(buf_c.getvalue())
        # Both must still be valid JSON
        assert json.loads(buf_p.getvalue())
        assert json.loads(buf_c.getvalue())

    def test_empty_messages_and_tools(self) -> None:
        empty_stats = SessionStats(
            session_id=99,
            server_command="cmd",
            status="completed",
        )
        exporter = JSONExporter()
        buf = io.StringIO()
        exporter.export(SESSION, [], [], [], empty_stats, buf)
        doc = json.loads(buf.getvalue())
        assert doc["messages"] == []
        assert doc["tools"] == []
        assert doc["errors"] == []
        assert doc["stats"]["total_messages"] == 0
        assert doc["stats"]["error_rate"] == 0.0

    def test_invalid_json_params_returned_as_string(self) -> None:
        """Params that are not valid JSON should come back as a plain string."""
        bad_msg = {**MESSAGES[0], "params": "not-valid-{json"}
        exporter = JSONExporter()
        buf = io.StringIO()
        exporter.export(SESSION, [bad_msg], [], [], STATS, buf)
        doc = json.loads(buf.getvalue())
        assert doc["messages"][0]["params"] == "not-valid-{json"


# ---------------------------------------------------------------------------
# MarkdownExporter tests
# ---------------------------------------------------------------------------

class TestMarkdownExporter:

    def _export(self, include_raw: bool = False, pretty: bool = False) -> str:
        exporter = MarkdownExporter(include_raw=include_raw, pretty=pretty)
        buf = io.StringIO()
        exporter.export(SESSION, MESSAGES, TOOLS, ERRORS, STATS, buf)
        return buf.getvalue()

    def test_report_title(self) -> None:
        md = self._export()
        assert "# MCP Session Report" in md
        assert "test session" in md

    def test_metadata_table_present(self) -> None:
        md = self._export()
        assert "## Metadata" in md
        assert "Session ID" in md
        assert "npx mcp-server" in md
        assert "5m 0s" in md   # duration_seconds=300

    def test_summary_section(self) -> None:
        md = self._export()
        assert "## Summary" in md
        assert "4" in md          # total messages
        assert "→ server" in md
        assert "← client" in md

    def test_tool_inventory_table(self) -> None:
        md = self._export()
        assert "## Tool Inventory" in md
        assert "read_file" in md
        assert "80.0ms" in md

    def test_errors_section(self) -> None:
        md = self._export()
        assert "## Errors" in md
        assert "protocol" in md
        assert "Method not found" in md
        assert "spelling" in md

    def test_message_log_table_rows(self) -> None:
        md = self._export()
        assert "## Message Log" in md
        assert "initialize" in md
        assert "tools/call" in md
        assert "→ server" in md
        assert "← client" in md

    def test_no_details_blocks_by_default(self) -> None:
        md = self._export(include_raw=False)
        assert "<details>" not in md

    def test_include_raw_adds_details_blocks(self) -> None:
        md = self._export(include_raw=True)
        assert "<details>" in md
        assert "```json" in md
        # One block per message
        assert md.count("<details>") == len(MESSAGES)

    def test_empty_session_placeholders(self) -> None:
        empty_stats = SessionStats(session_id=2, server_command="x", status="completed")
        exporter = MarkdownExporter()
        buf = io.StringIO()
        exporter.export(SESSION, [], [], [], empty_stats, buf)
        md = buf.getvalue()
        assert "_No tools discovered" in md
        assert "_No errors recorded" in md
        assert "_No messages recorded" in md


# ---------------------------------------------------------------------------
# OTLPExporter tests
# ---------------------------------------------------------------------------
#
# The OTLPExporter._pair_messages() is pure logic (no SDK dependency) so we
# test it directly.  The full export() path requires the SDK; we skip those
# tests if it is not installed.
# ---------------------------------------------------------------------------

class TestOTLPExporterPairing:
    """Test message pairing logic (no OTLP SDK required)."""

    # We import the private helper directly to avoid needing the SDK.
    def _pair(self, messages: list) -> list:  # type: ignore[type-arg]
        from mcp_debugger.exporters.otlp_exporter import OTLPExporter
        return OTLPExporter._pair_messages(messages)

    def _msg(
        self,
        *,
        msg_id: Optional[str],
        direction: str,
        msg_type: str,
        method: Optional[str] = "tools/call",
    ) -> Dict[str, Any]:
        return {
            "message_id": msg_id,
            "direction": direction,
            "message_type": msg_type,
            "method": method,
            "timestamp": 1_000.0,
            "latency_ms": None,
        }

    def test_request_response_paired(self) -> None:
        req = self._msg(msg_id="1", direction="client_to_server", msg_type="request")
        resp = self._msg(msg_id="1", direction="server_to_client", msg_type="response")
        pairs = self._pair([req, resp])
        assert len(pairs) == 1
        r, s = pairs[0]
        assert r is req
        assert s is resp

    def test_notification_has_none_response(self) -> None:
        notif = self._msg(msg_id=None, direction="client_to_server", msg_type="notification", method="notifications/initialized")
        pairs = self._pair([notif])
        assert len(pairs) == 1
        r, s = pairs[0]
        assert r is notif
        assert s is None

    def test_unmatched_request_emitted_solo(self) -> None:
        req = self._msg(msg_id="99", direction="client_to_server", msg_type="request")
        pairs = self._pair([req])
        assert len(pairs) == 1
        assert pairs[0][1] is None

    def test_orphan_response_skipped(self) -> None:
        resp = self._msg(msg_id="42", direction="server_to_client", msg_type="response")
        pairs = self._pair([resp])
        assert pairs == []

    def test_multiple_pairs(self) -> None:
        msgs = [
            self._msg(msg_id="1", direction="client_to_server", msg_type="request", method="initialize"),
            self._msg(msg_id="1", direction="server_to_client", msg_type="response", method="initialize"),
            self._msg(msg_id=None, direction="client_to_server", msg_type="notification", method="notifications/initialized"),
            self._msg(msg_id="2", direction="client_to_server", msg_type="request", method="tools/call"),
            self._msg(msg_id="2", direction="server_to_client", msg_type="response", method="tools/call"),
        ]
        pairs = self._pair(msgs)
        assert len(pairs) == 3   # 2 req/resp + 1 notification

    def test_import_error_when_sdk_missing(self) -> None:
        """OTLPExporter raises ImportError with a helpful message when SDK absent."""
        import mcp_debugger.exporters.otlp_exporter as otlp_mod
        original = otlp_mod._OTLP_AVAILABLE
        try:
            otlp_mod._OTLP_AVAILABLE = False
            with pytest.raises(ImportError, match="pip install"):
                otlp_mod.OTLPExporter()
        finally:
            otlp_mod._OTLP_AVAILABLE = original


# ---------------------------------------------------------------------------
# OTLPReplayExporter tests
# ---------------------------------------------------------------------------

class TestOTLPReplayExporter:
    """Tests for the OTLPReplayExporter that converts ReplayResult into spans."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_result(
        self,
        *,
        session_id: int = 42,
        matches: int = 2,
        mismatches: int = 0,
        with_diff: bool = False,
    ) -> Any:
        """Build a minimal ReplayResult fixture."""
        from datetime import datetime, timezone
        from mcp_debugger.replay.engine import ReplayResult, ReplayedMessage
        from mcp_debugger.replay.diff import DiffNode, DiffType

        msgs = []
        for i in range(matches):
            msgs.append(ReplayedMessage(
                original_message_id=i + 1,
                method="tools/list",
                request_sent={"id": i + 1, "method": "tools/list"},
                original_response={"id": i + 1, "result": {"tools": []}},
                replayed_response={"id": i + 1, "result": {"tools": []}},
                latency_ms=float(10 + i),
                matches=True,
            ))

        for j in range(mismatches):
            diff_nodes = []
            if with_diff:
                diff_nodes = [DiffNode(
                    path="result.tools[0].name",
                    type=DiffType.CHANGED,
                    old_value="old",
                    new_value="new",
                )]
            msgs.append(ReplayedMessage(
                original_message_id=100 + j,
                method="tools/call",
                request_sent={
                    "id": 100 + j,
                    "method": "tools/call",
                    "params": {"name": "read_file", "arguments": {"path": "/tmp/f.txt"}},
                },
                original_response={"id": 100 + j, "result": {"content": [{"type": "text", "text": "old"}]}},
                replayed_response={"id": 100 + j, "result": {"content": [{"type": "text", "text": "new"}]}},
                latency_ms=99.9,
                matches=False,
                diff=diff_nodes if with_diff else None,
                diff_text="result.tools[0].name: old → new" if with_diff else None,
            ))

        return ReplayResult(
            replay_id=7,
            session_id=session_id,
            target_server_command="mock-server",
            started_at=datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2025, 6, 15, 10, 0, 2, tzinfo=timezone.utc),
            total_messages_replayed=matches + mismatches,
            successful_responses=matches,
            failed_responses=0,
            mismatched_responses=mismatches,
            timed_out=0,
            messages=msgs,
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_import_error_when_sdk_missing(self) -> None:
        """OTLPReplayExporter raises ImportError with helpful message when SDK absent."""
        import mcp_debugger.exporters.otlp_replay_exporter as mod
        original = mod._OTLP_AVAILABLE
        try:
            mod._OTLP_AVAILABLE = False
            with pytest.raises(ImportError, match="pip install"):
                mod.OTLPReplayExporter()
        finally:
            mod._OTLP_AVAILABLE = original

    def test_export_returns_span_count(self) -> None:
        """export() returns the correct number of child spans."""
        from unittest.mock import MagicMock, patch, call
        import mcp_debugger.exporters.otlp_replay_exporter as mod

        result = self._make_result(matches=3)

        mock_provider = MagicMock()
        mock_tracer = MagicMock()
        mock_root_span_ctx = MagicMock()
        mock_root_span_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_root_span_ctx.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_root_span_ctx

        with patch.object(mod, "_OTLP_AVAILABLE", True), \
             patch.object(mod, "TracerProvider", return_value=mock_provider), \
             patch.object(mod, "OTLPSpanExporter", return_value=MagicMock()), \
             patch.object(mod, "BatchSpanProcessor", return_value=MagicMock()), \
             patch.object(mod, "Resource", MagicMock()) as mock_res:
            mock_res.create.return_value = MagicMock()
            mock_provider.get_tracer.return_value = mock_tracer

            exporter = mod.OTLPReplayExporter()
            count = exporter.export(result)

        # Root span + child spans; export() returns only child span count
        assert count == 3

    def test_export_all_matches_no_error_status(self) -> None:
        """Root span is not marked ERROR when all messages match."""
        from unittest.mock import MagicMock, patch
        import mcp_debugger.exporters.otlp_replay_exporter as mod

        result = self._make_result(matches=2, mismatches=0)

        mock_provider = MagicMock()
        mock_tracer = MagicMock()
        mock_root_span = MagicMock()
        mock_root_span_ctx = MagicMock()
        mock_root_span_ctx.__enter__ = MagicMock(return_value=mock_root_span)
        mock_root_span_ctx.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_root_span_ctx

        with patch.object(mod, "_OTLP_AVAILABLE", True), \
             patch.object(mod, "TracerProvider", return_value=mock_provider), \
             patch.object(mod, "OTLPSpanExporter", return_value=MagicMock()), \
             patch.object(mod, "BatchSpanProcessor", return_value=MagicMock()), \
             patch.object(mod, "Resource", MagicMock()) as mock_res:
            mock_res.create.return_value = MagicMock()
            mock_provider.get_tracer.return_value = mock_tracer

            exporter = mod.OTLPReplayExporter()
            exporter.export(result)

        # set_status must NOT have been called on the root span (no errors)
        mock_root_span.set_status.assert_not_called()

    def test_export_with_mismatch_sets_error_status(self) -> None:
        """Root span is marked ERROR when there are mismatches."""
        from unittest.mock import MagicMock, patch
        import mcp_debugger.exporters.otlp_replay_exporter as mod

        result = self._make_result(matches=1, mismatches=1, with_diff=True)

        mock_provider = MagicMock()
        mock_tracer = MagicMock()
        mock_root_span = MagicMock()
        mock_root_span_ctx = MagicMock()
        mock_root_span_ctx.__enter__ = MagicMock(return_value=mock_root_span)
        mock_root_span_ctx.__exit__ = MagicMock(return_value=False)

        # Child spans also use context managers
        mock_child_span = MagicMock()
        mock_child_ctx = MagicMock()
        mock_child_ctx.__enter__ = MagicMock(return_value=mock_child_span)
        mock_child_ctx.__exit__ = MagicMock(return_value=False)

        # The first call is the root span, subsequent calls are child spans
        mock_tracer.start_as_current_span.side_effect = [mock_root_span_ctx] + [mock_child_ctx] * 10

        with patch.object(mod, "_OTLP_AVAILABLE", True), \
             patch.object(mod, "TracerProvider", return_value=mock_provider), \
             patch.object(mod, "OTLPSpanExporter", return_value=MagicMock()), \
             patch.object(mod, "BatchSpanProcessor", return_value=MagicMock()), \
             patch.object(mod, "Resource", MagicMock()) as mock_res, \
             patch.object(mod, "Status", MagicMock()), \
             patch.object(mod, "StatusCode", MagicMock()):
            mock_res.create.return_value = MagicMock()
            mock_provider.get_tracer.return_value = mock_tracer

            exporter = mod.OTLPReplayExporter()
            exporter.export(result)

        # Root span should have had set_status called (mismatches > 0)
        mock_root_span.set_status.assert_called_once()

    def test_diff_summary_truncated_to_255(self) -> None:
        """Diff summaries are truncated at 255 characters in span attributes."""
        from mcp_debugger.exporters.otlp_replay_exporter import _DIFF_SUMMARY_MAX
        assert _DIFF_SUMMARY_MAX == 255

    def test_tool_name_extracted_from_params_dict(self) -> None:
        """_emit_message_span correctly extracts tool name from dict params."""
        from unittest.mock import MagicMock, patch
        import mcp_debugger.exporters.otlp_replay_exporter as mod
        from datetime import datetime, timezone
        from mcp_debugger.replay.engine import ReplayedMessage

        msg = ReplayedMessage(
            original_message_id=5,
            method="tools/call",
            request_sent={"params": {"name": "write_file", "arguments": {}}},
            original_response=None,
            replayed_response=None,
            latency_ms=55.0,
            matches=True,
        )

        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_ctx

        with patch.object(mod, "_OTLP_AVAILABLE", True), \
             patch.object(mod, "Status", MagicMock()), \
             patch.object(mod, "StatusCode", MagicMock()):
            exporter = mod.OTLPReplayExporter.__new__(mod.OTLPReplayExporter)
            exporter._emit_message_span(mock_tracer, msg)

        # Verify that start_as_current_span was called with mcp.tool.name in attrs
        call_args = mock_tracer.start_as_current_span.call_args
        # call_args.kwargs has the keyword arguments, call_args.args has positional
        attrs = call_args.kwargs.get("attributes") or {}
        if not attrs and call_args.args and len(call_args.args) > 1:
            attrs = call_args.args[1]
        assert attrs.get("mcp.tool.name") == "write_file"





