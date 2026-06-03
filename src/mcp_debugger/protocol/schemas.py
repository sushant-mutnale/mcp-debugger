"""Pydantic validation schemas for the MCP protocol."""

from typing import Any, Dict, Literal, Optional, Union
from pydantic import BaseModel, Field


class JSONRPCRequest(BaseModel):
    """Represents a standard JSON-RPC 2.0 Request message."""

    model_config = {
        "extra": "forbid",
    }

    jsonrpc: Literal["2.0"] = Field(
        default="2.0", description="Must be exactly '2.0'"
    )
    id: Union[int, str] = Field(
        ..., description="Request ID used to match request-response pairs"
    )
    method: str = Field(..., min_length=1, description="The MCP method being called")
    params: Optional[Dict[str, Union[str, int, float, bool, None, list, dict]]] = Field(
        default=None, description="Optional arguments associated with the method"
    )


class JSONRPCResponse(BaseModel):
    """Represents a successful JSON-RPC 2.0 Response message."""

    model_config = {
        "extra": "forbid",
    }

    jsonrpc: Literal["2.0"] = Field(
        default="2.0", description="Must be exactly '2.0'"
    )
    id: Union[int, str] = Field(
        ..., description="Must match the id of the original request"
    )
    result: Any = Field(..., description="The payload returned by the server on success")
