import io
import json
from typing import Any, Dict

from mcp_debugger.analytics import SessionStats, ToolMetric
from mcp_debugger.exporters.json_exporter import JSONExporter

# Shared test fixtures for exporters
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
        assert isinstance(first["params"], dict)
        assert first["params"]["protocolVersion"] == "2025-03-26"
        assert isinstance(first["timestamp"], str)
        assert "T" in first["timestamp"]

    def test_tools_include_call_count_and_latency(self) -> None:
        doc = self._export()
        assert len(doc["tools"]) == 1
        tool = doc["tools"][0]
        assert tool["name"] == "read_file"
        assert tool["call_count"] == 1
        assert tool["avg_latency_ms"] == 80.0
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
        assert s["error_rate"] == 0.25
        assert s["tools_called"] == 1
        assert s["avg_latency_ms"] == 65.0

    def test_pretty_print_uses_indentation(self) -> None:
        exporter_pretty = JSONExporter(pretty=True)
        exporter_compact = JSONExporter(pretty=False)
        buf_p = io.StringIO()
        buf_c = io.StringIO()
        exporter_pretty.export(SESSION, MESSAGES, TOOLS, ERRORS, STATS, buf_p)
        exporter_compact.export(SESSION, MESSAGES, TOOLS, ERRORS, STATS, buf_c)
        assert len(buf_p.getvalue()) > len(buf_c.getvalue())
        assert json.loads(buf_p.getvalue())
        assert json.loads(buf_c.getvalue())

    def test_empty_messages_and_tools(self) -> None:
        exporter = JSONExporter()
        buf = io.StringIO()
        exporter.export(SESSION, [], [], [], STATS, buf)
        doc = json.loads(buf.getvalue())
        assert doc["messages"] == []
        assert doc["tools"] == []
        assert doc["errors"] == []
