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
    assert sug is not None
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
    assert sug is not None
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
    assert sug is not None
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
    assert sug is not None
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
    assert sug is not None
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
    assert sug is not None
    assert "permissions" in sug.lower()

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
    assert sug2 is not None
    assert "access rights" in sug2.lower()


def test_error_classifier_edge_cases() -> None:
    classifier = ErrorClassifier()

    # 1. Error with 'data' field
    res_data = classifier.classify({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32602, "message": "Invalid params", "data": "detail-info"}
    })
    assert res_data is not None
    assert "detail-info" in res_data[1]

    # 2. Standard protocol errors (-32700, -32600, -32603)
    for code in (-32700, -32600, -32603):
        res_proto = classifier.classify({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": code, "message": "Protocol error"}
        })
        assert res_proto is not None
        assert res_proto[0] == "protocol"
        assert "protocol error occurred" in res_proto[2].lower()

    # 3. Unknown / unclassified error code
    res_unknown = classifier.classify({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": 9999, "message": "Some custom error"}
    })
    assert res_unknown is not None
    assert res_unknown[0] == "unknown"

