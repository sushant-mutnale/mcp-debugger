from mcp_debugger.protocol.error_classifier import ErrorClassifier

def test_error_classifier_non_error() -> None:
    classifier = ErrorClassifier()
    assert classifier.classify({"jsonrpc": "2.0", "id": 1, "result": {"success": True}}) is None
    assert classifier.classify({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_error_classifier_jsonrpc_errors() -> None:
    classifier = ErrorClassifier()

    # Code -32601: Method not found
    res = classifier.classify({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32601, "message": "Method not found"}
    })
    assert res is not None
    cat, msg, sug = res
    assert cat == "protocol"
    assert "Method not found" in msg
    assert "spelling" in sug.lower()

    # Code -32602: Invalid params
    res = classifier.classify({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32602, "message": "Invalid params"}
    })
    assert res is not None
    cat, msg, sug = res
    assert cat == "protocol"
    assert "Invalid params" in msg
    assert "arguments" in sug.lower()

    # Code -32001: Server-side tool execution error
    res = classifier.classify({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32001, "message": "Tool execution crashed"}
    })
    assert res is not None
    cat, msg, sug = res
    assert cat == "tool_execution"
    assert "Tool execution crashed" in msg
    assert "details" in sug.lower()


def test_error_classifier_heuristics() -> None:
    classifier = ErrorClassifier()

    # Timeout heuristic
    res = classifier.classify({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32603, "message": "The connection timed out"}
    })
    assert res is not None
    cat, msg, sug = res
    assert cat == "timeout"
    assert "timed out" in sug.lower()

    # Connection heuristic
    res = classifier.classify({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32603, "message": "broken pipe"}
    })
    assert res is not None
    cat, msg, sug = res
    assert cat == "connection"
    assert "Connection lost" in sug


def test_error_classifier_tool_failures() -> None:
    classifier = ErrorClassifier()

    # Successful JSON-RPC but tool isError=True
    res = classifier.classify({
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "isError": True,
            "content": [
                {"type": "text", "text": "File not found: /test/file.txt"}
            ]
        }
    })
    assert res is not None
    cat, msg, sug = res
    assert cat == "tool_execution"
    assert "File not found" in msg
    assert "permissions" in sug.lower()

    # Successful JSON-RPC but tool isError=True with permission denied
    res2 = classifier.classify({
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "isError": True,
            "content": [
                {"type": "text", "text": "Permission denied reading directory"}
            ]
        }
    })
    assert res2 is not None
    cat2, msg2, sug2 = res2
    assert cat2 == "tool_execution"
    assert "Permission denied" in msg2
    assert "access rights" in sug2.lower()
