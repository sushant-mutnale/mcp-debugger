"""Protocol compliance validator for MCP messages and sessions."""

import json
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

import jsonschema

from mcp_debugger.storage.database import Database


class ValidationResult(BaseModel):
    """Represents the outcome of a single protocol compliance check."""

    rule_name: str = Field(..., description="Unique identifier for the compliance rule")
    passed: bool = Field(..., description="Whether the check succeeded")
    severity: str = Field(..., description="Severity level: 'critical', 'warning', or 'info'")
    message: str = Field(..., description="Human-readable explanation of the validation result")
    suggestion: Optional[str] = Field(default=None, description="Optional remediation advice")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Contextual message payload")


class ProtocolValidator:
    """Validator engine for ensuring MCP specification compliance."""

    STANDARD_METHODS: Set[str] = {
        # Client -> Server requests
        "initialize",
        "tools/list",
        "tools/call",
        "resources/list",
        "resources/templates/list",
        "resources/read",
        "prompts/list",
        "prompts/get",
        "logging/setLevel",
        # Client -> Server notifications
        "notifications/initialized",
        "notifications/cancelled",
        "notifications/progress",
        "notifications/roots/list-changed",
        # Server -> Client requests
        "roots/list",
        # Server -> Client notifications
        "notifications/message",
        "notifications/resources/list-changed",
        "notifications/tools/list-changed",
        "notifications/prompts/list-changed",
        # Bi-directional requests
        "ping",
    }

    TYPO_CORRECTIONS: Dict[str, str] = {
        "tool/list": "tools/list",
        "tool/call": "tools/call",
        "tools/list-changed": "notifications/tools/list-changed",
        "resources/list-changed": "notifications/resources/list-changed",
        "prompts/list-changed": "notifications/prompts/list-changed",
        "roots/list-changed": "notifications/roots/list-changed",
        "initialized": "notifications/initialized",
    }

    CAPABILITY_REQUIRED_FOR_METHOD: Dict[str, str] = {
        "tools/list": "tools",
        "tools/call": "tools",
        "resources/list": "resources",
        "resources/templates/list": "resources",
        "resources/read": "resources",
        "prompts/list": "prompts",
        "prompts/get": "prompts",
        "logging/setLevel": "logging",
    }

    def __init__(self, protocol_version: str = "2025-03-26"):
        self.version = protocol_version

    def validate_message(
        self, message: Dict[str, Any], direction: str, context: Optional[Dict[str, Any]] = None
    ) -> List[ValidationResult]:
        """Validate a single MCP message envelope and payload in isolation."""
        results: List[ValidationResult] = []

        # 1. Check JSON-RPC version
        jsonrpc = message.get("jsonrpc")
        if jsonrpc != "2.0":
            results.append(
                ValidationResult(
                    rule_name="jsonrpc_version",
                    passed=False,
                    severity="critical",
                    message=f"JSON-RPC version must be exactly '2.0', got {repr(jsonrpc)}",
                    suggestion="Set the 'jsonrpc' field value to '2.0'",
                    context=message,
                )
            )

        method = message.get("method")
        msg_id = message.get("id")
        has_id = "id" in message
        has_method = "method" in message

        is_response = False

        if has_method:
            if not isinstance(method, str) or not method:
                results.append(
                    ValidationResult(
                        rule_name="method_format",
                        passed=False,
                        severity="critical",
                        message="Method name must be a non-empty string",
                        context=message,
                    )
                )
            if has_id:
                if not isinstance(msg_id, (int, str)):
                    results.append(
                        ValidationResult(
                            rule_name="request_id_type",
                            passed=False,
                            severity="critical",
                            message=f"Request ID must be an integer or string, got {type(msg_id).__name__}",
                            context=message,
                        )
                    )
            # Notification if no id
        elif has_id:
            is_response = True
            has_result = "result" in message
            has_error = "error" in message

            if has_result and has_error:
                results.append(
                    ValidationResult(
                        rule_name="response_envelope",
                        passed=False,
                        severity="critical",
                        message="Response must contain either 'result' or 'error', not both",
                        context=message,
                    )
                )
            elif not has_result and not has_error:
                results.append(
                    ValidationResult(
                        rule_name="response_envelope",
                        passed=False,
                        severity="critical",
                        message="Response must contain either 'result' or 'error'",
                        context=message,
                    )
                )

            if msg_id is not None and not isinstance(msg_id, (int, str)):
                results.append(
                    ValidationResult(
                        rule_name="response_id_type",
                        passed=False,
                        severity="critical",
                        message=f"Response ID must be an integer, string, or null, got {type(msg_id).__name__}",
                        context=message,
                    )
                )
        else:
            results.append(
                ValidationResult(
                    rule_name="envelope_type",
                    passed=False,
                    severity="critical",
                    message="Message must be a Request (method and id), Response (id), or Notification (method)",
                    context=message,
                )
            )

        # 2. Check method name syntax and spelling
        if has_method and isinstance(method, str) and method:
            if method not in self.STANDARD_METHODS:
                if method in self.TYPO_CORRECTIONS:
                    correction = self.TYPO_CORRECTIONS[method]
                    results.append(
                        ValidationResult(
                            rule_name="method_name",
                            passed=False,
                            severity="warning",
                            message=f"Method '{method}' is not a standard MCP method",
                            suggestion=f"Did you mean '{correction}'?",
                            context=message,
                        )
                    )
                else:
                    results.append(
                        ValidationResult(
                            rule_name="method_name",
                            passed=False,
                            severity="warning",
                            message=f"Method '{method}' is not recognized in standard MCP spec (custom methods allowed in permissive mode)",
                            context=message,
                        )
                    )

        # 3. Check tool definitions in tools/list response result
        if is_response and isinstance(message.get("result"), dict):
            result_dict = message["result"]
            if "tools" in result_dict:
                tools_list = result_dict["tools"]
                if isinstance(tools_list, list):
                    for i, t in enumerate(tools_list):
                        if not isinstance(t, dict):
                            results.append(
                                ValidationResult(
                                    rule_name="tool_format",
                                    passed=False,
                                    severity="critical",
                                    message=f"Tool definition at index {i} must be a dictionary object",
                                    context=message,
                                )
                            )
                            continue
                        tool_name = t.get("name")
                        if not isinstance(tool_name, str) or not tool_name:
                            results.append(
                                ValidationResult(
                                    rule_name="tool_name",
                                    passed=False,
                                    severity="critical",
                                    message=f"Tool definition at index {i} is missing a valid 'name' property",
                                    context=message,
                                )
                            )

                        input_schema = t.get("inputSchema")
                        if input_schema is None:
                            results.append(
                                ValidationResult(
                                    rule_name="tool_input_schema",
                                    passed=False,
                                    severity="critical",
                                    message=f"Tool '{tool_name or i}' is missing the required 'inputSchema' property",
                                    context=message,
                                )
                            )
                        elif not isinstance(input_schema, dict):
                            results.append(
                                ValidationResult(
                                    rule_name="tool_input_schema_format",
                                    passed=False,
                                    severity="critical",
                                    message=f"Tool '{tool_name or i}' inputSchema must be a JSON object",
                                    context=message,
                                )
                            )
                        else:
                            try:
                                jsonschema.Draft7Validator.check_schema(input_schema)
                            except Exception as schema_err:
                                results.append(
                                    ValidationResult(
                                        rule_name="tool_schema_validity",
                                        passed=False,
                                        severity="critical",
                                        message=f"Tool '{tool_name or i}' inputSchema is not a valid JSON schema: {schema_err}",
                                        suggestion="Ensure inputSchema matches Draft-07 format standards",
                                        context=message,
                                    )
                                )

        # If no checks failed, insert a generic passed check
        if not results:
            results.append(
                ValidationResult(
                    rule_name="message_compliance",
                    passed=True,
                    severity="info",
                    message="Message is compliant with standard envelopes",
                    context=message,
                )
            )

        return results

    async def validate_session(self, session_id: int, db: Database) -> List[ValidationResult]:
        """Validate the entire chronological sequence of logged messages for a session."""
        session = await db.get_session(session_id)
        if not session:
            return [
                ValidationResult(
                    rule_name="session_exists",
                    passed=False,
                    severity="critical",
                    message=f"Session #{session_id} not found in database",
                )
            ]

        rows = await db.get_messages(session_id)
        if not rows:
            return [
                ValidationResult(
                    rule_name="session_messages",
                    passed=False,
                    severity="warning",
                    message=f"Session #{session_id} exists but contains no recorded messages",
                )
            ]

        results: List[ValidationResult] = []

        initialized_handshake_started = False
        initialized_handshake_responded = False
        initialized_notification_sent = False

        negotiated_server_capabilities: Dict[str, Any] = {}
        initialize_request_id: Optional[Any] = None

        for row in rows:
            # Reconstruct message dictionary from DB fields
            msg_dict: Dict[str, Any] = {
                "jsonrpc": "2.0",
            }
            if row.get("message_id") is not None:
                mid = row["message_id"]
                try:
                    msg_dict["id"] = int(mid)
                except ValueError:
                    msg_dict["id"] = mid

            if row.get("method") is not None:
                msg_dict["method"] = row["method"]

            if row.get("params") is not None:
                try:
                    msg_dict["params"] = json.loads(row["params"])
                except Exception:
                    pass

            if row.get("result") is not None:
                try:
                    msg_dict["result"] = json.loads(row["result"])
                except Exception:
                    pass

            if row.get("error") is not None:
                try:
                    msg_dict["error"] = json.loads(row["error"])
                except Exception:
                    pass

            direction = row.get("direction", "client_to_server")
            message_type = row.get("message_type")
            method = msg_dict.get("method")

            # 1. Run single-message isolation check
            msg_results = self.validate_message(msg_dict, direction)
            # Add failures/warnings from isolation checks (filter out the generic compliance pass)
            for r in msg_results:
                if not r.passed:
                    results.append(r)

            # 2. Handshake ordering & capability compliance
            if direction == "client_to_server":
                if message_type == "request":
                    if method == "initialize":
                        initialized_handshake_started = True
                        initialize_request_id = msg_dict.get("id")
                    else:
                        if not initialized_handshake_started:
                            results.append(
                                ValidationResult(
                                    rule_name="initialize_first",
                                    passed=False,
                                    severity="critical",
                                    message=f"First request from client was '{method}', expected 'initialize'",
                                    suggestion="Ensure client invokes 'initialize' request before any other command",
                                    context=msg_dict,
                                )
                            )

                        if not initialized_notification_sent:
                            if not initialized_handshake_responded:
                                results.append(
                                    ValidationResult(
                                        rule_name="handshake_order",
                                        passed=False,
                                        severity="critical",
                                        message=f"Client request '{method}' sent before server initialize response",
                                        context=msg_dict,
                                    )
                                )
                            else:
                                if method != "notifications/initialized":
                                    results.append(
                                        ValidationResult(
                                            rule_name="handshake_order",
                                            passed=False,
                                            severity="warning",
                                            message=f"Client request '{method}' sent before sending 'notifications/initialized' notification",
                                            suggestion="Send 'notifications/initialized' immediately after receiving initialize response",
                                            context=msg_dict,
                                        )
                                    )

                        # Capability alignment check
                        if method in self.CAPABILITY_REQUIRED_FOR_METHOD:
                            required_cap = self.CAPABILITY_REQUIRED_FOR_METHOD[method]
                            if (
                                initialized_handshake_responded
                                and required_cap not in negotiated_server_capabilities
                            ):
                                results.append(
                                    ValidationResult(
                                        rule_name="capability_alignment",
                                        passed=False,
                                        severity="warning",
                                        message=f"Client requested '{method}' but server did not declare '{required_cap}' capability in handshake response",
                                        suggestion=f"Enable '{required_cap}' capability support on server configuration",
                                        context=msg_dict,
                                    )
                                )

                elif message_type == "notification":
                    if method == "notifications/initialized":
                        initialized_notification_sent = True
                        if not initialized_handshake_responded:
                            results.append(
                                ValidationResult(
                                    rule_name="handshake_order",
                                    passed=False,
                                    severity="critical",
                                    message="Client sent 'notifications/initialized' before initialize response was received",
                                    context=msg_dict,
                                )
                            )
                    else:
                        # Other notification from client before handshake completion
                        if not initialized_notification_sent and method != "notifications/cancelled":
                            results.append(
                                ValidationResult(
                                    rule_name="handshake_order",
                                    passed=False,
                                    severity="warning",
                                    message=f"Client sent notification '{method}' before completing initialized handshake",
                                    context=msg_dict,
                                )
                            )

            elif direction == "server_to_client":
                if message_type == "response":
                    if (
                        initialize_request_id is not None
                        and msg_dict.get("id") == initialize_request_id
                    ):
                        initialized_handshake_responded = True
                        result_data = msg_dict.get("result")
                        if isinstance(result_data, dict):
                            negotiated_server_capabilities = result_data.get("capabilities", {})

        # If everything in session validated cleanly, add a success validation result
        if not results:
            results.append(
                ValidationResult(
                    rule_name="session_compliance",
                    passed=True,
                    severity="info",
                    message="Session handshake and capability flow is fully compliant with specifications",
                )
            )

        return results
