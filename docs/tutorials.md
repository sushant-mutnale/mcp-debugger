# Tutorials

Step-by-step guides for the most common `mcp-debugger` workflows.

---

## Tutorial 1: Debug a New MCP Server

**Goal:** You've just written an MCP server and want to see what messages it actually sends and whether it complies with the protocol.

### Step 1 — Record a session

Start `mcp-debugger` as the proxy in front of your server:

```bash
mcp-debugger proxy \
  --server "python my_server.py" \
  --name "initial-debug"
```

Now interact with your server through an MCP client (Claude Desktop, a test script, etc.). When done, press `Ctrl+C`.

### Step 2 — Find the session ID

```bash
mcp-debugger list
```

Example output:

```
 ID │ Name           │ Status    │ Messages │ Started
────┼────────────────┼───────────┼──────────┼─────────────────────
  1 │ initial-debug  │ completed │      47  │ 2025-06-25 10:30:01
```

### Step 3 — Browse the messages

```bash
mcp-debugger inspect 1
```

Filter to only see tool calls:

```bash
mcp-debugger inspect 1 --method tools/call
```

### Step 4 — Check protocol compliance

```bash
mcp-debugger validate 1
```

Or validate a live server directly:

```bash
mcp-debugger validate --server "python my_server.py"
```

A passing result looks like:

```
✓ initialize_first       Client sent 'initialize' as first message
✓ server_capabilities    Server returned valid capabilities
✓ tool_schema_validity   All tool schemas are valid JSON Schema Draft-07
```

### Step 5 — Check discovered tools

```bash
mcp-debugger tools 1

# See full schema for a specific tool
mcp-debugger tools 1 --detail read_file
```

### Step 6 — View errors

```bash
mcp-debugger errors 1
```

---

## Tutorial 2: Regression Test a Server After a Code Change

**Goal:** You've updated your MCP server and want to ensure the output hasn't regressed compared to a previous known-good session.

### Step 1 — Record a baseline session (before your change)

```bash
mcp-debugger proxy \
  --server "python my_server.py" \
  --name "baseline-v1"
```

Note the session ID — let's say it's `5`.

### Step 2 — Make your code change

Edit `my_server.py` as needed.

### Step 3 — Replay the baseline session against the new version

```bash
mcp-debugger replay 5 \
  --server "python my_server.py" \
  --verbose
```

- ✅ **Green lines** = responses match
- ❌ **Red lines** = responses differ (inline diff shown)

### Step 4 — Investigate mismatches

If there are diffs, inspect the original messages from the baseline:

```bash
mcp-debugger inspect 5 --method tools/call
```

Compare field by field. If the difference is expected (e.g. a timestamp field), you can ignore it with a config option:

```bash
mcp-debugger config set replay.diff_ignore_paths "$.result.timestamp"
```

### Step 5 — Run stats comparison

Record a new session with the updated server:

```bash
mcp-debugger proxy --server "python my_server.py" --name "updated-v2"
```

Then compare the two sessions:

```bash
mcp-debugger compare 5 6
```

This shows latency deltas, error rate changes, and new/missing tool calls.

### Step 6 — Save replay results for later

```bash
mcp-debugger replay 5 --server "python my_server.py" --save
```

The replay results are stored in the database for future comparison.

---

## Tutorial 3: Integrate mcp-debugger into a CI Pipeline

**Goal:** Automatically validate your MCP server on every pull request using GitHub Actions.

### Step 1 — Add mcp-debugger to your project dependencies

In your `pyproject.toml` or `requirements-test.txt`:

```toml
[project.optional-dependencies]
test = [
    "mcp-debugger",
]
```

### Step 2 — Write a validation script

Create `scripts/validate_server.sh`:

```bash
#!/bin/bash
set -e

echo "Starting MCP server validation..."

mcp-debugger validate \
  --server "python -m my_package.server" \
  --json > validation_results.json

# Check for failures
python3 - << 'EOF'
import json, sys
results = json.load(open("validation_results.json"))
failed = [r for r in results if not r["passed"] and r["severity"] == "critical"]
if failed:
    print(f"FAILED: {len(failed)} critical rule(s) violated:")
    for f in failed:
        print(f"  - {f['rule_name']}: {f['message']}")
    sys.exit(1)
print(f"PASSED: {len(results)} rules checked, 0 critical failures")
EOF
```

### Step 3 — Add to GitHub Actions workflow

Create `.github/workflows/validate-server.yml`:

```yaml
name: Validate MCP Server

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install dependencies
        run: |
          pip install -e ".[test]"

      - name: Validate MCP server
        run: bash scripts/validate_server.sh

      - name: Upload validation results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: validation-results
          path: validation_results.json
```

### Step 4 — Add replay regression testing to CI

After recording a known-good baseline session locally, export it:

```bash
mcp-debugger export 1 --format json --output tests/fixtures/baseline-session.json
```

Then write a test that replays it:

```python
# tests/test_server_regression.py
import subprocess
import json

def test_server_replay():
    result = subprocess.run(
        ["mcp-debugger", "replay", "1", "--server", "python -m my_package.server", "--json"],
        capture_output=True, text=True
    )
    report = json.loads(result.stdout)
    mismatches = [r for r in report if not r["matched"]]
    assert len(mismatches) == 0, f"{len(mismatches)} response(s) changed"
```

### Step 5 — Export traces to Jaeger for observability (optional)

In CI, spin up a Jaeger container and send traces:

```yaml
- name: Start Jaeger
  run: |
    docker run -d -p 4317:4317 -p 16686:16686 jaegertracing/all-in-one

- name: Record and export session
  run: |
    # Record
    timeout 10 mcp-debugger proxy \
      --server "python -m my_package.server" \
      --name "ci-run" || true
    # Export traces
    mcp-debugger export 1 --format otlp \
      --endpoint http://localhost:4317 --insecure
```

---

## Tutorial 4: Export a Session Report

**Goal:** Generate a human-readable session report to include in a pull request or share with your team.

### Step 1 — Record a session

```bash
mcp-debugger proxy --server "python my_server.py" --name "demo"
```

### Step 2 — Generate a Markdown report

```bash
mcp-debugger export 1 --format markdown --output session-report.md
```

With full message bodies:

```bash
mcp-debugger export 1 --format markdown --include-raw --output full-report.md
```

### Step 3 — Generate a stats summary

```bash
mcp-debugger stats 1 --output stats-report.md
```

### Step 4 — Include in your PR description

The Markdown files render nicely in GitHub PR descriptions and issue comments.

---

## Tutorial 5: Using Aliases for Repeated Commands

**Goal:** Avoid typing long server commands every time.

### Step 1 — Define aliases in config

```bash
mcp-debugger config set aliases.fs "npx -y @modelcontextprotocol/server-filesystem /tmp"
mcp-debugger config set aliases.gh "npx -y @modelcontextprotocol/server-github"
mcp-debugger config set aliases.local "python -m my_package.server --debug"
```

### Step 2 — Use them in commands

```bash
# Instead of: mcp-debugger proxy --server "npx -y ..."
mcp-debugger proxy --server "$(mcp-debugger config get aliases.fs)" --name "fs-session"

# Or set a default server so you never need --server at all
mcp-debugger config set replay.default_server "python -m my_package.server"
mcp-debugger replay 5   # no --server flag needed
```
