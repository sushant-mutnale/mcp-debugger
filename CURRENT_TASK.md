Day 16: Diff Integration – Visualising Response Differences
You built the core replay engine (Day 15), which can replay a session and compare original vs. replayed responses. But the output is just raw data – a JSON dump of mismatches. Developers need a beautiful, human‑readable diff to quickly understand what changed.

Day 16 adds a diff visualisation layer that:

Compares original and replayed responses semantically (not just string equality).

Highlights added, removed, and changed fields.

Outputs to the terminal using Rich (colour‑coded, side‑by‑side or inline diff).

Optionally exports diffs as JSON for CI/CD scripts.

By the end of Day 16, the replay engine will produce a DiffResult that can be rendered as a Rich panel or saved as JSON.

🎯 Core Objective
Extend the replay engine with a diff module (src/mcp_debugger/replay/diff.py) that:

Compares two JSON values (original response vs. replayed response) recursively.

Produces a structured diff – a tree of changes (added, removed, changed, unchanged).

Renders the diff as:

Rich table / panel – side‑by‑side for small changes.

Inline diff – showing only changed fields with colour (+ added, - removed, ~ changed).

Integrates with ReplayResult so that each ReplayedMessage has a .diff property.

Deliverables by end of day:

src/mcp_debugger/replay/diff.py with compare_json(original, replayed) -> DiffNode.

Rich rendering function render_diff(diff_node) that outputs colour‑coded text.

Integration with replay engine: ReplayedMessage.diff is populated.

Unit tests for diff logic (recursive, nested objects, arrays).

CLI preview – not yet a full command, but you can call from a test script.

🧠 Expected Behaviour

1. Diff Data Structure (DiffNode)
   python
   from enum import Enum
   from pydantic import BaseModel
   from typing import Any, Dict, List, Union

class DiffType(str, Enum):
UNCHANGED = "unchanged"
ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"

class DiffNode(BaseModel):
path: str # JSONPath-like, e.g., "result.content[0].text"
type: DiffType
old_value: Any = None
new_value: Any = None
children: List['DiffNode'] = [] # for nested diffs
Example: If original had {"result": {"status": "ok"}} and replayed has {"result": {"status": "success"}}, the diff node would be:

path = "result.status", type = CHANGED, old_value = "ok", new_value = "success".

2. Comparison Algorithm
   Recursively traverse both JSON objects (dicts, lists, primitives).

For dicts:

Keys only in original → REMOVED.

Keys only in replayed → ADDED.

Keys in both → recursively compare values; if different → CHANGED, else UNCHANGED.

For lists:

Simple approach: compare by index (assumes order preserved). If lengths differ, report CHANGED at the list level.

Advanced: use difflib to find insertions/deletions (optional, not needed for MVP).

For primitives (string, number, bool, null): compare directly.

3. Rich Rendering
   Option A: Side‑by‑side panel (recommended for small diffs)

text
┌──────────────────────────────┬──────────────────────────────┐
│ Original │ Replayed │
├──────────────────────────────┼──────────────────────────────┤
│ { │ { │
│ "status": "ok", │ "status": "success", │
│ "count": 42 │ "count": 42 │
│ } │ } │
└──────────────────────────────┴──────────────────────────────┘
Use rich.panel.Panel with two panels side‑by‑side (or use rich.columns.Columns).

Colour differences: changed fields in yellow, added in green, removed in red.

Option B: Inline diff (better for large JSON)

text
result.status

- "ok"

* "success"

result.extra

- "new_field": 123
  Print each changed field on a new line with colour.

For nested paths, use indentation.

Option C: Full diff tree (Rich tree widget)

text
📦 result
└── status: "ok" → "success" [changed]
└── extra: + "new_field" [added]
Choose Option B (inline diff) for MVP – simplest to implement and readable in terminal.

4. Integration with Replay Result
   Modify ReplayedMessage (from Day 15) to include:

python
class ReplayedMessage(BaseModel): # ... existing fields ...
diff: Optional[List[DiffNode]] = None
diff_text: Optional[str] = None # pre‑rendered diff for terminal
After comparing responses, call compare_json() and store the result. Also generate a human‑readable diff string using render_diff().

🔗 Integration with Previous Days
Day 15 (Replay Engine): The replay loop now calls compare_json after each response.

Day 2 (Models): Not directly used, but diff logic works on any JSON-serialisable data.

Day 17 (CLI replay command): Will display the diff using the rendered string.

⚙️ Production Considerations
Performance
Deep comparison of large JSON (e.g., a tool schema of 1MB) could be slow. For MVP, it’s acceptable. Add a size cap (e.g., skip diff if > 100KB) and warn.

Handling Non‑Deterministic Fields
Some fields are expected to differ (e.g., timestamp, request_id). You can add an ignore list of paths to skip during comparison. For MVP, ignore nothing – the user will see the differences. A future enhancement could be a configuration file: diff_ignore_paths = ["$.timestamp", "$.id"].

Array Comparison
Simple index‑based comparison works for most MCP responses because order is usually stable.

If arrays can reorder (e.g., tool list), you may get false mismatches. For MVP, accept this. Document that replay diff for unordered arrays may show false positives.

Output Format for CI
When --json is used, the replay command (Day 17) should output the structured diff as JSON, not rendered text. This allows scripts to assert that no changes occurred.

✅ Day 16 Verification Checklist

# Check How to verify

1 compare_json() exists and returns DiffNode tree Unit test: compare two simple dicts – correct DiffNode with CHANGED.
2 Recursive diff works for nested objects Nested dict with a changed leaf → path includes full hierarchy.
3 Added fields detected Original missing a key, replayed has it → ADDED.
4 Removed fields detected Original has key, replayed missing → REMOVED.
5 Array comparison (by index) works Two arrays of same length with one different element → CHANGED at index path.
6 Primitive types compared correctly Number vs string → CHANGED.
7 render_diff() produces inline colour‑coded output Call with a diff tree → string contains -, +, and ANSI colour codes.
8 Diff is integrated into ReplayedMessage After replay, each message has non‑empty diff if responses differ.
9 Unit tests for compare_json cover edge cases (empty dict, null, list of primitives) pytest tests/test_replay.py::test_diff passes.
10 Diff performance: 1MB JSON < 0.5 seconds Measure with time.perf_counter() – acceptable for MVP.
11 mypy --strict passes –
12 ruff check passes –
13 Documentation: add diff examples to docs/replay.md –
14 Commit with message feat(replay): add diff visualisation –
🚀 After Day 16 – Immediate Next Steps
