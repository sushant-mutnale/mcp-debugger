import re
from typing import Any


class ErrorClassifier:
    """Classifies Model Context Protocol (MCP) and JSON-RPC runtime errors."""

    @staticmethod
    def extract_missing_capability(err: dict[str, Any], raw_msg: str) -> str | None:
        """Extract missing capability key from error data or error message."""
        data = err.get("data")
        if isinstance(data, dict):
            for k in (
                "capability",
                "required_capability",
                "missing_capability",
                "missingCapability",
                "requiredCapability",
                "key",
                "name",
            ):
                val = data.get(k)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        elif isinstance(data, str) and data.strip():
            clean = data.strip().strip("'\"`")
            if " " not in clean and len(clean) < 50:
                return clean

        patterns = [
            r"(?:missing\s+required\s+client\s+capability|missingrequiredclientcapabilityerror|missing\s+client\s+capability)[\s:]+['\"`]?([a-zA-Z0-9_\-/\.]+)",
            r"client\s+capability\s+['\"`]?([a-zA-Z0-9_\-/\.]+)['\"`]?\s+is\s+required",
            r"capability\s+['\"`]?([a-zA-Z0-9_\-/\.]+)['\"`]?\s+is\s+missing",
        ]
        for pat in patterns:
            m = re.search(pat, raw_msg, re.IGNORECASE)
            if m:
                cap = m.group(1).strip("'\"`").strip()
                if cap:
                    return cap
        return None

    def classify(self, message: dict[str, Any]) -> tuple[str, str, str | None] | None:
        """
        Classifies a JSON-RPC message dictionary if it is an error response or a tool execution error.

        Returns a tuple of (category, message, suggestion) or None if not an error.
        """
        # 1. Check for standard JSON-RPC error response
        if "error" in message and isinstance(message["error"], dict):
            err = message["error"]
            code = err.get("code")
            raw_msg = err.get("message", "Unknown error")

            # Append error data if present for more context
            data = err.get("data")
            if data is not None:
                raw_msg = f"{raw_msg}: {data}"

            try:
                error_code = int(code) if code is not None else None
            except (ValueError, TypeError):
                error_code = None
            msg_lower = raw_msg.lower()

            # Heuristics for timeout and connection errors
            if any(term in msg_lower for term in ("timeout", "timed out")):
                return (
                    "timeout",
                    raw_msg,
                    "Request timed out – increase timeout or optimise tool.",
                )
            if any(term in msg_lower for term in ("connection", "pipe", "broken", "refused")):
                return (
                    "connection",
                    raw_msg,
                    "Connection lost – server may have crashed. Check server logs.",
                )

            # JSON-RPC error code checks
            if error_code == -32601:
                return (
                    "protocol",
                    raw_msg,
                    "Method not found – check spelling. Did you mean 'tools/list'?",
                )
            if error_code == -32602:
                return (
                    "protocol",
                    raw_msg,
                    "Invalid params – tool arguments do not match inputSchema.",
                )

            # Code -32003: UnsupportedProtocolVersionError (stateless 2026-07-28 / HTTP 400 Bad Request)
            if (
                error_code == -32003
                or "unsupportedprotocolversion" in msg_lower
                or "unsupported protocol version" in msg_lower
            ):
                return (
                    "protocol",
                    raw_msg,
                    "Unsupported protocol version – check supported versions via server/discover "
                    "and update client _meta.protocolVersion to upgrade or downgrade.",
                )

            # Code -32004 or MissingRequiredClientCapabilityError
            if (
                error_code == -32004
                or "missingrequiredclientcapability" in msg_lower
                or "missing required client capability" in msg_lower
                or "missing client capability" in msg_lower
            ):
                missing_cap = self.extract_missing_capability(err, raw_msg)
                if missing_cap:
                    sug = (
                        f"Missing required client capability '{missing_cap}' – "
                        f"declare '{missing_cap}' in client _meta.clientCapabilities."
                    )
                else:
                    sug = (
                        "Missing required client capability – "
                        "declare required capabilities in client _meta.clientCapabilities."
                    )
                return (
                    "protocol",
                    raw_msg,
                    sug,
                )

            if error_code is not None and -32099 <= error_code <= -32000:
                return (
                    "tool_execution",
                    raw_msg,
                    "Tool execution error – see error message for details.",
                )
            if error_code is not None and error_code in (-32700, -32600, -32603):
                return (
                    "protocol",
                    raw_msg,
                    "JSON-RPC protocol error occurred.",
                )

            # Fallback for standard error objects
            return (
                "unknown",
                raw_msg,
                "Unclassified error – check server logs for details.",
            )

        # 2. Check for tool execution errors inside successful JSON-RPC results (result.isError == True)
        if "result" in message and isinstance(message["result"], dict):
            res = message["result"]
            if res.get("isError") is True:
                content_list = res.get("content", [])
                error_msgs = []
                if isinstance(content_list, list):
                    for item in content_list:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text", "")
                            if text:
                                error_msgs.append(text)

                error_msg = (
                    "; ".join(error_msgs) if error_msgs else "Tool reported execution failure"
                )
                msg_lower = error_msg.lower()

                # Heuristic suggestions for common tool execution errors
                suggestion = "Tool execution error – check path or arguments."
                if "file not found" in msg_lower or "no such file" in msg_lower:
                    suggestion = "File not found – check file path and permissions."
                elif "permission denied" in msg_lower or "access denied" in msg_lower:
                    suggestion = "Permission denied – ensure server has proper access rights."

                return (
                    "tool_execution",
                    error_msg,
                    suggestion,
                )

        return None
