# Session Replay and Diffing

The MCP Debugger includes a replay engine and semantic diff module to help you re-run recorded sessions against target servers and view changes in response payloads.

## Replay Engine

The replay engine reads a recorded session's client messages and plays them back chronologically to a newly launched server. During replay, it captures the actual responses and compares them against the original responses logged during the recording.

## Semantic Diffing

When a replayed response differs from the original response, a recursive semantic diff is generated. This highlights:
- **`added`**: Fields present in the replayed response but missing from the original.
- **`removed`**: Fields present in the original response but missing from the replayed response.
- **`changed`**: Fields whose values or types have changed.

### Diff Data Structure (`DiffNode`)

Differences are computed into a hierarchical tree of `DiffNode` objects:

```python
class DiffType(str, Enum):
    UNCHANGED = "unchanged"
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"

class DiffNode(BaseModel):
    path: str              # JSONPath-like path to the diff
    type: DiffType         # Diff classification
    old_value: Any = None  # Original value (for CHANGED/REMOVED)
    new_value: Any = None  # Replayed value (for CHANGED/ADDED)
    children: List[DiffNode] = []
```

### Rendering Terminal Diffs

The engine renders these diffs to the console using color-coded inline styling (compatible with the Rich library):

```
  ~ result:
    ~ result.status:
      - "error"
      + "ok"
```

Here:
- `~` indicates a modified object or field.
- `-` indicates the original value (rendered in red).
- `+` indicates the new replayed value (rendered in green).

## Performance Safeguards

For large payloads (e.g., tool listings containing schemas exceeding 100 KB), executing recursive diffs can be computationally expensive. The diffing engine automatically caps comparisons at 100 KB per response. If either the original or replayed response exceeds this threshold, diff rendering is skipped, and a warning is printed:

`[JSON too large to diff]`
