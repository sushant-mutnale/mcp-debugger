"""Pydantic validation schemas for the MCP protocol."""

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


class JSONRPCRequest(BaseModel):
    """Represents a standard JSON-RPC 2.0 Request message."""

    model_config = {
        "extra": "forbid",
    }

    jsonrpc: Literal["2.0"] = Field(default="2.0", description="Must be exactly '2.0'")
    id: Union[int, str] = Field(..., description="Request ID used to match request-response pairs")
    method: str = Field(..., min_length=1, description="The MCP method being called")
    params: Optional[Union[Dict[str, Any], List[Any]]] = Field(
        default=None, description="Optional arguments associated with the method"
    )


class JSONRPCResponse(BaseModel):
    """Represents a successful JSON-RPC 2.0 Response message."""

    model_config = {
        "extra": "forbid",
    }

    jsonrpc: Literal["2.0"] = Field(default="2.0", description="Must be exactly '2.0'")
    id: Union[int, str] = Field(..., description="Must match the id of the original request")
    result: Any = Field(..., description="The payload returned by the server on success")


class ErrorDetails(BaseModel):
    """Represents detailed error fields within a JSON-RPC error response."""

    model_config = {
        "extra": "forbid",
    }

    code: int = Field(..., description="Integer error code indicating the error type")
    message: str = Field(..., description="Short string summarizing the error")
    data: Optional[Any] = Field(default=None, description="Additional structured debug data")


class JSONRPCErrorResponse(BaseModel):
    """Represents a failed JSON-RPC 2.0 Response message."""

    model_config = {
        "extra": "forbid",
    }

    jsonrpc: Literal["2.0"] = Field(default="2.0", description="Must be exactly '2.0'")
    id: Optional[Union[int, str]] = Field(
        ..., description="Must match the id of the original request or be null/None"
    )
    error: ErrorDetails = Field(..., description="The structured error details")


class JSONRPCNotification(BaseModel):
    """Represents a JSON-RPC 2.0 Notification message."""

    model_config = {
        "extra": "forbid",
    }

    jsonrpc: Literal["2.0"] = Field(default="2.0", description="Must be exactly '2.0'")
    method: str = Field(..., min_length=1, description="The notification method name")
    params: Optional[Union[Dict[str, Any], List[Any]]] = Field(
        default=None, description="Optional arguments associated with the notification"
    )
