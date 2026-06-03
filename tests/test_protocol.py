"""Tests for the protocol schemas."""

import pytest
from pydantic import ValidationError

from mcp_debugger.protocol.schemas import (
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCErrorResponse,
    ErrorDetails,
    JSONRPCNotification,
)


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
