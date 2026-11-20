import uuid
from types import SimpleNamespace

from mcp_debugger.adapters.langchain import MCPDebuggerCallbackHandler
from mcp_debugger.sdk import set_active_session


class MockBackend:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    def record_step(
        self,
        session_id: int,
        step_index: int,
        step_type: str,
        agent_name: str | None,
        input_data: str | None,
        output_data: str | None,
        latency_ms: float | None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
    ) -> int:
        step = {
            "id": len(self.steps) + 1,
            "session_id": session_id,
            "step_index": step_index,
            "step_type": step_type,
            "agent_name": agent_name,
            "input": input_data,
            "output": output_data,
            "latency_ms": latency_ms,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
        }
        self.steps.append(step)
        return step["id"]


def test_chain_lifecycle() -> None:
    """on_chain_start and on_chain_end log a thought step."""
    backend = MockBackend()
    set_active_session(301, backend)

    handler = MCPDebuggerCallbackHandler(agent_name="langchain_chain")
    run_id = uuid.uuid4()

    handler.on_chain_start(
        serialized={"name": "RetrievalQA"},
        inputs={"query": "Explain MCP 2026"},
        run_id=run_id,
    )
    handler.on_chain_end(
        outputs={"result": "MCP 2026 is stateless"},
        run_id=run_id,
    )

    assert len(backend.steps) == 1
    step = backend.steps[0]
    assert step["session_id"] == 301
    assert step["step_type"] == "thought"
    assert step["agent_name"] == "langchain_chain"
    assert "Explain MCP 2026" in step["input"]
    assert "MCP 2026 is stateless" in step["output"]
    assert step["latency_ms"] >= 0.0


def test_tool_lifecycle() -> None:
    """on_tool_start and on_tool_end log a tool_call step."""
    backend = MockBackend()
    set_active_session(302, backend)

    handler = MCPDebuggerCallbackHandler(agent_name="agent_executor")
    run_id = uuid.uuid4()

    handler.on_tool_start(
        serialized={"name": "database_lookup"},
        input_str='{"table": "users", "id": 42}',
        run_id=run_id,
    )
    handler.on_tool_end(
        output='{"name": "Alice"}',
        run_id=run_id,
    )

    assert len(backend.steps) == 1
    step = backend.steps[0]
    assert step["session_id"] == 302
    assert step["step_type"] == "tool_call"
    assert step["agent_name"] == "agent_executor"
    assert "database_lookup" in step["input"]
    assert "Alice" in step["output"]


def test_llm_lifecycle_with_tokens() -> None:
    """on_llm_start and on_llm_end log an llm_call step with token usage."""
    backend = MockBackend()
    set_active_session(303, backend)

    handler = MCPDebuggerCallbackHandler(agent_name="chat_agent")
    run_id = uuid.uuid4()

    handler.on_llm_start(
        serialized={"name": "ChatOpenAI", "kwargs": {"model_name": "gpt-4o"}},
        prompts=["Hello world"],
        run_id=run_id,
    )

    mock_response = SimpleNamespace(
        generations=[[SimpleNamespace(text="Hello! How can I help?")]],
        llm_output={
            "token_usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
            },
            "model_name": "gpt-4o",
        },
    )

    handler.on_llm_end(response=mock_response, run_id=run_id)

    assert len(backend.steps) == 1
    step = backend.steps[0]
    assert step["session_id"] == 303
    assert step["step_type"] == "llm_call"
    assert step["agent_name"] == "chat_agent"
    assert "Hello world" in step["input"]
    assert "How can I help" in step["output"]
    assert step["tokens_input"] == 12
    assert step["tokens_output"] == 8


def test_errors_and_noop() -> None:
    """Error hooks log error output, and handler safely no-ops with no active session."""
    backend = MockBackend()
    set_active_session(304, backend)

    handler = MCPDebuggerCallbackHandler(agent_name="resilient_agent")
    run_id = uuid.uuid4()

    handler.on_tool_start(
        serialized={"name": "broken_tool"},
        input_str="do something",
        run_id=run_id,
    )
    handler.on_tool_error(
        error=TimeoutError("Request timed out"),
        run_id=run_id,
    )

    assert len(backend.steps) == 1
    assert "TimeoutError" in backend.steps[0]["output"]

    # Chain error
    c_id = uuid.uuid4()
    handler.on_chain_start(None, {"x": "fail"}, run_id=c_id)
    handler.on_chain_error(error=RuntimeError("Chain broke"), run_id=c_id)
    assert len(backend.steps) == 2
    assert "RuntimeError" in backend.steps[1]["output"]

    # LLM error
    l_id = uuid.uuid4()
    handler.on_llm_start(None, ["prompt"], run_id=l_id)
    handler.on_llm_error(error=ValueError("LLM bad input"), run_id=l_id)
    assert len(backend.steps) == 3
    assert "ValueError" in backend.steps[2]["output"]

    # No active session
    set_active_session(None, None)
    rid = uuid.uuid4()
    handler.on_chain_start(None, {"x": 1}, run_id=rid)
    handler.on_chain_end({"y": 2}, run_id=rid)
    assert len(backend.steps) == 3
