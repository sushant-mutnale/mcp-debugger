import time
from mcp_debugger.replay.engine import deep_compare
from mcp_debugger.replay.diff import compare_json, render_diff, DiffType


def test_deep_compare() -> None:
    """Verify deep comparison of JSON objects works, ignoring expected variant keys."""
    obj1 = {"status": "ok", "timestamp": 1234567, "data": {"val": 10, "latency_ms": 50}}
    obj2 = {"status": "ok", "timestamp": 7654321, "data": {"val": 10, "latency_ms": 20}}
    assert deep_compare(obj1, obj2)

    # Different value
    obj3 = {"status": "failed", "timestamp": 1234567, "data": {"val": 10}}
    assert not deep_compare(obj1, obj3)

    # Different nested value
    obj4 = {"status": "ok", "timestamp": 1234567, "data": {"val": 20}}
    assert not deep_compare(obj1, obj4)

    # Missing keys
    obj5 = {"status": "ok"}
    assert not deep_compare(obj1, obj5)


def test_diff() -> None:
    """Verify compare_json and render_diff on JSON structures."""
    # 1. Simple unchanged
    assert compare_json({"a": 1}, {"a": 1}) is None

    # 2. Simple changed
    diff = compare_json({"a": 1}, {"a": 2})
    assert diff is not None
    assert diff.type == DiffType.CHANGED
    assert len(diff.children) == 1
    assert diff.children[0].path == "a"
    assert diff.children[0].type == DiffType.CHANGED
    assert diff.children[0].old_value == 1
    assert diff.children[0].new_value == 2

    # 3. Added and Removed keys
    diff = compare_json({"a": 1, "b": 2}, {"b": 2, "c": 3})
    assert diff is not None
    assert len(diff.children) == 2
    paths = {c.path: c for c in diff.children}
    assert "a" in paths
    assert paths["a"].type == DiffType.REMOVED
    assert paths["a"].old_value == 1

    assert "c" in paths
    assert paths["c"].type == DiffType.ADDED
    assert paths["c"].new_value == 3

    # 4. Nested dict changed
    diff = compare_json({"meta": {"status": "ok"}}, {"meta": {"status": "error"}})
    assert diff is not None
    # Check hierarchy
    assert diff.children[0].path == "meta"
    assert diff.children[0].children[0].path == "meta.status"
    assert diff.children[0].children[0].type == DiffType.CHANGED
    assert diff.children[0].children[0].old_value == "ok"
    assert diff.children[0].children[0].new_value == "error"

    # 5. List index comparison
    diff = compare_json({"arr": [1, 2, 3]}, {"arr": [1, 5, 3, 4]})
    assert diff is not None
    # Changed index [1] and added index [3]
    arr_diff = diff.children[0]
    assert arr_diff.path == "arr"
    assert len(arr_diff.children) == 2
    assert arr_diff.children[0].path == "arr[1]"
    assert arr_diff.children[0].type == DiffType.CHANGED
    assert arr_diff.children[0].old_value == 2
    assert arr_diff.children[0].new_value == 5
    assert arr_diff.children[1].path == "arr[3]"
    assert arr_diff.children[1].type == DiffType.ADDED
    assert arr_diff.children[1].new_value == 4

    # 6. Type changes
    diff = compare_json({"val": 42}, {"val": "forty-two"})
    assert diff is not None
    assert diff.children[0].type == DiffType.CHANGED
    assert diff.children[0].old_value == 42
    assert diff.children[0].new_value == "forty-two"

    # 7. Render diff output containing Rich markup representation
    rendered = render_diff(diff)
    assert "[yellow]" in rendered
    assert "[red]- 42" in rendered
    assert "[green]+ \"forty-two\"" in rendered

    # 8. Performance test with 1MB JSON (hits guard)
    large_orig = {"data": [i for i in range(150000)]}
    large_rep = {"data": [i if i != 75000 else -1 for i in range(150000)]}

    start = time.perf_counter()
    large_diff = compare_json(large_orig, large_rep)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5
    assert large_diff is not None
    assert "[JSON too large to diff]" in str(large_diff.old_value)


def test_diff_edge_cases() -> None:
    """Verify size guard exceptions, list removals, rendering variations, and leaf render types."""
    # 1. Exception in size guard (circular references or non-serializable objects)
    diff_obj = compare_json(object(), object())
    assert diff_obj is not None
    assert diff_obj.type == DiffType.CHANGED

    # 2. List element removed
    diff_list_rem = compare_json([1, 2], [1])
    assert diff_list_rem is not None
    assert len(diff_list_rem.children) == 1
    assert diff_list_rem.children[0].type == DiffType.REMOVED

    # 3. List comparison returning None when identical
    assert compare_json([1, 2], [1, 2]) is None

    # 4. Nested object render_diff hitting path with children
    diff_nested = compare_json({"nested": {"a": 1}}, {"nested": {"a": 2}})
    assert diff_nested is not None
    rendered = render_diff(diff_nested)
    assert "~ nested:" in rendered

    # 5. Render diff with ADDED and REMOVED leaf node types
    diff_added = compare_json({}, {"added_key": 100})
    assert diff_added is not None
    rendered_added = render_diff(diff_added)
    assert "+ added_key: 100" in rendered_added

    diff_removed = compare_json({"removed_key": 200}, {})
    assert diff_removed is not None
    rendered_removed = render_diff(diff_removed)
    assert "- removed_key: 200" in rendered_removed

