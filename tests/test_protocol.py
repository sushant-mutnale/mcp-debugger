"""Tests for the protocol schemas."""

import pytest
from pydantic import ValidationError

from mcp_debugger.protocol.schemas import JSONRPCRequest


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
