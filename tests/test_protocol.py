"""Tests for the protocol schemas."""

import pytest
from pydantic import ValidationError

from mcp_debugger.protocol.schemas import (
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCErrorResponse,
    ErrorDetails,
    JSONRPCNotification,
    parse_jsonrpc_message,
)
from mcp_debugger.protocol.validator import ProtocolValidator


def test_valid_request() -> None:
    """Verify that a valid JSON-RPC request is correctly parsed."""
    req = JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/list")
    assert req.jsonrpc == "2.0"
    assert req.id == 1
    assert req.method == "tools/list"
    assert req.params is None


def test_valid_request_with_params() -> None:
    """Verify that a valid JSON-RPC request with params is correctly parsed."""
    req = JSONRPCRequest(jsonrpc="2.0", id="req-123", method="tools/call", params={"name": "test"})
    assert req.id == "req-123"
    assert req.params == {"name": "test"}


def test_invalid_jsonrpc_version() -> None:
    """Verify that an invalid jsonrpc version raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCRequest(jsonrpc="1.0", id=1, method="tools/list")  # type: ignore
    assert "jsonrpc" in str(exc_info.value)


def test_missing_id() -> None:
    """Verify that a missing id raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCRequest(jsonrpc="2.0", method="tools/list")  # type: ignore
    assert "id" in str(exc_info.value)


def test_empty_method() -> None:
    """Verify that an empty method name raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCRequest(jsonrpc="2.0", id=1, method="")
    assert "method" in str(exc_info.value)


def test_extra_fields_forbidden() -> None:
    """Verify that passing extra fields raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/list", extra_field="forbidden")  # type: ignore
    assert "extra_field" in str(exc_info.value)


def test_valid_response() -> None:
    """Verify that a valid JSON-RPC success response is parsed correctly."""
    resp = JSONRPCResponse(jsonrpc="2.0", id=1, result="success_payload")
    assert resp.jsonrpc == "2.0"
    assert resp.id == 1
    assert resp.result == "success_payload"


def test_valid_response_with_complex_result() -> None:
    """Verify that a response with a nested result dict is parsed correctly."""
    resp = JSONRPCResponse(jsonrpc="2.0", id="resp-456", result={"status": "ok", "count": 42})
    assert resp.id == "resp-456"
    assert resp.result == {"status": "ok", "count": 42}


def test_response_missing_result() -> None:
    """Verify that a missing result raises validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCResponse(jsonrpc="2.0", id=1)  # type: ignore
    assert "result" in str(exc_info.value)


def test_response_extra_fields_forbidden() -> None:
    """Verify that extra fields on response are forbidden."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCResponse(jsonrpc="2.0", id=1, result="ok", extra_val="invalid")  # type: ignore
    assert "extra_val" in str(exc_info.value)


def test_valid_error_response() -> None:
    """Verify that a valid JSON-RPC error response is parsed correctly."""
    err = ErrorDetails(code=-32601, message="Method not found", data={"trace": "some-trace"})
    resp = JSONRPCErrorResponse(jsonrpc="2.0", id=1, error=err)
    assert resp.jsonrpc == "2.0"
    assert resp.id == 1
    assert resp.error.code == -32601
    assert resp.error.message == "Method not found"
    assert resp.error.data == {"trace": "some-trace"}


def test_valid_error_response_with_null_id() -> None:
    """Verify that an error response with a null/None id is allowed (e.g. parse error)."""
    err = ErrorDetails(code=-32700, message="Parse error")
    resp = JSONRPCErrorResponse(jsonrpc="2.0", id=None, error=err)
    assert resp.id is None
    assert resp.error.code == -32700


def test_error_missing_details() -> None:
    """Verify that a missing error field raises validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCErrorResponse(jsonrpc="2.0", id=1)  # type: ignore
    assert "error" in str(exc_info.value)


def test_error_invalid_code_type() -> None:
    """Verify that a non-integer error code raises validation error."""
    with pytest.raises(ValidationError) as exc_info:
        ErrorDetails(code="not-int", message="Error")  # type: ignore
    assert "code" in str(exc_info.value)


def test_valid_notification() -> None:
    """Verify that a valid JSON-RPC notification is parsed correctly."""
    notif = JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")
    assert notif.jsonrpc == "2.0"
    assert notif.method == "notifications/initialized"
    assert notif.params is None


def test_valid_notification_with_params() -> None:
    """Verify that a notification with parameters is parsed correctly."""
    notif = JSONRPCNotification(
        jsonrpc="2.0", method="notifications/message", params={"level": "info", "message": "hello"}
    )
    assert notif.method == "notifications/message"
    assert notif.params == {"level": "info", "message": "hello"}


def test_notification_with_id_forbidden() -> None:
    """Verify that a notification containing an id fails validation."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized", id=1)  # type: ignore
    assert "id" in str(exc_info.value)


def test_notification_empty_method() -> None:
    """Verify that notification with empty method raises validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCNotification(jsonrpc="2.0", method="")
    assert "method" in str(exc_info.value)


def test_parse_jsonrpc_message() -> None:
    """Verify that parse_jsonrpc_message correctly parses different JSON-RPC payloads."""
    # 1. Request
    req = parse_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert isinstance(req, JSONRPCRequest)
    assert req.id == 1
    assert req.method == "tools/list"

    # 2. Response
    resp = parse_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "result": "ok"})
    assert isinstance(resp, JSONRPCResponse)
    assert resp.id == 1
    assert resp.result == "ok"

    # 3. Error Response
    err = parse_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -123, "message": "fail"}}
    )
    assert isinstance(err, JSONRPCErrorResponse)
    assert err.id == 1
    assert err.error.code == -123

    # 4. Notification
    notif = parse_jsonrpc_message({"jsonrpc": "2.0", "method": "notify"})
    assert isinstance(notif, JSONRPCNotification)
    assert notif.method == "notify"

    # 5. Invalid version
    with pytest.raises(ValueError, match="Invalid JSON-RPC version"):
        parse_jsonrpc_message({"jsonrpc": "1.0", "id": 1, "method": "test"})

    # 6. Response missing both result and error
    with pytest.raises(ValueError, match="Response must contain either 'result' or 'error'"):
        parse_jsonrpc_message({"jsonrpc": "2.0", "id": 1})

    # 7. Neither request, response, nor notification
    with pytest.raises(
        ValueError, match="Message is neither a request, response, nor notification"
    ):
        parse_jsonrpc_message({"jsonrpc": "2.0"})


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
    from unittest.mock import AsyncMock
    from mcp_debugger.storage.database import Database

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
    from unittest.mock import AsyncMock
    from mcp_debugger.storage.database import Database

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

