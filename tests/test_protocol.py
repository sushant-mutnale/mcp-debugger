"""Tests for the protocol schemas."""

import pytest
from pydantic import ValidationError

from mcp_debugger.protocol.schemas import JSONRPCRequest, JSONRPCResponse


def test_valid_request():
    """Verify that a valid JSON-RPC request is correctly parsed."""
    req = JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/list")
    assert req.jsonrpc == "2.0"
    assert req.id == 1
    assert req.method == "tools/list"
    assert req.params is None


def test_valid_request_with_params():
    """Verify that a valid JSON-RPC request with params is correctly parsed."""
    req = JSONRPCRequest(
        jsonrpc="2.0", id="req-123", method="tools/call", params={"name": "test"}
    )
    assert req.id == "req-123"
    assert req.params == {"name": "test"}


def test_invalid_jsonrpc_version():
    """Verify that an invalid jsonrpc version raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCRequest(jsonrpc="1.0", id=1, method="tools/list")  # type: ignore
    assert "jsonrpc" in str(exc_info.value)


def test_missing_id():
    """Verify that a missing id raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCRequest(jsonrpc="2.0", method="tools/list")  # type: ignore
    assert "id" in str(exc_info.value)


def test_empty_method():
    """Verify that an empty method name raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCRequest(jsonrpc="2.0", id=1, method="")
    assert "method" in str(exc_info.value)


def test_extra_fields_forbidden():
    """Verify that passing extra fields raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/list", extra_field="forbidden")  # type: ignore
    assert "extra_field" in str(exc_info.value)


def test_valid_response():
    """Verify that a valid JSON-RPC success response is parsed correctly."""
    resp = JSONRPCResponse(jsonrpc="2.0", id=1, result="success_payload")
    assert resp.jsonrpc == "2.0"
    assert resp.id == 1
    assert resp.result == "success_payload"


def test_valid_response_with_complex_result():
    """Verify that a response with a nested result dict is parsed correctly."""
    resp = JSONRPCResponse(jsonrpc="2.0", id="resp-456", result={"status": "ok", "count": 42})
    assert resp.id == "resp-456"
    assert resp.result == {"status": "ok", "count": 42}


def test_response_missing_result():
    """Verify that a missing result raises validation error."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCResponse(jsonrpc="2.0", id=1)  # type: ignore
    assert "result" in str(exc_info.value)


def test_response_extra_fields_forbidden():
    """Verify that extra fields on response are forbidden."""
    with pytest.raises(ValidationError) as exc_info:
        JSONRPCResponse(jsonrpc="2.0", id=1, result="ok", extra_val="invalid")  # type: ignore
    assert "extra_val" in str(exc_info.value)
