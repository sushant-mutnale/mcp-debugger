"""Protocol compliance validator for MCP messages and sessions."""

import json
from typing import Any

import jsonschema
from pydantic import BaseModel, Field

from mcp_debugger.storage.database import Database


class ValidationResult(BaseModel):
    """Represents the outcome of a single protocol compliance check."""

    rule_name: str = Field(..., description="Unique identifier for the compliance rule")
    passed: bool = Field(..., description="Whether the check succeeded")
    severity: str = Field(..., description="Severity level: 'critical', 'warning', or 'info'")
    message: str = Field(..., description="Human-readable explanation of the validation result")
    suggestion: str | None = Field(default=None, description="Optional remediation advice")
    context: dict[str, Any] | None = Field(default=None, description="Contextual message payload")


class ProtocolValidator:
    """Validator engine for ensuring MCP specification compliance."""

    DIALECT_STATEFUL: str = "2025-03-26"
    DIALECT_STATELESS: str = "2026-07-28"

    META_PROTOCOL_VERSION_KEY: str = "io.modelcontextprotocol/protocolVersion"
    META_CLIENT_INFO_KEY: str = "io.modelcontextprotocol/clientInfo"
    META_CLIENT_CAPABILITIES_KEY: str = "io.modelcontextprotocol/clientCapabilities"

    STANDARD_METHODS: set[str] = {
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
        # Stateless 2026-07-28 RPCs
        "server/discover",
        "subscriptions/listen",
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

    TYPO_CORRECTIONS: dict[str, str] = {
        "tool/list": "tools/list",
        "tool/call": "tools/call",
        "tools/list-changed": "notifications/tools/list-changed",
        "resources/list-changed": "notifications/resources/list-changed",
        "prompts/list-changed": "notifications/prompts/list-changed",
        "roots/list-changed": "notifications/roots/list-changed",
        "initialized": "notifications/initialized",
    }

    CAPABILITY_REQUIRED_FOR_METHOD: dict[str, str] = {
        "tools/list": "tools",
        "tools/call": "tools",
        "resources/list": "resources",
        "resources/templates/list": "resources",
        "resources/read": "resources",
        "prompts/list": "prompts",
        "prompts/get": "prompts",
        "logging/setLevel": "logging",
    }

    NOTIFICATION_TOPIC_MAPPING: dict[str, list[str]] = {
        "notifications/tools/list-changed": [
            "toolsListChanged",
            "tools",
            "notifications/tools/list-changed",
        ],
        "toolsListChanged": ["toolsListChanged", "tools"],
        "notifications/prompts/list-changed": [
            "promptsListChanged",
            "prompts",
            "notifications/prompts/list-changed",
        ],
        "promptsListChanged": ["promptsListChanged", "prompts"],
        "notifications/resources/list-changed": [
            "resourcesListChanged",
            "resources",
            "notifications/resources/list-changed",
        ],
        "resourcesListChanged": ["resourcesListChanged", "resources"],
        "notifications/roots/list-changed": [
            "rootsListChanged",
            "roots",
            "notifications/roots/list-changed",
        ],
        "rootsListChanged": ["rootsListChanged", "roots"],
        "notifications/message": ["message", "notifications/message"],
        "notifications/progress": ["progress", "notifications/progress"],
    }

    def __init__(self, protocol_version: str = "2025-03-26"):
        self.version = protocol_version

    @classmethod
    def detect_dialect(cls, messages: list[dict[str, Any]]) -> str:
        """Inspect message stream to auto-detect whether session is 2025 stateful or 2026 stateless."""
        for msg in messages:
            direction = msg.get("direction", "client_to_server")
            if direction != "client_to_server":
                continue

            method = msg.get("method")
            if method == "initialize":
                return cls.DIALECT_STATEFUL

            if method == "server/discover":
                return cls.DIALECT_STATELESS

            params = msg.get("params")
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except Exception:
                    params = {}

            if isinstance(params, dict):
                meta = params.get("_meta")
                if isinstance(meta, dict):
                    if cls.META_PROTOCOL_VERSION_KEY in meta or "protocolVersion" in meta:
                        return cls.DIALECT_STATELESS

            meta_top = msg.get("_meta")
            if isinstance(meta_top, dict):
                if cls.META_PROTOCOL_VERSION_KEY in meta_top or "protocolVersion" in meta_top:
                    return cls.DIALECT_STATELESS

        return cls.DIALECT_STATEFUL

    def validate_message(
        self, message: dict[str, Any], direction: str, context: dict[str, Any] | None = None
    ) -> list[ValidationResult]:
        """Validate a single MCP message envelope and payload in isolation."""
        results: list[ValidationResult] = []

        # 1. Check JSON-RPC version
        jsonrpc = message.get("jsonrpc")
        if jsonrpc != "2.0":
            results.append(
                ValidationResult(
                    rule_name="jsonrpc_version",
                    passed=False,
                    severity="critical",
                    message=f"JSON-RPC version must be exactly '2.0', got {jsonrpc!r}",
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

            if has_error and isinstance(message.get("error"), dict):
                err_dict = message["error"]
                err_code = None
                try:
                    if "code" in err_dict and err_dict["code"] is not None:
                        err_code = int(err_dict["code"])
                except (ValueError, TypeError):
                    pass
                raw_err_msg = str(err_dict.get("message", ""))
                err_data = str(err_dict.get("data", ""))
                combined = f"{raw_err_msg} {err_data}".lower()

                if (
                    err_code == -32003
                    or "unsupportedprotocolversion" in combined
                    or "unsupported protocol version" in combined
                ):
                    results.append(
                        ValidationResult(
                            rule_name="stateless_protocol_version",
                            passed=False,
                            severity="critical",
                            message=f"Server returned UnsupportedProtocolVersionError (-32003): {raw_err_msg}",
                            suggestion="Check supported versions via server/discover and update client _meta.protocolVersion",
                            context=message,
                        )
                    )
                elif (
                    err_code == -32004
                    or "missingrequiredclientcapability" in combined
                    or "missing required client capability" in combined
                    or "missing client capability" in combined
                ):
                    from mcp_debugger.protocol.error_classifier import ErrorClassifier

                    missing_cap = ErrorClassifier.extract_missing_capability(err_dict, raw_err_msg)
                    cap_flag = f" '{missing_cap}'" if missing_cap else ""
                    results.append(
                        ValidationResult(
                            rule_name="stateless_client_capability",
                            passed=False,
                            severity="critical",
                            message=f"Server returned MissingRequiredClientCapabilityError (-32004): {raw_err_msg}",
                            suggestion=f"Declare missing capability{cap_flag} in client _meta.clientCapabilities",
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

        # 3. Check subscriptions/listen request payload
        if has_method and method == "subscriptions/listen":
            params = message.get("params")
            subs = None
            if isinstance(params, dict):
                subs = params.get("subscriptions") or params.get("topics")
            if not isinstance(subs, list) or not all(isinstance(s, str) for s in subs):
                results.append(
                    ValidationResult(
                        rule_name="subscriptions_listen_schema",
                        passed=False,
                        severity="warning",
                        message="'subscriptions/listen' params should include 'subscriptions' as a list of topic strings",
                        context=message,
                    )
                )
            else:
                results.append(
                    ValidationResult(
                        rule_name="subscriptions_listen_schema",
                        passed=True,
                        severity="info",
                        message="Valid subscriptions/listen request",
                        context=message,
                    )
                )

        # 4. Check tool definitions in tools/list response result
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

            # 5. Check server/discover response structure (MCP 2026-07-28)
            if "supportedVersions" in result_dict or (
                context and context.get("method") == "server/discover"
            ):
                supp_vers = result_dict.get("supportedVersions")
                caps = result_dict.get("capabilities")
                srv_info = result_dict.get("serverInfo")
                instr = result_dict.get("instructions")

                disc_errors: list[str] = []
                if not isinstance(supp_vers, list) or not all(
                    isinstance(v, str) for v in supp_vers
                ):
                    disc_errors.append("'supportedVersions' must be a list of strings")
                if not isinstance(caps, dict):
                    disc_errors.append("'capabilities' must be an object")
                if (
                    not isinstance(srv_info, dict)
                    or not srv_info.get("name")
                    or not isinstance(srv_info.get("name"), str)
                ):
                    disc_errors.append(
                        "'serverInfo' must be an object with a non-empty 'name' string"
                    )
                if instr is not None and not isinstance(instr, str):
                    disc_errors.append("'instructions' must be a string if provided")

                if disc_errors:
                    for err_msg in disc_errors:
                        results.append(
                            ValidationResult(
                                rule_name="server_discover_schema",
                                passed=False,
                                severity="critical",
                                message=f"Invalid server/discover response: {err_msg}",
                                context=message,
                            )
                        )
                else:
                    results.append(
                        ValidationResult(
                            rule_name="server_discover_schema",
                            passed=True,
                            severity="info",
                            message="server/discover response is fully compliant with MCP 2026-07-28",
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

    async def validate_session(self, session_id: int, db: Database) -> list[ValidationResult]:
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

        results: list[ValidationResult] = []

        session_protocol = session.get("protocol_version") if session else None
        dialect = session_protocol or self.detect_dialect(rows)

        initialized_handshake_started = False
        initialized_handshake_responded = False
        initialized_notification_sent = False
        active_subscriptions: set[str] = set()

        negotiated_server_capabilities: dict[str, Any] = {}
        initialize_request_id: Any | None = None

        for row in rows:
            # Reconstruct message dictionary from DB fields
            msg_dict: dict[str, Any] = {
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

            # Track client subscriptions/listen calls
            if direction == "client_to_server" and method == "subscriptions/listen":
                params = msg_dict.get("params")
                if isinstance(params, dict):
                    subs = params.get("subscriptions") or params.get("topics")
                    if isinstance(subs, list):
                        for s in subs:
                            if isinstance(s, str):
                                active_subscriptions.add(s)

            # Check unsolicited server notifications
            if direction == "server_to_client" and message_type == "notification" and method:
                if active_subscriptions:
                    possible_topics = self.NOTIFICATION_TOPIC_MAPPING.get(method, [method])
                    if (
                        not any(t in active_subscriptions for t in possible_topics)
                        and method not in active_subscriptions
                    ):
                        results.append(
                            ValidationResult(
                                rule_name="unsolicited_notification",
                                passed=False,
                                severity="warning",
                                message=f"Server sent notification '{method}' which was not subscribed to via subscriptions/listen",
                                suggestion="Subscribe to this notification type using subscriptions/listen before server emits it",
                                context=msg_dict,
                            )
                        )

            # 2. Handshake ordering & capability compliance
            if dialect == self.DIALECT_STATELESS:
                if direction == "client_to_server" and message_type == "request":
                    params = msg_dict.get("params")
                    meta = params.get("_meta") if isinstance(params, dict) else None
                    has_meta_ver = False
                    if isinstance(meta, dict):
                        has_meta_ver = bool(
                            meta.get(self.META_PROTOCOL_VERSION_KEY) or meta.get("protocolVersion")
                        )
                    if not has_meta_ver and isinstance(msg_dict.get("_meta"), dict):
                        meta_top = msg_dict["_meta"]
                        has_meta_ver = bool(
                            meta_top.get(self.META_PROTOCOL_VERSION_KEY)
                            or meta_top.get("protocolVersion")
                        )
                    if not has_meta_ver:
                        results.append(
                            ValidationResult(
                                rule_name="stateless_meta_declaration",
                                passed=False,
                                severity="critical",
                                message=f"Client request '{method}' missing required '_meta' protocolVersion declaration",
                                suggestion=f"Include '_meta' with '{self.META_PROTOCOL_VERSION_KEY}' in params",
                                context=msg_dict,
                            )
                        )
            else:
                # Stateful 2025-03-26 handshake validation
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
                            if (
                                not initialized_notification_sent
                                and method != "notifications/cancelled"
                            ):
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
