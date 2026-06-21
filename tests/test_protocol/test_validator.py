import pytest
from unittest.mock import AsyncMock
from mcp_debugger.protocol.validator import ProtocolValidator
from mcp_debugger.storage.database import Database


def test_validator_message_jsonrpc_version() -> None:
    """Verify that validator flags invalid JSON-RPC version."""
    validator = ProtocolValidator()
    res = validator.validate_message(
        {"jsonrpc": "1.0", "id": 1, "method": "tools/list"}, "client_to_server"
    )
    assert len(res) == 1
    assert not res[0].passed
    assert res[0].severity == "critical"
    assert res[0].rule_name == "jsonrpc_version"


def test_validator_message_missing_id() -> None:
    """Verify that validator flags requests/responses that lack envelope structure."""
    validator = ProtocolValidator()
    res = validator.validate_message({"jsonrpc": "2.0"}, "client_to_server")
    assert len(res) == 1
    assert not res[0].passed
    assert res[0].severity == "critical"
    assert res[0].rule_name == "envelope_type"


def test_validator_message_valid_request() -> None:
    """Verify that validator accepts a valid request envelope."""
    validator = ProtocolValidator()
    res = validator.validate_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "client_to_server"
    )
    assert len(res) == 1
    assert res[0].passed
    assert res[0].rule_name == "message_compliance"


def test_validator_message_unknown_method() -> None:
    """Verify that validator warns on unrecognized method names under permissive mode."""
    validator = ProtocolValidator()
    res = validator.validate_message(
        {"jsonrpc": "2.0", "id": 1, "method": "custom/extension"}, "client_to_server"
    )
    assert len(res) == 1
    assert not res[0].passed
    assert res[0].severity == "warning"
    assert res[0].rule_name == "method_name"
    assert "not recognized" in res[0].message


def test_validator_message_typo_correction() -> None:
    """Verify that validator suggests corrections for common spelling errors in method names."""
    validator = ProtocolValidator()
    res = validator.validate_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tool/list"}, "client_to_server"
    )
    assert len(res) == 1
    assert not res[0].passed
    assert res[0].severity == "warning"
    assert res[0].rule_name == "method_name"
    assert res[0].suggestion == "Did you mean 'tools/list'?"


def test_validator_message_tool_schema_validation() -> None:
    """Verify that validator evaluates tool inputSchema definitions correctly."""
    validator = ProtocolValidator()

    # 1. Valid tool schema
    valid_resp = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {
                    "name": "my_tool",
                    "description": "desc",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"param1": {"type": "string"}},
                    },
                }
            ]
        },
    }
    res = validator.validate_message(valid_resp, "server_to_client")
    assert len(res) == 1
    assert res[0].passed
    assert res[0].rule_name == "message_compliance"

    # 2. Invalid tool schema (e.g. invalid type representation in JSON Schema)
    invalid_resp = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {
                    "name": "my_tool",
                    "description": "desc",
                    "inputSchema": {
                        "type": ["invalid_type_array"]  # Invalid schema type array configuration
                    },
                }
            ]
        },
    }
    res2 = validator.validate_message(invalid_resp, "server_to_client")
    assert len(res2) >= 1
    assert any(not r.passed and r.rule_name == "tool_schema_validity" for r in res2)


@pytest.mark.asyncio
async def test_validator_session_handshake_order() -> None:
    """Verify that session handshake sequence rules are correctly checked."""
    validator = ProtocolValidator()
    db = AsyncMock(spec=Database)
    db.get_session.return_value = {"id": 1, "status": "running"}

    # 1. Out of order handshake (tools/list called first)
    db.get_messages.return_value = [
        {
            "message_id": "1",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "tools/list",
            "params": None,
            "result": None,
            "error": None,
        }
    ]
    res = await validator.validate_session(1, db)
    assert any(not r.passed and r.rule_name == "initialize_first" for r in res)

    # 2. Correct handshake sequence
    db.get_messages.return_value = [
        {
            "message_id": "1",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "initialize",
            "params": '{"protocolVersion":"2025-03-26"}',
            "result": None,
            "error": None,
        },
        {
            "message_id": "1",
            "direction": "server_to_client",
            "message_type": "response",
            "method": "initialize",
            "params": None,
            "result": '{"protocolVersion":"2025-03-26", "capabilities": {}}',
            "error": None,
        },
        {
            "message_id": None,
            "direction": "client_to_server",
            "message_type": "notification",
            "method": "notifications/initialized",
            "params": None,
            "result": None,
            "error": None,
        },
    ]
    res2 = await validator.validate_session(1, db)
    assert len(res2) == 1
    assert res2[0].passed
    assert res2[0].rule_name == "session_compliance"


@pytest.mark.asyncio
async def test_validator_session_capability_alignment() -> None:
    """Verify that server capability warnings are generated if requesting undeclared support."""
    validator = ProtocolValidator()
    db = AsyncMock(spec=Database)
    db.get_session.return_value = {"id": 1, "status": "running"}

    # Server initialize response declares empty capabilities (no tools)
    # But client still sends tools/list request
    db.get_messages.return_value = [
        {
            "message_id": "1",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "initialize",
            "params": '{"protocolVersion":"2025-03-26"}',
            "result": None,
            "error": None,
        },
        {
            "message_id": "1",
            "direction": "server_to_client",
            "message_type": "response",
            "method": "initialize",
            "params": None,
            "result": '{"protocolVersion":"2025-03-26", "capabilities": {}}',
            "error": None,
        },
        {
            "message_id": None,
            "direction": "client_to_server",
            "message_type": "notification",
            "method": "notifications/initialized",
            "params": None,
            "result": None,
            "error": None,
        },
        {
            "message_id": "2",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "tools/list",
            "params": None,
            "result": None,
            "error": None,
        },
    ]
    res = await validator.validate_session(1, db)
    assert any(not r.passed and r.rule_name == "capability_alignment" for r in res)


def test_validator_invalid_method_format() -> None:
    """Verify that validator flags invalid method name formats."""
    validator = ProtocolValidator()
    # method is empty or not string
    res = validator.validate_message({"jsonrpc": "2.0", "id": 1, "method": ""}, "client_to_server")
    assert any(not r.passed and r.rule_name == "method_format" for r in res)
    res2 = validator.validate_message(
        {"jsonrpc": "2.0", "id": 1, "method": 123}, "client_to_server"
    )
    assert any(not r.passed and r.rule_name == "method_format" for r in res2)


def test_validator_request_invalid_id_type() -> None:
    """Verify that request ID type must be integer or string."""
    validator = ProtocolValidator()
    res = validator.validate_message(
        {"jsonrpc": "2.0", "id": [1], "method": "tools/list"}, "client_to_server"
    )
    assert any(not r.passed and r.rule_name == "request_id_type" for r in res)


def test_validator_response_conflicts_and_id() -> None:
    """Verify that responses with conflicting fields or invalid ID type are flagged."""
    validator = ProtocolValidator()
    # both result and error
    res1 = validator.validate_message(
        {"jsonrpc": "2.0", "id": 1, "result": {}, "error": {}}, "server_to_client"
    )
    assert any(not r.passed and r.rule_name == "response_envelope" for r in res1)

    # neither result nor error
    res2 = validator.validate_message({"jsonrpc": "2.0", "id": 1}, "server_to_client")
    assert any(not r.passed and r.rule_name == "response_envelope" for r in res2)

    # invalid response ID type
    res3 = validator.validate_message(
        {"jsonrpc": "2.0", "id": [1], "result": {}}, "server_to_client"
    )
    assert any(not r.passed and r.rule_name == "response_id_type" for r in res3)


def test_validator_invalid_tool_definitions() -> None:
    """Verify that malformed tool definitions in tools/list response are flagged."""
    validator = ProtocolValidator()

    # Tool not a dictionary
    invalid_resp1 = {"jsonrpc": "2.0", "id": 1, "result": {"tools": ["not-a-dict"]}}
    res1 = validator.validate_message(invalid_resp1, "server_to_client")
    assert any(not r.passed and r.rule_name == "tool_format" for r in res1)

    # Tool missing name or invalid type
    invalid_resp2 = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"description": "desc"}]}}
    res2 = validator.validate_message(invalid_resp2, "server_to_client")
    assert any(not r.passed and r.rule_name == "tool_name" for r in res2)

    # Tool missing inputSchema
    invalid_resp3 = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "my_tool"}]}}
    res3 = validator.validate_message(invalid_resp3, "server_to_client")
    assert any(not r.passed and r.rule_name == "tool_input_schema" for r in res3)

    # Tool inputSchema not a dict
    invalid_resp4 = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": [{"name": "my_tool", "inputSchema": "not-a-dict"}]},
    }
    res4 = validator.validate_message(invalid_resp4, "server_to_client")
    assert any(not r.passed and r.rule_name == "tool_input_schema_format" for r in res4)


@pytest.mark.asyncio
async def test_validator_session_exist_checks() -> None:
    """Verify session validator returns errors for non-existent session or empty session."""
    validator = ProtocolValidator()
    db = AsyncMock(spec=Database)
    db.get_session.return_value = None

    res1 = await validator.validate_session(999, db)
    assert len(res1) == 1
    assert not res1[0].passed
    assert res1[0].rule_name == "session_exists"

    db.get_session.return_value = {"id": 1}
    db.get_messages.return_value = []

    res2 = await validator.validate_session(1, db)
    assert len(res2) == 1
    assert not res2[0].passed
    assert res2[0].rule_name == "session_messages"


@pytest.mark.asyncio
async def test_validator_session_handshake_errors() -> None:
    """Verify other out-of-order session handshakes are caught."""
    validator = ProtocolValidator()
    db = AsyncMock(spec=Database)
    db.get_session.return_value = {"id": 1, "status": "running"}

    # Case A: Request sent before initialize response was received
    db.get_messages.return_value = [
        {
            "message_id": "not-an-integer",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "initialize",
            "params": "{invalid-json}",
            "result": "{invalid-json}",
            "error": "{invalid-json}",
        },
        {
            "message_id": "2",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "tools/list",
        },
    ]
    resA = await validator.validate_session(1, db)
    assert any(
        not r.passed
        and r.message == "Client request 'tools/list' sent before server initialize response"
        for r in resA
    )

    # Case B: Request sent before notifications/initialized is sent
    db.get_messages.return_value = [
        {
            "message_id": "1",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "initialize",
        },
        {
            "message_id": "1",
            "direction": "server_to_client",
            "message_type": "response",
            "method": "initialize",
            "result": "{}",
        },
        {
            "message_id": "2",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "tools/list",
        },
    ]
    resB = await validator.validate_session(1, db)
    assert any(
        not r.passed
        and r.rule_name == "handshake_order"
        and "notifications/initialized" in r.message
        for r in resB
    )

    # Case C: Client sent notifications/initialized before initialize response was received
    db.get_messages.return_value = [
        {
            "message_id": "1",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "initialize",
        },
        {
            "message_id": None,
            "direction": "client_to_server",
            "message_type": "notification",
            "method": "notifications/initialized",
        },
    ]
    resC = await validator.validate_session(1, db)
    assert any(
        not r.passed
        and r.message
        == "Client sent 'notifications/initialized' before initialize response was received"
        for r in resC
    )

    # Case D: Client sent other notification before completing initialized handshake
    db.get_messages.return_value = [
        {
            "message_id": "1",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "initialize",
        },
        {
            "message_id": None,
            "direction": "client_to_server",
            "message_type": "notification",
            "method": "custom/notify",
        },
    ]
    resD = await validator.validate_session(1, db)
    assert any(
        not r.passed and "before completing initialized handshake" in r.message for r in resD
    )
