import json

from mcp_debugger.attribution.classifier import FailureClassifier
from mcp_debugger.attribution.models import FailureCategory, FailureDiagnosis


def test_detect_tool_loop() -> None:
    """Detects when an agent repeatedly executes identical tool calls in a loop."""
    classifier = FailureClassifier(loop_threshold=3)

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "thought",
            "agent_name": "coder",
            "input": "Plan tasks",
            "output": "Starting work",
        },
        {
            "id": 2,
            "step_index": 1,
            "step_type": "tool_call",
            "agent_name": "coder",
            "input": json.dumps({"tool": "read_file", "args": ["data.txt"]}),
            "output": "File not ready",
        },
        {
            "id": 3,
            "step_index": 2,
            "step_type": "tool_call",
            "agent_name": "coder",
            "input": json.dumps({"tool": "read_file", "args": ["data.txt"]}),
            "output": "File not ready",
        },
        {
            "id": 4,
            "step_index": 3,
            "step_type": "tool_call",
            "agent_name": "coder",
            "input": json.dumps({"tool": "read_file", "args": ["data.txt"]}),
            "output": "File not ready",
        },
    ]

    diagnosis = classifier.classify_session(session_id=10, steps=steps)
    assert isinstance(diagnosis, FailureDiagnosis)
    assert diagnosis.category == FailureCategory.AGENT
    assert diagnosis.details.get("loop_detected") is True
    assert diagnosis.details.get("tool_name") == "read_file"
    assert diagnosis.root_cause_step_index == 1
    assert "loop" in diagnosis.summary.lower()


def test_detect_empty_result_trap() -> None:
    """Detects when a tool returning empty content traps the agent into a crash."""
    classifier = FailureClassifier()

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "thought",
            "agent_name": "researcher",
            "input": "Find users",
            "output": "Querying database",
        },
        {
            "id": 2,
            "step_index": 1,
            "step_type": "tool_call",
            "agent_name": "researcher",
            "input": json.dumps({"tool": "find_users", "args": {"role": "admin"}}),
            "output": json.dumps({"content": []}),  # Empty payload trap
        },
        {
            "id": 3,
            "step_index": 2,
            "step_type": "thought",
            "agent_name": "researcher",
            "input": "Parse results",
            "output": "Error: IndexError: list index out of range",
        },
    ]

    diagnosis = classifier.classify_session(session_id=11, steps=steps)
    assert diagnosis.category == FailureCategory.TOOL
    assert diagnosis.details.get("empty_result_trap") is True
    assert diagnosis.root_cause_step_index == 1
    assert "empty result" in diagnosis.summary.lower()


def test_detect_protocol_violation() -> None:
    """Detects protocol level violations from JSON-RPC wire messages."""
    classifier = FailureClassifier()

    messages = [
        {
            "id": 101,
            "direction": "client_to_server",
            "method": "unsupported/method",
            "message_type": "request",
            "params": "{}",
        },
        {
            "id": 102,
            "direction": "server_to_client",
            "message_type": "response",
            "error": json.dumps({"code": -32601, "message": "Method not found"}),
        },
    ]

    diagnosis = classifier.classify_session(session_id=12, messages=messages)
    assert diagnosis.category == FailureCategory.PROTOCOL
    assert "protocol" in diagnosis.summary.lower() or "method not found" in diagnosis.summary.lower()


def test_clean_session_without_failures() -> None:
    """Clean session without errors or loops returns FailureCategory.NONE."""
    classifier = FailureClassifier()

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "thought",
            "agent_name": "agent",
            "input": "Calculate sum",
            "output": "Adding 1 and 2",
        },
        {
            "id": 2,
            "step_index": 1,
            "step_type": "tool_call",
            "agent_name": "agent",
            "input": json.dumps({"tool": "add", "args": [1, 2]}),
            "output": "3",
        },
    ]

    diagnosis = classifier.classify_session(session_id=13, steps=steps)
    assert diagnosis.category == FailureCategory.NONE
    assert diagnosis.root_cause_step_index is None


def test_detect_cyclic_tool_loop() -> None:
    """Detects when an agent alternates tools in a repeating cycle."""
    classifier = FailureClassifier(loop_threshold=3)

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "tool_call",
            "input": {"tool": "search", "args": {"q": "cats"}},
            "output": "no result",
        },
        {
            "id": 2,
            "step_index": 1,
            "step_type": "tool_call",
            "input": {"tool": "list_files", "args": {}},
            "output": "empty",
        },
        {
            "id": 3,
            "step_index": 2,
            "step_type": "tool_call",
            "input": {"tool": "search", "args": {"q": "cats"}},
            "output": "no result",
        },
        {
            "id": 4,
            "step_index": 3,
            "step_type": "tool_call",
            "input": {"tool": "list_files", "args": {}},
            "output": "empty",
        },
        {
            "id": 5,
            "step_index": 4,
            "step_type": "tool_call",
            "input": {"tool": "search", "args": {"q": "cats"}},
            "output": "no result",
        },
        {
            "id": 6,
            "step_index": 5,
            "step_type": "tool_call",
            "input": {"tool": "list_files", "args": {}},
            "output": "empty",
        },
    ]

    diagnosis = classifier.classify_session(session_id=14, steps=steps)
    assert diagnosis.category == FailureCategory.AGENT
    assert diagnosis.details.get("cycle_detected") is True
    assert diagnosis.root_cause_step_index == 0


def test_detect_tool_is_error() -> None:
    """Detects when a tool reports isError: true in its output."""
    classifier = FailureClassifier()

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "tool_call",
            "input": {"tool": "query_db", "args": {"sql": "SELECT * FROM unknown"}},
            "output": json.dumps({"isError": True, "content": "Table does not exist"}),
        }
    ]

    diagnosis = classifier.classify_session(session_id=15, steps=steps)
    assert diagnosis.category == FailureCategory.TOOL
    assert diagnosis.details.get("tool_error") is True
    assert diagnosis.root_cause_step_index == 0
    assert "query_db" in diagnosis.summary


def test_protocol_violation_dict_and_clean_messages() -> None:
    """Detects protocol error formatted as dict and clean messages return NONE."""
    classifier = FailureClassifier()

    # Protocol error as dict
    messages = [
        {
            "id": 1,
            "direction": "server_to_client",
            "message_type": "response",
            "error": {"code": -32003, "message": "Stateless capability missing"},
        }
    ]
    diag = classifier.classify_session(session_id=16, messages=messages)
    assert diag.category == FailureCategory.PROTOCOL
    assert diag.details.get("error_code") == -32003

    # Clean messages
    clean_messages = [
        {
            "id": 1,
            "direction": "client_to_server",
            "message_type": "request",
            "method": "tools/list",
            "params": "{}",
        },
        {
            "id": 2,
            "direction": "server_to_client",
            "message_type": "response",
            "result": "{}",
        },
    ]
    diag_clean = classifier.classify_session(session_id=17, messages=clean_messages)
    assert diag_clean.category == FailureCategory.NONE


def test_empty_result_without_subsequent_crash() -> None:
    """Empty result handled gracefully by agent does not trigger empty result trap."""
    classifier = FailureClassifier()

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "tool_call",
            "input": json.dumps({"tool": "find_items", "args": {}}),
            "output": json.dumps({"content": []}),
        },
        {
            "id": 2,
            "step_index": 1,
            "step_type": "thought",
            "input": "Check items",
            "output": "No items were found. Task completed successfully with zero items.",
        },
    ]

    diag = classifier.classify_session(session_id=18, steps=steps)
    assert diag.category == FailureCategory.NONE

