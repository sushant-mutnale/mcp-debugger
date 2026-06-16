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

## OpenTelemetry Export (OTLP)

Replay results can be exported as OpenTelemetry traces to any compatible backend (Jaeger, Grafana Tempo, Datadog, etc.).

### Installation

```bash
pip install 'mcp-debugger[otlp]'
```

### Usage

```bash
mcp-debugger replay 42 --server "npx -y @modelcontextprotocol/server-filesystem /tmp" \
  --otlp-export \
  --otlp-endpoint http://localhost:4317 \
  --otlp-insecure
```

If `--otlp-export` is given but the OTLP libraries are not installed, a warning is printed and replay completes normally — the exit code is not affected.

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--otlp-export` | `False` | Enable OTLP trace export |
| `--otlp-endpoint` | `http://localhost:4317` | gRPC collector endpoint |
| `--otlp-insecure / --otlp-tls` | `--otlp-insecure` | Disable/enable TLS |
| `--otlp-service-name` | `mcp-debugger` | Service name for traces |

### Trace Structure

Each replay run produces one trace:

- **Root span** (`mcp.replay session-<id>`): Carries aggregate statistics — total messages, matches, mismatches, timeouts, errors, match percentage, and duration.
- **Child spans** (`mcp.replay.<method>`): One per replayed message, carrying:
  - `mcp.method` — the MCP method name
  - `mcp.replay.matched` — boolean, whether response matched
  - `mcp.replay.latency_ms` — round-trip latency
  - `mcp.replay.diff_summary` — first 255 chars of diff text (if mismatched)
  - `mcp.tool.name` — tool name for `tools/call` spans
  - A `mcp.replay.diff` event with the structured diff payload (for mismatches)

Spans are marked `ERROR` status when:
- Any mismatch exists (child span for that message, and root span if totals > 0)
- The message timed out or returned a server error

### Local Testing with Jaeger

```bash
# Start Jaeger all-in-one
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one

# Run replay with OTLP export
mcp-debugger replay 42 --server "..." --otlp-export

# View traces at http://localhost:16686
```

