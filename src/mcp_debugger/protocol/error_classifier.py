from typing import Any, Dict, Optional, Tuple


class ErrorClassifier:
    """Classifies Model Context Protocol (MCP) and JSON-RPC runtime errors."""

    def classify(self, message: Dict[str, Any]) -> Optional[Tuple[str, str, Optional[str]]]:
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
            except ValueError:
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
