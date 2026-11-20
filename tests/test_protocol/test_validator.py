import json
from unittest.mock import AsyncMock

import pytest

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


def test_detect_dialect_stateful() -> None:
    """Verify that a session starting with initialize is detected as 2025-03-26 stateful dialect."""
    validator = ProtocolValidator()
    messages = [
        {
            "direction": "client_to_server",
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        }
    ]
    dialect = validator.detect_dialect(messages)
    assert dialect == "2025-03-26"


def test_detect_dialect_stateless() -> None:
    """Verify that a session with _meta protocolVersion or server/discover is detected as 2026-07-28."""
    validator = ProtocolValidator()
    # Case 1: _meta with SEP-2575 URI
    messages1 = [
        {
            "direction": "client_to_server",
            "method": "tools/list",
            "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}},
        }
    ]
    assert validator.detect_dialect(messages1) == "2026-07-28"

    # Case 2: server/discover RPC
    messages2 = [{"direction": "client_to_server", "method": "server/discover"}]
    assert validator.detect_dialect(messages2) == "2026-07-28"


@pytest.mark.asyncio
async def test_validate_session_stateless_valid() -> None:
    """Verify that a stateless session without initialize passes without handshake errors."""
    validator = ProtocolValidator()
    db = AsyncMock(spec=Database)
    db.get_session.return_value = {"id": 1, "protocol_version": None}
    db.get_messages.return_value = [
        {
            "message_id": "1",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "tools/list",
            "params": json.dumps(
                {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientInfo": {"name": "agent-x", "version": "0.1"},
                    }
                }
            ),
        },
        {
            "message_id": "1",
            "direction": "server_to_client",
            "message_type": "response",
            "method": "tools/list",
            "result": json.dumps({"tools": []}),
        },
    ]

    results = await validator.validate_session(1, db)
    # Should NOT have initialize_first or handshake_order failures
    failed_rules = [r.rule_name for r in results if not r.passed]
    assert "initialize_first" not in failed_rules
    assert "handshake_order" not in failed_rules


@pytest.mark.asyncio
async def test_validate_session_stateless_missing_meta() -> None:
    """Verify that in a stateless session, requests missing _meta declaration fail validation."""
    validator = ProtocolValidator()
    db = AsyncMock(spec=Database)
    db.get_session.return_value = {"id": 1, "protocol_version": "2026-07-28"}
    db.get_messages.return_value = [
        {
            "message_id": "1",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "tools/list",
            "params": "{}",
        }
    ]

    results = await validator.validate_session(1, db)
    assert any(not r.passed and r.rule_name == "stateless_meta_declaration" for r in results)


def test_validator_server_discover_valid_response() -> None:
    """Verify that validator passes a compliant server/discover response."""
    validator = ProtocolValidator()
    valid_discover_resp = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "supportedVersions": ["2026-07-28", "2025-03-26"],
            "capabilities": {"tools": {}, "prompts": {}},
            "serverInfo": {"name": "test-discover-server", "version": "1.0.0"},
            "instructions": "Use tools wisely.",
        },
    }
    results = validator.validate_message(valid_discover_resp, "server_to_client")
    assert any(r.passed and r.rule_name == "server_discover_schema" for r in results)


def test_validator_server_discover_invalid_response() -> None:
    """Verify that validator rejects non-compliant server/discover response missing required fields."""
    validator = ProtocolValidator()
    # Missing serverInfo and invalid supportedVersions type
    invalid_discover_resp = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "supportedVersions": "not-a-list",
            "capabilities": "not-a-dict",
        },
    }
    results = validator.validate_message(invalid_discover_resp, "server_to_client")
    failed = [r for r in results if not r.passed and r.rule_name == "server_discover_schema"]
    assert len(failed) > 0
    assert failed[0].severity == "critical"


def test_validator_subscriptions_listen_valid_request() -> None:
    """Verify that subscriptions/listen request with a list of topics passes validation."""
    validator = ProtocolValidator()
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "subscriptions/listen",
        "params": {
            "subscriptions": ["toolsListChanged", "promptsListChanged"],
            "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"},
        },
    }
    results = validator.validate_message(msg, "client_to_server")
    assert any(r.passed and r.rule_name == "subscriptions_listen_schema" for r in results)


@pytest.mark.asyncio
async def test_validator_unsolicited_notification_warning() -> None:
    """Verify that server notification of an unrequested topic triggers a warning."""
    validator = ProtocolValidator()
    db = AsyncMock(spec=Database)
    db.get_session.return_value = {"id": 1, "protocol_version": "2026-07-28"}
    db.get_messages.return_value = [
        # Client subscribes only to toolsListChanged
        {
            "message_id": "1",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "subscriptions/listen",
            "params": json.dumps(
                {
                    "subscriptions": ["toolsListChanged"],
                    "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"},
                }
            ),
        },
        # Server sends an unrequested prompts notification
        {
            "message_id": None,
            "direction": "server_to_client",
            "message_type": "notification",
            "method": "notifications/prompts/list-changed",
            "params": "{}",
        },
    ]

    results = await validator.validate_session(1, db)
    warnings = [r for r in results if not r.passed and r.rule_name == "unsolicited_notification"]
    assert len(warnings) == 1
    assert "notifications/prompts/list-changed" in warnings[0].message


@pytest.mark.asyncio
async def test_validator_solicited_notification_pass() -> None:
    """Verify that subscribed notification topics do not trigger unsolicited warnings."""
    validator = ProtocolValidator()
    db = AsyncMock(spec=Database)
    db.get_session.return_value = {"id": 1, "protocol_version": "2026-07-28"}
    db.get_messages.return_value = [
        # Client subscribes to toolsListChanged
        {
            "message_id": "1",
            "direction": "client_to_server",
            "message_type": "request",
            "method": "subscriptions/listen",
            "params": json.dumps(
                {
                    "subscriptions": ["toolsListChanged"],
                    "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"},
                }
            ),
        },
        # Server sends subscribed tools notification
        {
            "message_id": None,
            "direction": "server_to_client",
            "message_type": "notification",
            "method": "notifications/tools/list-changed",
            "params": "{}",
        },
    ]

    results = await validator.validate_session(1, db)
    warnings = [r for r in results if not r.passed and r.rule_name == "unsolicited_notification"]
    assert len(warnings) == 0


def test_validator_unsupported_protocol_version_error() -> None:
    """Verify that validator flags UnsupportedProtocolVersionError (-32003) as critical failure."""
    validator = ProtocolValidator()
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -32003,
            "message": "Unsupported protocol version",
        },
    }
    results = validator.validate_message(msg, "server_to_client")
    crit = [r for r in results if not r.passed and r.severity == "critical"]
    assert len(crit) == 1
    assert crit[0].rule_name == "stateless_protocol_version"
    assert "server/discover" in crit[0].suggestion
    assert "_meta.protocolVersion" in crit[0].suggestion


def test_validator_missing_client_capability_error() -> None:
    """Verify that validator flags MissingRequiredClientCapabilityError (-32004) with missing capability."""
    validator = ProtocolValidator()
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -32004,
            "message": "Missing required client capability: roots",
        },
    }
    results = validator.validate_message(msg, "server_to_client")
    crit = [r for r in results if not r.passed and r.severity == "critical"]
    assert len(crit) == 1
    assert crit[0].rule_name == "stateless_client_capability"
    assert "roots" in crit[0].suggestion
    assert "_meta.clientCapabilities" in crit[0].suggestion
