from datetime import UTC, datetime
import json
from unittest.mock import MagicMock, patch

import pytest

import mcp_debugger.exporters.otlp_exporter as mod_otlp
import mcp_debugger.exporters.otlp_replay_exporter as mod_replay
from mcp_debugger.replay.diff import DiffNode, DiffType
from mcp_debugger.replay.engine import ReplayedMessage, ReplayResult


class TestOTLPExporter:
    def test_import_error_when_sdk_missing(self) -> None:
        """OTLPExporter raises ImportError with helpful message when SDK absent."""
        original = mod_otlp._OTLP_AVAILABLE
        try:
            mod_otlp._OTLP_AVAILABLE = False
            with pytest.raises(ImportError, match="pip install"):
                mod_otlp.OTLPExporter()
        finally:
            mod_otlp._OTLP_AVAILABLE = original

    def test_export_returns_span_count(self) -> None:
        """export() returns the correct number of child spans."""
        session = {
            "id": 1,
            "friendly_name": "test-session",
            "server_command": "npx mcp-server",
            "status": "completed",
        }
        messages = [
            {
                "id": 101,
                "direction": "client_to_server",
                "method": "initialize",
                "timestamp": 1_718_020_800_000.0,
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
        ]

        mock_provider = MagicMock()
        mock_tracer = MagicMock()
        mock_root_span_ctx = MagicMock()
        mock_root_span_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_root_span_ctx.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_root_span_ctx

        with (
            patch.object(mod_otlp, "_OTLP_AVAILABLE", True),
            patch(
                "mcp_debugger.exporters.otlp_exporter.TracerProvider",
                return_value=mock_provider,
                create=True,
            ),
            patch(
                "mcp_debugger.exporters.otlp_exporter.OTLPSpanExporter",
                return_value=MagicMock(),
                create=True,
            ),
            patch(
                "mcp_debugger.exporters.otlp_exporter.BatchSpanProcessor",
                return_value=MagicMock(),
                create=True,
            ),
            patch("mcp_debugger.exporters.otlp_exporter.Resource", create=True) as mock_res,
        ):
            mock_res.create.return_value = MagicMock()
            mock_provider.get_tracer.return_value = mock_tracer

            exporter = mod_otlp.OTLPExporter()
            count = exporter.export(session, messages)

        # There are 2 messages, which are paired into 1 request-response pair
        assert count == 1

    def test_export_edge_cases(self) -> None:
        """Test OTLPExporter edge cases: errors, unmatched requests, tools/call parsing, etc."""
        # Helper to test _get_tool_name helper directly
        assert mod_otlp._get_tool_name(None) is None
        assert mod_otlp._get_tool_name('{"not-name": 1}') is None
        assert mod_otlp._get_tool_name("invalid-json") is None
        assert mod_otlp._get_tool_name('{"name": "hello_tool"}') == "hello_tool"

        session = {
            "id": 1,
            "friendly_name": "test-session",
            "server_command": "npx mcp-server",
            "status": "completed",
        }
        messages = [
            # 1. tools/call request (matched)
            {
                "id": 101,
                "direction": "client_to_server",
                "method": "tools/call",
                "timestamp": 1_718_020_800_000.0,
                "latency_ms": None,
                "params": '{"name": "my_tool"}',
                "message_type": "request",
                "message_id": "1",
            },
            # 2. tools/call response (isError)
            {
                "id": 102,
                "direction": "server_to_client",
                "method": "tools/call",
                "timestamp": 1_718_020_800_050.0,
                "latency_ms": 50.0,
                "params": None,
                "result": '{"isError": true}',
                "error": None,
                "message_type": "response",
                "message_id": "1",
            },
            # 3. Notification (no message_id or method type notification)
            {
                "id": 103,
                "direction": "client_to_server",
                "method": "notifications/initialized",
                "timestamp": 1_718_020_800_100.0,
                "message_type": "notification",
            },
            # 4. Request with message_id but no method (invalid or missing method)
            {
                "id": 104,
                "direction": "client_to_server",
                "timestamp": 1_718_020_800_200.0,
                "message_type": "request",
                "message_id": "2",
            },
            # 5. Response with error field
            {
                "id": 105,
                "direction": "server_to_client",
                "timestamp": 1_718_020_800_250.0,
                "message_type": "response",
                "message_id": "2",
                "error": '{"code": -32601, "message": "Method not found"}',
                "latency_ms": 10.0,
            },
            # 6. Unmatched request
            {
                "id": 106,
                "direction": "client_to_server",
                "method": "ping",
                "timestamp": 1_718_020_800_300.0,
                "message_type": "request",
                "message_id": "3",
            },
            # 7. Request with no message_id (line 138 path)
            {
                "id": 107,
                "direction": "client_to_server",
                "method": "ping",
                "timestamp": 1_718_020_800_400.0,
                "message_type": "request",
                "message_id": None,
            },
        ]

        mock_provider = MagicMock()
        mock_tracer = MagicMock()
        mock_root_span_ctx = MagicMock()
        mock_root_span_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_root_span_ctx.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_root_span_ctx

        with (
            patch.object(mod_otlp, "_OTLP_AVAILABLE", True),
            patch(
                "mcp_debugger.exporters.otlp_exporter.TracerProvider",
                return_value=mock_provider,
                create=True,
            ),
            patch(
                "mcp_debugger.exporters.otlp_exporter.OTLPSpanExporter",
                return_value=MagicMock(),
                create=True,
            ),
            patch(
                "mcp_debugger.exporters.otlp_exporter.BatchSpanProcessor",
                return_value=MagicMock(),
                create=True,
            ),
            patch("mcp_debugger.exporters.otlp_exporter.Resource", create=True) as mock_res,
        ):
            mock_res.create.return_value = MagicMock()
            mock_provider.get_tracer.return_value = mock_tracer

            exporter = mod_otlp.OTLPExporter()
            count = exporter.export(session, messages)

        # Expected:
        # pair 1: req (101) + resp (102) -> tools/call isError
        # pair 2: notification (103)
        # pair 3: req (104) + resp (105) -> error response
        # pair 4: unmatched request (106)
        # pair 5: request no msg_id (107)
        assert count == 5


class TestOTLPReplayExporter:
    def _make_result(
        self, matches: int, mismatches: int = 0, with_diff: bool = False
    ) -> ReplayResult:
        session_id = 42
        msgs = []
        for i in range(matches):
            msgs.append(
                ReplayedMessage(
                    original_message_id=100 + i,
                    method="ping",
                    request_sent={"id": 100 + i, "method": "ping"},
                    original_response={"id": 100 + i, "result": "pong"},
                    replayed_response={"id": 100 + i, "result": "pong"},
                    latency_ms=45.2,
                    matches=True,
                )
            )

        for j in range(mismatches):
            diff_nodes = []
            if with_diff:
                diff_nodes.append(
                    DiffNode(
                        path="result",
                        type=DiffType.CHANGED,
                        old_value="old",
                        new_value="new",
                        children=[],
                    )
                )

            msgs.append(
                ReplayedMessage(
                    original_message_id=200 + j,
                    method="tools/call",
                    request_sent={
                        "id": 200 + j,
                        "method": "tools/call",
                        "params": {"name": "read_file"},
                    },
                    original_response={
                        "id": 200 + j,
                        "result": {"content": [{"type": "text", "text": "old"}]},
                    },
                    replayed_response={
                        "id": 200 + j,
                        "result": {"content": [{"type": "text", "text": "new"}]},
                    },
                    latency_ms=99.9,
                    matches=False,
                    diff=diff_nodes if with_diff else None,
                    diff_text="result.tools[0].name: old → new" if with_diff else None,
                )
            )
            # Additional message to cover string/serialized params and error scenarios
            msgs.append(
                ReplayedMessage(
                    original_message_id=300 + j,
                    method="tools/call",
                    request_sent={
                        "id": 300 + j,
                        "method": "tools/call",
                        "params": '{"name": "string_param_tool"}',
                    },
                    original_response={"id": 300 + j, "result": "old"},
                    replayed_response=None,
                    latency_ms=0.0,
                    matches=False,
                    error="Timeout error occurred",
                )
            )

        return ReplayResult(
            replay_id=7,
            session_id=session_id,
            target_server_command="mock-server",
            started_at=datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC),
            ended_at=datetime(2025, 6, 15, 10, 0, 2, tzinfo=UTC),
            total_messages_replayed=matches + mismatches,
            successful_responses=matches,
            failed_responses=0,
            mismatched_responses=mismatches,
            timed_out=0,
            messages=msgs,
        )

    def test_import_error_when_sdk_missing(self) -> None:
        """OTLPReplayExporter raises ImportError with helpful message when SDK absent."""
        original = mod_replay._OTLP_AVAILABLE
        try:
            mod_replay._OTLP_AVAILABLE = False
            with pytest.raises(ImportError, match="pip install"):
                mod_replay.OTLPReplayExporter()
        finally:
            mod_replay._OTLP_AVAILABLE = original

    def test_export_returns_span_count(self) -> None:
        """export() returns the correct number of child spans."""
        result = self._make_result(matches=3)

        mock_provider = MagicMock()
        mock_tracer = MagicMock()
        mock_root_span_ctx = MagicMock()
        mock_root_span_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_root_span_ctx.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_root_span_ctx

        with (
            patch.object(mod_replay, "_OTLP_AVAILABLE", True),
            patch.object(mod_replay, "TracerProvider", return_value=mock_provider),
            patch.object(mod_replay, "OTLPSpanExporter", return_value=MagicMock()),
            patch.object(mod_replay, "BatchSpanProcessor", return_value=MagicMock()),
            patch.object(mod_replay, "Resource", MagicMock()) as mock_res,
        ):
            mock_res.create.return_value = MagicMock()
            mock_provider.get_tracer.return_value = mock_tracer

            exporter = mod_replay.OTLPReplayExporter()
            count = exporter.export(result)

        assert count == 3

    def test_export_all_matches_no_error_status(self) -> None:
        """Root span is not marked ERROR when all messages match."""
        result = self._make_result(matches=2, mismatches=0)

        mock_provider = MagicMock()
        mock_tracer = MagicMock()
        mock_root_span = MagicMock()
        mock_root_span_ctx = MagicMock()
        mock_root_span_ctx.__enter__ = MagicMock(return_value=mock_root_span)
        mock_root_span_ctx.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_root_span_ctx

        with (
            patch.object(mod_replay, "_OTLP_AVAILABLE", True),
            patch.object(mod_replay, "TracerProvider", return_value=mock_provider),
            patch.object(mod_replay, "OTLPSpanExporter", return_value=MagicMock()),
            patch.object(mod_replay, "BatchSpanProcessor", return_value=MagicMock()),
            patch.object(mod_replay, "Resource", MagicMock()) as mock_res,
        ):
            mock_res.create.return_value = MagicMock()
            mock_provider.get_tracer.return_value = mock_tracer

            exporter = mod_replay.OTLPReplayExporter()
            exporter.export(result)

        mock_root_span.set_status.assert_not_called()

    def test_export_with_mismatch_sets_error_status(self) -> None:
        """Root span is marked ERROR when there are mismatches."""
        result = self._make_result(matches=1, mismatches=1, with_diff=True)

        mock_provider = MagicMock()
        mock_tracer = MagicMock()
        mock_root_span = MagicMock()
        mock_root_span_ctx = MagicMock()
        mock_root_span_ctx.__enter__ = MagicMock(return_value=mock_root_span)
        mock_root_span_ctx.__exit__ = MagicMock(return_value=False)

        mock_child_span = MagicMock()
        mock_child_ctx = MagicMock()
        mock_child_ctx.__enter__ = MagicMock(return_value=mock_child_span)
        mock_child_ctx.__exit__ = MagicMock(return_value=False)

        mock_tracer.start_as_current_span.side_effect = [mock_root_span_ctx] + [mock_child_ctx] * 10

        with (
            patch.object(mod_replay, "_OTLP_AVAILABLE", True),
            patch.object(mod_replay, "TracerProvider", return_value=mock_provider),
            patch.object(mod_replay, "OTLPSpanExporter", return_value=MagicMock()),
            patch.object(mod_replay, "BatchSpanProcessor", return_value=MagicMock()),
            patch.object(mod_replay, "Resource", MagicMock()) as mock_res,
            patch.object(mod_replay, "Status", MagicMock()),
            patch.object(mod_replay, "StatusCode", MagicMock()),
        ):
            mock_res.create.return_value = MagicMock()
            mock_provider.get_tracer.return_value = mock_tracer

            exporter = mod_replay.OTLPReplayExporter()
            exporter.export(result)

        mock_root_span.set_status.assert_called_once()

    def test_replay_export_genai_semantic_conventions(self) -> None:
        """Replay exporter child spans follow {method} {target} and include gen_ai.* attributes."""
        result = self._make_result(matches=0, mismatches=1, with_diff=True)

        mock_provider = MagicMock()
        mock_tracer = MagicMock()
        mock_root_span = MagicMock()
        mock_root_span_ctx = MagicMock()
        mock_root_span_ctx.__enter__ = MagicMock(return_value=mock_root_span)
        mock_root_span_ctx.__exit__ = MagicMock(return_value=False)

        mock_child_span = MagicMock()
        mock_child_ctx = MagicMock()
        mock_child_ctx.__enter__ = MagicMock(return_value=mock_child_span)
        mock_child_ctx.__exit__ = MagicMock(return_value=False)

        mock_tracer.start_as_current_span.side_effect = [mock_root_span_ctx] + [mock_child_ctx] * 10

        with (
            patch.object(mod_replay, "_OTLP_AVAILABLE", True),
            patch.object(mod_replay, "TracerProvider", return_value=mock_provider),
            patch.object(mod_replay, "OTLPSpanExporter", return_value=MagicMock()),
            patch.object(mod_replay, "BatchSpanProcessor", return_value=MagicMock()),
            patch.object(mod_replay, "Resource", MagicMock()) as mock_res,
            patch.object(mod_replay, "Status", MagicMock()),
            patch.object(mod_replay, "StatusCode", MagicMock()),
        ):
            mock_res.create.return_value = MagicMock()
            mock_provider.get_tracer.return_value = mock_tracer

            exporter = mod_replay.OTLPReplayExporter()
            exporter.export(result)

        calls = mock_tracer.start_as_current_span.call_args_list
        # First call is root span
        root_name = calls[0].kwargs.get("name") or calls[0].args[0]
        assert root_name == f"mcp.replay session-{result.session_id}"
        # Second call is child span for read_file
        child_span_name = calls[1].args[0] if calls[1].args else calls[1].kwargs.get("name")
        assert child_span_name == "tools/call read_file"
        child_attrs = calls[1].kwargs["attributes"]
        assert child_attrs["gen_ai.system"] == "mcp"
        assert child_attrs["gen_ai.operation.name"] == "execute_tool"
        assert child_attrs["gen_ai.tool.name"] == "read_file"
        assert child_attrs["mcp.tool.name"] == "read_file"


class TestGenAISemanticConventions:
    def test_extract_target(self) -> None:
        """Target extraction for tools, resources, prompts, and untargeted methods."""
        assert mod_otlp._extract_target("tools/call", {"name": "echo"}) == "echo"
        assert mod_otlp._extract_target("tools/call", '{"name": "get_sum"}') == "get_sum"
        assert mod_otlp._extract_target("tools/call", None) is None
        assert mod_otlp._extract_target("tools/call", "invalid json") is None

        assert (
            mod_otlp._extract_target("resources/read", {"uri": "file:///tmp/log.txt"})
            == "file:///tmp/log.txt"
        )
        assert (
            mod_otlp._extract_target("resources/subscribe", '{"uri": "postgres://db/table"}')
            == "postgres://db/table"
        )
        assert mod_otlp._extract_target("prompts/get", {"name": "summarizer"}) == "summarizer"
        assert mod_otlp._extract_target("tools/list", None) is None
        assert mod_otlp._extract_target("initialize", {"protocolVersion": "2025-03-26"}) is None

    def test_extract_genai_attributes(self) -> None:
        """Extraction of gen_ai.* attributes (system, model, tokens, operation)."""
        params = {
            "name": "calc",
            "_meta": {
                "model": "gpt-4o",
            },
        }
        result = {
            "content": [{"type": "text", "text": "42"}],
            "_meta": {
                "model": "gpt-4o-2024-08-06",
                "usage": {
                    "input_tokens": 15,
                    "output_tokens": 5,
                    "total_tokens": 20,
                },
            },
        }
        attrs = mod_otlp._extract_genai_attributes(
            method="tools/call",
            params=params,
            result=result,
            message_id="msg-42",
        )
        assert attrs["gen_ai.system"] == "mcp"
        assert attrs["gen_ai.operation.name"] == "execute_tool"
        assert attrs["gen_ai.tool.name"] == "calc"
        assert attrs["gen_ai.tool.call.id"] == "msg-42"
        assert attrs["gen_ai.request.model"] == "gpt-4o"
        assert attrs["gen_ai.response.model"] == "gpt-4o-2024-08-06"
        assert attrs["gen_ai.usage.input_tokens"] == 15
        assert attrs["gen_ai.usage.output_tokens"] == 5
        assert attrs["gen_ai.usage.total_tokens"] == 20

    def test_export_spans_genai_format(self) -> None:
        """OTLPExporter emits span names with {mcp.method.name} {target} and gen_ai attributes."""
        session = {
            "id": 10,
            "friendly_name": "ai-session",
            "server_command": "mcp-server",
            "status": "completed",
            "protocol_version": "2026-07-28",
            "server_info": '{"capabilities": {"tools": {"listChanged": true}}}',
        }
        messages = [
            {
                "id": 1,
                "message_id": "call-1",
                "direction": "client_to_server",
                "method": "tools/call",
                "timestamp": 1_000.0,
                "latency_ms": None,
                "params": '{"name": "echo", "_meta": {"model": "claude-3-5-sonnet"}}',
                "message_type": "request",
            },
            {
                "id": 2,
                "message_id": "call-1",
                "direction": "server_to_client",
                "method": "tools/call",
                "timestamp": 1_050.0,
                "latency_ms": 50.0,
                "params": None,
                "result": json.dumps(
                    {
                        "content": [{"type": "text", "text": "hello"}],
                        "_meta": {
                            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}
                        },
                    }
                ),
                "error": None,
                "message_type": "response",
            },
            {
                "id": 3,
                "message_id": "call-2",
                "direction": "client_to_server",
                "method": "tools/list",
                "timestamp": 1_100.0,
                "params": None,
                "message_type": "request",
            },
            {
                "id": 4,
                "message_id": "call-2",
                "direction": "server_to_client",
                "method": "tools/list",
                "timestamp": 1_120.0,
                "latency_ms": 20.0,
                "result": '{"tools": []}',
                "message_type": "response",
            },
        ]

        mock_provider = MagicMock()
        mock_tracer = MagicMock()
        mock_span_ctx = MagicMock()
        mock_span_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_span_ctx.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_span_ctx

        with (
            patch.object(mod_otlp, "_OTLP_AVAILABLE", True),
            patch("mcp_debugger.exporters.otlp_exporter.TracerProvider", return_value=mock_provider, create=True),
            patch("mcp_debugger.exporters.otlp_exporter.OTLPSpanExporter", return_value=MagicMock(), create=True),
            patch("mcp_debugger.exporters.otlp_exporter.BatchSpanProcessor", return_value=MagicMock(), create=True),
            patch("mcp_debugger.exporters.otlp_exporter.Resource", create=True) as mock_res,
        ):
            mock_res.create.return_value = MagicMock()
            mock_provider.get_tracer.return_value = mock_tracer

            exporter = mod_otlp.OTLPExporter()
            count = exporter.export(session, messages)

        assert count == 2
        calls = mock_tracer.start_as_current_span.call_args_list
        # call 0: root span
        assert calls[0].kwargs["name"] == "mcp-session ai-session"
        root_attrs = calls[0].kwargs["attributes"]
        assert root_attrs["gen_ai.system"] == "mcp"
        assert root_attrs["mcp.protocol_version"] == "2026-07-28"
        assert "tools" in root_attrs["mcp.capabilities"]

        # call 1: tools/call echo span
        tool_call_span_name = calls[1].args[0]
        assert tool_call_span_name == "tools/call echo"
        tool_attrs = calls[1].kwargs["attributes"]
        assert tool_attrs["gen_ai.system"] == "mcp"
        assert tool_attrs["gen_ai.operation.name"] == "execute_tool"
        assert tool_attrs["gen_ai.tool.name"] == "echo"
        assert tool_attrs["gen_ai.tool.call.id"] == "call-1"
        assert tool_attrs["gen_ai.request.model"] == "claude-3-5-sonnet"
        assert tool_attrs["gen_ai.usage.input_tokens"] == 10
        assert tool_attrs["gen_ai.usage.output_tokens"] == 20
        assert tool_attrs["gen_ai.usage.total_tokens"] == 30

        # call 2: tools/list span (untargeted method)
        list_span_name = calls[2].args[0]
        assert list_span_name == "tools/list"

