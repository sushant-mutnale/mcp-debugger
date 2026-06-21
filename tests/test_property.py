import json
from typing import Any, Dict
import pytest
from hypothesis import given, strategies as st

from mcp_debugger.protocol.schemas import (
    JSONRPCRequest,
)
from mcp_debugger.protocol.validator import ProtocolValidator
from mcp_debugger.replay.diff import compare_json, DiffType, DiffNode


# ---------------------------------------------------------------------------
# Strategies for Generating JSON-RPC payloads
# ---------------------------------------------------------------------------

# Strategy for valid JSON-RPC ID (int or string)
jsonrpc_id = st.one_of(
    st.integers(min_value=-1000, max_value=1000), st.text(min_size=1, max_size=20)
)

# Strategy for params (dict or list or None)
json_value = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(),
    ),
    lambda children: st.one_of(st.lists(children), st.dictionaries(st.text(), children)),
    max_leaves=5,
)
jsonrpc_params = st.one_of(st.none(), st.lists(json_value), st.dictionaries(st.text(), json_value))

# Strategy for Request Dict base
request_dict_base = st.fixed_dictionaries(
    {
        "jsonrpc": st.just("2.0"),
        "id": jsonrpc_id,
        "method": st.text(min_size=1, max_size=50),
    }
)


@given(request_data=request_dict_base, params=jsonrpc_params)
def test_request_round_trip(request_data: Dict[str, Any], params: Any) -> None:
    """Any generated valid request dict can be parsed, serialized, and re-parsed identically."""
    full_data = request_data.copy()
    if params is not None:
        full_data["params"] = params

    # Create request
    req = JSONRPCRequest.model_validate(full_data)

    # Serialize to dict and back
    dumped = req.model_dump(exclude_none=True)
    assert dumped["jsonrpc"] == "2.0"
    assert dumped["id"] == full_data["id"]
    assert dumped["method"] == full_data["method"]

    # Round-trip JSON string serialization
    json_str = req.model_dump_json(exclude_none=True)
    reparsed_dict = json.loads(json_str)
    reparsed_req = JSONRPCRequest.model_validate(reparsed_dict)

    assert reparsed_req.id == req.id
    assert reparsed_req.method == req.method
    assert reparsed_req.params == req.params


@given(msg_data=json_value)
def test_validator_never_raises_on_arbitrary_input(msg_data: Any) -> None:
    """ProtocolValidator.validate_message() should never crash, regardless of input shape/type."""
    validator = ProtocolValidator()

    # Test dictionary input
    if isinstance(msg_data, dict):
        # We ensure it doesn't crash on dict input with arbitrary direction
        for direction in ("client_to_server", "server_to_client", "invalid_dir"):
            try:
                results = validator.validate_message(msg_data, direction=direction)
                assert isinstance(results, list)
            except Exception as e:
                pytest.fail(f"validate_message raised unexpected exception {e} on dict: {msg_data}")


def _swap_diff_node(node: DiffNode) -> DiffNode:
    """Helper to logically invert a DiffNode (swap added/removed, old_value/new_value)."""
    new_type = node.type
    if node.type == DiffType.ADDED:
        new_type = DiffType.REMOVED
    elif node.type == DiffType.REMOVED:
        new_type = DiffType.ADDED

    return DiffNode(
        path=node.path,
        type=new_type,
        old_value=node.new_value,
        new_value=node.old_value,
        children=[_swap_diff_node(c) for c in node.children],
    )


@given(a=json_value, b=json_value)
def test_compare_json_symmetry_and_identity(a: Any, b: Any) -> None:
    """Verify core properties of compare_json: identity and logical symmetry."""
    # 1. Identity: compare(a, a) must be None (meaning no differences)
    assert compare_json(a, a) is None

    # 2. Null equivalence: compare(a, b) is None iff compare(b, a) is None
    diff_ab = compare_json(a, b)
    diff_ba = compare_json(b, a)
    assert (diff_ab is None) == (diff_ba is None)

    # 3. Structural/logical symmetry if differences exist
    if diff_ab is not None and diff_ba is not None:
        # Check that path is identical
        assert diff_ab.path == diff_ba.path

        # Check that inverting diff_ab logically matches diff_ba
        inverted = _swap_diff_node(diff_ab)
        assert inverted.type == diff_ba.type
        assert inverted.old_value == diff_ba.old_value
        assert inverted.new_value == diff_ba.new_value
        assert len(inverted.children) == len(diff_ba.children)
