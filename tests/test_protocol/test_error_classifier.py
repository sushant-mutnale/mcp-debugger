from mcp_debugger.protocol.error_classifier import ErrorClassifier


def test_error_classifier_non_error() -> None:
    classifier = ErrorClassifier()
    assert classifier.classify({"jsonrpc": "2.0", "id": 1, "result": {"success": True}}) is None
    assert classifier.classify({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_error_classifier_jsonrpc_errors() -> None:
    classifier = ErrorClassifier()

    # Code -32601: Method not found
    res = classifier.classify(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}
    )
    assert res is not None
    cat, msg, sug = res
    assert cat == "protocol"
    assert "Method not found" in msg
    assert sug is not None
    assert "spelling" in sug.lower()

    # Code -32602: Invalid params
    res = classifier.classify(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "Invalid params"}}
    )
    assert res is not None
    cat, msg, sug = res
    assert cat == "protocol"
    assert "Invalid params" in msg
    assert sug is not None
    assert "arguments" in sug.lower()

    # Code -32001: Server-side tool execution error
    res = classifier.classify(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "Tool execution crashed"}}
    )
    assert res is not None
    cat, msg, sug = res
    assert cat == "tool_execution"
    assert "Tool execution crashed" in msg
    assert sug is not None
    assert "details" in sug.lower()


def test_error_classifier_heuristics() -> None:
    classifier = ErrorClassifier()

    # Timeout heuristic
    res = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32603, "message": "The connection timed out"},
        }
    )
    assert res is not None
    cat, msg, sug = res
    assert cat == "timeout"
    assert sug is not None
    assert "timed out" in sug.lower()

    # Connection heuristic
    res = classifier.classify(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": "broken pipe"}}
    )
    assert res is not None
    cat, msg, sug = res
    assert cat == "connection"
    assert sug is not None
    assert "Connection lost" in sug


def test_error_classifier_tool_failures() -> None:
    classifier = ErrorClassifier()

    # Successful JSON-RPC but tool isError=True
    res = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": "File not found: /test/file.txt"}],
            },
        }
    )
    assert res is not None
    cat, msg, sug = res
    assert cat == "tool_execution"
    assert "File not found" in msg
    assert sug is not None
    assert "permissions" in sug.lower()

    res2 = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": "Permission denied reading directory"}],
            },
        }
    )
    assert res2 is not None
    cat2, msg2, sug2 = res2
    assert cat2 == "tool_execution"
    assert "Permission denied" in msg2
    assert sug2 is not None
    assert "access rights" in sug2.lower()


def test_error_classifier_edge_cases() -> None:
    classifier = ErrorClassifier()

    # 1. Error with 'data' field
    res_data = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32602, "message": "Invalid params", "data": "detail-info"},
        }
    )
    assert res_data is not None
    assert "detail-info" in res_data[1]

    # 2. Standard protocol errors (-32700, -32600, -32603)
    for code in (-32700, -32600, -32603):
        res_proto = classifier.classify(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": code, "message": "Protocol error"}}
        )
        assert res_proto is not None
        assert res_proto[0] == "protocol"
        assert "protocol error occurred" in res_proto[2].lower()

    # 3. Unknown / unclassified error code
    res_unknown = classifier.classify(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": 9999, "message": "Some custom error"}}
    )
    assert res_unknown is not None
    assert res_unknown[0] == "unknown"


def test_error_classifier_unsupported_protocol_version() -> None:
    classifier = ErrorClassifier()

    # Code -32003 with standard message
    res = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32003, "message": "Unsupported protocol version"},
        }
    )
    assert res is not None
    cat, msg, sug = res
    assert cat == "protocol"
    assert "Unsupported protocol version" in msg
    assert sug is not None
    assert "server/discover" in sug
    assert "_meta.protocolVersion" in sug
    assert "upgrade" in sug.lower() or "downgrade" in sug.lower()

    # Code -32003 as string
    res_str = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {
                "code": "-32003",
                "message": "UnsupportedProtocolVersionError: version 2024-11-05 not supported",
            },
        }
    )
    assert res_str is not None
    assert res_str[0] == "protocol"
    assert "server/discover" in res_str[2]

    # HTTP 400 Bad Request style or message containing UnsupportedProtocolVersionError
    res_http = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "error": {
                "code": 400,
                "message": "UnsupportedProtocolVersionError: protocol version rejected",
            },
        }
    )
    assert res_http is not None
    assert res_http[0] == "protocol"
    assert "server/discover" in res_http[2]


def test_error_classifier_missing_required_client_capability() -> None:
    classifier = ErrorClassifier()

    # Code -32004 with message containing capability key
    res1 = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32004,
                "message": "Missing required client capability: roots",
            },
        }
    )
    assert res1 is not None
    cat1, msg1, sug1 = res1
    assert cat1 == "protocol"
    assert "roots" in msg1
    assert sug1 is not None
    assert "roots" in sug1
    assert "_meta.clientCapabilities" in sug1 or "clientCapabilities" in sug1

    # Code -32004 with data dictionary containing capability
    res2 = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {
                "code": -32004,
                "message": "MissingRequiredClientCapabilityError",
                "data": {"capability": "sampling"},
            },
        }
    )
    assert res2 is not None
    cat2, msg2, sug2 = res2
    assert cat2 == "protocol"
    assert sug2 is not None
    assert "sampling" in sug2

    # Code -32000 (ordinarily tool_execution) but message indicates MissingRequiredClientCapabilityError
    res3 = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "error": {
                "code": -32000,
                "message": "Missing required client capability 'prompts'",
            },
        }
    )
    assert res3 is not None
    cat3, msg3, sug3 = res3
    assert cat3 == "protocol"
    assert sug3 is not None
    assert "prompts" in sug3

    # Standard tool execution error -32000 without capability message remains tool_execution
    res_std = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "error": {"code": -32000, "message": "Generic tool failure occurred"},
        }
    )
    assert res_std is not None
    assert res_std[0] == "tool_execution"


def test_error_classifier_stateless_edge_cases() -> None:
    classifier = ErrorClassifier()

    # Code -32004 without specific capability named
    res = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32004,
                "message": "Missing required client capability",
            },
        }
    )
    assert res is not None
    assert res[0] == "protocol"
    assert res[2] is not None
    assert "clientCapabilities" in res[2]

    # Code -32004 with string in data
    res_data_str = classifier.classify(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {
                "code": -32004,
                "message": "Missing client capability",
                "data": "roots",
            },
        }
    )
    assert res_data_str is not None
    assert res_data_str[0] == "protocol"
    assert "roots" in res_data_str[2]
