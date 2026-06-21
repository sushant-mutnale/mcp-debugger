import io
from mcp_debugger.analytics import SessionStats, ToolMetric
from mcp_debugger.exporters.markdown_exporter import MarkdownExporter

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
    total_messages=2,
    client_to_server_count=1,
    server_to_client_count=1,
    top_tools=[
        ToolMetric(name="read_file", calls=1, avg_latency_ms=80.0, error_rate=0.0, errors_count=0)
    ],
    errors_by_category={"protocol": 1},
    latency_min=50.0,
    latency_max=80.0,
    latency_avg=65.0,
    latency_trend=[50.0, 80.0],
    method_distribution={"initialize": 1},
    error_trend=[0, 0],
)


class TestMarkdownExporter:
    def test_markdown_sections_and_formatting(self) -> None:
        exporter = MarkdownExporter()
        buf = io.StringIO()
        exporter.export(SESSION, MESSAGES, TOOLS, ERRORS, STATS, buf)
        md = buf.getvalue()

        # Check main header
        assert "# MCP Session Report – test session" in md

        # Check sub headers
        assert "## Metadata" in md
        assert "## Summary" in md
        assert "## Tool Inventory" in md
        assert "## Errors" in md
        assert "## Message Log" in md

        # Assert key values are rendered in the tables
        assert "npx mcp-server" in md
        assert "completed" in md
        assert "read_file" in md
        assert "Method not found" in md
        assert "initialize" in md
        assert "→ server" in md
